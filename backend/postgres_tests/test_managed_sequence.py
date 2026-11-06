"""V2 sequence winners over real PostgreSQL locks, in both existing CI roles."""

import pytest

from postgres_tests.test_managed_issuance import fixture_process
from postgres_tests.test_migrations import database as database
from postgres_tests.test_migrations import migrate


PREPARE = r"""
import copy, json, hashlib, threading, time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import event, text
from managed_results import Results
from managed_runtime import Runtimes, capability_hash
from managed_wire import digest
from models import ManagedRuntime, ManagedRuntimeAttempt, ManagedStop

fixture.register(s)
runtimes = Runtimes(Results(s['service']))
runtime_id = '00000000-0000-0000-0000-000000000011'
identity = dict(daemon_id='daemon-fixture', container_id='1'*64,
    image_id='sha256:'+'2'*64, project='managed-worker',
    started_at='2026-11-02T17:59:00.000000001Z', owner_nonce='3'*64)
runtimes.register(s['db'], s['owner'], runtime_id=runtime_id,
    enrollment_id='enrollment-1', runner_id=fixture.RUNNER, origin=fixture.ORIGIN,
    identity=identity, capability_sha256=capability_hash('a'*64),
    expires_in_seconds=3600, max_attempts=3)
host = SimpleNamespace(headers={'authorization':'VardrStop '+'a'*64})

def claim(db, job, sequence):
    return runtimes.claim(db, s['runner'], job_id=job, body=s['body'],
        runtime_id=runtime_id, runtime_sha256=digest(identity), runtime_sequence=sequence)

with patch.object(fixture.control, 'now', lambda: fixture.NOW.replace(tzinfo=None)):
    claimed = claim(s['db'], 'job-1', 1)
    c = s['db'].query(ManagedContract).filter_by(job_id='job-1').one()
    args = dict(job_id='job-1', body=fixture.control.ControlRequest(
        runner_id=fixture.RUNNER, origin=fixture.ORIGIN, token=claimed['execution_control']['token']),
        contract_id=c.id, attempt_id=c.attempt_id, fence=c.fence,
        contract_sha256=digest(c.envelope))
    s['db'].rollback()
    s['service'].consume(s['db'], s['runner'], **args)
    runtimes.bind(s['db'], s['runner'], **args, runtime_id=runtime_id,
        runtime_sha256=digest(identity), runtime_sequence=1)
    raw = json.dumps(dict(test_case_id='case-1', case_hash=s['plan']['case_hash'],
        executions=[dict(identity_id='owner',status_code=200,observed_outcome='allow')], findings=[]))
    ack = runtimes.results.submit(s['db'], s['runner'], **args,
        artifact=raw, artifact_sha256=hashlib.sha256(raw.encode()).hexdigest())
    terminal = runtimes.results.finish(s['db'], s['runner'], **args,
        receipt_sha256=ack['receipt_sha256'], outcome='completed', termination_confirmed=True)
release_args = dict(**args, runtime_id=runtime_id,runtime_sha256=digest(identity),runtime_sequence=1,
    terminal_receipt_sha256=digest(terminal),native_done_sha256='5'*64)
binding = {k:terminal[k] for k in ('origin','job_id','runner_id','contract_id','attempt_id','fence','contract_sha256')}
exit_args = dict(runtime_id=runtime_id,runtime_sha256=digest(identity),
    finished_at='2026-11-02T18:00:01Z',exit_code=0,observation_sha256='4'*64)
s['db'].rollback()

def new_job(job):
    with Session(engine) as db:
        db.add(ScanJob(id=job,program_id='eng-1',owner_github_id='owner-1',tool_type='vardrgate_api_test',
            target_source='scope',authorization_contract_required=True,config={'test_case_id':'case-1'}))
        db.commit()
    with Session(engine) as db:
        context=s['review']['context']
        review=s['service'].review(db,s['owner'],job_id=job,enrollment_id='enrollment-1',
            authorization_id='auth-1',plan=s['plan'],**{key:context[key] for key in
            ('expires_at','max_executions','max_duration_seconds','max_artifact_bytes','credential_grants')})
        s['service'].register(db,s['owner'],job_id=job,enrollment_id='enrollment-1',authorization_id='auth-1',
            plan=s['plan'],approval=fixture.signed(review['context'],job))

def race(functions,winner,table,sql_kind='FOR UPDATE'):
    loser=next(name for name in functions if name!=winner)
    entered,release,querying=threading.Event(),threading.Event(),threading.Event()
    threads={};waiting={};holder={};original=s['service']._locked_time
    def held(db,now):
        if threading.get_ident()==threads.get(winner) and not entered.is_set():
            holder['pid']=db.connection().connection.driver_connection.info.backend_pid
            entered.set(); assert release.wait(10)
        return original(db,now)
    def tracing(conn,cursor,statement,parameters,context,executemany):
        if threading.get_ident()==threads.get(loser) and table in statement and sql_kind in statement:
            waiting['pid']=conn.connection.driver_connection.info.backend_pid;querying.set()
    def invoke(name):
        threads[name]=threading.get_ident()
        with Session(engine) as db:
            return functions[name](db)
    event.listen(engine,'before_cursor_execute',tracing)
    try:
        with patch.object(s['service'],'_locked_time',held),ThreadPoolExecutor(2) as pool:
            first=pool.submit(invoke,winner);second=None
            try:
                assert entered.wait(5),'winner did not hold its real locks'
                second=pool.submit(invoke,loser)
                assert querying.wait(5),'loser did not reach expected lock query'
                until=time.monotonic()+5;blocked=False
                while time.monotonic()<until:
                    with engine.connect() as conn:
                        blocked=bool(conn.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE pid=:pid "
                            "AND wait_event_type='Lock' AND :holder=ANY(pg_blocking_pids(pid))"),
                            {'pid':waiting['pid'],'holder':holder['pid']}))
                    if blocked:break
                    time.sleep(.02)
                assert blocked and not second.done(),'no exact real database waiter'
                with Session(engine) as observer:
                    observer.query(ManagedClock).filter_by(id=1).with_for_update(nowait=True).one()
                    observer.rollback()
            finally:release.set()
            accepted=first.result(10)
            try:second.result(10)
            except WireRefused:pass
            else:raise AssertionError('both mutually exclusive cursor operations committed')
            return accepted
    finally:event.remove(engine,'before_cursor_execute',tracing)
"""


@pytest.mark.parametrize("winner", ["release", "retire"])
def test_completed_release_and_physical_retirement_have_one_winner(
    database, tmp_path, winner
):
    _, url = database
    migrate(url, "upgrade", "head")
    fixture_process(
        url,
        tmp_path,
        PREPARE
        + r"""
functions={
    'release':lambda db:runtimes.release(db,s['runner'],**release_args),
    'retire':lambda db:runtimes.observed_exit(db,host,**exit_args,binding=binding,runtime_sequence=1),
}
race(functions,'WINNER','programs')
with Session(engine) as db:
    row=db.get(ManagedRuntime,runtime_id);attempt=db.get(ManagedRuntimeAttempt,(runtime_id,1))
    assert row.retired is ('WINNER'=='retire')
    assert (attempt.released_at is not None) is ('WINNER'=='release')
    assert runtimes.results._completion(binding,runtimes.results._result(db,binding),db.get(JobExecution,'job-1'))==terminal
    assert db.query(ManagedStop).count()==0
    assert (db.get(Engagement,'eng-1').targets_spent,db.get(Engagement,'eng-1').duration_allocated)==(1,30)
print('PASS: exactly one release or physical retirement, immutable success and spend')
""".replace("WINNER", winner),
    )


@pytest.mark.parametrize("winner", ["claim", "retire"])
def test_idle_epoch_retirement_and_next_claim_have_one_winner(
    database, tmp_path, winner
):
    _, url = database
    migrate(url, "upgrade", "head")
    fixture_process(
        url,
        tmp_path,
        PREPARE
        + r"""
runtimes.release(s['db'],s['runner'],**release_args)
new_job('job-2')
functions={
    'claim':lambda db:claim(db,'job-2',2),
    'retire':lambda db:runtimes.observed_unbound_exit(db,host,**exit_args,last_sequence=1),
}
race(functions,'WINNER','managed_runtimes')
with Session(engine) as db:
    row=db.get(ManagedRuntime,runtime_id);engagement=db.get(Engagement,'eng-1')
    assert row.retired is ('WINNER'=='retire')
    assert row.last_sequence==(1 if row.retired else 2)
    assert row.active_sequence==(None if row.retired else 2)
    assert (engagement.targets_spent,engagement.duration_allocated)==((1,30) if row.retired else (2,60))
    assert db.query(ManagedRuntimeAttempt).count()==row.last_sequence
    assert db.query(ManagedStop).count()==0
print('PASS: exactly one idle epoch retirement or next claim, Runtime precedes Clock')
""".replace("WINNER", winner),
    )


def test_different_engagements_compete_for_one_exact_next_runtime_sequence(
    database, tmp_path
):
    _, url = database
    migrate(url, "upgrade", "head")
    fixture_process(
        url,
        tmp_path,
        PREPARE
        + r"""
from datetime import timedelta
from models import Authorization, AuthorizationTestCase, ScopeItem
runtimes.release(s['db'],s['runner'],**release_args)
new_job('job-2')
with Session(engine) as db:
    case=copy.deepcopy(db.get(AuthorizationTestCase,'case-1').spec)
    db.add(Engagement(id='eng-2',owner_github_id='owner-1',name='Separate authority',
        engagement_type='pentest',engagement_status='active',concurrency_limit=1,target_limit=10,duration_limit=120))
    db.commit()
    db.add_all([
        Authorization(id='auth-2',program_id='eng-2',owner_github_id='owner-1',permits='Synthetic only',
            status='active',window_start=fixture.NOW-timedelta(hours=1),window_end=fixture.NOW+timedelta(hours=1)),
        AuthorizationTestCase(id='case-2',program_id='eng-2',owner_github_id='owner-1',name='Fixed case',spec=case),
        ScopeItem(program_id='eng-2',value='https://api.example.test',kind='url',scope_type='in'),
        ScanJob(id='job-3',program_id='eng-2',owner_github_id='owner-1',tool_type='vardrgate_api_test',
            target_source='scope',authorization_contract_required=True,config={'test_case_id':'case-2'}),
    ]);db.commit()
with Session(engine) as db:
    permission_context=s['review']['context']
    review=s['service'].review(db,s['owner'],job_id='job-3',enrollment_id='enrollment-1',authorization_id='auth-2',
        plan=s['plan'],**{key:permission_context[key] for key in
        ('expires_at','max_executions','max_duration_seconds','max_artifact_bytes','credential_grants')})
    s['service'].register(db,s['owner'],job_id='job-3',enrollment_id='enrollment-1',authorization_id='auth-2',
        plan=s['plan'],approval=fixture.signed(review['context'],'job-3'))
# Different engagement parents still share the admitted API key. The winner holds
# that key FOR UPDATE, so the loser's earlier authentication metadata UPDATE waits
# before Enrollment or Runtime locks. Observe the actual existing serialization.
race({'first':lambda db:claim(db,'job-2',2),'second':lambda db:claim(db,'job-3',2)},'first','api_keys','UPDATE')
with Session(engine) as db:
    row=db.get(ManagedRuntime,runtime_id)
    assert row.last_sequence==row.active_sequence==2
    assert db.get(ManagedRuntimeAttempt,(runtime_id,2)).job_id=='job-2'
    assert db.get(ScanJob,'job-3').status=='pending'
    assert (db.get(Engagement,'eng-2').targets_spent,db.get(Engagement,'eng-2').duration_allocated)==(0,0)
    assert db.query(ManagedRuntimeAttempt).count()==2
print('PASS: different parent locks still serialize one next sequence without loser spend')
""",
    )


def test_database_rejects_unsupported_old_writers_without_spending_or_retiring(
    database, tmp_path
):
    _, url = database
    migrate(url, "upgrade", "head")
    fixture_process(
        url,
        tmp_path,
        PREPARE
        + r"""
from sqlalchemy.exc import IntegrityError
new_job('job-2')
def old_prepare(*,db,now,job,approval,projection):
    row=db.query(ManagedRuntime).filter_by(id=runtime_id).with_for_update().one()
    def associate(contract):
        row.job_id,row.contract_id,row.attempt_id=job.id,contract.id,contract.attempt_id
        row.fence,row.contract_sha256=contract.fence,digest(contract.envelope)
        row.bound_at=now().replace(tzinfo=None)
        db.flush()
    return associate
with Session(engine) as db:
    try:s['service'].claim(db,s['runner'],job_id='job-2',body=s['body'],on_claim=old_prepare)
    except IntegrityError:pass
    else:raise AssertionError('unsupported old claim overwrote v2 binding state')
for json_null in (False,True):
    with Session(engine) as db:
        row=db.get(ManagedRuntime,runtime_id)
        row.retired,row.report_sha256=True,'6'*64
        row.retirement_receipt=None if json_null else __import__('sqlalchemy').null()
        try:db.flush()
        except IntegrityError:db.rollback()
        else:raise AssertionError('unsupported old retirement omitted the v2 receipt')
with Session(engine) as db:
    row=db.get(ManagedRuntime,runtime_id)
    assert row.retired is False and row.report_sha256 is None
    assert row.last_sequence==row.active_sequence==1 and row.contract_id is None
    assert db.query(ManagedRuntimeAttempt).count()==1
    assert db.get(ScanJob,'job-2').status=='pending'
    assert db.query(ManagedContract).count()==db.query(JobExecution).count()==1
    assert db.query(ManagedApproval).filter_by(job_id='job-2').one().issued==0
    assert (db.get(Engagement,'eng-1').targets_spent,db.get(Engagement,'eng-1').duration_allocated)==(1,30)
print('PASS: migration CHECKs reject unsupported old claim and retirement with no lost state or spend')
""",
    )
