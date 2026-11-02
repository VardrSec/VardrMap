"""Managed issuer locks/rollback in disposable administrator/application schemas."""

import os
import subprocess
import sys

import pytest
from postgres_tests.test_migrations import BACKEND, migrate
from postgres_tests.test_migrations import database as database


def fixture_process(url, tmp_path, body):
    allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PATH", "SYSTEMDRIVE"}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env.update(
        DATABASE_URL=url,
        ENV="test",
        BACKEND_JWT_SECRET="test-secret-key-for-pytest-needs-32-chars!!",
        PYTHON_DOTENV_DISABLED="1",
        PYTHONNOUSERSITE="1",
        TEMP=str(tmp_path),
        TMP=str(tmp_path),
        USERPROFILE=str(tmp_path),
        APPDATA=str(tmp_path),
        LOCALAPPDATA=str(tmp_path),
        PYTHONPATH=os.environ.get("NM2_FIXTURE_PYTHONPATH", str(BACKEND)),
    )
    setup = r"""
import importlib.util, tempfile
from pathlib import Path
from sqlalchemy.orm import Session
from db import engine
from managed_wire import WireRefused
from models import Engagement, ManagedApproval, ManagedClock, ManagedContract, JobExecution, ScanJob
spec=importlib.util.spec_from_file_location('isolated_managed_fixture',Path('tests/test_managed_issuance.py'))
fixture=importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
# Reuse the exact public fixture over the migrated PostgreSQL schema, not SQLite.
fixture.create_engine=lambda *a,**kw: engine
context=fixture.specimen.__wrapped__(Path(tempfile.mkdtemp(prefix='nm2-managed-')))
s=next(context)
try:
"""
    code = (
        setup
        + "\n".join("    " + line for line in body.splitlines())
        + "\nfinally:\n    next(context,None)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    # The enclosing isolated runner quarantines raw failure output. It must not
    # expose inherited host service credentials: this child uses an allowlist.
    assert result.returncode == 0, result.stdout + result.stderr


def test_managed_refresh_renews_and_denial_rolls_back(database, tmp_path):
    _, url = database
    migrate(url, "upgrade", "head")
    fixture_process(
        url,
        tmp_path,
        r"""
from unittest.mock import patch
from datetime import timedelta
with patch.object(fixture.control, 'now', lambda: s['wall'][0].replace(tzinfo=None)):
    fixture.register(s)
    claimed = fixture.claim(s)
    contract = s['db'].query(ManagedContract).one()
    body = fixture.control.ControlRequest(runner_id=fixture.RUNNER, origin=fixture.ORIGIN,
                                          token=claimed['execution_control']['token'])
    args = dict(job_id='job-1', body=body, contract_id=contract.id,
                attempt_id=contract.attempt_id, fence=contract.fence)
    s['wall'][0] += timedelta(seconds=9)
    refreshed = s['service'].refresh(s['db'], s['runner'], **args)
    assert refreshed['action']=='continue' and refreshed['lease_seconds']==10
    assert refreshed['lease_expires_at']=='2026-11-02T18:00:19Z'
    with Session(engine) as db:
        assert db.get(JobExecution,'job-1').expires_at == (fixture.NOW+timedelta(seconds=19)).replace(tzinfo=None)
        db.get(Engagement,'eng-1').managed_authority_revision += 1
        db.commit()
    s['wall'][0] += timedelta(seconds=1)
    try:
        s['service'].refresh(s['db'], s['runner'], **args)
        raise AssertionError('stale authority renewed')
    except WireRefused:
        pass
    with Session(engine) as db:
        assert db.get(JobExecution,'job-1').expires_at == (fixture.NOW+timedelta(seconds=19)).replace(tzinfo=None)
        assert db.get(Engagement,'eng-1').duration_allocated == 30
""",
    )


def test_managed_concurrent_claim_and_atomic_migration(database, tmp_path):
    _, url = database
    migrate(url, "upgrade", "head")
    fixture_process(
        url,
        tmp_path,
        r"""
fixture.test_concurrent_claims_have_one_global_winner(s)
with Session(engine) as db:
    assert db.query(ManagedContract).count()==1
    assert db.query(ManagedApproval).one().issued==1
    assert db.get(Engagement,'eng-1').duration_allocated==30
print('PASS: one global owned contract/ordinal/fee winner')
""",
    )


def test_managed_durable_clock_interleaving(database, tmp_path):
    _, url = database
    migrate(url, "upgrade", "head")
    fixture_process(
        url,
        tmp_path,
        r"""
fixture.test_interleaved_denial_high_water_cannot_be_overwritten(s,'claim')
print('PASS: later denial survives earlier in-flight issuer and rollback')
""",
    )


def test_managed_stale_approval_revocation(database, tmp_path):
    _, url = database
    migrate(url, "upgrade", "head")
    fixture_process(
        url,
        tmp_path,
        r"""
fixture.test_stale_approval_identity_cannot_hide_revocation(s)
print('PASS: stale approval identity cannot revive revoked permission')
""",
    )


def test_managed_expiry_behind_engagement_writer_lock(database, tmp_path):
    _, url = database
    migrate(url, "upgrade", "head")
    fixture_process(
        url,
        tmp_path,
        r"""
import threading, time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from sqlalchemy import text
import execution_control as control
fixture.register(s); s['db'].rollback()
entered=threading.Event(); original=control.lock_job
def waiting(*a,**kw):
    entered.set()
    return original(*a,**kw)
def issue():
    with Session(engine) as db: return fixture.claim(s,db=db)
with Session(engine) as writer, patch.object(control,'lock_job',waiting), ThreadPoolExecutor(1) as pool:
    writer.query(Engagement).filter_by(id='eng-1').with_for_update().one()
    pending=pool.submit(issue); assert entered.wait(5)
    until=time.monotonic()+5; blocked=False
    while time.monotonic()<until:
        with engine.connect() as conn:
            blocked=bool(conn.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND pid<>pg_backend_pid()")))
        if blocked: break
        time.sleep(.02)
    assert blocked and not pending.done()
    s['wall'][0]=fixture.NOW+fixture.timedelta(minutes=2); s['ticks'][0]=120.0
    writer.commit()
    try: pending.result(10)
    except WireRefused as exc: assert str(exc)=='approval_expired_or_not_yet_valid'
    else: raise AssertionError('pre-lock time extended expired permission')
fixture.unchanged(s)
assert s['db'].get(ManagedClock,1).observed >= (fixture.NOW+fixture.timedelta(minutes=2)).replace(tzinfo=None)
s['wall'][0]=fixture.NOW; s['ticks'][0]=0.0
try: fixture.claim(s)
except WireRefused as exc: assert str(exc)=='clock_rollback'
else: raise AssertionError('rollback revived expired unused approval')
fixture.unchanged(s)
print('PASS: actual engagement lock wait consumes validity, commits no reservation, preserves denied time')
""",
    )


@pytest.mark.parametrize("order", ["before", "after"])
def test_managed_key_revocation_races(database, tmp_path, order):
    _, url = database
    migrate(url, "upgrade", "head")
    fixture_process(
        url,
        tmp_path,
        r"""
import threading, time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi import HTTPException
from routers.apikeys import revoke_api_key
from sqlalchemy import text
owner={'github_id':'owner-1','scope':'full'}
fixture.register(s); s['db'].rollback()
order='ORDER'
def revoke():
    with Session(engine) as db: return revoke_api_key('key-1',owner,db)
if order=='before':
    original=s['service']._enrollment
    def removed(*a,**kw):
        revoke()
        return original(*a,**kw)
    with patch.object(s['service'],'_enrollment',removed):
        try: fixture.claim(s)
        except WireRefused as exc: assert str(exc)=='enrollment_key_unavailable'
        else: raise AssertionError('key deletion before key lock did not deny')
    fixture.unchanged(s)
else:
    signing=threading.Event(); release=threading.Event(); original=s['wire'].issue
    def held(*a,**kw):
        signing.set(); assert release.wait(10)
        return original(*a,**kw)
    def issue():
        with Session(engine) as db: return fixture.claim(s,db=db)
    with patch.object(s['wire'],'issue',held), ThreadPoolExecutor(2) as pool:
        issued=pool.submit(issue); assert signing.wait(5)
        removed=pool.submit(revoke)
        until=time.monotonic()+5; waiting=False
        while time.monotonic()<until:
            with engine.connect() as conn:
                waiting=bool(conn.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query ILIKE '%DELETE FROM api_keys%' AND pid<>pg_backend_pid()")))
            if waiting: break
            time.sleep(.02)
        assert waiting and not removed.done(), 'deletion did not wait for issuer key lock'
        release.set(); receipt=issued.result(10); removed.result(10)
    with Session(engine) as db:
        assert db.query(ManagedContract).count()==1
        assert db.query(ManagedApproval).one().issued==1
        assert db.get(Engagement,'eng-1').duration_allocated==30
        from execution_control import ControlRequest
        row=db.query(ManagedContract).one()
        body=ControlRequest(runner_id=fixture.RUNNER,origin=fixture.ORIGIN,token=receipt['execution_control']['token'])
        try: s['service'].current(db,s['runner'],job_id='job-1',body=body,contract_id=row.id,attempt_id=row.attempt_id,fence=row.fence)
        except HTTPException as exc: assert exc.status_code==401
        else: raise AssertionError('deleted key remained authenticated for current status')
print('PASS: key deletion/issuance linearization with no refund or revived authentication')
""".replace("ORDER", order),
    )


@pytest.mark.parametrize("mutation", ["authorization", "scope"])
def test_managed_authority_mutation_races(database, tmp_path, mutation):
    _, url = database
    migrate(url, "upgrade", "head")
    fixture_process(
        url,
        tmp_path,
        r"""
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from routers.authorizations import update_authorization
from schemas import AuthorizationUpdate
from routers.scope import add_out_scope_item, delete_scope_item
from schemas import ScopeItemCreate
from sqlalchemy import text
fixture.register(s)
owner={'github_id':'owner-1','scope':'full'}
mode='MUTATION'

def mutate(db):
    if mode=='authorization':
        return update_authorization('eng-1','auth-1',AuthorizationUpdate(status='revoked'),owner,db)
    return add_out_scope_item('eng-1',ScopeItemCreate(value='https://api.example.test',kind='url'),owner,db)
def revert(db, result):
    if mode=='authorization':
        return update_authorization('eng-1','auth-1',AuthorizationUpdate(status='active'),owner,db)
    return delete_scope_item('eng-1','out',result['id'],owner,db)

# Revoke and restore first: monotonic revision prevents revival of the old receipt.
with Session(engine) as db:
    prior=mutate(db)
with Session(engine) as db:
    revert(db,prior)
try: fixture.claim(s)
except WireRefused as exc: assert str(exc)=='authority_revision_changed'
else: raise AssertionError('changed/reverted authority revived old permission')
fixture.unchanged(s)

# Obtain a new explicit signed fixture approval for the changed revision.
s['db'].rollback()
review=s['service'].review(s['db'],s['owner'],job_id='job-1',enrollment_id='enrollment-1',authorization_id='auth-1',plan=s['plan'],
    expires_at=fixture.stamp(fixture.NOW+fixture.timedelta(minutes=1)),max_executions=2,max_duration_seconds=60,
    max_artifact_bytes=1000000,credential_grants=s['review']['context']['credential_grants'])
s['review']=review; s['approval']=fixture.signed(review['context'],'replacement-approval')
fixture.register(s); s['db'].rollback()

# A holds the engagement lock at signing; B's real authorization mutation must
# remain blocked until A commits. pg_stat_activity establishes an actual lock wait.
signing=threading.Event(); release=threading.Event()
original=s['wire'].issue
def held(*a,**kw):
    signing.set(); assert release.wait(10)
    return original(*a,**kw)
def issue():
    with Session(engine) as db: return fixture.claim(s,db=db)
def revoke():
    with Session(engine) as db:
        return mutate(db)
with patch.object(s['wire'],'issue',held), ThreadPoolExecutor(2) as pool:
    issued=pool.submit(issue); assert signing.wait(5)
    changed=pool.submit(revoke)
    import time
    until=time.monotonic()+5; waiting=False
    while time.monotonic()<until:
        with engine.connect() as conn:
            waiting=bool(conn.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND pid<>pg_backend_pid()")))
        if waiting: break
        time.sleep(.02)
    assert waiting and not changed.done(), 'mutation did not wait for issuer engagement lock'
    release.set(); receipt=issued.result(10); changed.result(10)
with Session(engine) as db:
    assert db.query(ManagedContract).count()==1
    assert db.get(Engagement,'eng-1').duration_allocated==30
    assert db.get(Engagement,'eng-1').managed_authority_revision>review['context']['authority_revision']
    assert db.get(JobExecution,'job-1').capacity_reserved
    from execution_control import ControlRequest
    row=db.query(ManagedContract).one()
    body=ControlRequest(runner_id=fixture.RUNNER,origin=fixture.ORIGIN,token=receipt['execution_control']['token'])
    try:
        s['service'].current(db,s['runner'],job_id='job-1',body=body,contract_id=row.id,attempt_id=row.attempt_id,fence=row.fence)
    except WireRefused as exc: assert str(exc)=='authority_revision_changed'
    else: raise AssertionError('current status failed to observe committed mutation')
print('PASS: prior revision denial; issue linearizes before blocked mutation; current-authority check rejects afterward; queue remains disabled')
""".replace("MUTATION", mutation),
    )
