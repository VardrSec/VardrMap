import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import enforcement
import redaction
import sse as _sse
from db import get_db
from deps import (
    accessible_engagement_ids,
    get_current_user,
    get_engagement_or_404,
    log_action,
    require_member_write,
)
from limiter import limiter
from models import (
    AuthorizationTestCase,
    Evidence,
    JobEvent,
    JobResultReceipt,
    ReconItem,
    ScanItem,
    ScanJob,
    ScheduledScan,
    ScopeItem,
    User,
)
from notifications import send_webhook

router = APIRouter(tags=["jobs"])

# Schedule intervals live here (not in routers/schedules.py) because both this
# module and schedules.py need them, and schedules.py already imports from here.
SCHEDULE_INTERVALS: dict[str, timedelta] = {
    "hourly": timedelta(hours=1),
    "daily":  timedelta(days=1),
    "weekly": timedelta(weeks=1),
}


EventKind = Literal["started", "targets_resolved", "running", "uploaded", "done", "failed", "log"]


class EventCreate(BaseModel):
    kind: EventKind
    text: str = Field(default="", max_length=2000)


# VardrGate jobs are self-contained: the request under test travels inside the
# stored test case rather than being resolved from scope or recon.
_VARDRGATE = "vardrgate_api_test"

_VALID_TOOLS = {"httpx", "nuclei", "subfinder", "nmap", "dnsx", "naabu", _VARDRGATE}
_VALID_SOURCES = {"scope", "recon"}

# Per-tool allowed config keys. Keys not in this set are rejected.
_TOOL_CONFIG_KEYS: dict[str, set[str]] = {
    "httpx":     {"status_code", "limit"},
    "nuclei":    {"severity", "templates"},
    "subfinder": {"recursive", "sources"},
    "nmap":      {"top_ports", "timing"},
    "dnsx":      {"limit", "timeout"},
    "naabu":     {"top_ports", "limit", "timeout"},
    # Only the reference. The spec is stored in authorization_test_cases and
    # inlined at hand-off, which keeps this config flat like every other tool's.
    _VARDRGATE:  {"test_case_id", "timeout"},
}
_NUCLEI_SEVERITIES = {"info", "low", "medium", "high", "critical"}

# Config keys parsed as plain integers, with the bounds VardrRunner enforces.
# Keeping the bounds here means a bad value is refused at queue time rather than
# failing on the operator's machine after the job has been claimed.
_INT_CONFIG_BOUNDS: dict[tuple[str, str], tuple[int, int]] = {
    ("dnsx", "limit"):       (1, 1_000_000),
    ("dnsx", "timeout"):     (1, 86_400),
    ("naabu", "top_ports"):  (1, 65_535),
    ("naabu", "limit"):      (1, 1_000_000),
    ("naabu", "timeout"):    (1, 86_400),
}


def _validate_test_case_ref(program_id: str, config: dict, db: Session) -> None:
    """A vardrgate job must name a test case that exists in this engagement.

    Checked at queue time rather than at hand-off: a job referencing a missing or
    borrowed case can never run, and refusing it here beats letting it sit pending
    until a runner picks it up and fails it. Scoping by `program_id` also stops the
    field being used to pull another engagement's case into a job.
    """
    tc_id = str((config or {}).get("test_case_id") or "").strip()
    if not tc_id:
        raise HTTPException(
            status_code=400,
            detail=f"{_VARDRGATE} requires config.test_case_id",
        )
    exists = (
        db.query(AuthorizationTestCase.id)
        .filter(
            AuthorizationTestCase.id == tc_id,
            AuthorizationTestCase.program_id == program_id,
        )
        .first()
    )
    if not exists:
        raise HTTPException(
            status_code=404,
            detail="Test case not found",
        )


def _validate_job_config(tool_type: str, config: dict) -> None:
    allowed = _TOOL_CONFIG_KEYS.get(tool_type, set())
    unknown = set(config.keys()) - allowed
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown config keys for {tool_type}: {sorted(unknown)}",
        )
    if tool_type == "httpx" and "limit" in config:
        try:
            int(config["limit"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="httpx config.limit must be an integer")
    if tool_type == "nuclei" and config.get("severity"):
        parts = [s.strip() for s in str(config["severity"]).split(",") if s.strip()]
        bad = [s for s in parts if s not in _NUCLEI_SEVERITIES]
        if bad:
            raise HTTPException(
                status_code=400,
                detail=f"nuclei severity must be info/low/medium/high/critical, got: {bad}",
            )
    if tool_type == "nmap" and "timing" in config:
        try:
            t = int(config["timing"])
            if not (0 <= t <= 4):
                raise ValueError
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="nmap config.timing must be 0-4")
    for key, (low, high) in (
        (k, bounds) for (t, k), bounds in _INT_CONFIG_BOUNDS.items() if t == tool_type
    ):
        if key not in config or config[key] in (None, ""):
            continue
        try:
            value = int(config[key])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{tool_type} config.{key} must be an integer")
        if not (low <= value <= high):
            raise HTTPException(
                status_code=400, detail=f"{tool_type} config.{key} must be between {low} and {high}"
            )


class JobCreate(BaseModel):
    tool_type: str              # one of _VALID_TOOLS
    target_source: str          # "scope" or "recon"
    config: Optional[dict] = None
    depends_on: Optional[str] = None  # scan_job id this job waits on before running


class PipelineStage(BaseModel):
    tool_type: str
    target_source: str
    config: Optional[dict] = None


class PipelineCreate(BaseModel):
    # Ordered stages: each becomes a scan_job that waits on the one before it.
    # The UI's named chains (Attack Surface, Host Enumeration) are just stage lists;
    # any ordered subset is valid, since depends_on is linked over what arrives.
    stages: list[PipelineStage] = Field(min_length=1, max_length=8)


class JobStatusUpdate(BaseModel):
    status: str                          # "running" | "done" | "failed"
    error_message: Optional[str] = None


def serialize_job(j: ScanJob) -> dict:
    return {
        "id": j.id,
        "program_id": j.program_id,
        "tool_type": j.tool_type,
        "target_source": j.target_source,
        "config": j.config or {},
        "status": j.status,
        "depends_on": j.depends_on,
        "created_at":   j.created_at.isoformat()   if j.created_at   else None,
        "started_at":   j.started_at.isoformat()   if j.started_at   else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        "error_message": j.error_message or "",
    }


@router.post("/engagements/{program_id}/jobs")
def create_job(
    program_id: str,
    body: JobCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    if body.tool_type not in _VALID_TOOLS:
        raise HTTPException(status_code=400, detail=f"tool_type must be one of {sorted(_VALID_TOOLS)}")
    if body.target_source not in _VALID_SOURCES:
        raise HTTPException(status_code=400, detail="target_source must be scope or recon")
    if body.config:
        _validate_job_config(body.tool_type, body.config)
    if body.tool_type == _VARDRGATE:
        _validate_test_case_ref(program_id, body.config or {}, db)
    if body.depends_on:
        _validate_dependency(body.depends_on, program_id, current_user["github_id"], db)

    # Advisory: authorization, testing window and scope are evaluated and
    # reported, not enforced — staying in scope is the operator's call. Only
    # stop-work refuses, and that raises from inside check(). Re-checked at
    # claim, because a job queued inside the window may be claimed after it closes.
    decision = enforcement.check(
        db,
        engagement,
        capability=body.tool_type,
        targets=_resolve_targets(program_id, body.target_source, body.config or {}, db),
    )

    job = ScanJob(
        program_id=program_id,
        owner_github_id=current_user["github_id"],
        tool_type=body.tool_type,
        target_source=body.target_source,
        config=body.config or {},
        depends_on=body.depends_on,
    )
    db.add(job)
    db.flush()  # assigns job.id without committing
    log_action(db, current_user["github_id"], "create", "scan_job", job.id, program_id)
    db.commit()
    db.refresh(job)
    _sse.notify(program_id, {"type": "job_update", "job_id": job.id, "status": job.status})
    return {**serialize_job(job), "warnings": enforcement.as_warnings(decision)}


def _writable_engagement(job: ScanJob, current_user: dict, db: Session):
    """Resolve the job's engagement and refuse viewers.

    The global /jobs/{id} endpoints resolve access through
    accessible_engagement_ids, which answers "can this caller see the
    engagement" — not "may they change it". Without this, an organization
    viewer could mutate jobs they are only entitled to read.
    """
    engagement = get_engagement_or_404(job.program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    return engagement


def _check_run_transition(job: ScanJob, current_user: dict, db: Session, now) -> list[dict]:
    """Re-evaluate policy before a job enters `running`; returns any warnings.

    PATCH /jobs/{id} can set status directly — VardrRunner uses it — so this
    path is evaluated like the others. Scope and window findings are advisory
    here too; stop-work still refuses, from inside check().
    """
    engagement = get_engagement_or_404(job.program_id, current_user, db)
    decision = enforcement.check(
        db,
        engagement,
        capability=job.tool_type,
        targets=_resolve_targets(job.program_id, job.target_source, job.config or {}, db),
        now=now,
    )
    return enforcement.as_warnings(decision)


def _validate_dependency(parent_id: str, program_id: str, github_id: str, db: Session) -> None:
    """A dependency must be an existing job the caller owns in the same engagement.
    Prevents dangling waits and cross-engagement/cross-user references."""
    parent = (
        db.query(ScanJob)
        .filter(
            ScanJob.id == parent_id,
            ScanJob.program_id.in_(accessible_engagement_ids(github_id, db)),
            ScanJob.program_id == program_id,
        )
        .first()
    )
    if not parent:
        raise HTTPException(status_code=400, detail="depends_on must reference an existing job in this engagement")


@router.post("/engagements/{program_id}/pipelines", status_code=201)
def create_pipeline(
    program_id: str,
    body: PipelineCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Queue an ordered chain of jobs where each stage waits on the previous one.

    The canonical recon pipeline is subfinder -> httpx -> nuclei: one click queues
    all three, and each stage only becomes eligible in GET /jobs/pending once its
    parent completes. Validation is per-stage and identical to single-job creation,
    so a bad stage rejects the whole pipeline before anything is written.
    """
    engagement = get_engagement_or_404(program_id, current_user, db)
    require_member_write(engagement, current_user, db)
    for i, stage in enumerate(body.stages):
        if stage.tool_type not in _VALID_TOOLS:
            raise HTTPException(status_code=400, detail=f"stage {i}: tool_type must be one of {sorted(_VALID_TOOLS)}")
        if stage.target_source not in _VALID_SOURCES:
            raise HTTPException(status_code=400, detail=f"stage {i}: target_source must be scope or recon")
        if stage.config:
            _validate_job_config(stage.tool_type, stage.config)
        if stage.tool_type == _VARDRGATE:
            _validate_test_case_ref(program_id, stage.config or {}, db)

    created: list[ScanJob] = []
    prev_id: Optional[str] = None
    for stage in body.stages:
        job = ScanJob(
            program_id=program_id,
            owner_github_id=current_user["github_id"],
            tool_type=stage.tool_type,
            target_source=stage.target_source,
            config=stage.config or {},
            depends_on=prev_id,
        )
        db.add(job)
        db.flush()  # assign job.id so the next stage can depend on it
        log_action(db, current_user["github_id"], "create", "scan_job", job.id, program_id)
        created.append(job)
        prev_id = job.id
    db.commit()
    for job in created:
        db.refresh(job)
    _sse.notify(program_id, {"type": "job_update", "job_id": created[0].id, "status": created[0].status})
    return {"jobs": [serialize_job(j) for j in created]}


class JobPreview(BaseModel):
    tool_type: str
    target_source: str
    config: Optional[dict] = None


def _resolve_targets(program_id: str, target_source: str, config: dict, db: Session) -> list[str]:
    """Resolve the target list a job would run against, server-side. This mirrors what
    VardrRunner fetches (in-scope items for 'scope'; recon rows for 'recon') so the UI
    can show a dry-run preview before queuing. It is an estimate — the runner applies
    final host normalization — but it catches "I'm about to scan 4,000 hosts" mistakes."""
    if target_source == "scope":
        rows = (
            db.query(ScopeItem.value)
            .filter(ScopeItem.program_id == program_id, ScopeItem.scope_type == "in")
            .all()
        )
        targets = [v for (v,) in rows if v]
    else:  # recon
        rows = (
            db.query(ReconItem.url, ReconItem.host)
            .filter(ReconItem.program_id == program_id)
            .all()
        )
        targets = [url or host for (url, host) in rows if (url or host)]
    # De-dup while preserving order.
    seen: set[str] = set()
    deduped = [t for t in targets if not (t in seen or seen.add(t))]
    if config and config.get("limit"):
        try:
            deduped = deduped[: int(config["limit"])]
        except (TypeError, ValueError):
            pass
    return deduped


@router.post("/engagements/{program_id}/jobs/preview")
def preview_job(
    program_id: str,
    body: JobPreview,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Dry-run: resolve the targets a job would run against without queuing anything.
    Returns the total count and a capped sample so the Composer can confirm intent."""
    get_engagement_or_404(program_id, current_user, db)
    if body.tool_type not in _VALID_TOOLS:
        raise HTTPException(status_code=400, detail=f"tool_type must be one of {sorted(_VALID_TOOLS)}")
    if body.target_source not in _VALID_SOURCES:
        raise HTTPException(status_code=400, detail="target_source must be scope or recon")
    if body.config:
        _validate_job_config(body.tool_type, body.config)
    targets = _resolve_targets(program_id, body.target_source, body.config or {}, db)
    return {
        "tool_type": body.tool_type,
        "target_source": body.target_source,
        "count": len(targets),
        "sample": targets[:20],
        "truncated": len(targets) > 20,
    }


@router.get("/engagements/{program_id}/jobs")
def list_jobs(
    program_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_engagement_or_404(program_id, current_user, db)
    jobs = (
        db.query(ScanJob)
        .filter(ScanJob.program_id == program_id)
        .order_by(ScanJob.created_at.desc())
        .all()
    )
    return {"jobs": [serialize_job(j) for j in jobs]}


def _materialize_due_schedules(db: Session, github_id: str) -> None:
    """Turn due scheduled scans into pending jobs and advance their next_run_at.

    next_run_at advances from now (not from the old next_run_at) so a daemon
    that was offline for a week creates one catch-up job, not seven.
    """
    now = datetime.now(timezone.utc)
    due = (
        db.query(ScheduledScan)
        .filter(
            ScheduledScan.program_id.in_(accessible_engagement_ids(github_id, db)),
            ScheduledScan.enabled == True,  # noqa: E712 — SQLAlchemy needs the comparison
            ScheduledScan.next_run_at <= now,
        )
        .all()
    )
    for schedule in due:
        db.add(ScanJob(
            program_id=schedule.program_id,
            owner_github_id=github_id,
            tool_type=schedule.tool_type,
            target_source=schedule.target_source,
            config=schedule.config or {},
        ))
        schedule.last_run_at = now
        schedule.next_run_at = now + SCHEDULE_INTERVALS.get(schedule.interval, timedelta(days=1))
    if due:
        db.commit()


@router.get("/jobs/pending")
def get_pending_jobs(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pending jobs the runner may execute now, oldest first. Used by VardrRunner to poll.

    Pipeline stages with an unmet dependency are held back: a job waits until its
    parent is "done", and is auto-failed if its parent failed (or vanished) so it
    never hangs the queue forever.

    A `vardrgate_api_test` job stores only `test_case_id`; the stored spec is
    inlined here so the runner receives the `test_case` object its config parser
    expects. See `_inline_test_cases`.
    """
    _materialize_due_schedules(db, current_user["github_id"])
    pending = (
        db.query(ScanJob)
        .filter(
            ScanJob.program_id.in_(accessible_engagement_ids(current_user["github_id"], db)),
            ScanJob.status == "pending",
        )
        .order_by(ScanJob.created_at.asc())
        .all()
    )
    eligible = _filter_by_dependencies(pending, db)
    eligible, specs = _resolve_test_cases(eligible, db)
    return {"jobs": [_serialize_with_spec(j, specs) for j in eligible]}


def _resolve_test_cases(
    jobs: list[ScanJob], db: Session
) -> tuple[list[ScanJob], dict[str, dict]]:
    """Look up the stored spec for each vardrgate job. Returns (eligible, job_id -> spec).

    A vardrgate job stores only `test_case_id`, which keeps `ScanJob.config` flat
    for validation and lets one stored case back many runs. VardrRunner's
    `VardrGateConfig.from_dict` requires `test_case` as an object, so the spec is
    inlined at hand-off — which is what lets this integration land without a
    VardrRunner release.

    The spec is returned alongside rather than written onto the job, so the
    expansion exists only in the response and can never be flushed back into
    `scan_jobs.config`.

    A job whose case has been deleted is auto-failed rather than handed over: it
    can never succeed, and leaving it pending would hang the queue the same way a
    dangling dependency does.
    """
    targets = [j for j in jobs if j.tool_type == _VARDRGATE]
    if not targets:
        return jobs, {}

    wanted = {str((j.config or {}).get("test_case_id") or "") for j in targets}
    wanted.discard("")
    # Keyed by (case id, engagement) so a case can never be pulled across engagements.
    stored: dict[tuple[str, str], dict] = {}
    if wanted:
        for row in (
            db.query(AuthorizationTestCase)
            .filter(AuthorizationTestCase.id.in_(wanted))
            .all()
        ):
            stored[(row.id, row.program_id)] = row.spec or {}

    eligible: list[ScanJob] = []
    specs: dict[str, dict] = {}
    failed = False
    now = datetime.now(timezone.utc)
    for job in jobs:
        if job.tool_type != _VARDRGATE:
            eligible.append(job)
            continue
        tc_id = str((job.config or {}).get("test_case_id") or "")
        spec = stored.get((tc_id, job.program_id))
        if not spec:
            job.status = "failed"
            job.completed_at = now
            job.error_message = (
                f"authorization test case {tc_id or '(unset)'} no longer exists"
            )
            failed = True
            continue
        eligible.append(job)
        specs[job.id] = spec

    if failed:
        db.commit()
    return eligible, specs


def _serialize_with_spec(job: ScanJob, specs: dict[str, dict]) -> dict:
    data = serialize_job(job)
    spec = specs.get(job.id)
    if spec is not None:
        data["config"] = {**data["config"], "test_case": spec}
    return data


def _filter_by_dependencies(pending: list[ScanJob], db: Session) -> list[ScanJob]:
    """Return only jobs whose dependency is satisfied. Auto-fail jobs whose parent
    failed or no longer exists so they don't wait forever."""
    eligible: list[ScanJob] = []
    now = datetime.now(timezone.utc)
    changed = False
    # Resolve parent statuses in one query rather than per-job.
    parent_ids = {j.depends_on for j in pending if j.depends_on}
    parent_status: dict[str, str] = {}
    if parent_ids:
        for pid, status in db.query(ScanJob.id, ScanJob.status).filter(ScanJob.id.in_(parent_ids)).all():
            parent_status[pid] = status
    for job in pending:
        if not job.depends_on:
            eligible.append(job)
            continue
        status = parent_status.get(job.depends_on)
        if status == "done":
            eligible.append(job)
        elif status in (None, "failed"):
            job.status = "failed"
            job.completed_at = now
            job.error_message = "upstream pipeline stage failed" if status == "failed" else "upstream pipeline stage not found"
            changed = True
        # parent still pending/running -> hold this stage, don't surface it
    if changed:
        db.commit()
    return eligible


@router.patch("/jobs/{job_id}")
def update_job(
    job_id: str,
    body: JobStatusUpdate,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update job status. VardrRunner uses this to claim (running) and complete (done/failed) jobs."""
    job = (
        db.query(ScanJob)
        .filter(
            ScanJob.id == job_id,
            ScanJob.program_id.in_(accessible_engagement_ids(current_user["github_id"], db)),
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=404)

    valid = ("pending", "running", "done", "failed")
    if body.status not in valid:
        raise HTTPException(status_code=400, detail=f"status must be one of {valid}")

    _writable_engagement(job, current_user, db)

    now = datetime.now(timezone.utc)
    warnings: list[dict] = []
    if body.status == "running" and job.status != "running":
        warnings = _check_run_transition(job, current_user, db, now)

    job.status = body.status
    if body.status == "running" and not job.started_at:
        job.started_at = now
    if body.status in ("done", "failed"):
        job.completed_at = datetime.now(timezone.utc)
    if body.error_message is not None:
        job.error_message = body.error_message

    db.commit()
    db.refresh(job)

    # Notify on failure — but not for operator-initiated cancels (the user
    # clicked the button themselves; a webhook ping would just be noise)
    is_cancel = "cancelled" in (job.error_message or "").lower()
    if body.status == "failed" and not is_cancel:
        user = db.query(User).filter(User.github_id == current_user["github_id"]).first()
        if user and user.webhook_url:
            program_name = job.engagement.name if job.engagement else job.program_id
            message = (
                f"❌ VardrMap: {job.tool_type} job failed for {program_name}"
                + (f" — {job.error_message[:300]}" if job.error_message else "")
            )
            background_tasks.add_task(send_webhook, user.webhook_url, message)

    return {**serialize_job(job), "warnings": warnings}


@router.post("/jobs/{job_id}/claim")
def claim_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Atomically claim a pending job. Returns 409 if the job is not in 'pending'
    state, 404 if it does not exist or is not owned by the caller.

    The transition is a single conditional UPDATE (... WHERE status = 'pending'),
    so when two runners race for the same job exactly one wins — the database,
    not application-level read-then-write, enforces it. The affected row count
    tells us whether this caller made the transition.
    """
    now = datetime.now(timezone.utc)

    # Re-evaluate before handing work to a runner. A job queued while the testing
    # window was open may be claimed after it closed, or after stop-work was
    # engaged. Scope and window findings ride back as warnings; stop-work refuses.
    # This read does not weaken the claim race below: the conditional UPDATE is
    # still what arbitrates between two runners.
    warnings: list[dict] = []
    pending = (
        db.query(ScanJob)
        .filter(
            ScanJob.id == job_id,
            ScanJob.program_id.in_(accessible_engagement_ids(current_user["github_id"], db)),
        )
        .first()
    )
    if pending is not None:
        _writable_engagement(pending, current_user, db)
    if pending is not None and pending.status == "pending":
        engagement = get_engagement_or_404(pending.program_id, current_user, db)
        warnings = enforcement.as_warnings(
            enforcement.check(
                db,
                engagement,
                capability=pending.tool_type,
                targets=_resolve_targets(
                    pending.program_id, pending.target_source, pending.config or {}, db
                ),
                now=now,
            )
        )

    claimed = (
        db.query(ScanJob)
        .filter(
            ScanJob.id == job_id,
            ScanJob.program_id.in_(accessible_engagement_ids(current_user["github_id"], db)),
            ScanJob.status == "pending",
        )
        .update(
            {ScanJob.status: "running", ScanJob.started_at: now},
            synchronize_session=False,
        )
    )
    db.commit()

    if claimed == 0:
        # We didn't win the transition. Read once to distinguish "not found / not
        # mine" (404) from "exists but no longer pending" (409). The read stays
        # scoped to the owner so a non-owner's job is reported as 404, not 403.
        job = (
            db.query(ScanJob)
            .filter(
            ScanJob.id == job_id,
            ScanJob.program_id.in_(accessible_engagement_ids(current_user["github_id"], db)),
        )
            .first()
        )
        if not job:
            raise HTTPException(status_code=404)
        raise HTTPException(status_code=409, detail=f"job is already {job.status}")

    job = (
        db.query(ScanJob)
        .filter(
            ScanJob.id == job_id,
            ScanJob.program_id.in_(accessible_engagement_ids(current_user["github_id"], db)),
        )
        .first()
    )
    return {**serialize_job(job), "warnings": warnings}


def serialize_event(e: JobEvent) -> dict:
    return {
        "id":             e.id,
        "job_id":         e.job_id,
        "kind":           e.kind,
        "text":           e.text,
        "created_at":     e.created_at.isoformat() if e.created_at else None,
    }


@router.post("/jobs/{job_id}/events", status_code=201)
@limiter.limit("600/minute")
def create_job_event(
    request: Request,
    job_id: str,
    body: EventCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """VardrRunner posts lifecycle events here while executing a job."""
    job = (
        db.query(ScanJob)
        .filter(
            ScanJob.id == job_id,
            ScanJob.program_id.in_(accessible_engagement_ids(current_user["github_id"], db)),
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=404)
    _writable_engagement(job, current_user, db)

    event = JobEvent(
        job_id=job_id,
        owner_github_id=current_user["github_id"],
        kind=body.kind,
        text=body.text,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    if body.kind in ("done", "failed"):
        _sse.notify(job.program_id, {"type": "job_update", "job_id": job_id, "status": body.kind})
    return serialize_event(event)


@router.delete("/jobs/{job_id}")
def delete_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Permanently delete a job and its events. Useful for removing stuck jobs."""
    job = (
        db.query(ScanJob)
        .filter(
            ScanJob.id == job_id,
            ScanJob.program_id.in_(accessible_engagement_ids(current_user["github_id"], db)),
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=404)
    _writable_engagement(job, current_user, db)
    log_action(db, current_user["github_id"], "delete", "scan_job", job_id, job.program_id)
    db.delete(job)
    db.commit()
    return {"message": "Job deleted"}


@router.get("/jobs/{job_id}/events")
def get_job_events(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Frontend polls this to stream job lifecycle events into the Terminal."""
    job = (
        db.query(ScanJob)
        .filter(
            ScanJob.id == job_id,
            ScanJob.program_id.in_(accessible_engagement_ids(current_user["github_id"], db)),
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=404)

    events = (
        db.query(JobEvent)
        .filter(JobEvent.job_id == job_id)
        .order_by(JobEvent.created_at.asc())
        .all()
    )
    return {"events": [serialize_event(e) for e in events]}


# -----------------------------------------------------------------------------
# VardrGate result upload
# -----------------------------------------------------------------------------

# VardrGate's model.Severity — identical to the set used everywhere else here, so
# no translation is needed, only validation.
_VG_SEVERITIES = {"info", "low", "medium", "high", "critical"}
_MAX_RESULT_BYTES = 512_000


class VardrGateUpload(BaseModel):
    """One `engine.Result` from VardrGate.

    Fields mirror the Go struct. `executions[].body` and every credential value
    carry `json:"-"` upstream, so a well-behaved runner never sends them — but
    everything stored here is redacted regardless, because the guarantee should
    not rest on the sender.
    """

    test_case_id: str = Field(default="", max_length=200)
    executions: list[dict] = Field(default_factory=list, max_length=100)
    findings: list[dict] = Field(default_factory=list, max_length=500)


def _finding_description(finding: dict) -> str:
    """Readable detail: which identity, how confident, and the evidence lines."""
    parts: list[str] = []
    identity = str(finding.get("identity_id") or "").strip()
    if identity:
        parts.append(f"identity: {identity}")
    confidence = str(finding.get("confidence") or "").strip()
    if confidence:
        parts.append(f"confidence: {confidence}")
    evidence = finding.get("evidence")
    if isinstance(evidence, list):
        for line in evidence[:20]:
            if str(line).strip():
                parts.append(str(line))
    return redaction.redact_text("\n".join(parts))


@router.post("/jobs/{job_id}/upload")
def upload_job_result(
    job_id: str,
    body: VardrGateUpload,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Receive a VardrGate result and file it against the engagement.

    Findings become `scan_items` with `source="vardrgate"`, which puts them
    through the triage and promote-to-finding flow nuclei results already use
    rather than inventing a parallel one. `template_id` carries the VardrGate test
    case id, the same role a nuclei template id plays.

    Executions become `evidence` — the request/response record backing each
    finding, with the content hash and retention handling that entity already
    provides.

    Everything is redacted on write. VardrGate excludes credential values and
    response bodies from its own JSON, but a control that depends on the sender
    behaving is not a control.
    """
    job = (
        db.query(ScanJob)
        .filter(
            ScanJob.id == job_id,
            ScanJob.program_id.in_(accessible_engagement_ids(current_user["github_id"], db)),
        )
        .with_for_update()
        .first()
    )
    if not job:
        raise HTTPException(status_code=404)
    _writable_engagement(job, current_user, db)

    if job.tool_type != _VARDRGATE:
        raise HTTPException(
            status_code=400,
            detail=f"job {job_id} is a '{job.tool_type}' job; /upload accepts {_VARDRGATE} results",
        )

    canonical_payload = json.dumps(
        body.model_dump(), sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    if len(canonical_payload) > _MAX_RESULT_BYTES:
        raise HTTPException(status_code=413, detail="result payload is too large")
    payload_hash = hashlib.sha256(canonical_payload).hexdigest()

    receipt = db.query(JobResultReceipt).filter(JobResultReceipt.job_id == job.id).first()
    if receipt:
        if receipt.payload_hash != payload_hash:
            raise HTTPException(
                status_code=409,
                detail="this job already has a different uploaded result",
            )
        return {
            "job_id": job.id,
            "scan_items_created": receipt.scan_items_created,
            "evidence_created": receipt.evidence_created,
            "already_processed": True,
        }

    # The test case id on the job is authoritative: it is what was queued. A
    # mismatched id in the payload means the runner ran something else.
    queued_case = str((job.config or {}).get("test_case_id") or "")
    template_id = str(body.test_case_id or "")[:200]

    target = ""
    case = (
        db.query(AuthorizationTestCase)
        .filter(
            AuthorizationTestCase.id == queued_case,
            AuthorizationTestCase.program_id == job.program_id,
        )
        .first()
    )
    if case:
        target = str(((case.spec or {}).get("request") or {}).get("url") or "")[:2000]
        authoritative_id = case.test_case_id or ""
        if template_id and template_id != authoritative_id:
            raise HTTPException(
                status_code=400,
                detail="result test_case_id does not match the test case queued for this job",
            )
        template_id = authoritative_id

    created_items = 0
    for finding in body.findings:
        if not isinstance(finding, dict):
            continue
        severity = str(finding.get("severity") or "info").lower().strip()
        if severity not in _VG_SEVERITIES:
            # Unknown severity ranks below info upstream; mirror that rather than
            # guessing, so an added level never silently reads as critical.
            severity = "info"
        message = redaction.redact_text(str(finding.get("message") or ""))
        db.add(
            ScanItem(
                program_id=job.program_id,
                source="vardrgate",
                template_id=template_id,
                title=message[:200] or str(finding.get("category") or "authorization finding"),
                severity=severity,
                asset=target,
                matched_at=target,
                type=str(finding.get("category") or "")[:50],
                description=_finding_description(finding),
                status="new",
                job_id=job.id,
            )
        )
        created_items += 1

    created_evidence = 0
    for execution in body.executions:
        if not isinstance(execution, dict):
            continue
        identity = str(execution.get("identity_id") or "unknown")
        detail: dict[str, Any] = {
            "identity_id": identity,
            "status_code": execution.get("status_code"),
            "observed_outcome": execution.get("observed_outcome"),
            "duration_ms": execution.get("duration_ms"),
            "headers": execution.get("headers") or {},
        }
        if execution.get("error"):
            detail["error"] = execution.get("error")
            detail["error_kind"] = execution.get("error_kind")
        if isinstance(execution.get("response_profile"), dict):
            # Newer VardrGate versions emit a body-free structural profile.
            # Preserve it as evidence without coupling this endpoint to that
            # independently versioned schema.
            detail["response_profile"] = execution["response_profile"]
        text = json.dumps(redaction.redact_mapping(detail), indent=2, sort_keys=True, default=str)
        db.add(
            Evidence(
                program_id=job.program_id,
                kind="tool_result",
                title=f"vardrgate · {identity} → {execution.get('status_code', '?')}"[:200],
                body=text,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                collector="vardrrunner",
                source="vardrgate",
                sensitivity="confidential",
                retention="engagement",
                redacted=True,
                collected_at=datetime.now(timezone.utc),
            )
        )
        created_evidence += 1

    log_action(db, current_user["github_id"], "create", "vardrgate_result", job.id, job.program_id)
    db.add(JobResultReceipt(
        job_id=job.id,
        payload_hash=payload_hash,
        scan_items_created=created_items,
        evidence_created=created_evidence,
    ))
    db.commit()
    _sse.notify(job.program_id, {"type": "job_update", "job_id": job.id, "status": job.status})
    return {
        "job_id": job.id,
        "scan_items_created": created_items,
        "evidence_created": created_evidence,
        "already_processed": False,
    }
