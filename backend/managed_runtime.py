"""Unregistered ADR0043 admission and independent host stop-only authority."""

import hashlib
import hmac
import re
import uuid
from datetime import datetime, timedelta, timezone

import execution_control as control
from fastapi import HTTPException
from managed_stops import Stops
from managed_wire import digest, fields, integer, require, stamp
from models import (
    Engagement,
    JobExecution,
    ManagedApproval,
    ManagedContract,
    ManagedEnrollment,
    ManagedRuntime,
    ScanJob,
)

CAPABILITY_PREFIX = b"VardrSec.WorkerStop.v1\0"
IDENTITY_FIELDS = {
    "daemon_id",
    "container_id",
    "image_id",
    "project",
    "started_at",
    "owner_nonce",
}
BINDING_FIELDS = {
    "origin",
    "job_id",
    "runner_id",
    "contract_id",
    "attempt_id",
    "fence",
    "contract_sha256",
}


def fingerprint(value):
    require(
        type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value),
        "invalid_runtime_hash",
    )
    return value


def identifier(value):
    require(
        type(value) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value),
        "invalid_runtime_identity",
    )
    return value


def normalized_start(value):
    """Canonicalize aliases while retaining every Docker RFC3339Nano digit."""
    require(type(value) is str, "invalid_runtime_time")
    match = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z", value)
    require(match is not None, "invalid_runtime_time")
    try:
        base = datetime.strptime(match[1], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        require(False, "invalid_runtime_time")
    require(base.year > 1, "unset_runtime_time")
    return match[1] + "." + (match[2] or "").ljust(9, "0") + "Z"


def check_identity(value):
    fields(value, IDENTITY_FIELDS)
    identifier(value["daemon_id"])
    identifier(value["project"])
    fingerprint(value["container_id"])
    require(
        type(value["image_id"]) is str and value["image_id"].startswith("sha256:"),
        "invalid_runtime_image",
    )
    fingerprint(value["image_id"][7:])
    fingerprint(value["owner_nonce"])
    started = normalized_start(value["started_at"])
    physical = digest(
        {
            "daemon_id": value["daemon_id"],
            "container_id": value["container_id"],
            "started_at": started,
        }
    )
    return digest(value), physical


def capability_hash(secret):
    fingerprint(secret)
    return hashlib.sha256(CAPABILITY_PREFIX + secret.encode("ascii")).hexdigest()


def _uuid(value):
    require(type(value) is str, "invalid_runtime_uuid")
    try:
        require(str(uuid.UUID(value)) == value, "invalid_runtime_uuid")
    except ValueError:
        require(False, "invalid_runtime_uuid")
    return value


class Runtimes:
    def __init__(self, results):
        self.results, self.issuer, self.stops = results, results.issuer, Stops(results)

    @staticmethod
    def _check(row):
        sha, physical = check_identity(row.identity)
        fingerprint(row.capability_sha256)
        fingerprint(row.principal_sha256)
        require(
            row.runtime_sha256 == sha
            and row.physical_sha256 == physical
            and row.owner_nonce == row.identity["owner_nonce"]
            and type(row.revoked) is bool
            and type(row.retired) is bool
            and isinstance(row.registered_at, datetime)
            and isinstance(row.expires_at, datetime)
            and 60 <= integer(row.ttl_seconds, 60, 604800) <= 604800
            and row.expires_at
            == row.registered_at + timedelta(seconds=row.ttl_seconds),
            "retained_runtime_inconsistent",
        )
        bound = Runtimes._binding(row)
        require(
            (bound is not None or row.confirmed_at is None)
            and (row.report_sha256 is None or row.retired)
            and (not row.retired or row.report_sha256 is not None),
            "retained_runtime_inconsistent",
        )
        if row.report_sha256 is not None:
            fingerprint(row.report_sha256)

    @staticmethod
    def _public(row):
        return {
            "schema": "vardr.worker-admission/1",
            "runtime_id": row.id,
            "runtime_sha256": row.runtime_sha256,
            "enrollment_id": row.enrollment_id,
            "runner_id": row.runner_id,
            "origin": row.origin,
            "capability_sha256": row.capability_sha256,
            "identity": row.identity,
            "expires_at": stamp(row.expires_at.replace(tzinfo=timezone.utc)),
        }

    @staticmethod
    def _binding(row):
        values = (
            row.job_id,
            row.contract_id,
            row.attempt_id,
            row.fence,
            row.contract_sha256,
            row.bound_at,
        )
        if all(value is None for value in values):
            return None
        require(all(value is not None for value in values), "partial_runtime_binding")
        identifier(row.job_id)
        _uuid(row.contract_id)
        _uuid(row.attempt_id)
        integer(row.fence, 1)
        fingerprint(row.contract_sha256)
        return {
            "origin": row.origin,
            "job_id": row.job_id,
            "runner_id": row.runner_id,
            "contract_id": row.contract_id,
            "attempt_id": row.attempt_id,
            "fence": row.fence,
            "contract_sha256": row.contract_sha256,
        }

    @staticmethod
    def _active(row, instant):
        require(
            not row.revoked and row.expires_at > instant, "runtime_grant_unavailable"
        )

    def register(
        self,
        db,
        request,
        *,
        runtime_id,
        enrollment_id,
        runner_id,
        origin,
        identity: dict,
        capability_sha256,
        expires_in_seconds,
    ):
        _uuid(runtime_id)
        _uuid(runner_id)
        fingerprint(capability_sha256)
        ttl = integer(expires_in_seconds, 60, 604800)
        sha, physical = check_identity(identity)
        with self.issuer.operation(db) as now:
            actor = self.issuer._operator(db, request)
            self.issuer._begin_write(db)
            enrollment, _ = self.issuer._enrollment(
                db, enrollment_id, actor["github_id"]
            )
            require(
                origin == self.issuer.origin == enrollment.origin
                and runner_id == enrollment.runner_id,
                "runtime_enrollment_binding",
            )
            # Enrollment/key locks precede runtime everywhere that needs both.
            row = (
                db.query(ManagedRuntime)
                .filter_by(id=runtime_id)
                .with_for_update()
                .populate_existing()
                .first()
            )
            if row is None:
                instant = now().replace(tzinfo=None)
                row = ManagedRuntime(
                    id=runtime_id,
                    owner=actor["github_id"],
                    enrollment_id=enrollment.id,
                    enrollment_revision=enrollment.revision,
                    api_key_id=enrollment.api_key_id,
                    principal_sha256=enrollment.principal_hash,
                    runner_id=runner_id,
                    origin=origin,
                    identity=identity,
                    runtime_sha256=sha,
                    physical_sha256=physical,
                    owner_nonce=identity["owner_nonce"],
                    capability_sha256=capability_sha256,
                    ttl_seconds=ttl,
                    registered_at=instant,
                    expires_at=instant + timedelta(seconds=ttl),
                    revoked=False,
                    retired=False,
                )
                db.add(row)
            else:
                self._check(row)
                require(
                    row.owner == actor["github_id"]
                    and row.enrollment_id == enrollment.id
                    and row.enrollment_revision == enrollment.revision
                    and row.api_key_id == enrollment.api_key_id
                    and row.principal_sha256 == enrollment.principal_hash
                    and row.runner_id == runner_id
                    and row.origin == origin
                    and row.runtime_sha256 == sha
                    and row.identity == identity
                    and row.capability_sha256 == capability_sha256
                    and row.ttl_seconds == ttl,
                    "runtime_registration_changed",
                )
            db.flush()
            self.issuer._locked_time(db, now)
            reply = self._public(row)
            db.commit()
            return reply

    def revoke(self, db, request, *, runtime_id):
        _uuid(runtime_id)
        with self.issuer.operation(db) as now:
            actor = self.issuer._operator(db, request)
            self.issuer._begin_write(db)
            row = (
                db.query(ManagedRuntime)
                .filter_by(id=runtime_id)
                .with_for_update()
                .populate_existing()
                .first()
            )
            if row is None or row.owner != actor["github_id"]:
                raise HTTPException(404)
            row.revoked = True
            db.flush()
            self.issuer._locked_time(db, now)
            db.commit()
            return {"runtime_id": runtime_id, "revoked": True}

    def bind(
        self,
        db,
        request,
        *,
        job_id,
        body,
        runtime_id,
        runtime_sha256,
        contract_id,
        attempt_id,
        fence,
        contract_sha256,
    ):
        _uuid(runtime_id)
        fingerprint(runtime_sha256)
        with self.issuer.operation(db) as now:
            _, job, execution, approval, binding = self.results._owned(
                db,
                request,
                job_id,
                body,
                contract_id,
                attempt_id,
                fence,
                contract_sha256,
            )
            approval, projection = self.issuer._claim_permission(
                db, request, job, body, now, job_statuses=("running",)
            )
            row = (
                db.query(ManagedRuntime)
                .filter_by(id=runtime_id)
                .with_for_update()
                .populate_existing()
                .first()
            )
            require(row is not None, "runtime_unavailable")
            self._check(row)
            expected = projection["authority_snapshot"]["enrollment"]
            require(
                row.owner == approval.owner == execution.owner
                and row.enrollment_id == approval.enrollment_id == expected["id"]
                and row.enrollment_revision == expected["revision"]
                and row.api_key_id == expected["api_key_id"]
                and row.principal_sha256
                == execution.principal_hash
                == expected["principal_sha256"]
                and row.origin == binding["origin"]
                and row.runner_id == binding["runner_id"]
                and row.runtime_sha256 == runtime_sha256
                and not row.retired
                and self._binding(row) == binding
                and row.confirmed_at is None,
                "runtime_attempt_binding",
            )
            self._active(row, now().replace(tzinfo=None))
            row.confirmed_at = now().replace(tzinfo=None)
            db.flush()
            self.issuer._locked_time(db, now)
            instant = max(now().replace(tzinfo=None), control.now())
            self._active(row, instant)
            require(
                execution.state == "active" and execution.expires_at > instant,
                "runtime_live_permission_required",
            )
            self.issuer.wire.approval(
                approval.envelope, projection["context"], approval.owner, now()
            )
            reply = {
                "schema": "vardr.worker-runtime-binding/1",
                **binding,
                "runtime_id": runtime_id,
                "runtime_sha256": runtime_sha256,
                "bound": True,
            }
            db.commit()
            return reply

    def claim(self, db, request, *, job_id, body, runtime_id, runtime_sha256):
        _uuid(runtime_id)
        fingerprint(runtime_sha256)

        def prepare(*, db, now, job, approval, projection):
            row = (
                db.query(ManagedRuntime)
                .filter_by(id=runtime_id)
                .with_for_update()
                .populate_existing()
                .first()
            )
            require(row is not None, "runtime_unavailable")
            self._check(row)
            enrolled = projection["authority_snapshot"]["enrollment"]
            require(
                row.owner == approval.owner
                and row.enrollment_id == enrolled["id"]
                and row.enrollment_revision == enrolled["revision"]
                and row.api_key_id == enrolled["api_key_id"]
                and row.principal_sha256 == enrolled["principal_sha256"]
                and row.origin == body.origin == self.issuer.origin
                and row.runner_id == str(body.runner_id) == enrolled["runner_id"]
                and row.runtime_sha256 == runtime_sha256
                and not row.retired
                and self._binding(row) is None,
                "runtime_claim_binding",
            )
            self._active(row, now().replace(tzinfo=None))

            def associate(contract):
                row.job_id, row.contract_id, row.attempt_id = (
                    job.id,
                    contract.id,
                    contract.attempt_id,
                )
                row.fence, row.contract_sha256 = (
                    contract.fence,
                    digest(contract.envelope),
                )
                row.bound_at = now().replace(tzinfo=None)
                db.flush()
                self._active(row, now().replace(tzinfo=None))

            return associate

        return self.issuer.claim(
            db, request, job_id=job_id, body=body, on_claim=prepare
        )

    def _host(self, db, request, runtime_id, *, locked=False):
        _uuid(runtime_id)
        header = request.headers.get("authorization", "")
        match = re.fullmatch(r"VardrStop ([a-f0-9]{64})", header)
        query = db.query(ManagedRuntime).filter_by(id=runtime_id)
        if locked:
            query = query.with_for_update().populate_existing()
        row = query.first()
        if (
            row is None
            or match is None
            or not hmac.compare_digest(row.capability_sha256, capability_hash(match[1]))
        ):
            raise HTTPException(404)
        self._check(row)
        return row

    def _lock_host_attempt(self, db, row, supplied):
        binding = self._binding(row)
        require(binding is not None and binding == supplied, "host_attempt_binding")
        parent = db.query(ScanJob.program_id).filter_by(id=binding["job_id"]).scalar()
        require(parent is not None, "host_job_unavailable")
        # Same serialization order as native result/stop writes, no fake token or
        # fabricated native handle. Authentication is the independent stop grant.
        db.query(Engagement).filter_by(
            id=parent
        ).with_for_update().populate_existing().one()
        job = (
            db.query(ScanJob)
            .filter_by(id=binding["job_id"])
            .with_for_update()
            .populate_existing()
            .one()
        )
        execution = (
            db.query(JobExecution)
            .filter_by(job_id=job.id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        contract = (
            db.query(ManagedContract)
            .filter_by(job_id=job.id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        require(
            execution is not None and contract is not None,
            "host_owned_attempt_required",
        )
        approval = (
            db.query(ManagedApproval)
            .filter_by(id=contract.approval_record_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        enrollment = (
            db.query(ManagedEnrollment)
            .filter_by(id=row.enrollment_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        require(
            approval is not None
            and enrollment is not None
            and job.authorization_contract_required
            and job.tool_type == "vardrgate_api_test"
            and job.managed_approval_id == approval.id
            and approval.job_id == job.id
            and approval.engagement_id == job.program_id
            and approval.enrollment_id == row.enrollment_id
            and approval.owner == execution.owner == enrollment.owner == row.owner
            and enrollment.api_key_id == row.api_key_id
            and enrollment.principal_hash
            == execution.principal_hash
            == row.principal_sha256
            and enrollment.runner_id == execution.runner_id == row.runner_id
            and enrollment.origin == execution.origin == row.origin
            and (contract.consumed or row.confirmed_at is None)
            and (contract.id, contract.attempt_id, contract.fence)
            == (row.contract_id, row.attempt_id, row.fence)
            and digest(contract.envelope) == row.contract_sha256,
            "host_retained_identity_required",
        )
        # Enrollment/API-key revocation blocks execution, not this independently
        # approved, still-active reporting grant for an already bound attempt.
        return job, execution, binding, contract

    def observed_exit(
        self,
        db,
        request,
        *,
        runtime_id,
        runtime_sha256,
        binding,
        finished_at,
        exit_code,
        observation_sha256,
    ):
        fingerprint(runtime_sha256)
        fingerprint(observation_sha256)
        integer(exit_code, 0, 255)
        finished = normalized_start(finished_at)
        report = {
            "runtime_sha256": runtime_sha256,
            **binding,
            "finished_at": finished_at,
            "exit_code": exit_code,
            "observation_sha256": observation_sha256,
        }
        report_sha = digest(report)
        with self.issuer.operation(db) as now:
            self.issuer._begin_write(db)
            row = self._host(db, request, runtime_id)
            require(row.runtime_sha256 == runtime_sha256, "host_runtime_binding")
            require(
                finished >= normalized_start(row.identity["started_at"]),
                "host_exit_before_start",
            )
            job, execution, expected, contract = self._lock_host_attempt(
                db, row, binding
            )
            row = self._host(db, request, runtime_id, locked=True)
            self._active(row, now().replace(tzinfo=None))
            old = self.stops._row(db, expected)
            result = self.results._result(db, expected)
            require(old is None or result is None, "conflicting_runtime_receipts")
            require(
                (
                    old is None
                    and (result is None or result.outcome is None)
                    and not row.retired
                    and row.report_sha256 is None
                )
                or (
                    (
                        old is not None
                        or (result is not None and result.outcome == "failed")
                    )
                    and row.retired
                    and row.report_sha256 == report_sha
                ),
                "host_report_changed",
            )
            if result is not None:
                require(contract.consumed is True, "result_consumption_required")
                receipt = self.results._fail_locked(
                    db, now, job, execution, expected, result
                )
                job.error_message = "observed_exit"
            else:
                receipt = self.stops._stop_locked(
                    db,
                    now,
                    job,
                    execution,
                    expected,
                    outcome="failed",
                    cause="observed_exit",
                )
            row.retired, row.report_sha256 = True, report_sha
            db.flush()
            self.issuer._locked_time(db, now)
            self._active(row, now().replace(tzinfo=None))
            db.commit()
            return {
                "schema": "vardr.worker-host-stop/1",
                "runtime_id": runtime_id,
                "runtime_sha256": runtime_sha256,
                "receipt": receipt,
            }

    @staticmethod
    def _unbound_receipt(row):
        require(
            row.retired is True
            and row.confirmed_at is None
            and Runtimes._binding(row) is None,
            "unbound_runtime_retirement_required",
        )
        receipt = {
            "schema": "vardr.worker-unbound-retirement/1",
            "runtime_id": row.id,
            "runtime_sha256": row.runtime_sha256,
            "origin": row.origin,
            "runner_id": row.runner_id,
            "enrollment_id": row.enrollment_id,
            "report_sha256": fingerprint(row.report_sha256),
            "bound": False,
            "retired": True,
        }
        return {**receipt, "receipt_sha256": digest(receipt)}

    def observed_unbound_exit(
        self,
        db,
        request,
        *,
        runtime_id,
        runtime_sha256,
        finished_at,
        exit_code,
        observation_sha256,
    ):
        fingerprint(runtime_sha256)
        fingerprint(observation_sha256)
        integer(exit_code, 0, 255)
        finished = normalized_start(finished_at)
        report_sha = digest(
            {
                "schema": "vardr.worker-unbound-exit-report/1",
                "runtime_id": runtime_id,
                "runtime_sha256": runtime_sha256,
                "finished_at": finished_at,
                "exit_code": exit_code,
                "observation_sha256": observation_sha256,
            }
        )
        with self.issuer.operation(db) as now:
            self.issuer._begin_write(db)
            # Runtime precedes Clock in claim preparation too. A retire winner
            # permanently refuses a late claim; a claim winner needs bound exit.
            row = self._host(db, request, runtime_id, locked=True)
            require(row.runtime_sha256 == runtime_sha256, "host_runtime_binding")
            require(
                finished >= normalized_start(row.identity["started_at"]),
                "host_exit_before_start",
            )
            self._active(row, now().replace(tzinfo=None))
            require(self._binding(row) is None, "unbound_runtime_required")
            require(
                (not row.retired and row.report_sha256 is None)
                or (row.retired and row.report_sha256 == report_sha),
                "host_report_changed",
            )
            row.retired, row.report_sha256 = True, report_sha
            db.flush()
            self.issuer._locked_time(db, now)
            self._active(row, now().replace(tzinfo=None))
            receipt = self._unbound_receipt(row)
            db.commit()
            return {
                "schema": "vardr.worker-host-stop/1",
                "runtime_id": runtime_id,
                "runtime_sha256": runtime_sha256,
                "receipt": receipt,
            }

    def receipt(self, db, request, *, runtime_id, runtime_sha256):
        """Hash-authenticated immutable observation even after grant expiry/revoke."""
        row = self._host(db, request, runtime_id)
        require(
            row.runtime_sha256 == fingerprint(runtime_sha256), "host_runtime_binding"
        )
        binding, receipt = self._binding(row), None
        if binding is None and row.retired:
            receipt = self._unbound_receipt(row)
        elif binding is not None:
            stop, result = (
                self.stops._row(db, binding),
                self.results._result(db, binding),
            )
            require(stop is None or result is None, "conflicting_runtime_receipts")
            if stop is not None:
                if stop.cause == "observed_exit":
                    require(
                        row.retired and row.report_sha256 is not None,
                        "host_retirement_proof_missing",
                    )
                    fingerprint(row.report_sha256)
                receipt = self.stops._receipt(binding, stop)
            elif result is not None and result.outcome is not None:
                require(
                    result.outcome in {"completed", "failed", "cancelled"}
                    and result.finished_at is not None,
                    "invalid_terminal_result",
                )
                receipt = {
                    "schema": "vardr.managed-completion/1",
                    **binding,
                    "receipt_sha256": result.receipt_sha256,
                    "outcome": result.outcome,
                    "capacity_reserved": False,
                }
        db.rollback()
        return {
            "schema": "vardr.worker-receipt-observation/1",
            "runtime_id": runtime_id,
            "runtime_sha256": runtime_sha256,
            "binding": binding,
            "receipt": receipt,
        }


def retired_host_stop(db, binding, stop):
    """Narrow read-only proof of issued-but-unconsumed physical-exit retirement."""
    if stop.cause != "observed_exit" or stop.outcome != "failed":
        return False
    row = (
        db.query(ManagedRuntime)
        .filter_by(contract_id=binding["contract_id"], retired=True)
        .first()
    )
    if row is None or row.report_sha256 is None:
        return False
    Runtimes._check(row)
    fingerprint(row.report_sha256)
    execution = db.get(JobExecution, binding["job_id"])
    return (
        Runtimes._binding(row) == binding
        and row.confirmed_at is None
        and execution is not None
        and execution.state == "failed"
        and execution.capacity_reserved is False
    )


def observed_runtime_retirement(
    db,
    *,
    runtime_id,
    runtime_sha256,
    enrollment,
    principal,
    owner,
    binding,
):
    """Original enrolled-key observation, not an execution/stop capability."""
    _uuid(runtime_id)
    fingerprint(runtime_sha256)
    row = (
        db.query(ManagedRuntime)
        .filter_by(id=runtime_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if row is None or row.owner != owner:
        raise HTTPException(404)
    Runtimes._check(row)
    require(
        row.runtime_sha256 == runtime_sha256
        and row.enrollment_id == enrollment.id
        and row.enrollment_revision == enrollment.revision
        and row.api_key_id == enrollment.api_key_id
        and row.principal_sha256 == principal == enrollment.principal_hash
        and row.owner == enrollment.owner
        and row.origin == enrollment.origin
        and row.runner_id == enrollment.runner_id
        and Runtimes._binding(row) == binding,
        "original_runtime_association_required",
    )
    return Runtimes._unbound_receipt(row) if binding is None and row.retired else None
