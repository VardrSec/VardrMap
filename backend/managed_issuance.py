"""Unregistered transactional issuer prototype; no worker or enrollment route.

Only isolated fixtures install a ContractWire and provision associations. The
ordinary jobs API refuses marked work. Runner remains the full policy validator.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import concurrency_budget
import duration_budget
import execution_control as control
import managed_authority
import target_budget
from deps import get_current_user
from managed_wire import WireRefused, digest, integer, parse, require, stamp, timestamp, unb64
from models import (
    ApiKey,
    Engagement,
    ManagedApproval,
    ManagedClock,
    ManagedContract,
    ManagedEnrollment,
    ScanJob,
)
from nm1_authorization import project_current_authority
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session


class Issuer:
    def __init__(self, origin, wire, *, clock=None, monotonic=time.monotonic):
        # Reuse the existing configured-origin restrictions; no payload-directed lookup.
        control.ClaimControl(runner_id=uuid.UUID(int=1), origin=origin)
        self.origin = origin
        self.wire = wire
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic

    def _now(self, anchor, entered):
        wall = self.clock()
        stamp(wall)
        elapsed = self.monotonic() - entered
        require(elapsed >= 0, "clock_rollback")
        return max(wall, anchor + timedelta(seconds=elapsed)).astimezone(timezone.utc)

    def _observe(self, bind, anchor, entered):
        # Separate from ownership/budget mutations, including their failure paths.
        # Retry only the empty-table initialization race; no issuance is retried.
        for attempt in range(2):
            try:
                with Session(bind=bind) as ledger:
                    if bind.dialect.name == "sqlite":
                        ledger.execute(text("BEGIN IMMEDIATE"))
                    row = ledger.query(ManagedClock).filter_by(id=1).with_for_update().first()
                    now = self._now(anchor, entered).replace(tzinfo=None)
                    if row is None:
                        ledger.add(ManagedClock(id=1, observed=now))
                    else:
                        require(
                            isinstance(row.observed, datetime) and now >= row.observed,
                            "clock_rollback",
                        )
                        row.observed = now
                    ledger.commit()
                    return
            except IntegrityError:
                if attempt:
                    raise WireRefused("clock_state_failed") from None
            except WireRefused:
                raise
            except (SQLAlchemyError, TypeError, ValueError):
                raise WireRefused("clock_state_failed") from None

    @contextmanager
    def operation(self, db):
        managed_authority.require_clean_issuer_session(db)
        anchor = self.clock()
        stamp(anchor)
        entered = self.monotonic()
        bind = db.get_bind()
        self._observe(bind, anchor, entered)
        try:
            yield lambda: self._now(anchor, entered)
        except BaseException:
            db.rollback()
            self._observe(bind, anchor, entered)
            raise

    def _operator(self, db, request):
        header = request.headers.get("authorization", "")
        require(not header.startswith("Bearer vmap_"), "operator_session_required")
        user = get_current_user(request, authorization=header or None, db=db)
        require(user.get("scope") == "full", "operator_session_required")
        method = "local_session" if user.get("auth_method") == "local" else "github_session"
        require(
            method == "local_session" or header.startswith("Bearer "), "operator_session_required"
        )
        return {**user, "auth_method": method}

    def _begin_write(self, db):
        # Auth helpers may commit metadata. Acquire the permission writer only
        # afterward, before authoritative reads. This is a no-op on PostgreSQL.
        managed_authority.begin_write(db)

    def _enrollment(self, db, enrollment_id, owner):
        row = (
            db.query(ManagedEnrollment)
            .filter_by(id=enrollment_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        require(
            row is not None
            and not row.revoked
            and row.owner == owner
            and row.origin == self.origin,
            "enrollment_unavailable",
        )
        key = (
            db.query(ApiKey)
            .filter_by(id=row.api_key_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        require(
            key is not None and key.github_id == owner and key.scope in {"runner", "full"},
            "enrollment_key_unavailable",
        )
        integer(row.revision, 1)
        return row, key

    def _projection(
        self,
        db,
        job,
        actor,
        enrollment,
        authorization_id,
        plan,
        permission,
        revision,
        job_statuses=("pending",),
    ):
        engagement = db.get(Engagement, job.program_id)
        require(revision == engagement.managed_authority_revision, "authority_revision_changed")
        for name, maximum in (
            ("max_executions", 1000),
            ("max_duration_seconds", 86400),
            ("max_artifact_bytes", 1024**3),
        ):
            integer(permission[name], 1, maximum)
        result = project_current_authority(
            db,
            job_id=job.id,
            authorization_id=authorization_id,
            actor=actor,
            plan=plan,
            runner_id=enrollment.runner_id,
            authority_revision=revision,
            expires_at=timestamp(permission["expires_at"]),
            max_executions=permission["max_executions"],
            max_duration_seconds=permission["max_duration_seconds"],
            max_artifact_bytes=permission["max_artifact_bytes"],
            credential_grants=permission["credential_grants"],
            now=timestamp(permission["not_before"]),
            job_statuses=job_statuses,
        )
        snapshot = {
            "schema": "vardr.map-managed-authority/1",
            "origin": self.origin,
            "authority_revision": engagement.managed_authority_revision,
            "authority": result["authority_snapshot"],
            "owner": engagement.owner_github_id,
            "engagement_type": engagement.engagement_type,
            "engagement_status": engagement.engagement_status,
            "limits": {
                "concurrency": engagement.concurrency_limit,
                "targets": engagement.target_limit,
                "duration": engagement.duration_limit,
            },
            "enrollment": {
                "id": enrollment.id,
                "revision": enrollment.revision,
                "api_key_id": enrollment.api_key_id,
                "principal_sha256": enrollment.principal_hash,
                "runner_id": enrollment.runner_id,
            },
        }
        result["authority_snapshot"] = snapshot
        result["context"]["authority_sha256"] = digest(snapshot)
        return result

    def _review_locked(self, db, job, actor, enrollment_id, authorization_id, plan, permission):
        require(job.status == "pending", "pending_job_required")
        enrollment, _ = self._enrollment(db, enrollment_id, actor["github_id"])
        revision = db.get(Engagement, job.program_id).managed_authority_revision
        return self._projection(
            db, job, actor, enrollment, authorization_id, plan, permission, revision
        )

    def _locked_time(self, db, now):
        # Parent/job/approval/enrollment locks precede this final short clock lock.
        # Initial observations hold only this clock and release it before parents.
        current = now().replace(tzinfo=None)
        changed = (
            db.query(ManagedClock)
            .filter(ManagedClock.id == 1, ManagedClock.observed <= current)
            .update({ManagedClock.observed: current}, synchronize_session=False)
        )
        require(changed == 1, "clock_rollback")

    def review(
        self,
        db,
        request,
        *,
        job_id,
        enrollment_id,
        authorization_id,
        plan,
        expires_at,
        max_executions,
        max_duration_seconds,
        max_artifact_bytes,
        credential_grants,
    ):
        """Unsigned owner-session review request; never executable permission."""
        with self.operation(db) as now:
            actor = self._operator(db, request)
            self._begin_write(db)
            job = control.lock_job(db, job_id, actor)
            permission = {
                "not_before": stamp(now()),
                "expires_at": expires_at,
                "max_executions": max_executions,
                "max_duration_seconds": max_duration_seconds,
                "max_artifact_bytes": max_artifact_bytes,
                "credential_grants": credential_grants,
            }
            result = self._review_locked(
                db, job, actor, enrollment_id, authorization_id, plan, permission
            )
            db.rollback()  # Review reserves no permission or mutable authority state.
            return result

    def register(self, db, request, *, job_id, enrollment_id, authorization_id, plan, approval):
        """Persist an exact separately signed receipt; no approval-signing operation."""
        with self.operation(db) as now:
            actor = self._operator(db, request)
            self._begin_write(db)
            job = control.lock_job(db, job_id, actor)
            # Authenticate the receipt before using its context as review inputs.
            payload = parse(unb64(approval["payload"], 256 * 1024), 256 * 1024)
            receipt = self.wire.approval(approval, payload["context"], actor["github_id"], now())
            record_id = self.wire.issuer_id + ":" + receipt["approval_id"]
            existing = (
                db.query(ManagedApproval)
                .filter_by(id=record_id)
                .with_for_update()
                .populate_existing()
                .first()
            )
            if existing is not None:
                require(
                    existing.job_id == job_id
                    and job.managed_approval_id == record_id
                    and digest(existing.envelope) == digest(approval),
                    "approval_id_reused",
                )
                require(not existing.revoked, "approval_unavailable")
                self._locked_time(db, now)
                db.commit()
                return existing
            result = self._review_locked(
                db, job, actor, enrollment_id, authorization_id, plan, receipt["context"]
            )
            self.wire.approval(approval, result["context"], actor["github_id"], now())
            row = ManagedApproval(
                id=record_id,
                issuer=self.wire.issuer_id,
                approval_id=receipt["approval_id"],
                job_id=job.id,
                engagement_id=job.program_id,
                enrollment_id=enrollment_id,
                authorization_id=authorization_id,
                revision=result["context"]["authority_revision"],
                owner=actor["github_id"],
                envelope=approval,
                plan=plan,
                context=result["context"],
                authority_snapshot=result["authority_snapshot"],
                issued=0,
                revoked=False,
            )
            db.add(row)
            job.managed_approval_id = record_id
            job.authorization_contract_required = True
            db.flush()
            self._locked_time(db, now)
            self.wire.approval(approval, result["context"], actor["github_id"], now())
            db.commit()
            return row

    def revoke(self, db, request, *, job_id):
        with self.operation(db) as now:
            actor = self._operator(db, request)
            self._begin_write(db)
            job = control.lock_job(db, job_id, actor)
            row = (
                db.query(ManagedApproval)
                .filter_by(id=job.managed_approval_id)
                .with_for_update()
                .populate_existing()
                .first()
            )
            require(row is not None and row.owner == actor["github_id"], "owner_approval_required")
            self._locked_time(db, now)
            row.revoked = True  # No un-revoke/reset operation.
            db.commit()

    def _claim_permission(self, db, request, job, body, now, *, job_statuses=("pending",)):
        approval = (
            db.query(ManagedApproval)
            .filter_by(id=job.managed_approval_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        require(
            approval is not None
            and not approval.revoked
            and approval.job_id == job.id
            and approval.engagement_id == job.program_id,
            "approval_unavailable",
        )
        enrollment, key = self._enrollment(db, approval.enrollment_id, approval.owner)
        header = request.headers.get("authorization", "")
        require(
            header.startswith("Bearer vmap_")
            and hashlib.sha256(header.removeprefix("Bearer ").encode()).hexdigest() == key.key_hash
            and control.principal(request) == enrollment.principal_hash
            and body.origin == self.origin
            and str(body.runner_id) == enrollment.runner_id,
            "enrolled_principal_runner_required",
        )
        actor = {"github_id": approval.owner}
        # This is current-authority reprojection of an already authenticated signed
        # record, not a fabricated human approval. Only register() accepts approvals.
        result = self._projection(
            db,
            job,
            actor,
            enrollment,
            approval.authorization_id,
            approval.plan,
            approval.context,
            approval.revision,
            job_statuses=job_statuses,
        )
        self.wire.approval(approval.envelope, result["context"], approval.owner, now())
        return approval, result

    def current(self, db, request, *, job_id, body, contract_id, attempt_id, fence):
        """Unregistered current-authority check; no lease renewal/consume/execute.

        A future control adapter must use this result before returning continue.
        Legacy control is deliberately unsupported for marked jobs meanwhile.
        """
        with self.operation(db) as now:
            user = get_current_user(
                request, authorization=request.headers.get("authorization"), db=db
            )
            self._begin_write(db)
            execution = control.owned(db, job_id, user, request, body)
            job = db.get(ScanJob, job_id)
            contract = (
                db.query(ManagedContract)
                .filter_by(job_id=job_id)
                .with_for_update()
                .populate_existing()
                .first()
            )
            require(
                contract is not None
                and (contract.id, contract.attempt_id, contract.fence)
                == (contract_id, attempt_id, fence),
                "owned_contract_fence_required",
            )
            approval, result = self._claim_permission(
                db, request, job, body, now, job_statuses=("running",)
            )
            self._locked_time(db, now)
            require(
                execution.state == "active" and execution.expires_at > control.now(),
                "live_control_expired_or_stopped",
            )
            self.wire.approval(approval.envelope, result["context"], approval.owner, now())
            db.commit()
            return {
                "contract_id": contract.id,
                "attempt_id": contract.attempt_id,
                "fence": contract.fence,
                "authority_revision": approval.revision,
                "authority_sha256": result["context"]["authority_sha256"],
            }

    def _budgets(self, body, approval):
        require(
            body.concurrency_budget is True
            and body.target_binding is not None
            and type(body.duration_seconds) is int
            and body.duration_seconds <= approval.context["max_duration_seconds"],
            "managed_budget_controls_required",
        )

    def claim(self, db, request, *, job_id, body):
        """Unregistered one-shot prototype; all ownership/fees/issuance commit together.

        Existing ScanJob/JobExecution permit one physical attempt per job. N is an
        approval ceiling, not a promise of automatic retries or reopened jobs.
        """
        with self.operation(db) as now:
            # Actual API-key authentication supplies the access principal; it is
            # never human approval. Its existing last-used commit precedes locks.
            user = get_current_user(
                request, authorization=request.headers.get("authorization"), db=db
            )
            self._begin_write(db)
            job = control.lock_job(db, job_id, user)
            require(job.status == "pending", "pending_job_required")
            approval, result = self._claim_permission(db, request, job, body, now)
            self._budgets(body, approval)
            self._locked_time(db, now)
            engagement = db.get(Engagement, job.program_id)
            concurrency_budget.before_claim(db, engagement, body)
            snapshot = result["case"]
            targets = target_budget.charge(engagement, job, snapshot, body)
            duration = duration_budget.allocate(engagement, body)
            changed = (
                db.query(ScanJob)
                .filter_by(id=job_id, status="pending", managed_approval_id=approval.id)
                .update(
                    {
                        ScanJob.status: "running",
                        ScanJob.started_at: now().replace(tzinfo=None),
                        ScanJob.case_snapshot: snapshot,
                    },
                    synchronize_session=False,
                )
            )
            require(changed == 1, "claim_conflict")
            capability = control.issue(db, job_id, user, request, body, targets, duration)
            ordinal = approval.issued + 1
            require(ordinal <= approval.context["max_executions"], "approval_exhausted")
            require(
                db.query(ManagedContract).filter_by(job_id=job_id).first() is None,
                "attempt_already_issued",
            )
            contract_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
            # Immutable one-attempt JobExecution means fence 1 is globally unique
            # for this exact job. No alias ID, re-open or unknown-attempt refund.
            envelope = self.wire.issue(
                approval.envelope,
                result["context"],
                approval.owner,
                now(),
                contract_id=contract_id,
                attempt_id=attempt_id,
                fence=1,
                ordinal=ordinal,
            )
            approval.issued = ordinal
            db.add(
                ManagedContract(
                    id=contract_id,
                    job_id=job_id,
                    approval_record_id=approval.id,
                    ordinal=ordinal,
                    attempt_id=attempt_id,
                    fence=1,
                    envelope=envelope,
                    consumed=False,
                )
            )
            db.flush()
            # Signing/flush/lock delays consume permission; denial rolls all fees,
            # ownership, ordinal and case snapshot back, preserving only clock.
            self._locked_time(db, now)
            self.wire.approval(approval.envelope, result["context"], approval.owner, now())
            db.commit()
            return {
                "execution_control": capability,
                "managed_authorization": {
                    "approval": approval.envelope,
                    "contract": envelope,
                    "plan": approval.plan,
                    "authority_snapshot": result["authority_snapshot"],
                },
            }
