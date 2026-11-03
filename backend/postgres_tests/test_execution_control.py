"""Real production-dialect lock-order regression, in disposable test schemas."""

import os
import subprocess
import sys

from postgres_tests.test_migrations import BACKEND, database as database, migrate


def test_cancel_finish_race_preserves_stop_or_prior_completion(database):
    engine, url = database
    migrate(url, "upgrade", "head")
    code = r"""
import hashlib, secrets, threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from fastapi import BackgroundTasks, HTTPException, Request
from sqlalchemy import event
from sqlalchemy.orm import Session
from db import engine
from models import Engagement, JobExecution, ScanJob, User
from execution_control import FinishControl
from routers.jobs import JobStatusUpdate, finish_execution, update_job
@event.listens_for(engine, "connect")
def bounded(connection, _):
    cursor=connection.cursor()
    cursor.execute("SET lock_timeout = '2s'")
    cursor.execute("SET statement_timeout = '5s'")
    cursor.close()
user={"github_id":"race-owner","scope":"full"}
authorization="Bearer vmap_" + secrets.token_hex(16)
request=Request({"type":"http","headers":[(b"authorization",authorization.encode())]})
with Session(engine) as db:
    db.add(User(github_id="race-owner",username="fixture")); db.commit()
    db.add(Engagement(id="race-eng",owner_github_id="race-owner",name="Synthetic race")); db.commit()
for index in range(20):
    job_id=f"race-job-{index}"
    token=secrets.token_hex(24)
    runner_id="00000000-0000-0000-0000-000000000001"
    with Session(engine) as db:
        db.add(ScanJob(id=job_id,program_id="race-eng",owner_github_id="race-owner",
                       tool_type="httpx",target_source="scope",status="running")); db.commit()
        db.add(JobExecution(job_id=job_id,runner_id=runner_id,origin="http://localhost",owner="race-owner",
                            principal_hash=hashlib.sha256(authorization.encode()).hexdigest(),
                            token_hash=hashlib.sha256(token.encode()).hexdigest(),
                            expires_at=datetime.utcnow()+timedelta(minutes=1),state="active")); db.commit()
    barrier=threading.Barrier(2)
    def cancel():
        with Session(engine) as db:
            barrier.wait(timeout=3)
            try:
                update_job(job_id,JobStatusUpdate(status="failed",error_message="cancelled"),BackgroundTasks(),user,db)
                return 200
            except HTTPException as exc:
                return exc.status_code
    def finish():
        with Session(engine) as db:
            barrier.wait(timeout=3)
            try:
                finish_execution(job_id,FinishControl(runner_id=runner_id,origin="http://localhost",token=token,outcome="completed"),request,user,db)
                return 200
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(2) as pool:
        left,right=pool.submit(cancel),pool.submit(finish)
        outcomes=[left.result(timeout=10),right.result(timeout=10)]
    with Session(engine) as db:
        execution=db.get(JobExecution,job_id); job=db.get(ScanJob,job_id)
        assert outcomes in ([200,409],[409,200]), outcomes
        if execution.state == "cancel_requested":
            assert job.status == "running" and job.completed_at is None
        else:
            assert execution.state == "completed" and job.status == "done"
print("20 cancel/finish races: no deadlock, lost stop or false cancellation")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url, "ENV": "staging"},
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
