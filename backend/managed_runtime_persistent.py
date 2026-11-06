"""Inactive v3 availability, wrapping the existing issuer and receipt services.

Identity admission and advisory presence are not job permission. No scanner,
credential provider, automatic replay or infrastructure is introduced here.
"""

from datetime import datetime, timedelta, timezone

import execution_control as control
from managed_persistent_wire import (
    MAX_SEQUENCE,
    MODE,
    checked_cursor,
    cursor,
    limits,
    sequence,
)
from managed_wire import canonical, digest, integer, require, stamp
from models import ManagedRuntime, ManagedRuntimeAttempt

PRESENCE_SECONDS = 15
REPORTING = {"purpose": "worker-stop-only", "expires_at": None}


class Persistent:
    def __init__(self, runtimes):
        self.r = runtimes
        self.issuer, self.results, self.stops = (
            runtimes.issuer,
            runtimes.results,
            runtimes.stops,
        )
        self.finite = runtimes.sequences

    def enabled(self):
        require(self.r.persistent_enabled is True, "persistent_runtime_inactive")

    @staticmethod
    def public(row):
        payload = {
            "schema": "vardr.worker-admission/3",
            "runtime_id": row.id,
            "runtime_sha256": row.runtime_sha256,
            "enrollment_id": row.enrollment_id,
            "runner_id": row.runner_id,
            "origin": row.origin,
            "capability_sha256": row.capability_sha256,
            "identity": row.identity,
            "mode": MODE,
            "limits": {
                "max_attempts": str(row.max_attempts)
                if row.max_attempts is not None
                else None,
                "idle_timeout_seconds": row.idle_timeout_seconds,
            },
            "reporting_authority": dict(REPORTING),
        }
        return {**payload, "admission_sha256": digest(payload)}

    @staticmethod
    def check_row(row):
        from managed_runtime import Runtimes, check_identity, fingerprint

        sha, physical = check_identity(row.identity)
        require(
            row.mode == MODE
            and row.runtime_sha256 == sha
            and row.physical_sha256 == physical
            and row.owner_nonce == row.identity["owner_nonce"]
            and row.ttl_seconds is None
            and row.expires_at is None
            and type(row.revoked) is bool
            and type(row.retired) is bool
            and type(row.new_work_disabled) is bool
            and isinstance(row.registered_at, datetime)
            and Runtimes._binding(row) is None
            and row.confirmed_at is None,
            "retained_persistent_runtime_inconsistent",
        )
        fingerprint(row.capability_sha256)
        fingerprint(row.principal_sha256)
        limits(Persistent.public(row)["limits"])
        integer(row.last_sequence, 0, MAX_SEQUENCE)
        require(
            row.head_sequence == (row.last_sequence or None), "runtime_head_changed"
        )
        cursor(row.last_sequence, row.active_sequence)
        require(
            type(row.admission_snapshot) is dict
            and canonical(row.admission_snapshot) == canonical(Persistent.public(row))
            and row.admission_sha256 == row.admission_snapshot["admission_sha256"],
            "runtime_admission_changed",
        )
        require(
            (row.report_sha256 is None) == (not row.retired),
            "runtime_retirement_changed",
        )
        if row.report_sha256 is not None:
            fingerprint(row.report_sha256)

    @staticmethod
    def admitted(row, *, new_work=True):
        require(
            not row.retired
            and not row.revoked
            and (not new_work or not row.new_work_disabled),
            "runtime_admission_unavailable",
        )

    @staticmethod
    def report_allowed(row):
        # Proposed Option A is purpose-limited until explicit revoke/retirement.
        # There is deliberately no execution lease or TTL renewal here.
        require(not row.revoked, "runtime_reporting_unavailable")

    def selected(self, db, row, number):
        integer(number, 1, MAX_SEQUENCE)
        attempt = (
            db.query(ManagedRuntimeAttempt)
            .filter_by(runtime_id=row.id, runtime_sequence=number)
            .populate_existing()
            .first()
        )
        require(
            attempt is not None and attempt.runtime_mode == MODE,
            "runtime_history_missing",
        )
        require(
            attempt.previous_sequence == (number - 1 or None)
            and isinstance(attempt.bound_at, datetime),
            "runtime_history_incomplete",
        )
        if number > 1:
            previous = (
                db.query(ManagedRuntimeAttempt)
                .filter_by(
                    runtime_id=row.id, runtime_sequence=number - 1, runtime_mode=MODE
                )
                .first()
            )
            require(previous is not None, "runtime_history_incomplete")
        binding = self.finite.binding(row, attempt)
        retained = (
            attempt.released_at,
            attempt.terminal_receipt,
            attempt.terminal_receipt_sha256,
            attempt.native_done_sha256,
            attempt.release_receipt,
        )
        if attempt.released_at is None:
            require(
                all(value is None for value in retained)
                and row.active_sequence == number == row.last_sequence,
                "runtime_history_incomplete",
            )
        else:
            require(
                all(value is not None for value in retained)
                and isinstance(attempt.released_at, datetime)
                and isinstance(attempt.confirmed_at, datetime),
                "runtime_history_incomplete",
            )
            terminal = self.finite.terminal(binding, attempt.terminal_receipt)
            require(
                terminal["schema"] == "vardr.managed-completion/1"
                and terminal["outcome"] in {"completed", "failed"}
                and digest(terminal) == attempt.terminal_receipt_sha256
                and canonical(attempt.release_receipt)
                == canonical(self.release_ack(row, attempt)),
                "runtime_release_changed",
            )
        return attempt

    def checked(self, db, row):
        """Indexed head/predecessor checks; database FKs retain the entire chain."""
        self.check_row(row)
        head = self.selected(db, row, row.last_sequence) if row.last_sequence else None
        future = (
            db.query(ManagedRuntimeAttempt.runtime_sequence)
            .filter(
                ManagedRuntimeAttempt.runtime_id == row.id,
                ManagedRuntimeAttempt.runtime_sequence > row.last_sequence,
            )
            .first()
        )
        require(future is None, "runtime_history_incomplete")
        require(
            row.active_sequence is not None
            or head is None
            or head.released_at is not None,
            "runtime_history_incomplete",
        )
        if row.retired:
            require(
                type(row.retirement_receipt) is dict
                and canonical(row.retirement_receipt)
                == canonical(
                    self.retirement(
                        row,
                        head if row.active_sequence else None,
                        row.retirement_receipt.get("attempt_receipt"),
                    )
                ),
                "runtime_retirement_changed",
            )
        else:
            require(row.retirement_receipt is None, "runtime_retirement_changed")
        return head

    def row(self, db, runtime_id, sha, admission_sha256, *, locked=False):
        from managed_runtime import fingerprint

        query = db.query(ManagedRuntime).filter_by(id=runtime_id)
        if locked:
            query = query.with_for_update().populate_existing()
        row = query.first()
        require(row is not None, "runtime_unavailable")
        self.checked(db, row)
        require(
            row.runtime_sha256 == fingerprint(sha)
            and row.admission_sha256 == fingerprint(admission_sha256),
            "runtime_admission_changed",
        )
        return row

    def register(
        self,
        db,
        request,
        *,
        runtime_id,
        enrollment_id,
        runner_id,
        origin,
        identity,
        capability_sha256,
        selected_limits,
        reporting_authority,
    ):
        from managed_runtime import _uuid, check_identity, fingerprint

        self.enabled()
        _uuid(runtime_id)
        _uuid(runner_id)
        fingerprint(capability_sha256)
        selected_limits = limits(selected_limits)
        require(
            type(reporting_authority) is dict
            and canonical(reporting_authority) == canonical(REPORTING),
            "runtime_reporting_policy_changed",
        )
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
            row = (
                db.query(ManagedRuntime)
                .filter_by(id=runtime_id)
                .with_for_update()
                .populate_existing()
                .first()
            )
            maximum = selected_limits["max_attempts"]
            maximum = sequence(maximum, 1) if maximum is not None else None
            if row is None:
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
                    mode=MODE,
                    ttl_seconds=None,
                    expires_at=None,
                    registered_at=now().replace(tzinfo=None),
                    revoked=False,
                    retired=False,
                    new_work_disabled=False,
                    max_attempts=maximum,
                    idle_timeout_seconds=selected_limits["idle_timeout_seconds"],
                    last_sequence=0,
                    head_sequence=None,
                )
                row.admission_snapshot = self.public(row)
                row.admission_sha256 = row.admission_snapshot["admission_sha256"]
                db.add(row)
            else:
                self.checked(db, row)
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
                    and row.max_attempts == maximum
                    and row.idle_timeout_seconds
                    == selected_limits["idle_timeout_seconds"],
                    "runtime_registration_changed",
                )
            db.flush()
            self.issuer._locked_time(db, now)
            reply = self.public(row)
            db.commit()
            return reply

    def claim(
        self,
        db,
        request,
        *,
        job_id,
        body,
        runtime_id,
        runtime_sha256,
        admission_sha256,
        runtime_sequence,
    ):
        self.enabled()
        number = sequence(runtime_sequence, 1)

        def prepare(*, db, now, job, approval, projection):
            row = self.row(
                db, runtime_id, runtime_sha256, admission_sha256, locked=True
            )
            enrolled = projection["authority_snapshot"]["enrollment"]
            require(
                row.owner == approval.owner
                and row.enrollment_id == enrolled["id"]
                and row.enrollment_revision == enrolled["revision"]
                and row.api_key_id == enrolled["api_key_id"]
                and row.principal_sha256 == enrolled["principal_sha256"]
                and row.origin == body.origin == self.issuer.origin
                and row.runner_id == str(body.runner_id) == enrolled["runner_id"]
                and row.active_sequence is None
                and number == row.last_sequence + 1
                and (row.max_attempts is None or number <= row.max_attempts),
                "runtime_claim_binding",
            )
            self.admitted(row)
            head = self.checked(db, row)
            idle_end = (
                (head.released_at if head else row.registered_at)
                + timedelta(seconds=row.idle_timeout_seconds)
                if row.idle_timeout_seconds is not None
                else None
            )
            require(
                idle_end is None or idle_end > now().replace(tzinfo=None),
                "runtime_idle_expired",
            )

            def associate(contract):
                require(
                    idle_end is None or idle_end > now().replace(tzinfo=None),
                    "runtime_idle_expired",
                )
                row.last_sequence = row.head_sequence = row.active_sequence = number
                db.add(
                    ManagedRuntimeAttempt(
                        runtime_id=row.id,
                        runtime_sequence=number,
                        runtime_mode=MODE,
                        previous_sequence=number - 1 or None,
                        job_id=job.id,
                        contract_id=contract.id,
                        attempt_id=contract.attempt_id,
                        fence=contract.fence,
                        contract_sha256=digest(contract.envelope),
                        bound_at=now().replace(tzinfo=None),
                    )
                )
                db.flush()
                self.admitted(row)

            return associate

        return self.issuer.claim(
            db, request, job_id=job_id, body=body, on_claim=prepare
        )

    def release_ack(self, row, attempt):
        from managed_runtime import fingerprint

        fingerprint(attempt.terminal_receipt_sha256)
        fingerprint(attempt.native_done_sha256)
        payload = {
            "schema": "vardr.worker-idle-release/2",
            "runtime_id": row.id,
            "runtime_sha256": row.runtime_sha256,
            "admission_sha256": row.admission_sha256,
            "runtime_sequence": str(attempt.runtime_sequence),
            "binding": self.finite.binding(row, attempt),
            "terminal_receipt_sha256": attempt.terminal_receipt_sha256,
            "native_done_sha256": attempt.native_done_sha256,
            "released": True,
        }
        return {**payload, "receipt_sha256": digest(payload)}

    def owned_attempt(self, db, request, job_id, body, values, *, owned=None):
        owned = (
            self.finite.owned(db, request, job_id, body, values)
            if owned is None
            else owned
        )
        _, job, execution, approval, binding = owned
        row = self.row(
            db,
            values["runtime_id"],
            values["runtime_sha256"],
            values["admission_sha256"],
            locked=True,
        )
        attempt = self.selected(db, row, sequence(values["runtime_sequence"], 1))
        snapshot = approval.authority_snapshot["enrollment"]
        require(
            self.finite.binding(row, attempt) == binding
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
        return row, attempt, owned

    def bind(self, db, request, *, job_id, body, **values):
        self.enabled()
        with self.issuer.operation(db) as now:
            owned = self.finite.owned(db, request, job_id, body, values)
            _, job, execution, approval, binding = owned
            approval, projection = self.issuer._claim_permission(
                db, request, job, body, now, job_statuses=("running",)
            )
            row, attempt, owned = self.owned_attempt(
                db, request, job_id, body, values, owned=owned
            )
            require(
                row.active_sequence == attempt.runtime_sequence
                and attempt.confirmed_at is None,
                "runtime_attempt_binding",
            )
            self.admitted(row, new_work=False)
            attempt.confirmed_at = now().replace(tzinfo=None)
            db.flush()
            self.issuer._locked_time(db, now)
            self.admitted(row, new_work=False)
            require(
                execution.state == "active"
                and execution.expires_at
                > max(now().replace(tzinfo=None), control.now()),
                "runtime_live_permission_required",
            )
            self.issuer.wire.approval(
                approval.envelope, projection["context"], approval.owner, now()
            )
            reply = {
                "schema": "vardr.worker-runtime-binding/3",
                **binding,
                "runtime_id": row.id,
                "runtime_sha256": row.runtime_sha256,
                "admission_sha256": row.admission_sha256,
                "runtime_sequence": str(attempt.runtime_sequence),
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
        terminal_receipt_sha256,
        native_done_sha256,
        **values,
    ):
        from managed_runtime import fingerprint

        self.enabled()
        fingerprint(terminal_receipt_sha256)
        fingerprint(
            native_done_sha256
        )  # Trusted-client correlation, not remote native attestation.
        with self.issuer.operation(db) as now:
            owned = self.finite.owned(db, request, job_id, body, values)
            _, job, execution, approval, binding = owned
            enrollment, _ = self.issuer._enrollment(
                db, approval.enrollment_id, approval.owner
            )
            row, attempt, owned = self.owned_attempt(
                db, request, job_id, body, values, owned=owned
            )
            require(
                enrollment.revision == row.enrollment_revision,
                "runtime_attempt_binding",
            )
            self.admitted(row, new_work=False)
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
                row.active_sequence == attempt.runtime_sequence
                and attempt.confirmed_at is not None,
                "runtime_attempt_binding",
            )
            result = self.results._result(db, binding)
            require(
                self.stops._row(db, binding) is None
                and result is not None
                and result.outcome in {"completed", "failed"}
                and execution.capacity_reserved is False
                and execution.state == result.outcome
                and job.status
                == ("done" if result.outcome == "completed" else "failed")
                and isinstance(result.finished_at, datetime),
                "reusable_completion_required",
            )
            terminal = self.results._completion(binding, result, execution)
            require(
                digest(terminal) == terminal_receipt_sha256,
                "runtime_terminal_digest_changed",
            )
            attempt.released_at = now().replace(tzinfo=None)
            attempt.terminal_receipt, attempt.terminal_receipt_sha256 = (
                terminal,
                terminal_receipt_sha256,
            )
            attempt.native_done_sha256 = native_done_sha256
            attempt.release_receipt = self.release_ack(row, attempt)
            row.active_sequence = None
            db.flush()
            self.issuer._locked_time(db, now)
            self.admitted(row, new_work=False)
            reply = attempt.release_receipt
            db.commit()
            return reply

    @staticmethod
    def disable_ack(row):
        payload = {
            "schema": "vardr.worker-disable/1",
            "runtime_id": row.id,
            "runtime_sha256": row.runtime_sha256,
            "admission_sha256": row.admission_sha256,
            "new_work_disabled": True,
        }
        return {**payload, "receipt_sha256": digest(payload)}

    def disable(self, db, request, *, runtime_id, runtime_sha256, admission_sha256):
        with self.issuer.operation(db) as now:
            self.issuer._begin_write(db)
            row = self.r._host(db, request, runtime_id, locked=True)
            self.checked(db, row)
            require(
                row.runtime_sha256 == runtime_sha256
                and row.admission_sha256 == admission_sha256,
                "runtime_admission_changed",
            )
            self.report_allowed(row)
            row.new_work_disabled = True
            db.flush()
            self.issuer._locked_time(db, now)
            self.report_allowed(row)
            reply = self.disable_ack(row)
            db.commit()
            return reply

    @staticmethod
    def mark_presence(row, state, instant):
        row.presence_at = instant
        row.presence = {
            "state": state,
            "cursor": cursor(row.last_sequence, row.active_sequence),
        }

    def availability(self, row, instant):
        current = cursor(row.last_sequence, row.active_sequence)
        observed = row.presence_at if isinstance(row.presence_at, datetime) else None
        end = observed + timedelta(seconds=PRESENCE_SECONDS) if observed else None
        fresh = observed is not None and observed <= instant < end
        state = "held"
        if row.retired:
            state = "stopped"
        elif (
            fresh
            and not row.new_work_disabled
            and not row.revoked
            and type(row.presence) is dict
            and set(row.presence) == {"state", "cursor"}
            and canonical(row.presence["cursor"]) == canonical(current)
            and row.presence["state"]
            == ("active" if row.active_sequence else "idle-ready")
        ):
            state = row.presence["state"]
        return {
            "state": state,
            "observed_at": stamp(observed.replace(tzinfo=timezone.utc))
            if observed
            else None,
            "fresh_until": stamp(end.replace(tzinfo=timezone.utc)) if end else None,
            "cursor": current,
        }

    def pending(self, db, enrollment, body, now):
        self.enabled()
        self.issuer._begin_write(db)
        row = self.row(
            db,
            str(body.runtime_id),
            body.runtime_sha256,
            body.admission_sha256,
            locked=True,
        )
        require(
            row.enrollment_id == enrollment.id
            and row.enrollment_revision == enrollment.revision
            and row.owner == enrollment.owner
            and row.api_key_id == enrollment.api_key_id
            and row.principal_sha256 == enrollment.principal_hash
            and row.origin == enrollment.origin == body.origin
            and row.runner_id == enrollment.runner_id == str(body.runner_id),
            "runtime_presence_binding",
        )
        self.admitted(row)
        require(
            checked_cursor(body.cursor.model_dump()) == (row.last_sequence, "idle")
            and row.active_sequence is None
            and (row.max_attempts is None or row.last_sequence < row.max_attempts),
            "runtime_presence_cursor_changed",
        )
        head = self.checked(db, row)
        idle_start = head.released_at if head else row.registered_at
        require(
            row.idle_timeout_seconds is None
            or idle_start + timedelta(seconds=row.idle_timeout_seconds)
            > now().replace(tzinfo=None),
            "runtime_idle_expired",
        )
        self.mark_presence(row, "idle-ready", now().replace(tzinfo=None))
        return row

    def control_guard(self, *, db, now, job, execution, contract, approval, projection):
        # Called by Issuer before its FIRST ManagedClock lock. No policy duplicate.
        attempt = (
            db.query(ManagedRuntimeAttempt)
            .filter_by(contract_id=contract.id, runtime_mode=MODE)
            .first()
        )
        if attempt is None:
            return
        self.enabled()
        row = (
            db.query(ManagedRuntime)
            .filter_by(id=attempt.runtime_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        require(row is not None, "runtime_unavailable")
        self.checked(db, row)
        enrolled = projection["authority_snapshot"]["enrollment"]
        require(
            row.active_sequence == attempt.runtime_sequence
            and row.enrollment_id == enrolled["id"]
            and row.enrollment_revision == enrolled["revision"]
            and row.principal_sha256
            == execution.principal_hash
            == enrolled["principal_sha256"]
            and row.api_key_id == enrolled["api_key_id"]
            and self.finite.binding(row, attempt)["job_id"] == job.id,
            "runtime_attempt_binding",
        )
        self.admitted(row, new_work=False)
        self.mark_presence(row, "active", now().replace(tzinfo=None))

    def retirement(self, row, attempt, terminal):
        from managed_runtime import fingerprint

        binding = self.finite.binding(row, attempt) if attempt else None
        require((binding is None) == (terminal is None), "runtime_retirement_changed")
        if binding:
            self.finite.terminal(binding, terminal)
        payload = {
            "schema": "vardr.worker-retirement/3",
            "runtime_id": row.id,
            "runtime_sha256": row.runtime_sha256,
            "admission_sha256": row.admission_sha256,
            "origin": row.origin,
            "runner_id": row.runner_id,
            "enrollment_id": row.enrollment_id,
            "runtime_sequence": str(attempt.runtime_sequence) if attempt else None,
            "last_sequence": str(row.last_sequence),
            "binding": binding,
            "attempt_receipt": terminal,
            "report_sha256": fingerprint(row.report_sha256),
            "retired": True,
        }
        return {**payload, "receipt_sha256": digest(payload)}

    def receipt(
        self,
        db,
        request,
        *,
        runtime_id,
        runtime_sha256,
        admission_sha256,
        runtime_sequence=None,
    ):
        from managed_runtime import fingerprint

        self.issuer._begin_write(db)
        # Result/stop readers acquire their receipt row locks. Do not acquire
        # Runtime first: writers hold the parent/job/receipt chain before Runtime.
        row = self.r._host(db, request, runtime_id)
        signature_fields = (
            "mode",
            "last_sequence",
            "head_sequence",
            "active_sequence",
            "retired",
            "report_sha256",
            "new_work_disabled",
            "revoked",
            "admission_sha256",
            "presence_at",
            "presence",
        )

        def signature(value):
            return tuple(
                canonical(getattr(value, key))
                if key == "presence"
                else getattr(value, key)
                for key in signature_fields
            )

        before = signature(row)
        head = self.checked(db, row)
        require(
            row.runtime_sha256 == fingerprint(runtime_sha256)
            and row.admission_sha256 == fingerprint(admission_sha256),
            "runtime_admission_changed",
        )
        if runtime_sequence is not None:
            number = sequence(runtime_sequence, 1)
            require(number <= row.last_sequence, "runtime_history_missing")
            attempt = self.selected(db, row, number)
            reply = {
                "schema": "vardr.worker-attempt-observation/2",
                "runtime_id": row.id,
                "runtime_sha256": row.runtime_sha256,
                "admission_sha256": row.admission_sha256,
                "runtime_sequence": runtime_sequence,
                "binding": self.finite.binding(row, attempt),
                "receipt": self.finite.current_receipt(db, row, attempt),
                "release": attempt.release_receipt,
            }
        else:
            active = None
            if row.active_sequence is not None:
                active = {
                    "runtime_sequence": str(row.active_sequence),
                    "binding": self.finite.binding(row, head),
                    "receipt": self.finite.current_receipt(db, row, head),
                }
            reply = {
                "schema": "vardr.worker-receipt-observation/3",
                "runtime_id": row.id,
                "runtime_sha256": row.runtime_sha256,
                "admission_sha256": row.admission_sha256,
                "cursor": cursor(row.last_sequence, row.active_sequence),
                "active": active,
                "retirement": row.retirement_receipt,
                "new_work_disabled": row.new_work_disabled,
                "reporting_revoked": row.revoked,
                "availability": self.availability(
                    row, self.issuer.clock().replace(tzinfo=None)
                ),
            }
        current = (
            db.query(*(getattr(ManagedRuntime, key) for key in signature_fields))
            .filter_by(id=row.id)
            .one()
        )
        require(signature(current) == before, "runtime_observation_changed")
        db.rollback()
        return reply

    def exit(
        self,
        db,
        request,
        *,
        runtime_id,
        runtime_sha256,
        admission_sha256,
        finished_at,
        exit_code,
        observation_sha256,
        runtime_sequence=None,
        last_sequence=None,
        binding=None,
    ):
        from managed_runtime import fingerprint, normalized_start

        self.enabled()
        fingerprint(runtime_sha256)
        fingerprint(admission_sha256)
        fingerprint(observation_sha256)
        integer(exit_code, 0, 255)
        finished = normalized_start(finished_at)
        bound = runtime_sequence is not None
        require(
            (binding is not None) == bound and bound == (last_sequence is None),
            "runtime_exit_cursor_required",
        )
        number = sequence(runtime_sequence, 1) if bound else sequence(last_sequence)
        report = {
            "schema": "vardr.worker-exit-report/3"
            if bound
            else "vardr.worker-unbound-exit-report/3",
            "runtime_id": runtime_id,
            "runtime_sha256": runtime_sha256,
            "admission_sha256": admission_sha256,
            "finished_at": finished_at,
            "exit_code": exit_code,
            "observation_sha256": observation_sha256,
        }
        if bound:
            report.update(**binding, runtime_sequence=runtime_sequence)
        else:
            report["last_sequence"] = last_sequence
        report_sha = digest(report)
        with self.issuer.operation(db) as now:
            self.issuer._begin_write(db)
            row = self.r._host(db, request, runtime_id)
            self.checked(db, row)
            require(
                row.runtime_sha256 == runtime_sha256
                and row.admission_sha256 == admission_sha256
                and finished >= normalized_start(row.identity["started_at"]),
                "host_runtime_binding",
            )
            self.report_allowed(row)
            attempt = None
            if bound:
                attempt = self.selected(db, row, number)
                job, execution, expected, contract = self.r._lock_host_attempt(
                    db, row, binding, attempt
                )
            # Parent/job locks precede Runtime. A waiting report never retargets.
            row = self.r._host(db, request, runtime_id, locked=True)
            self.checked(db, row)
            self.report_allowed(row)
            require(
                (
                    row.active_sequence == number == row.last_sequence
                    and self.finite.binding(row, self.selected(db, row, number))
                    == binding
                )
                if bound
                else (row.active_sequence is None and row.last_sequence == number),
                "runtime_exit_cursor_changed",
            )
            if row.retired:
                require(row.report_sha256 == report_sha, "host_report_changed")
                receipt = row.retirement_receipt
            else:
                terminal = None
                if bound:
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
                row.retired, row.new_work_disabled, row.report_sha256 = (
                    True,
                    True,
                    report_sha,
                )
                receipt = self.retirement(row, attempt, terminal)
                row.retirement_receipt = receipt
                db.flush()
                self.issuer._locked_time(db, now)
                self.report_allowed(row)
            db.commit()
            return {
                "schema": "vardr.worker-host-stop/1",
                "runtime_id": runtime_id,
                "runtime_sha256": runtime_sha256,
                "receipt": receipt,
            }
