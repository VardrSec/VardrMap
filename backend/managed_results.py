"""Unregistered managed evidence/completion and observation; never execute or renew."""

import hashlib
from datetime import timedelta

from pydantic import ValidationError

import assessments
import execution_control as control
from deps import get_current_user
from managed_wire import digest, integer, parse, require, timestamp
from models import (
    JobResultReceipt,
    ManagedApproval,
    ManagedContract,
    ManagedResult,
    ManagedStop,
    ScanJob,
)
from routers.jobs import VardrGateUpload, _writable_engagement, store_gate_result


class Results:
    def __init__(self, issuer):
        self.issuer = issuer

    def _owned(
        self, db, request, job_id, body, contract_id, attempt_id, fence, contract_sha256
    ):
        integer(fence, 1)
        user = get_current_user(
            request, authorization=request.headers.get("authorization"), db=db
        )
        self.issuer._begin_write(db)
        execution = control.owned(db, job_id, user, request, body)
        job = db.get(ScanJob, job_id)
        _writable_engagement(job, user, db)
        contract = (
            db.query(ManagedContract)
            .filter_by(job_id=job_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        require(
            job.tool_type == "vardrgate_api_test"
            and job.authorization_contract_required
            and job.managed_approval_id
            and contract is not None
            and contract.consumed
            and (contract.id, contract.attempt_id, contract.fence)
            == (contract_id, attempt_id, fence)
            and type(contract_sha256) is str
            and digest(contract.envelope) == contract_sha256,
            "owned_consumed_contract_required",
        )
        approval = (
            db.query(ManagedApproval)
            .filter_by(id=contract.approval_record_id)
            .with_for_update()
            .populate_existing()
            .one()
        )
        require(
            approval.id == job.managed_approval_id and approval.job_id == job.id,
            "result_approval_binding",
        )
        binding = {
            **control.binding(execution),
            "contract_id": contract.id,
            "attempt_id": contract.attempt_id,
            "fence": contract.fence,
            "contract_sha256": contract_sha256,
        }
        return user, job, execution, approval, binding

    @staticmethod
    def _result(db, binding):
        row = (
            db.query(ManagedResult)
            .filter_by(contract_id=binding["contract_id"])
            .with_for_update()
            .populate_existing()
            .first()
        )
        if row is not None:
            require(
                (row.job_id, row.attempt_id, row.fence, row.contract_sha256)
                == (
                    binding["job_id"],
                    binding["attempt_id"],
                    binding["fence"],
                    binding["contract_sha256"],
                )
                and row.receipt_sha256
                == digest(
                    {
                        "schema": "vardr.managed-result/1",
                        **binding,
                        "artifact_sha256": row.artifact_sha256,
                        "case_sha256": row.case_sha256,
                    }
                ),
                "retained_result_binding",
            )
        return row

    @staticmethod
    def _ack(binding, row):
        return {
            "schema": "vardr.managed-result-receipt/1",
            **binding,
            "artifact_sha256": row.artifact_sha256,
            "case_sha256": row.case_sha256,
            "receipt_sha256": row.receipt_sha256,
            "evidence_created": row.evidence_created,
            "scan_items_created": row.scan_items_created,
        }

    @staticmethod
    def _completion(binding, row, execution):
        require(
            execution.state == row.outcome and execution.capacity_reserved is False,
            "retained_completion_inconsistent",
        )
        return {
            "schema": "vardr.managed-completion/1",
            **binding,
            "receipt_sha256": row.receipt_sha256,
            "outcome": row.outcome,
            "capacity_reserved": False,
        }

    def submit(
        self,
        db,
        request,
        *,
        job_id,
        body,
        contract_id,
        attempt_id,
        fence,
        contract_sha256,
        artifact,
        artifact_sha256,
    ):
        """Retain redacted case-bound evidence, including after expiry; no release."""
        with self.issuer.operation(db) as now:
            user, job, execution, approval, binding = self._owned(
                db,
                request,
                job_id,
                body,
                contract_id,
                attempt_id,
                fence,
                contract_sha256,
            )
            require(
                db.query(ManagedStop)
                .filter_by(contract_id=contract_id)
                .with_for_update()
                .first()
                is None,
                "stop_protocol_already_started",
            )
            require(
                type(artifact) is str and len(artifact) <= 512000,
                "result_document_required",
            )
            try:
                data = artifact.encode("utf-8")
            except UnicodeError:
                require(False, "invalid_result_encoding")
            require(
                0 < len(data) <= min(512000, approval.context["max_artifact_bytes"]),
                "result_size",
            )
            require(
                hashlib.sha256(data).hexdigest() == artifact_sha256,
                "artifact_hash_mismatch",
            )
            raw = parse(data, 512000)
            require(type(raw) is dict, "result_document_required")
            try:
                result = VardrGateUpload.model_validate(raw)
            except ValidationError:
                require(False, "invalid_gate_result")
            case_hash = (
                assessments.case_hash(job.case_snapshot) if job.case_snapshot else None
            )
            require(
                case_hash
                and result.case_hash == case_hash == approval.plan["case_hash"]
                and result.test_case_id == job.case_snapshot.get("id"),
                "result_case_binding",
            )
            row = self._result(db, binding)
            if row is not None:
                require(
                    row.artifact_sha256 == artifact_sha256
                    and row.case_sha256 == case_hash,
                    "different_managed_result",
                )
                db.commit()
                return self._ack(binding, row)
            require(
                db.query(JobResultReceipt).filter_by(job_id=job.id).first() is None,
                "foreign_result_receipt",
            )
            retained = store_gate_result(db, job, result, user)
            row = ManagedResult(
                contract_id=contract_id,
                job_id=job.id,
                attempt_id=attempt_id,
                fence=fence,
                contract_sha256=contract_sha256,
                artifact_sha256=artifact_sha256,
                case_sha256=case_hash,
                receipt_sha256=digest(
                    {
                        "schema": "vardr.managed-result/1",
                        **binding,
                        "artifact_sha256": artifact_sha256,
                        "case_sha256": case_hash,
                    }
                ),
                evidence_created=retained["evidence_created"],
                scan_items_created=retained["scan_items_created"],
                preflight_failed=any(p.status != "passed" for p in result.preflight),
            )
            db.add(row)
            db.flush()
            self.issuer._locked_time(db, now)
            db.commit()
            return self._ack(binding, row)

    def finish(
        self,
        db,
        request,
        *,
        job_id,
        body,
        contract_id,
        attempt_id,
        fence,
        contract_sha256,
        receipt_sha256,
        outcome,
        termination_confirmed,
    ):
        """An owned Runner assertion, not independent process/OS attestation."""
        require(
            type(outcome) is str
            and outcome in {"completed", "failed", "cancelled"}
            and termination_confirmed is True,
            "known_termination_required",
        )
        with self.issuer.operation(db) as now:
            user, job, execution, approval, binding = self._owned(
                db,
                request,
                job_id,
                body,
                contract_id,
                attempt_id,
                fence,
                contract_sha256,
            )
            row = self._result(db, binding)
            require(
                row is not None and row.receipt_sha256 == receipt_sha256,
                "owned_result_receipt_required",
            )
            if row.outcome is not None:
                require(row.outcome == outcome, "different_completion")
                db.commit()
                return self._completion(binding, row, execution)
            require(
                execution.state not in {"completed", "failed", "cancelled"},
                "foreign_completion",
            )
            require(execution.capacity_reserved is True, "owned_reservation_required")
            if outcome == "completed":
                require(not row.preflight_failed, "preflight_failure_not_success")
                approval, projection = self.issuer._claim_permission(
                    db, request, job, body, now, job_statuses=("running",)
                )
                permission = projection["context"]

                def live(*, check_state=True):
                    instant = max(now().replace(tzinfo=None), control.now())
                    ends = [
                        timestamp(permission[k]).replace(tzinfo=None)
                        for k in ("expires_at", "testing_end")
                    ]
                    ends += [
                        timestamp(g["expires_at"]).replace(tzinfo=None)
                        for g in permission["credential_grants"]
                    ]
                    require(
                        job.started_at is not None and execution.duration_seconds > 0,
                        "finite_allocation_required",
                    )
                    ends.append(
                        job.started_at
                        + timedelta(
                            seconds=min(
                                execution.duration_seconds,
                                permission["max_duration_seconds"],
                            )
                        )
                    )
                    require(
                        (not check_state or execution.state == "active")
                        and execution.expires_at > instant
                        and min(ends) > instant,
                        "completion_permission_not_live",
                    )
                    self.issuer.wire.approval(
                        approval.envelope, permission, approval.owner, now()
                    )

                live()
            row.outcome = outcome
            row.finished_at = now().replace(tzinfo=None)
            execution.state, execution.capacity_reserved = outcome, False
            job.status = "done" if outcome == "completed" else "failed"
            job.completed_at = row.finished_at
            job.error_message = "" if outcome == "completed" else outcome
            db.flush()
            self.issuer._locked_time(db, now)
            if outcome == "completed":
                live(check_state=False)
            db.commit()
            return self._completion(binding, row, execution)

    def inspect(
        self,
        db,
        request,
        *,
        job_id,
        body,
        contract_id,
        attempt_id,
        fence,
        contract_sha256,
    ):
        """Authenticated observation only; no renew, completion, release or replay."""
        with self.issuer.operation(db):
            _, _, execution, _, binding = self._owned(
                db,
                request,
                job_id,
                body,
                contract_id,
                attempt_id,
                fence,
                contract_sha256,
            )
            row = self._result(db, binding)
            result = {
                "schema": "vardr.managed-reconciliation/1",
                **binding,
                "consumed": True,
                "capacity_reserved": execution.capacity_reserved,
                "execution_state": execution.state,
                "result": self._ack(binding, row) if row else None,
                "completion": self._completion(binding, row, execution)
                if row and row.outcome
                else None,
            }
            db.rollback()  # Observation cannot turn missing data into a completion.
            return result
