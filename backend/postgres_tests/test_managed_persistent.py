"""Persistent v3 real-lock checks over the existing two migrated CI roles."""

import pytest

from postgres_tests.test_managed_issuance import fixture_process
from postgres_tests.test_managed_sequence import PREPARE as FINITE_FIXTURE
from postgres_tests.test_migrations import database as database
from postgres_tests.test_migrations import migrate

# Reuse only the existing generic human-review and real-lock test utilities,
# never its finite registration, claim, receipt or expected runtime behavior.
HELPERS = FINITE_FIXTURE[FINITE_FIXTURE.index("def new_job(") :]

BASE = r"""
import copy,json,hashlib,threading,time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import event,text,delete
from sqlalchemy.exc import IntegrityError
from managed_results import Results
from managed_runtime import Runtimes,capability_hash
from managed_wire import digest
from models import ManagedRuntime,ManagedRuntimeAttempt,ManagedStop

fixture.control.now=lambda:s['wall'][0].replace(tzinfo=None)
fixture.register(s)
runtimes=Runtimes(Results(s['service']),persistent_enabled=True)
runtime_id='00000000-0000-0000-0000-000000000011'
identity=dict(daemon_id='daemon-fixture',container_id='1'*64,image_id='sha256:'+'2'*64,
    project='managed-worker',started_at='2026-11-02T17:59:00.000000001Z',owner_nonce='3'*64)
admission=runtimes.register(s['db'],s['owner'],runtime_id=runtime_id,
    enrollment_id='enrollment-1',runner_id=fixture.RUNNER,origin=fixture.ORIGIN,
    identity=identity,capability_sha256=capability_hash('a'*64),mode='persistent',
    limits=dict(max_attempts=None,idle_timeout_seconds=None),
    reporting_authority=dict(purpose='worker-stop-only',expires_at=None))
metadata=dict(runtime_id=runtime_id,runtime_sha256=digest(identity),
    admission_sha256=admission['admission_sha256'])
host=SimpleNamespace(headers={'authorization':'VardrStop '+'a'*64})

def claim(db,job,number):
    return runtimes.claim(db,s['runner'],job_id=job,body=s['body'],
        **metadata,runtime_sequence=str(number))
s['db'].rollback()
"""

ACTIVE = (
    BASE
    + r"""
claimed=claim(s['db'],'job-1',1)
c=s['db'].query(ManagedContract).filter_by(job_id='job-1').one()
args=dict(job_id='job-1',body=fixture.control.ControlRequest(runner_id=fixture.RUNNER,
    origin=fixture.ORIGIN,token=claimed['execution_control']['token']),
    contract_id=c.id,attempt_id=c.attempt_id,fence=c.fence,contract_sha256=digest(c.envelope))
s['db'].rollback()
s['service'].consume(s['db'],s['runner'],**args,on_control=runtimes.persistent.control_guard)
runtimes.bind(s['db'],s['runner'],**args,**metadata,runtime_sequence='1')
s['db'].rollback()
"""
)

TERMINAL = (
    ACTIVE
    + r"""
raw=json.dumps(dict(test_case_id='case-1',case_hash=s['plan']['case_hash'],
    executions=[dict(identity_id='owner',status_code=200,observed_outcome='allow')],findings=[]))
ack=runtimes.results.submit(s['db'],s['runner'],**args,
    artifact=raw,artifact_sha256=hashlib.sha256(raw.encode()).hexdigest())
terminal=runtimes.results.finish(s['db'],s['runner'],**args,
    receipt_sha256=ack['receipt_sha256'],outcome='failed',termination_confirmed=True)
release_args=dict(**args,**metadata,runtime_sequence='1',
    terminal_receipt_sha256=digest(terminal),native_done_sha256='5'*64)
binding={k:terminal[k] for k in ('origin','job_id','runner_id','contract_id','attempt_id','fence','contract_sha256')}
exit_args=dict(**metadata,finished_at='2026-11-02T18:00:01Z',exit_code=0,observation_sha256='4'*64)
s['db'].rollback()
"""
)


@pytest.mark.parametrize("operation", ["claim", "control"])
def test_persistent_runtime_wait_precedes_first_clock_lock(
    database, tmp_path, operation
):
    _, url = database
    migrate(url, "upgrade", "head")
    setup = BASE if operation == "claim" else ACTIVE
    action = (
        "claim(db,'job-1',1)"
        if operation == "claim"
        else "s['service'].refresh(db,s['runner'],**{k:v for k,v in args.items() if k!='contract_sha256'},on_control=runtimes.persistent.control_guard)"
    )
    fixture_process(
        url,
        tmp_path,
        setup
        + r"""
entered=threading.Event();claimant={}
def tracing(conn,cursor,statement,parameters,context,executemany):
    if threading.get_ident()==claimant.get('thread') and 'managed_runtimes' in statement and 'FOR UPDATE' in statement:
        claimant['pid']=conn.connection.driver_connection.info.backend_pid;entered.set()
def invoke():
    claimant['thread']=threading.get_ident()
    with Session(engine) as db:
        return ACTION
event.listen(engine,'before_cursor_execute',tracing)
try:
    with Session(engine) as holder,ThreadPoolExecutor(1) as pool:
        holder.execute(text("SET LOCAL statement_timeout='10s'"))
        holder.query(ManagedRuntime).filter_by(id=runtime_id).with_for_update().one()
        holder_pid=holder.connection().connection.driver_connection.info.backend_pid
        pending=pool.submit(invoke)
        try:
            assert entered.wait(5),'operation did not reach its Runtime FOR UPDATE'
            until=time.monotonic()+5;blocked=False
            while time.monotonic()<until:
                with engine.connect() as conn:
                    blocked=bool(conn.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE pid=:pid "
                        "AND wait_event_type='Lock' AND :holder=ANY(pg_blocking_pids(pid))"),
                        {'pid':claimant['pid'],'holder':holder_pid}))
                if blocked:break
                time.sleep(.02)
            assert blocked and not pending.done(),'exact Runtime waiter was not demonstrated'
            holder.query(ManagedClock).filter_by(id=1).with_for_update(nowait=True).one()
        finally:holder.rollback()
        reply=pending.result(10)
finally:event.remove(engine,'before_cursor_execute',tracing)
with Session(engine) as db:
    row=db.get(ManagedRuntime,runtime_id)
    assert row.last_sequence==row.head_sequence==row.active_sequence==1
    assert db.query(ManagedRuntimeAttempt).count()==1
    assert (db.get(Engagement,'eng-1').targets_spent,db.get(Engagement,'eng-1').duration_allocated)==(1,30)
print('PASS: persistent operation Runtime wait precedes Clock, one exact association and charge')
""".replace("ACTION", action),
    )


@pytest.mark.parametrize("winner", ["release", "retire"])
def test_persistent_failed_release_and_retirement_have_one_winner(
    database, tmp_path, winner
):
    _, url = database
    migrate(url, "upgrade", "head")
    fixture_process(
        url,
        tmp_path,
        TERMINAL
        + HELPERS
        + r"""
functions={
    'release':lambda db:runtimes.release(db,s['runner'],**release_args),
    'retire':lambda db:runtimes.observed_exit(db,host,**exit_args,binding=binding,runtime_sequence='1'),
}
race(functions,'WINNER','programs')
with Session(engine) as db:
    row=db.get(ManagedRuntime,runtime_id);attempt=db.get(ManagedRuntimeAttempt,(runtime_id,1))
    assert row.retired is ('WINNER'=='retire')
    assert (attempt.released_at is not None) is ('WINNER'=='release')
    assert row.head_sequence==row.last_sequence==1
    assert runtimes.results._completion(binding,runtimes.results._result(db,binding),db.get(JobExecution,'job-1'))==terminal
    assert db.query(ManagedStop).count()==0
    assert (db.get(Engagement,'eng-1').targets_spent,db.get(Engagement,'eng-1').duration_allocated)==(1,30)
print('PASS: one persistent failed-release or physical-retirement winner; exact result and spend retained')
""".replace("WINNER", winner),
    )


@pytest.mark.parametrize("winner", ["claim", "retire"])
def test_persistent_idle_retirement_fences_next_sequence(database, tmp_path, winner):
    _, url = database
    migrate(url, "upgrade", "head")
    fixture_process(
        url,
        tmp_path,
        TERMINAL
        + HELPERS
        + r"""
runtimes.release(s['db'],s['runner'],**release_args)
new_job('job-2')
functions={
    'claim':lambda db:claim(db,'job-2',2),
    'retire':lambda db:runtimes.observed_unbound_exit(db,host,**exit_args,last_sequence='1'),
}
race(functions,'WINNER','managed_runtimes')
with Session(engine) as db:
    row=db.get(ManagedRuntime,runtime_id);engagement=db.get(Engagement,'eng-1')
    assert row.retired is ('WINNER'=='retire')
    assert row.last_sequence==row.head_sequence==(1 if row.retired else 2)
    assert row.active_sequence==(None if row.retired else 2)
    assert (engagement.targets_spent,engagement.duration_allocated)==((1,30) if row.retired else (2,60))
    assert db.query(ManagedRuntimeAttempt).count()==row.last_sequence
print('PASS: persistent idle cursor never retargets; one claim or retirement and exact charges')
""".replace("WINNER", winner),
    )


def test_persistent_migrated_head_predecessor_and_parent_are_enforced(
    database, tmp_path
):
    _, url = database
    migrate(url, "upgrade", "head")
    fixture_process(
        url,
        tmp_path,
        TERMINAL
        + r"""
for fault in ('delete_head','missing_head','missing_predecessor'):
    with Session(engine) as db:
        try:
            if fault=='delete_head':
                db.execute(delete(ManagedRuntimeAttempt).where(ManagedRuntimeAttempt.runtime_id==runtime_id))
            elif fault=='missing_head':
                row=db.get(ManagedRuntime,runtime_id)
                row.last_sequence=row.head_sequence=row.active_sequence=2
            else:
                db.add(ManagedRuntimeAttempt(runtime_id=runtime_id,runtime_mode='persistent',runtime_sequence=3,
                    previous_sequence=2,job_id='orphan-job',contract_id='orphan-contract',attempt_id='orphan-attempt',
                    fence=1,contract_sha256='4'*64,bound_at=fixture.NOW.replace(tzinfo=None)))
            db.commit()
            raise AssertionError('persistent history constraint was bypassed')
        except IntegrityError:db.rollback()
with Session(engine) as db:
    assert db.get(ManagedRuntime,runtime_id).head_sequence==1
    assert db.query(ManagedRuntimeAttempt).count()==1
print('PASS: migrated persistent head/predecessor constraints retain all exact history')
""",
    )
