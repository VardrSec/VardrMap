"""Terminal provisioning with synthetic existing keys and disposable SQL only."""

import hashlib
import io
import json
import warnings
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import managed_enrollment as enrollment
import pytest
from models import ApiKey, ManagedEnrollment, User
from sqlalchemy import create_engine, delete, event, inspect
from sqlalchemy.orm import sessionmaker

KEY = "vmap_public_disposable_terminal_enrollment_fixture"
RUNNER = "00000000-0000-0000-0000-000000000009"
ORIGIN = "https://map.synthetic.test/backend"
VALUES = dict(owner="owner-1", api_key_id="key-1", runner_id=RUNNER, origin=ORIGIN)
ARGS = [
    "bind",
    "--owner",
    "owner-1",
    "--api-key-id",
    "key-1",
    "--runner-id",
    RUNNER,
    "--origin",
    ORIGIN,
]


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + (tmp_path / "enrollment.db").as_posix(),
        connect_args={"check_same_thread": False},
    )
    # Provisioning requires no engagement/authority/approval tables at all.
    for table in (User.__table__, ApiKey.__table__, ManagedEnrollment.__table__):
        table.create(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(User(github_id="owner-1", username="operator"))
        db.commit()
        db.add(
            ApiKey(
                id="key-1",
                github_id="owner-1",
                scope="runner",
                key_hash=hashlib.sha256(KEY.encode()).hexdigest(),
            )
        )
        db.commit()
    monkeypatch.setattr(enrollment, "SessionLocal", sessions)
    yield SimpleNamespace(engine=engine, sessions=sessions)
    engine.dispose()


def bind(database, **changes):
    with database.sessions() as db:
        return enrollment.bind(db, key=KEY, **{**VALUES, **changes})


def retained(database):
    with database.sessions() as db:
        return [
            (
                r.id,
                r.api_key_id,
                r.owner,
                r.principal_hash,
                r.runner_id,
                r.origin,
                r.revision,
                r.revoked,
            )
            for r in db.query(ManagedEnrollment).order_by(ManagedEnrollment.id)
        ]


def stdin(monkeypatch, data=b"", tty=False):
    stream = SimpleNamespace(buffer=io.BytesIO(data), isatty=lambda: tty)
    monkeypatch.setattr(enrollment.sys, "stdin", stream)
    return stream


def test_existing_key_binding_is_idempotent_and_creates_no_authority_or_credentials(
    database,
):
    first = bind(database)
    before = retained(database)
    assert bind(database) == first and retained(database) == before
    row = before[0]
    assert row[3] == hashlib.sha256(("Bearer " + KEY).encode()).hexdigest()
    assert row[3] != hashlib.sha256(KEY.encode()).hexdigest()
    assert first["revision"] == 1 and first["revoked"] is False
    assert set(inspect(database.engine).get_table_names()) == {
        "users",
        "api_keys",
        "managed_enrollments",
    }
    with database.sessions() as db:
        assert db.query(User).count() == db.query(ApiKey).count() == 1
        assert db.get(ApiKey, "key-1").last_used_at is None
    assert KEY not in repr(before) and KEY not in json.dumps(first)


@pytest.mark.parametrize(
    "change", ["owner", "key_id", "key", "scope", "origin", "runner", "missing_user"]
)
def test_invalid_or_foreign_prerequisites_create_nothing(database, change):
    values, key = dict(VALUES), KEY
    with database.sessions() as db:
        if change == "owner":
            values["owner"] = "other"
        elif change == "key_id":
            values["api_key_id"] = "missing"
        elif change == "key":
            key = "vmap_wrong_public_fixture"
        elif change == "scope":
            db.get(ApiKey, "key-1").scope = "invalid"
        elif change == "origin":
            values["origin"] = "http://localhost"
        elif change == "runner":
            values["runner_id"] = "not-a-uuid"
        else:
            db.execute(delete(User).where(User.github_id == "owner-1"))
        db.commit()
    with database.sessions() as db:
        with pytest.raises((enrollment.EnrollmentRefused, ValueError)):
            enrollment.bind(db, key=key, **values)
    assert retained(database) == []


@pytest.mark.parametrize("change", ["origin", "key_id", "revision", "deleted_key"])
def test_existing_binding_is_never_overwritten_or_repaired(database, change):
    first = bind(database)
    values = {}
    if change == "origin":
        values["origin"] = "https://different.synthetic.test/backend"
    else:
        with database.sessions() as db:
            row = db.get(ManagedEnrollment, first["enrollment_id"])
            if change == "key_id":
                row.api_key_id = "another-key"
            elif change == "revision":
                row.revision = 0
            else:
                db.delete(db.get(ApiKey, "key-1"))
            db.commit()
    before = retained(database)
    with pytest.raises(enrollment.EnrollmentRefused):
        bind(database, **values)
    assert retained(database) == before


def test_revocation_keeps_a_tombstone_and_never_revives_or_reincrements(database):
    first = bind(database)
    with database.sessions() as db:
        revoked = enrollment.revoke(
            db, owner="owner-1", enrollment_id=first["enrollment_id"]
        )
        assert (
            enrollment.revoke(db, owner="owner-1", enrollment_id=first["enrollment_id"])
            == revoked
        )
    assert revoked["revoked"] is True and revoked["revision"] == 2
    before = retained(database)
    with pytest.raises(enrollment.EnrollmentRefused):
        bind(database)
    assert retained(database) == before


def test_deleted_key_does_not_prevent_explicit_tombstone_revocation(database):
    first = bind(database)
    with database.sessions() as db:
        db.delete(db.get(ApiKey, "key-1"))
        db.commit()
        revoked = enrollment.revoke(
            db, owner="owner-1", enrollment_id=first["enrollment_id"]
        )
    assert revoked["revoked"] and revoked["revision"] == 2


@pytest.mark.parametrize("change", ["owner", "missing", "overflow"])
def test_revocation_refuses_foreign_missing_or_exhausted_revision(database, change):
    first = bind(database)
    owner, identity = "owner-1", first["enrollment_id"]
    if change == "owner":
        owner = "other"
    elif change == "missing":
        identity = "missing"
    else:
        with database.sessions() as db:
            db.get(ManagedEnrollment, identity).revision = enrollment.MAX_REVISION
            db.commit()
    before = retained(database)
    with database.sessions() as db:
        with pytest.raises(enrollment.EnrollmentRefused):
            enrollment.revoke(db, owner=owner, enrollment_id=identity)
    assert retained(database) == before


def test_provisioning_does_not_commit_or_discard_caller_pending_work(database):
    with database.sessions() as db:
        pending = User(github_id="pending", username="pending")
        db.add(pending)
        with pytest.raises(enrollment.EnrollmentRefused):
            enrollment.bind(db, key=KEY, **VALUES)
        assert pending in db.new
        db.rollback()
    assert retained(database) == []


def test_concurrent_sqlite_bindings_retain_one_association(database):
    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(lambda _: bind(database), range(2)))
    assert replies[0] == replies[1] and len(retained(database)) == 1


@pytest.mark.parametrize("ending", [b"", b"\n", b"\r\n"])
def test_explicit_stdin_is_bounded_and_never_prints_the_key(
    database, monkeypatch, capsys, ending
):
    stream = stdin(monkeypatch, KEY.encode() + ending)
    assert enrollment.main(ARGS + ["--key-stdin"]) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["origin"] == ORIGIN and result["runner_id"] == RUNNER
    assert KEY not in output.out + output.err and "principal_hash" not in output.out
    assert stream.buffer.tell() <= enrollment.KEY_MAX_BYTES + 3


def test_hidden_tty_is_the_default_without_a_plaintext_fallback(
    database, monkeypatch, capsys
):
    stdin(monkeypatch, tty=True)
    monkeypatch.setattr(enrollment.getpass, "getpass", lambda prompt: KEY)
    assert enrollment.main(ARGS) == 0
    output = capsys.readouterr()
    assert KEY not in output.out + output.err and len(retained(database)) == 1


def test_noninteractive_default_never_reads_a_key_without_explicit_stdin(
    database, monkeypatch, capsys
):
    stdin(monkeypatch, KEY.encode())
    calls = []
    monkeypatch.setattr(
        enrollment.getpass, "getpass", lambda prompt: calls.append(prompt)
    )
    assert enrollment.main(ARGS) == 2 and calls == []
    assert (
        retained(database) == []
        and capsys.readouterr().err == "managed_enrollment_refused\n"
    )


def test_echo_warning_is_an_error_instead_of_a_fallback(database, monkeypatch, capsys):
    stdin(monkeypatch, tty=True)

    def fallback(prompt):
        warnings.warn("synthetic_do_not_echo", enrollment.getpass.GetPassWarning)
        return KEY

    monkeypatch.setattr(enrollment.getpass, "getpass", fallback)
    assert enrollment.main(ARGS) == 2 and retained(database) == []
    output = capsys.readouterr()
    assert output.err == "managed_enrollment_refused\n" and output.out == ""


@pytest.mark.parametrize(
    "data",
    [b"", b"x" * 10000, b"\xff", KEY.encode() + b"\nextra", KEY.encode() + b"\n\n"],
)
def test_malformed_or_excessive_stdin_never_creates_a_binding(
    database, monkeypatch, capsys, data
):
    stream = stdin(monkeypatch, data)
    assert enrollment.main(ARGS + ["--key-stdin"]) == 2 and retained(database) == []
    assert stream.buffer.tell() <= enrollment.KEY_MAX_BYTES + 3
    output = capsys.readouterr()
    assert output.out == "" and output.err == "managed_enrollment_refused\n"


def test_unsupported_key_argument_is_rejected_without_echo(
    database, monkeypatch, capsys
):
    stdin(monkeypatch)
    assert enrollment.main(ARGS + ["--api-key", KEY]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err == "managed_enrollment_refused\n"


def test_missing_schema_is_not_created_or_migrated(database, monkeypatch, capsys):
    ManagedEnrollment.__table__.drop(database.engine)
    stdin(monkeypatch, KEY.encode())
    assert enrollment.main(ARGS + ["--key-stdin"]) == 2
    assert set(inspect(database.engine).get_table_names()) == {"users", "api_keys"}
    assert capsys.readouterr().err == "managed_enrollment_refused\n"


def test_database_failure_rolls_back_and_never_prints_its_details(
    database, monkeypatch, capsys
):
    stdin(monkeypatch, KEY.encode())

    def fault(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO managed_enrollments"):
            raise RuntimeError("synthetic_do_not_echo " + KEY)

    event.listen(database.engine, "after_cursor_execute", fault)
    try:
        assert enrollment.main(ARGS + ["--key-stdin"]) == 2
    finally:
        event.remove(database.engine, "after_cursor_execute", fault)
    output = capsys.readouterr()
    assert output.out == "" and output.err == "managed_enrollment_refused\n"
    assert retained(database) == []


def test_cli_revocation_needs_no_recovered_key_or_signing_material(database, capsys):
    first = bind(database)
    args = ["revoke", "--owner", "owner-1", "--enrollment-id", first["enrollment_id"]]
    assert enrollment.main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["revoked"] and output["revision"] == 2
