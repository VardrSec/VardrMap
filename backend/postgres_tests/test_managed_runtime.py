"""Runtime admission lock ordering in disposable real PostgreSQL schemas."""

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
