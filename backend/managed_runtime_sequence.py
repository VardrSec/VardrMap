"""Bounded explicit v2 sequencing; no retries, signing, execution or host access."""

from datetime import datetime

import execution_control as control
from fastapi import HTTPException
from managed_wire import canonical, digest, fields, integer, require
from models import JobExecution, ManagedRuntime, ManagedRuntimeAttempt


class Sequences:
    def __init__(self, runtimes):
        self.r = runtimes
        self.issuer, self.results, self.stops = (
            runtimes.issuer,
            runtimes.results,
            runtimes.stops,
        )

    @staticmethod
    def binding(row, attempt):
        from managed_runtime import BINDING_FIELDS, _uuid, fingerprint, identifier

        identifier(attempt.job_id)
        _uuid(attempt.contract_id)
        _uuid(attempt.attempt_id)
        integer(attempt.fence, 1)
        fingerprint(attempt.contract_sha256)
        return {
            key: getattr(attempt, key)
            if key not in {"origin", "runner_id"}
            else getattr(row, key)
            for key in BINDING_FIELDS
        }

    @staticmethod
    def terminal(binding, receipt):
        from managed_runtime import BINDING_FIELDS, fingerprint
        from managed_stops import RECEIPT_CAUSES

        require(type(receipt) is dict, "sequence_terminal_missing")
        stop = receipt.get("schema") == "vardr.managed-stop-receipt/1"
        fields(
            receipt,
            BINDING_FIELDS
            | {"schema", "outcome", "receipt_sha256", "capacity_reserved"}
            | ({"cause"} if stop else set()),
        )
        integer(receipt["fence"], 1)
        require(
            all(receipt[key] == value for key, value in binding.items())
            and receipt["capacity_reserved"] is False
            and receipt["outcome"] in {"completed", "failed", "cancelled"}
            and (stop or receipt["schema"] == "vardr.managed-completion/1"),
            "sequence_terminal_changed",
        )
        fingerprint(receipt["receipt_sha256"])
        if stop:
            require(
                receipt["cause"] in RECEIPT_CAUSES
                and receipt["outcome"] != "completed",
                "sequence_terminal_changed",
            )
        return receipt

    @staticmethod
    def release_ack(row, attempt):
        payload = {
            "schema": "vardr.worker-idle-release/1",
            "runtime_id": row.id,
            "runtime_sha256": row.runtime_sha256,
            "runtime_sequence": attempt.runtime_sequence,
            "binding": Sequences.binding(row, attempt),
            "terminal_receipt_sha256": attempt.terminal_receipt_sha256,
            "native_done_sha256": attempt.native_done_sha256,
            "released": True,
        }
        return {**payload, "receipt_sha256": digest(payload)}

    def checked(self, db, row):
        """At most 32 immutable entries; incomplete or inconsistent history refuses."""
        from managed_runtime import fingerprint

        require(getattr(row, "mode", None) is None, "runtime_protocol_changed")
        self.r._check(row)
        integer(row.max_attempts, 1, 32)
        integer(row.last_sequence, 0, row.max_attempts)
        attempts = (
            db.query(ManagedRuntimeAttempt)
            .filter_by(runtime_id=row.id)
            .order_by(ManagedRuntimeAttempt.runtime_sequence)
            .populate_existing()
            .limit(33)
            .all()
        )
        require(len(attempts) == row.last_sequence, "runtime_history_incomplete")
        for sequence, attempt in enumerate(attempts, 1):
            require(
                attempt.runtime_sequence == sequence
                and isinstance(attempt.bound_at, datetime),
                "runtime_history_incomplete",
            )
            binding = self.binding(row, attempt)
            release = (
                attempt.released_at,
                attempt.terminal_receipt,
                attempt.terminal_receipt_sha256,
                attempt.native_done_sha256,
                attempt.release_receipt,
            )
            if attempt.released_at is None:
                require(
                    all(value is None for value in release)
                    and row.active_sequence == sequence == row.last_sequence,
                    "runtime_history_incomplete",
                )
            else:
                require(
                    all(value is not None for value in release)
                    and isinstance(attempt.released_at, datetime)
                    and isinstance(attempt.confirmed_at, datetime),
                    "runtime_history_incomplete",
                )
                receipt = self.terminal(binding, attempt.terminal_receipt)
                require(
                    receipt["outcome"] == "completed"
                    and receipt["schema"] == "vardr.managed-completion/1"
                    and digest(receipt) == fingerprint(attempt.terminal_receipt_sha256),
                    "runtime_release_changed",
                )
                fingerprint(attempt.native_done_sha256)
                require(
                    canonical(attempt.release_receipt)
                    == canonical(self.release_ack(row, attempt)),
                    "runtime_release_changed",
                )
        if row.active_sequence is not None:
            integer(row.active_sequence, 1, row.max_attempts)
            require(
                row.active_sequence == row.last_sequence
                and attempts[-1].released_at is None,
                "runtime_history_incomplete",
            )
        require(
            (
                not attempts
                or row.active_sequence is not None
                or attempts[-1].released_at is not None
            ),
            "runtime_history_incomplete",
        )
        if row.retired:
            receipt = row.retirement_receipt
            require(
                type(receipt) is dict and len(canonical(receipt)) <= 16384,
                "runtime_retirement_changed",
            )
            expected = self.retirement(
                row,
                attempts[-1] if row.active_sequence else None,
                receipt.get("attempt_receipt"),
            )
            require(
                canonical(receipt) == canonical(expected), "runtime_retirement_changed"
            )
        else:
            require(row.retirement_receipt is None, "runtime_retirement_changed")
        return attempts

    def retirement(self, row, attempt, terminal):
        from managed_runtime import fingerprint

        binding = self.binding(row, attempt) if attempt else None
        require((binding is None) == (terminal is None), "runtime_retirement_changed")
        if binding:
            self.terminal(binding, terminal)
        payload = {
            "schema": "vardr.worker-retirement/2",
            "runtime_id": row.id,
            "runtime_sha256": row.runtime_sha256,
            "origin": row.origin,
            "runner_id": row.runner_id,
            "enrollment_id": row.enrollment_id,
            "runtime_sequence": attempt.runtime_sequence if attempt else None,
            "last_sequence": row.last_sequence,
            "binding": binding,
            "attempt_receipt": terminal,
            "report_sha256": fingerprint(row.report_sha256),
            "retired": True,
        }
        return {**payload, "receipt_sha256": digest(payload)}

    def current_receipt(self, db, row, attempt):
        if attempt.released_at is not None:
            return attempt.terminal_receipt
        if row.retired:
            return row.retirement_receipt["attempt_receipt"]
        binding = self.binding(row, attempt)
        stop, result = self.stops._row(db, binding), self.results._result(db, binding)
        require(stop is None or result is None, "conflicting_runtime_receipts")
        if stop:
            return self.stops._receipt(binding, stop)
        if result and result.outcome:
            require(
                isinstance(result.finished_at, datetime), "runtime_terminal_missing"
            )
            execution = db.get(JobExecution, attempt.job_id)
            require(execution is not None, "runtime_execution_missing")
            return self.results._completion(binding, result, execution)
        return None

    def claim(
        self, db, request, *, job_id, body, runtime_id, runtime_sha256, runtime_sequence
    ):
        integer(runtime_sequence, 1, 32)

        def prepare(*, db, now, job, approval, projection):
            row = (
                db.query(ManagedRuntime)
                .filter_by(id=runtime_id)
                .with_for_update()
                .populate_existing()
                .first()
            )
            require(row is not None, "runtime_unavailable")
            self.checked(db, row)
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
                and row.active_sequence is None
                and runtime_sequence == row.last_sequence + 1 <= row.max_attempts,
                "runtime_claim_binding",
            )
            self.r._active(row, now().replace(tzinfo=None))

            def associate(contract):
                row.last_sequence = row.active_sequence = runtime_sequence
                db.add(
                    ManagedRuntimeAttempt(
                        runtime_id=row.id,
                        runtime_sequence=runtime_sequence,
                        job_id=job.id,
                        contract_id=contract.id,
                        attempt_id=contract.attempt_id,
                        fence=contract.fence,
                        contract_sha256=digest(contract.envelope),
                        bound_at=now().replace(tzinfo=None),
                    )
                )
                db.flush()
                self.r._active(row, now().replace(tzinfo=None))

            return associate

        return self.issuer.claim(
            db, request, job_id=job_id, body=body, on_claim=prepare
        )

    def owned(self, db, request, job_id, body, values):
        return self.results._owned(
            db,
            request,
            job_id,
            body,
            **{
                key: values[key]
                for key in ("contract_id", "attempt_id", "fence", "contract_sha256")
            },
        )

    def locked_attempt(
        self,
        db,
        runtime_id,
        runtime_sha256,
        runtime_sequence,
        binding,
        approval,
        execution,
    ):
        integer(runtime_sequence, 1, 32)
        row = (
            db.query(ManagedRuntime)
            .filter_by(id=runtime_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        require(row is not None, "runtime_unavailable")
        attempts = self.checked(db, row)
        require(runtime_sequence <= len(attempts), "runtime_history_missing")
        attempt = attempts[runtime_sequence - 1]
        snapshot = approval.authority_snapshot["enrollment"]
        require(
            self.binding(row, attempt) == binding
            and row.runtime_sha256 == runtime_sha256
            and row.owner == execution.owner == approval.owner
            and row.enrollment_id == approval.enrollment_id == snapshot["id"]
            and row.enrollment_revision == snapshot["revision"]
            and row.api_key_id == snapshot["api_key_id"]
            and row.principal_sha256
            == execution.principal_hash
            == snapshot["principal_sha256"]
            and row.origin == binding["origin"]
            and row.runner_id == binding["runner_id"],
            "runtime_attempt_binding",
        )
        return row, attempt

    def bind(
        self,
        db,
        request,
        *,
        job_id,
        body,
        runtime_id,
        runtime_sha256,
        runtime_sequence,
        **values,
    ):
        with self.issuer.operation(db) as now:
            _, job, execution, approval, binding = self.owned(
                db, request, job_id, body, values
            )
            approval, projection = self.issuer._claim_permission(
                db, request, job, body, now, job_statuses=("running",)
            )
            row, attempt = self.locked_attempt(
                db,
                runtime_id,
                runtime_sha256,
                runtime_sequence,
                binding,
                approval,
                execution,
            )
            require(
                row.active_sequence == runtime_sequence
                and not row.retired
                and attempt.confirmed_at is None,
                "runtime_attempt_binding",
            )
            self.r._active(row, now().replace(tzinfo=None))
            attempt.confirmed_at = now().replace(tzinfo=None)
            db.flush()
            self.issuer._locked_time(db, now)
            instant = max(now().replace(tzinfo=None), control.now())
            self.r._active(row, instant)
            require(
                execution.state == "active" and execution.expires_at > instant,
                "runtime_live_permission_required",
            )
            self.issuer.wire.approval(
                approval.envelope, projection["context"], approval.owner, now()
            )
            reply = {
                "schema": "vardr.worker-runtime-binding/2",
                **binding,
                "runtime_id": runtime_id,
                "runtime_sha256": runtime_sha256,
                "runtime_sequence": runtime_sequence,
                "bound": True,
            }
            db.commit()
            return reply

    def release(
        self,
        db,
        request,
        *,
        job_id,
        body,
        runtime_id,
        runtime_sha256,
        runtime_sequence,
        terminal_receipt_sha256,
        native_done_sha256,
        **values,
    ):
        from managed_runtime import fingerprint

        fingerprint(terminal_receipt_sha256)
        fingerprint(
            native_done_sha256
        )  # Correlation only, not server-side native attestation.
        with self.issuer.operation(db) as now:
            _, job, execution, approval, binding = self.owned(
                db, request, job_id, body, values
            )
            # Current original enrollment/key remains required, but expired job
            # approval/lease cannot rewrite its already canonical completion.
            enrollment, _ = self.issuer._enrollment(
                db, approval.enrollment_id, approval.owner
            )
            row, attempt = self.locked_attempt(
                db,
                runtime_id,
                runtime_sha256,
                runtime_sequence,
                binding,
                approval,
                execution,
            )
            require(
                enrollment.revision == row.enrollment_revision,
                "runtime_attempt_binding",
            )
            self.r._active(row, now().replace(tzinfo=None))
            require(not row.retired, "runtime_retired")
            if attempt.released_at is not None:
                require(
                    attempt.terminal_receipt_sha256 == terminal_receipt_sha256
                    and attempt.native_done_sha256 == native_done_sha256,
                    "runtime_release_changed",
                )
                reply = attempt.release_receipt
                db.rollback()
                return reply
            require(
                row.active_sequence == runtime_sequence
                and attempt.confirmed_at is not None,
                "runtime_attempt_binding",
            )
            result = self.results._result(db, binding)
            require(
                self.stops._row(db, binding) is None
                and result is not None
                and result.outcome == "completed",
                "healthy_completion_required",
            )
            require(
                job.status == "done" and isinstance(result.finished_at, datetime),
                "healthy_completion_required",
            )
            terminal = self.results._completion(binding, result, execution)
            require(
                digest(terminal) == terminal_receipt_sha256,
                "runtime_terminal_digest_changed",
            )
            attempt.released_at = now().replace(tzinfo=None)
            attempt.terminal_receipt = terminal
            attempt.terminal_receipt_sha256 = terminal_receipt_sha256
            attempt.native_done_sha256 = native_done_sha256
            attempt.release_receipt = self.release_ack(row, attempt)
            row.active_sequence = None
            db.flush()
            self.issuer._locked_time(db, now)
            self.r._active(row, now().replace(tzinfo=None))
            reply = attempt.release_receipt
            db.commit()
            return reply

    def receipt(self, db, row, sequence=None):
        signature = (
            row.last_sequence,
            row.active_sequence,
            row.retired,
            row.report_sha256,
        )
        attempts = self.checked(db, row)
        if sequence is not None:
            integer(sequence, 1, 32)
            if sequence > len(attempts):
                raise HTTPException(404)
            attempt = attempts[sequence - 1]
            reply = {
                "schema": "vardr.worker-attempt-observation/1",
                "runtime_id": row.id,
                "runtime_sha256": row.runtime_sha256,
                "runtime_sequence": sequence,
                "binding": self.binding(row, attempt),
                "receipt": self.current_receipt(db, row, attempt),
                "release": attempt.release_receipt,
            }
        else:
            attempt = attempts[-1] if row.active_sequence else None
            reply = {
                "schema": "vardr.worker-receipt-observation/2",
                "runtime_id": row.id,
                "runtime_sha256": row.runtime_sha256,
                "last_sequence": row.last_sequence,
                "active": {
                    "runtime_sequence": attempt.runtime_sequence,
                    "binding": self.binding(row, attempt),
                    "receipt": self.current_receipt(db, row, attempt),
                }
                if attempt
                else None,
                "retirement": row.retirement_receipt,
            }
        # Reads never take Runtime after a receipt row lock. A monotone cursor
        # recheck refuses a mixed projection without reversing the write order.
        current = (
            db.query(
                ManagedRuntime.last_sequence,
                ManagedRuntime.active_sequence,
                ManagedRuntime.retired,
                ManagedRuntime.report_sha256,
            )
            .filter_by(id=row.id)
            .one()
        )
        require(tuple(current) == signature, "runtime_observation_changed")
        db.rollback()
        return reply

    def exit(
        self,
        db,
        request,
        *,
        runtime_id,
        runtime_sha256,
        finished_at,
        exit_code,
        observation_sha256,
        runtime_sequence=None,
        last_sequence=None,
        binding=None,
    ):
        from managed_runtime import fingerprint, normalized_start

        fingerprint(runtime_sha256)
        fingerprint(observation_sha256)
        integer(exit_code, 0, 255)
        bound = binding is not None
        integer(runtime_sequence if bound else last_sequence, 1 if bound else 0, 32)
        body = {
            "runtime_sha256": runtime_sha256,
            "finished_at": finished_at,
            "exit_code": exit_code,
            "observation_sha256": observation_sha256,
        }
        body.update(
            {**binding, "runtime_sequence": runtime_sequence}
            if bound
            else {"last_sequence": last_sequence}
        )
        report_sha = digest(
            {
                "schema": "vardr.worker-exit-report/2"
                if bound
                else "vardr.worker-unbound-exit-report/2",
                "runtime_id": runtime_id,
                **body,
            }
        )
        with self.issuer.operation(db) as now:
            self.issuer._begin_write(db)
            row = self.r._host(db, request, runtime_id)
            attempts = self.checked(db, row)
            require(
                row.runtime_sha256 == runtime_sha256
                and normalized_start(finished_at)
                >= normalized_start(row.identity["started_at"]),
                "host_runtime_binding",
            )
            if bound:
                require(runtime_sequence <= len(attempts), "runtime_history_missing")
                attempt = attempts[runtime_sequence - 1]
                job, execution, expected, contract = self.r._lock_host_attempt(
                    db, row, binding, attempt=attempt
                )
            row = self.r._host(db, request, runtime_id, locked=True)
            attempts = self.checked(db, row)
            self.r._active(row, now().replace(tzinfo=None))
            # Never retarget after a wait: the original cursor becomes permanently
            # impossible once it advances, even if the runtime becomes idle again.
            require(
                (
                    row.active_sequence == runtime_sequence == row.last_sequence
                    and self.binding(row, attempts[runtime_sequence - 1]) == binding
                )
                if bound
                else (
                    row.active_sequence is None and row.last_sequence == last_sequence
                ),
                "runtime_exit_cursor_changed",
            )
            if row.retired:
                require(row.report_sha256 == report_sha, "host_report_changed")
                receipt = row.retirement_receipt
            else:
                terminal = None
                if bound:
                    attempt = attempts[runtime_sequence - 1]
                    stop, result = (
                        self.stops._row(db, expected),
                        self.results._result(db, expected),
                    )
                    require(
                        stop is None or result is None, "conflicting_runtime_receipts"
                    )
                    if stop:
                        terminal = self.stops._receipt(expected, stop)
                    elif result and result.outcome:
                        require(
                            isinstance(result.finished_at, datetime),
                            "runtime_terminal_missing",
                        )
                        terminal = self.results._completion(expected, result, execution)
                    elif result:
                        require(
                            contract.consumed is True, "result_consumption_required"
                        )
                        terminal = self.results._fail_locked(
                            db, now, job, execution, expected, result
                        )
                        job.error_message = "observed_exit"
                    else:
                        terminal = self.stops._stop_locked(
                            db,
                            now,
                            job,
                            execution,
                            expected,
                            outcome="failed",
                            cause="observed_exit",
                        )
                row.retired, row.report_sha256 = True, report_sha
                receipt = self.retirement(row, attempt if bound else None, terminal)
                row.retirement_receipt = receipt
                db.flush()
                self.issuer._locked_time(db, now)
                self.r._active(row, now().replace(tzinfo=None))
            db.commit()
            return {
                "schema": "vardr.worker-host-stop/1",
                "runtime_id": runtime_id,
                "runtime_sha256": runtime_sha256,
                "receipt": receipt,
            }
