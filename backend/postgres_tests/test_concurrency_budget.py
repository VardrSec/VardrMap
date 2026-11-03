"""Production-dialect capacity races in isolated schemas, both fixture roles."""
import os
import subprocess
import sys

from postgres_tests.test_migrations import BACKEND, database as database, migrate


def test_budget_competing_claims_and_policy_races(database):
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
from routers.jobs import claim_job, finish_execution
from routers.engagements import configure_concurrency, ConcurrencyPolicy
user={"github_id":"budget-owner","scope":"full"}
request=Request({"type":"http","headers":[(b"authorization",b"Bearer vmap_public_synthetic_fixture")]})
binding={"runner_id":"00000000-0000-0000-0000-000000000001","origin":"http://localhost","concurrency_budget":True}
with Session(engine) as db:
    db.add(User(github_id=user["github_id"],username="fixture")); db.commit()
    for ident in ["eng-a","eng-b"]:
        db.add(Engagement(id=ident,owner_github_id=user["github_id"],name="fixture",concurrency_limit=1))
    db.commit()
for iteration in range(20):
    ids=[f"job-{iteration}-{n}" for n in range(2)]
    with Session(engine) as db:
        for ident in ids:
            db.add(ScanJob(id=ident,program_id="eng-a",owner_github_id=user["github_id"],tool_type="httpx",target_source="scope",status="pending"))
        db.commit()
    barrier=threading.Barrier(2)
    def claim(ident):
        with Session(engine) as db:
            barrier.wait(3)
            try: return ident,200,claim_job(ident,request,ClaimControl(**binding),user,db)
            except HTTPException as exc: return ident,exc.status_code,None
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(claim,ids))
    assert sorted(r[1] for r in results)==[200,409], results
    winner=next(r for r in results if r[1]==200)
    with Session(engine) as db:
        assert db.query(JobExecution).filter_by(capacity_reserved=True).count()==1
        try: configure_concurrency("eng-a",ConcurrencyPolicy(limit=None),user,db)
        except HTTPException as exc: assert exc.status_code==409; db.rollback()
        else: raise AssertionError("policy disabled over reservation")
    payload={**binding,"token":winner[2]["execution_control"]["token"],"outcome":"completed"}
    for _ in range(2):
        with Session(engine) as db:
            finish_execution(winner[0],FinishControl(**payload),request,user,db)
    with Session(engine) as db:
        assert db.query(JobExecution).filter_by(capacity_reserved=True).count()==0
for iteration in range(10):
    eng=f"enable-{iteration}"; ident=f"enable-job-{iteration}"
    with Session(engine) as db:
        db.add(Engagement(id=eng,owner_github_id=user["github_id"],name="fixture")); db.commit()
        db.add(ScanJob(id=ident,program_id=eng,owner_github_id=user["github_id"],tool_type="httpx",target_source="scope",status="pending")); db.commit()
    barrier=threading.Barrier(2)
    def configure():
        with Session(engine) as db:
            barrier.wait(3)
            try: configure_concurrency(eng,ConcurrencyPolicy(limit=1),user,db); return 200
            except HTTPException as exc: return exc.status_code
    def legacy():
        with Session(engine) as db:
            barrier.wait(3)
            try: claim_job(ident,request,None,user,db); return 200
            except HTTPException as exc: return exc.status_code
    with ThreadPoolExecutor(2) as pool:
        left,right=pool.submit(configure),pool.submit(legacy)
        assert sorted([left.result(10),right.result(10)])==[200,409]
for iteration in range(10):
    eng=f"disable-{iteration}"; ident=f"disable-job-{iteration}"
    with Session(engine) as db:
        db.add(Engagement(id=eng,owner_github_id=user["github_id"],name="fixture",concurrency_limit=1)); db.commit()
        db.add(ScanJob(id=ident,program_id=eng,owner_github_id=user["github_id"],tool_type="httpx",target_source="scope",status="pending")); db.commit()
    barrier=threading.Barrier(2)
    def disable():
        with Session(engine) as db:
            barrier.wait(3)
            try: configure_concurrency(eng,ConcurrencyPolicy(limit=None),user,db); return 200
            except HTTPException as exc: return exc.status_code
    def budgeted():
        with Session(engine) as db:
            barrier.wait(3)
            try: claim_job(ident,request,ClaimControl(**binding),user,db); return 200
            except HTTPException as exc: return exc.status_code
    with ThreadPoolExecutor(2) as pool:
        left,right=pool.submit(disable),pool.submit(budgeted)
        assert sorted([left.result(10),right.result(10)])==[200,409]
with Session(engine) as db:
    for eng in ["eng-a","eng-b"]:
        db.add(ScanJob(id=f"isolated-{eng}",program_id=eng,owner_github_id=user["github_id"],tool_type="httpx",target_source="scope",status="pending"))
    db.commit()
barrier=threading.Barrier(2)
with ThreadPoolExecutor(2) as pool:
    results=list(pool.map(claim,["isolated-eng-a","isolated-eng-b"]))
assert [r[1] for r in results]==[200,200], results
print("PASS: 20 competing claims; duplicate release; 10 enable and 10 disable races; separate engagements")
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND,
                            env={**os.environ, "DATABASE_URL": url, "ENV": "staging"},
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
