"""Unregistered enrolled-principal observation; never returns execution capability."""

import hashlib

import assessments
import execution_control as control
from deps import get_current_user
from managed_stops import Stops
from managed_wire import digest, integer, parse, require, unb64
from models import (
    JobExecution,
    ManagedApproval,
    ManagedContract,
    ManagedResult,
    ManagedStop,
)
from routers.jobs import _writable_engagement


def hash_value(value):
    require(
        type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value),
        "invalid_observation_hash",
    )
    return value


class Observations:
    def __init__(self, results):
        self.results, self.issuer = results, results.issuer
        self.stops = Stops(results)

    def inspect(self, db, request, *, job_id, body, plan_sha256, case_sha256, association_sha256):
        """Observe one original approval/association; no token, renewal or retry grant.

        Absence is a snapshot, not proof that an earlier claim cannot commit later.
        Approval expiry/revocation does not erase historical metadata. Current API
        authentication, non-revoked enrollment and membership are still required.
        """
        for value in (plan_sha256, case_sha256, association_sha256):
            hash_value(value)
        with self.issuer.operation(db):
            user = get_current_user(
                request, authorization=request.headers.get("authorization"), db=db
            )
            self.issuer._begin_write(db)
            job = control.lock_job(db, job_id, user)
            _writable_engagement(job, user, db)
            execution = (
                db.query(JobExecution)
                .filter_by(job_id=job_id)
                .with_for_update()
                .populate_existing()
                .first()
            )
            contract = (
                db.query(ManagedContract)
                .filter_by(job_id=job_id)
                .with_for_update()
                .populate_existing()
                .first()
            )
            approval = (
                db.query(ManagedApproval)
                .filter_by(id=job.managed_approval_id)
                .with_for_update()
                .populate_existing()
                .first()
            )
            require(
                job.authorization_contract_required
                and approval is not None
                and approval.owner == user["github_id"]
                and approval.job_id == job.id
                and approval.engagement_id == job.program_id,
                "owned_approval_required",
            )
            enrollment, key = self.issuer._enrollment(db, approval.enrollment_id, approval.owner)
            principal = control.principal(request)
            header = request.headers.get("authorization", "")
            require(
                body.origin == self.issuer.origin == enrollment.origin
                and str(body.runner_id) == enrollment.runner_id
                and principal == enrollment.principal_hash
                and header.startswith("Bearer vmap_")
                and hashlib.sha256(header.removeprefix("Bearer ").encode()).hexdigest()
                == key.key_hash,
                "enrolled_observer_required",
            )
            root = {
                "origin": self.issuer.origin,
                "job_id": job_id,
                "runner_id": enrollment.runner_id,
                "plan_sha256": plan_sha256,
                "case_sha256": case_sha256,
                "association_sha256": association_sha256,
            }
            require(
                digest(approval.plan) == plan_sha256
                and approval.plan["case_hash"] == case_sha256
                and digest(
                    {
                        "origin": self.issuer.origin,
                        "runner_id": enrollment.runner_id,
                        "principal_sha256": principal,
                    }
                )
                == association_sha256,
                "observation_fingerprint_binding",
            )
            reply = {
                "schema": "vardr.managed-claim-observation/1",
                **root,
                "claim": None,
                "execution_state": None,
                "capacity_reserved": False,
                "result": None,
                "completion": None,
                "stop": None,
            }
            if contract is None or execution is None:
                require(
                    contract is None
                    and execution is None
                    and approval.issued == 0
                    and job.status == "pending"
                    and db.query(ManagedResult).filter_by(job_id=job.id).first() is None
                    and db.query(ManagedStop).filter_by(job_id=job.id).first() is None,
                    "inconsistent_observed_claim",
                )
            else:
                require(
                    contract.approval_record_id == approval.id
                    and execution.owner == approval.owner
                    and execution.origin == self.issuer.origin
                    and execution.runner_id == enrollment.runner_id
                    and execution.principal_hash == principal
                    and job.case_snapshot is not None
                    and assessments.case_hash(job.case_snapshot) == case_sha256,
                    "inconsistent_observed_claim",
                )
                payload = parse(unb64(contract.envelope["payload"], 256 * 1024), 256 * 1024)
                integer(contract.fence, 1)
                require(
                    payload["job_id"] == job_id
                    and payload["runner_id"] == enrollment.runner_id
                    and payload["plan_sha256"] == plan_sha256
                    and payload["authority_revision"] == approval.revision
                    and (payload["contract_id"], payload["attempt_id"], payload["fence"])
                    == (contract.id, contract.attempt_id, contract.fence),
                    "inconsistent_observed_claim",
                )
                binding = {
                    **control.binding(execution),
                    "contract_id": contract.id,
                    "attempt_id": contract.attempt_id,
                    "fence": contract.fence,
                    "contract_sha256": digest(contract.envelope),
                }
                result = self.results._result(db, binding)
                stop = self.stops._row(db, binding)
                from managed_runtime import retired_host_stop

                require(
                    contract.consumed or (result is None and stop is None)
                    or (result is None and stop is not None
                        and retired_host_stop(db, binding, stop)),
                    "inconsistent_observed_consumption",
                )
                reply.update(
                    claim={
                        k: binding[k]
                        for k in ("contract_id", "attempt_id", "fence", "contract_sha256")
                    },
                    execution_state=execution.state,
                    capacity_reserved=execution.capacity_reserved,
                    result=self.results._ack(binding, result) if result else None,
                    completion=self.results._completion(binding, result, execution)
                    if result and result.outcome
                    else None,
                    stop=self.stops._ack(binding, stop, execution) if stop else None,
                )
                reply["claim"].update(
                    consumed=contract.consumed,
                    authority_revision=approval.revision,
                    authority_sha256=approval.context["authority_sha256"],
                )
            # No control/accounting/receipt mutations; existing telemetry is unchanged.
            db.rollback()
            return reply
