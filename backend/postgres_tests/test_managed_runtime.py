"""Runtime admission lock ordering in disposable real PostgreSQL schemas."""

import pytest

from postgres_tests.test_managed_issuance import fixture_process
from postgres_tests.test_migrations import database as database
from postgres_tests.test_migrations import migrate


def test_runtime_claim_waits_before_taking_the_operation_clock(database, tmp_path):
    _, url = database
    migrate(url, "upgrade", "head")
    fixture_process(
        url,
        tmp_path,
        r"""
import threading, time
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import event, text
from managed_results import Results
from managed_runtime import Runtimes, capability_hash
from managed_wire import digest
from models import ManagedRuntime

fixture.register(s)
runtimes = Runtimes(Results(s['service']))
runtime_id = '00000000-0000-0000-0000-000000000011'
identity = dict(daemon_id='daemon-fixture', container_id='1'*64,
    image_id='sha256:'+'2'*64, project='managed-worker',
    started_at='2026-11-02T17:59:00.000000001Z', owner_nonce='3'*64)
runtimes.register(s['db'], s['owner'], runtime_id=runtime_id,
    enrollment_id='enrollment-1', runner_id=fixture.RUNNER,
    origin=fixture.ORIGIN, identity=identity,
    capability_sha256=capability_hash('a'*64), expires_in_seconds=3600)
s['db'].rollback()

# Hold a real row lock. Observe the exact claimant backend blocked on that
# Runtime FOR UPDATE, rather than assuming a callback event proves a DB wait.
entered = threading.Event()
claimant = {}
def tracing(conn, cursor, statement, parameters, context, executemany):
    if (threading.get_ident() == claimant.get('thread')
            and 'managed_runtimes' in statement and 'FOR UPDATE' in statement):
        claimant['pid'] = conn.connection.driver_connection.info.backend_pid
        entered.set()

def issue():
    claimant['thread'] = threading.get_ident()
    with Session(engine) as db:
        return runtimes.claim(db, s['runner'], job_id='job-1', body=s['body'],
            runtime_id=runtime_id, runtime_sha256=digest(identity))

event.listen(engine, 'before_cursor_execute', tracing)
try:
    with Session(engine) as holder, ThreadPoolExecutor(1) as pool:
        holder.execute(text("SET LOCAL statement_timeout = '10s'"))
        holder.query(ManagedRuntime).filter_by(id=runtime_id).with_for_update().one()
        pending = pool.submit(issue)
        try:
            assert entered.wait(5), 'claim did not reach Runtime FOR UPDATE'
            until = time.monotonic() + 5
            blocked = False
            while time.monotonic() < until:
                with engine.connect() as conn:
                    blocked = bool(conn.scalar(text(
                        "SELECT count(*) FROM pg_stat_activity WHERE pid=:pid "
                        "AND wait_event_type='Lock' AND query LIKE '%managed_runtimes%' "
                        "AND query LIKE '%FOR UPDATE%'"), {'pid': claimant['pid']}))
                if blocked:
                    break
                time.sleep(.02)
            assert blocked and not pending.done(), 'claim did not wait on held runtime'
            # NOWAIT makes the previous late-hook ordering fail immediately:
            # it held Clock while waiting for Runtime, completing a lock cycle.
            clock = holder.query(ManagedClock).filter_by(id=1).with_for_update(nowait=True).one()
            assert clock.observed == fixture.NOW.replace(tzinfo=None)
        finally:
            holder.rollback()  # Release Runtime even when the ordering fails.
        receipt = pending.result(10)
finally:
    event.remove(engine, 'before_cursor_execute', tracing)

with Session(engine) as db:
    row = db.get(ManagedRuntime, runtime_id)
    contract = db.query(ManagedContract).one()
    assert row.contract_id == contract.id and row.confirmed_at is None
    assert row.contract_sha256 == digest(receipt['managed_authorization']['contract'])
    assert contract.consumed is False and db.query(ManagedApproval).one().issued == 1
    assert db.get(Engagement, 'eng-1').duration_allocated == 30
    assert db.get(Engagement, 'eng-1').targets_spent == 1
print('PASS: runtime waiter holds no clock; one exact unconsumed association and spend')
""",
    )


@pytest.mark.parametrize("winner", ["retire", "claim"])
def test_unbound_retirement_and_claim_have_one_serialized_winner(
    database, tmp_path, winner
):
    _, url = database
    migrate(url, "upgrade", "head")
    fixture_process(
        url,
        tmp_path,
        r"""
import threading, time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import event, text
from managed_results import Results
from managed_runtime import Runtimes, capability_hash
from managed_wire import digest
from models import ManagedRuntime

fixture.register(s)
service = s['service']; runtimes = Runtimes(Results(service))
runtime_id = '00000000-0000-0000-0000-000000000011'
identity = dict(daemon_id='daemon-fixture', container_id='1'*64,
    image_id='sha256:'+'2'*64, project='managed-worker',
    started_at='2026-11-02T17:59:00.000000001Z', owner_nonce='3'*64)
runtimes.register(s['db'], s['owner'], runtime_id=runtime_id,
    enrollment_id='enrollment-1', runner_id=fixture.RUNNER,
    origin=fixture.ORIGIN, identity=identity,
    capability_sha256=capability_hash('a'*64), expires_in_seconds=3600)
s['db'].rollback()
host = SimpleNamespace(headers={'authorization':'VardrStop '+'a'*64})
winner = 'WINNER'; loser = 'claim' if winner == 'retire' else 'retire'
entered, release, querying = threading.Event(), threading.Event(), threading.Event()
threads = {}; waiting = {}; table = 'managed_runtimes' if winner == 'retire' else 'managed_clock'
original_clock, original_issue = service._locked_time, s['wire'].issue

def held_clock(db, now):
    if winner == 'retire' and threading.get_ident() == threads.get('retire'):
        entered.set(); assert release.wait(10)
    return original_clock(db, now)

def held_issue(*args, **kwargs):
    if winner == 'claim':
        entered.set(); assert release.wait(10)
    return original_issue(*args, **kwargs)

def tracing(conn, cursor, statement, parameters, context, executemany):
    if (threading.get_ident() == threads.get(loser)
            and table in statement and 'FOR UPDATE' in statement):
        waiting['pid'] = conn.connection.driver_connection.info.backend_pid
        querying.set()

def issue():
    threads['claim'] = threading.get_ident()
    with Session(engine) as db:
        return runtimes.claim(db, s['runner'], job_id='job-1', body=s['body'],
            runtime_id=runtime_id, runtime_sha256=digest(identity))

def retire():
    threads['retire'] = threading.get_ident()
    with Session(engine) as db:
        return runtimes.observed_unbound_exit(db, host, runtime_id=runtime_id,
            runtime_sha256=digest(identity), finished_at='2026-11-02T18:00:01Z',
            exit_code=137, observation_sha256='4'*64)

functions = {'claim':issue, 'retire':retire}
event.listen(engine, 'before_cursor_execute', tracing)
try:
    with patch.object(service, '_locked_time', held_clock), patch.object(s['wire'], 'issue', held_issue), ThreadPoolExecutor(2) as pool:
        first = pool.submit(functions[winner])
        second = None
        try:
            assert entered.wait(5), 'winning transaction did not hold its real locks'
            second = pool.submit(functions[loser])
            assert querying.wait(5), 'loser did not reach its lock query'
            until = time.monotonic()+5; blocked = False
            while time.monotonic()<until:
                with engine.connect() as conn:
                    blocked = bool(conn.scalar(text(
                        "SELECT count(*) FROM pg_stat_activity WHERE pid=:pid "
                        "AND wait_event_type='Lock' AND query LIKE :query"),
                        {'pid':waiting['pid'], 'query':'%'+table+'%'}))
                if blocked: break
                time.sleep(.02)
            assert blocked and not second.done(), 'loser was not a real database lock waiter'
        finally:
            release.set()
        accepted = first.result(10)
        try: second.result(10)
        except WireRefused as exc:
            assert str(exc) == ('runtime_claim_binding' if winner == 'retire' else 'unbound_runtime_required')
        else: raise AssertionError('both claim and unbound retirement committed')
finally:
    event.remove(engine, 'before_cursor_execute', tracing)

with Session(engine) as db:
    row = db.get(ManagedRuntime, runtime_id)
    engagement = db.get(Engagement, 'eng-1')
    approval = db.query(ManagedApproval).one()
    if winner == 'retire':
        assert row.retired is True and row.contract_id is None
        assert accepted['receipt']['bound'] is False
        assert db.query(ManagedContract).count() == db.query(JobExecution).count() == 0
        assert db.get(ScanJob, 'job-1').status == 'pending'
        assert (approval.issued,engagement.targets_spent,engagement.duration_allocated) == (0,0,0)
    else:
        contract = db.query(ManagedContract).one()
        assert row.retired is False and row.report_sha256 is None and row.contract_id == contract.id
        assert contract.consumed is False and db.get(JobExecution, 'job-1').capacity_reserved is True
        assert (approval.issued,engagement.targets_spent,engagement.duration_allocated) == (1,1,30)
print('PASS: exactly one serialized runtime claim or unbound retirement; no invented claim or refund')
""".replace("WINNER", winner),
    )
