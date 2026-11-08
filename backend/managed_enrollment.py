"""Explicit terminal binding of an existing Map API key; never execution approval."""

import argparse
import getpass
import hashlib
import hmac
import json
import re
import sys
import uuid
import warnings

import managed_authority
from db import SessionLocal
from execution_control import ClaimControl
from models import ApiKey, ManagedEnrollment, User

KEY_MAX_BYTES = 256
MAX_REVISION = 2**31 - 1


class EnrollmentRefused(ValueError):
    """Fixed refusal without credential or database exception details."""


def _require(value):
    if not value:
        raise EnrollmentRefused("managed_enrollment_refused")


def _identifier(value):
    _require(type(value) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value))
    return value


def _key(value):
    _require(
        type(value) is str
        and len(value) <= KEY_MAX_BYTES
        and re.fullmatch(r"vmap_[A-Za-z0-9_-]+", value)
    )
    return value


def _view(row):
    return {
        "enrollment_id": row.id,
        "owner": row.owner,
        "api_key_id": row.api_key_id,
        "runner_id": row.runner_id,
        "origin": row.origin,
        "revision": row.revision,
        "revoked": row.revoked,
    }


def _own_transaction(db):
    # This terminal operation owns its transaction, never caller-pending work.
    _require(not db.in_transaction() and not db.new and not db.dirty and not db.deleted)


def _revision(row):
    _require(type(row.revision) is int and 1 <= row.revision <= MAX_REVISION)


def bind(db, *, owner, api_key_id, runner_id, origin, key):
    """Verify an existing key and retain one immutable principal/Runner binding."""
    owner, api_key_id, key = _identifier(owner), _identifier(api_key_id), _key(key)
    runner_id = str(uuid.UUID(runner_id))
    ClaimControl(runner_id=runner_id, origin=origin)
    _require(origin.startswith("https://"))
    key_hash = hashlib.sha256(key.encode("ascii")).hexdigest()
    principal = hashlib.sha256(("Bearer " + key).encode("ascii")).hexdigest()
    _own_transaction(db)
    try:
        managed_authority.begin_write(db)
        # Match the issuer's enrollment-before-key lock order. A unique-constraint
        # race refuses safely; an exact later invocation can observe the winner.
        row = (
            db.query(ManagedEnrollment)
            .filter_by(
                principal_hash=principal,
                runner_id=runner_id,
            )
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )
        stored = (
            db.query(ApiKey)
            .filter_by(id=api_key_id)
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )
        _require(
            stored is not None
            and stored.github_id == owner
            and stored.scope in {"runner", "full"}
            and type(stored.key_hash) is str
            and hmac.compare_digest(stored.key_hash, key_hash)
            and db.get(User, owner) is not None
        )
        if row is not None:
            _revision(row)
            _require(
                not row.revoked
                and row.owner == owner
                and row.api_key_id == api_key_id
                and row.origin == origin
            )
        else:
            row = ManagedEnrollment(
                id=str(uuid.uuid4()),
                api_key_id=api_key_id,
                owner=owner,
                principal_hash=principal,
                runner_id=runner_id,
                origin=origin,
                revision=1,
                revoked=False,
            )
            db.add(row)
        result = _view(row)
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


def revoke(db, *, owner, enrollment_id):
    """Retain a permanent tombstone; repeated revocation does not change revision."""
    owner, enrollment_id = _identifier(owner), _identifier(enrollment_id)
    _own_transaction(db)
    try:
        managed_authority.begin_write(db)
        row = (
            db.query(ManagedEnrollment)
            .filter_by(id=enrollment_id)
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )
        _require(row is not None and row.owner == owner)
        _revision(row)
        if not row.revoked:
            _require(row.revision < MAX_REVISION)
            row.revoked = True
            row.revision += 1
        result = _view(row)
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise


def _read_key(use_stdin):
    if use_stdin:
        # Explicit opt-in only. At most one key plus CRLF; never an unbounded read.
        data = sys.stdin.buffer.read(KEY_MAX_BYTES + 3)
        _require(len(data) <= KEY_MAX_BYTES + 2)
        return _key(data.removesuffix(b"\n").removesuffix(b"\r").decode("ascii"))
    _require(sys.stdin.isatty())
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return _key(getpass.getpass("Existing Map API key (hidden): "))


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # Even mistaken unsupported arguments must not echo a pasted credential.
        raise EnrollmentRefused("managed_enrollment_refused")


def main(argv=None):
    parser = _Parser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    binding = actions.add_parser("bind")
    for name in ("owner", "api-key-id", "runner-id", "origin"):
        binding.add_argument("--" + name, required=True)
    binding.add_argument(
        "--key-stdin",
        action="store_true",
        help="Explicitly read one bounded key from stdin instead of a hidden TTY prompt",
    )
    revocation = actions.add_parser("revoke")
    for name in ("owner", "enrollment-id"):
        revocation.add_argument("--" + name, required=True)
    try:
        args = parser.parse_args(argv)
        key = _read_key(args.key_stdin) if args.action == "bind" else None
        with SessionLocal() as db:
            if args.action == "bind":
                result = bind(
                    db,
                    owner=args.owner,
                    api_key_id=args.api_key_id,
                    runner_id=args.runner_id,
                    origin=args.origin,
                    key=key,
                )
            else:
                result = revoke(db, owner=args.owner, enrollment_id=args.enrollment_id)
    except KeyboardInterrupt:
        print("managed_enrollment_interrupted", file=sys.stderr)
        return 130
    except Exception:
        print("managed_enrollment_refused", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
