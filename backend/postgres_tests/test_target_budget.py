"""Cumulative target races in disposable administrator/restricted schemas."""
import os
import subprocess
import sys
from postgres_tests.test_migrations import BACKEND, database as database, migrate


def test_target_ceiling_competing_claims_and_persistent_spend(database):
    _, url = database
    migrate(url, "upgrade", "head")
    code = r'''
import threading
from concurrent.futures import ThreadPoolExecutor
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session
from db import engine
from models import Engagement, ScanJob, User, AuthorizationTestCase
from execution_control import ClaimControl, FinishControl
from target_budget import binding
from routers.jobs import claim_job, finish_execution, delete_job
from routers.engagements import configure_targets, TargetPolicy
user={"github_id":"target-owner","scope":"full"}
request=Request({"type":"http","headers":[(b"authorization",b"Bearer vmap_synthetic_target_fixture")]})
case={"id":"synthetic","request":{"method":"GET","url":"https://api.example.test/object"},"identities":[]}
body={"runner_id":"00000000-0000-0000-0000-000000000001","origin":"http://localhost","target_binding":binding(case)}
with Session(engine) as db:
    db.add(User(github_id=user["github_id"],username="fixture")); db.commit()
for iteration in range(20):
    eng=f"target-eng-{iteration}"; ids=[f"target-job-{iteration}-{i}" for i in range(2)]
    with Session(engine) as db:
        db.add(Engagement(id=eng,owner_github_id=user["github_id"],name="fixture",target_limit=1)); db.commit()
        db.add(AuthorizationTestCase(id=eng,program_id=eng,owner_github_id=user["github_id"],name="fixture",spec=case)); db.commit()
        for ident in ids:
            db.add(ScanJob(id=ident,program_id=eng,owner_github_id=user["github_id"],tool_type="vardrgate_api_test",target_source="scope",status="pending",config={"test_case_id":eng}))
        db.commit()
    barrier=threading.Barrier(2)
    def claim(ident):
        with Session(engine) as db:
            barrier.wait(3)
            try: return ident,200,claim_job(ident,request,ClaimControl(**body),user,db)
            except HTTPException as exc: return ident,exc.status_code,None
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(claim,ids))
    assert sorted(r[1] for r in results)==[200,409], results
    winner=next(r for r in results if r[1]==200); loser=next(r[0] for r in results if r[1]==409)
    payload={**body,"token":winner[2]["execution_control"]["token"],"outcome":"completed"}
    for _ in range(2):
        with Session(engine) as db:
            finish_execution(winner[0],FinishControl(**payload),request,user,db)
    with Session(engine) as db:
        delete_job(winner[0],user,db)
        assert db.get(Engagement,eng).targets_spent==1
        configure_targets(eng,TargetPolicy(limit=1),user,db)
    with Session(engine) as db:
        try: configure_targets(eng,TargetPolicy(limit=None),user,db)
        except HTTPException as exc: assert exc.status_code==409
        else: raise AssertionError("spent policy disabled")
    with Session(engine) as db:
        try: claim_job(loser,request,ClaimControl(**body),user,db)
        except HTTPException as exc: assert exc.status_code==409
        else: raise AssertionError("spent allowance reused")
    # A distinct engagement has an independent durable allowance.
    with Session(engine) as db:
        other=f"other-{iteration}"
        db.add(Engagement(id=other,owner_github_id=user["github_id"],name="fixture",target_limit=1)); db.commit()
        db.add(AuthorizationTestCase(id=other,program_id=other,owner_github_id=user["github_id"],name="fixture",spec=case)); db.commit()
        db.add(ScanJob(id=other,program_id=other,owner_github_id=user["github_id"],tool_type="vardrgate_api_test",target_source="scope",status="pending",config={"test_case_id":other})); db.commit()
        separate=claim_job(other,request,ClaimControl(**body),user,db)
        assert separate["execution_control"]["target_budget"]["spent"]==1
        assert db.get(Engagement,eng).targets_spent==1
        try: claim_job(loser,request,ClaimControl(**body),user,db)
        except HTTPException as exc: assert exc.status_code==409
        else: raise AssertionError("separate engagement reset first allowance")
for mode in ["enable","disable"]:
    for iteration in range(10):
        eng=f"policy-{mode}-{iteration}"
        with Session(engine) as db:
            db.add(Engagement(id=eng,owner_github_id=user["github_id"],name="fixture",target_limit=1 if mode=="disable" else None)); db.commit()
            db.add(AuthorizationTestCase(id=eng,program_id=eng,owner_github_id=user["github_id"],name="fixture",spec=case)); db.commit()
            db.add(ScanJob(id=eng,program_id=eng,owner_github_id=user["github_id"],tool_type="vardrgate_api_test",target_source="scope",status="pending",config={"test_case_id":eng})); db.commit()
        barrier=threading.Barrier(2)
        def policy():
            with Session(engine) as db:
                barrier.wait(3)
                try: configure_targets(eng,TargetPolicy(limit=None if mode=="disable" else 1),user,db); return 200
                except HTTPException as exc: return exc.status_code
        def execution():
            with Session(engine) as db:
                barrier.wait(3)
                try: claim_job(eng,request,ClaimControl(**body) if mode=="disable" else None,user,db); return 200
                except HTTPException as exc: return exc.status_code
        with ThreadPoolExecutor(2) as pool:
            left,right=pool.submit(policy),pool.submit(execution)
            outcomes=[left.result(10),right.result(10)]
            assert sorted(outcomes)==[200,409], outcomes
        with Session(engine) as db:
            engagement=db.get(Engagement,eng); job=db.get(ScanJob,eng)
            if mode=="enable":
                assert not (engagement.target_limit is not None and job.status=="running")
                assert engagement.targets_spent==0
            elif job.status=="running":
                assert engagement.target_limit==1 and engagement.targets_spent==1
            else:
                assert engagement.target_limit is None and engagement.targets_spent==0
print("PASS: 20 competing target claims and separate-engagement claims; duplicate finish/deletion holds; 10 enable and 10 disable races")
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND,
                            env={**os.environ, "DATABASE_URL": url, "ENV": "staging"},
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
