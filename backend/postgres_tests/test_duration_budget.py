"""Finite allocation and policy races in isolated PostgreSQL role schemas."""
import os
import subprocess
import sys
from postgres_tests.test_migrations import BACKEND, database as database, migrate


def test_duration_allocations_compete_and_survive_unknown(database):
    _, url = database
    migrate(url, "upgrade", "head")
    code = r'''
import threading
from concurrent.futures import ThreadPoolExecutor
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session
from db import engine
from models import Engagement, ScanJob, User, JobExecution
from execution_control import ClaimControl, FinishControl
from routers.jobs import claim_job, finish_execution, delete_job
from routers.engagements import configure_duration, DurationPolicy
user={"github_id":"duration-owner","scope":"full"}
request=Request({"type":"http","headers":[(b"authorization",b"Bearer vmap_synthetic_duration_fixture")]})
body={"runner_id":"00000000-0000-0000-0000-000000000001","origin":"http://localhost","duration_seconds":2}
with Session(engine) as db:
    db.add(User(github_id=user["github_id"],username="fixture")); db.commit()
def create(eng, limit, ids):
    with Session(engine) as db:
        db.add(Engagement(id=eng,owner_github_id=user["github_id"],name="fixture",duration_limit=limit)); db.commit()
        for ident in ids:
            db.add(ScanJob(id=ident,program_id=eng,owner_github_id=user["github_id"],tool_type="httpx",target_source="scope",status="pending"))
        db.commit()
for iteration in range(20):
    eng=f"duration-{iteration}"; ids=[f"duration-job-{iteration}-{i}" for i in range(2)]
    create(eng,3,ids)
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
    receipt=winner[2]["execution_control"]
    assert receipt["duration_budget"]=={"allocated_seconds":2,"total_allocated_seconds":2,"limit_seconds":3}
    payload={**body,"token":receipt["token"]}
    with Session(engine) as db:
        try: claim_job(winner[0],request,ClaimControl(**body),user,db)
        except HTTPException as exc: assert exc.status_code==409
        else: raise AssertionError("duplicate claim succeeded")
    for outcome in ["uncertain","cancelled","cancelled"]:
        with Session(engine) as db:
            finish_execution(winner[0],FinishControl(**payload,outcome=outcome),request,user,db)
        # A new session/connection observes durable allocation after unknown/terminal outcomes.
        with Session(engine) as db:
            assert db.get(Engagement,eng).duration_allocated==2
            assert db.get(JobExecution,winner[0]).duration_seconds==2
    with Session(engine) as db:
        delete_job(winner[0],user,db)
        configure_duration(eng,DurationPolicy(limit_seconds=3),user,db)
        assert db.get(Engagement,eng).duration_allocated==2
    for requested in [None,1]:
        with Session(engine) as db:
            try: configure_duration(eng,DurationPolicy(limit_seconds=requested),user,db)
            except HTTPException as exc: assert exc.status_code==409
            else: raise AssertionError("allocated permission reset")
    other=f"other-duration-{iteration}"
    create(other,3,[other])
    with Session(engine) as db:
        separate=claim_job(other,request,ClaimControl(**body),user,db)
        assert separate["execution_control"]["duration_budget"]["total_allocated_seconds"]==2
        assert db.get(Engagement,eng).duration_allocated==2
        try: claim_job(loser,request,ClaimControl(**body),user,db)
        except HTTPException as exc: assert exc.status_code==409
        else: raise AssertionError("independent engagement refunded prior allocation")
for mode in ["enable","disable"]:
    for iteration in range(10):
        eng=f"duration-policy-{mode}-{iteration}"
        create(eng,2 if mode=="disable" else None,[eng])
        barrier=threading.Barrier(2)
        def policy():
            with Session(engine) as db:
                barrier.wait(3)
                try: configure_duration(eng,DurationPolicy(limit_seconds=None if mode=="disable" else 2),user,db); return 200
                except HTTPException as exc: return exc.status_code
        def execute():
            with Session(engine) as db:
                barrier.wait(3)
                try: claim_job(eng,request,ClaimControl(**body) if mode=="disable" else None,user,db); return 200
                except HTTPException as exc: return exc.status_code
        with ThreadPoolExecutor(2) as pool:
            left,right=pool.submit(policy),pool.submit(execute)
            outcomes=[left.result(10),right.result(10)]
            assert sorted(outcomes)==[200,409], outcomes
        with Session(engine) as db:
            row=db.get(Engagement,eng); job=db.get(ScanJob,eng)
            if mode=="enable":
                assert not (row.duration_limit is not None and job.status=="running")
                assert row.duration_allocated==0
            elif job.status=="running":
                assert row.duration_limit==2 and row.duration_allocated==2
            else:
                assert row.duration_limit is None and row.duration_allocated==0
print("PASS: 20 competing allocations and actual separate claims; unknown/deletion/duplicate holds; 10 enable and 10 disable races")
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND,
                            env={**os.environ, "DATABASE_URL": url, "ENV": "staging"},
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
