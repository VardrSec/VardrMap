"""Unregistered known-stop reporting and observation; never execute or infer exit."""

from managed_wire import digest, require
from models import ManagedStop

CANCEL_CAUSES = frozenset({"local_emergency_stop", "remote_stop_requested"})
FAIL_CAUSES = frozenset(
    {
        "control_cap_unavailable",
        "control_lease_expired",
        "authorization_deadline",
        "tool_timeout",
        "descendants_after_tool_exit",
    }
)
CAUSES = CANCEL_CAUSES | FAIL_CAUSES
RECEIPT_CAUSES = CAUSES | frozenset({"observed_exit"})


def stop_hash(binding, outcome, cause):
    return digest(
        {
            "schema": "vardr.managed-stop/1",
            **binding,
            "outcome": outcome,
            "cause": cause,
            "termination_confirmed": True,
        }
    )


class Stops:
    def __init__(self, results):
        self.results = results
        self.issuer = results.issuer

    @staticmethod
    def _row(db, binding):
        row = (
            db.query(ManagedStop)
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
                and row.cause in RECEIPT_CAUSES
                and row.outcome == ("cancelled" if row.cause in CANCEL_CAUSES else "failed")
                and row.receipt_sha256 == stop_hash(binding, row.outcome, row.cause),
                "retained_stop_binding",
            )
        return row

    @staticmethod
    def _ack(binding, row, execution):
        require(
            execution.state == row.outcome and execution.capacity_reserved is False,
            "retained_stop_inconsistent",
        )
        return Stops._receipt(binding, row)

    @staticmethod
    def _receipt(binding, row):
        """Immutable receipt fields, also retained after the live job is deleted."""
        return {
            "schema": "vardr.managed-stop-receipt/1",
            **binding,
            "outcome": row.outcome,
            "cause": row.cause,
            "receipt_sha256": row.receipt_sha256,
            "capacity_reserved": False,
        }

    def report(
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
        outcome,
        cause,
        termination_confirmed,
    ):
        require(
            type(cause) is str
            and cause in CAUSES
            and termination_confirmed is True
            and type(outcome) is str
            and outcome == ("cancelled" if cause in CANCEL_CAUSES else "failed"),
            "known_stop_report_required",
        )
        with self.issuer.operation(db) as now:
            _, job, execution, _, binding = self.results._owned(
                db,
                request,
                job_id,
                body,
                contract_id,
                attempt_id,
                fence,
                contract_sha256,
            )
            ack = self._stop_locked(
                db, now, job, execution, binding, outcome=outcome, cause=cause
            )
            db.commit()
            return ack

    def _stop_locked(self, db, now, job, execution, binding, *, outcome, cause):
        """Internal terminal mutation after caller authentication and attempt locks.

        Native report() retains its original CAUSES guard. The independently
        authenticated host producer can supply only its fixed observed_exit.
        Both producers serialize the same result/stop exclusion and reservation.
        """
        require(
            type(cause) is str and cause in RECEIPT_CAUSES
            and type(outcome) is str
            and outcome == ("cancelled" if cause in CANCEL_CAUSES else "failed"),
            "known_stop_report_required",
        )
        row = self._row(db, binding)
        if row is not None:
            require(
                (row.outcome, row.cause) == (outcome, cause), "different_stop_receipt"
            )
            return self._ack(binding, row, execution)
        require(
            self.results._result(db, binding) is None, "result_protocol_already_started"
        )
        require(
            execution.state not in {"completed", "failed", "cancelled"}
            and execution.capacity_reserved is True,
            "owned_reservation_required",
        )
        row = ManagedStop(
            **{
                key: binding[key]
                for key in (
                    "contract_id",
                    "job_id",
                    "attempt_id",
                    "fence",
                    "contract_sha256",
                )
            },
            outcome=outcome,
            cause=cause,
            receipt_sha256=stop_hash(binding, outcome, cause),
            finished_at=now().replace(tzinfo=None),
        )
        db.add(row)
        execution.state, execution.capacity_reserved = outcome, False
        job.status, job.completed_at, job.error_message = (
            "failed",
            row.finished_at,
            cause,
        )
        db.flush()
        self.issuer._locked_time(db, now)
        return self._ack(binding, row, execution)

    def inspect(
        self, db, request, *, job_id, body, contract_id, attempt_id, fence, contract_sha256
    ):
        with self.issuer.operation(db):
            _, _, execution, _, binding = self.results._owned(
                db, request, job_id, body, contract_id, attempt_id, fence, contract_sha256
            )
            row = self._row(db, binding)
            result = {
                "schema": "vardr.managed-stop-observation/1",
                **binding,
                "consumed": True,
                "capacity_reserved": execution.capacity_reserved,
                "execution_state": execution.state,
                "stop": self._ack(binding, row, execution) if row else None,
            }
            db.rollback()
            return result
