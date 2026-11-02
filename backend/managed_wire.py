"""Small v1 wire boundary; no scope/plan policy validator or approval signer.

Approval public keys and the distinct contract private key are provisioned by a
trusted bootstrap adapter. Nothing here discovers keys, enrolls a caller, reads
credentials, or treats API authentication as human execution approval.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone


class WireRefused(ValueError):
    """Fixed reason only; do not expose a remote payload or crypto exception."""


def require(condition, reason):
    if not condition:
        raise WireRefused(reason)


def canonical(value):
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    except (ValueError, TypeError, RecursionError):
        raise WireRefused("invalid_document") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def fields(value, names):
    require(type(value) is dict and set(value) == set(names), "invalid_fields")
    return value


def identifier(value):
    require(
        type(value) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value), "invalid_identifier"
    )
    return value


def integer(value, minimum=0, maximum=2**53 - 1):
    require(type(value) is int and minimum <= value <= maximum, "invalid_integer")
    return value


def timestamp(value):
    require(
        type(value) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value),
        "invalid_time",
    )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise WireRefused("invalid_time") from None


def stamp(value):
    require(isinstance(value, datetime) and value.tzinfo is not None, "trusted_clock_required")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(data, maximum=1024 * 1024):
    require(type(data) is bytes and 0 < len(data) <= maximum, "document_size")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_key")
            result[key] = value
        return result

    def constant(_):
        raise WireRefused("invalid_number")

    def number(value):
        parsed = float(value)
        require(math.isfinite(parsed), "invalid_number")
        return parsed

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=constant,
            parse_float=number,
        )
    except (ValueError, UnicodeError, RecursionError):
        raise WireRefused("malformed_document") from None

    def depth(item, level=0):
        require(level <= 32, "document_depth")
        for child in (
            item.values() if isinstance(item, dict) else item if isinstance(item, list) else ()
        ):
            depth(child, level + 1)

    depth(value)
    return value


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64(value, maximum):
    require(
        type(value) is str
        and 0 < len(value) <= (maximum * 4 + 2) // 3
        and re.fullmatch(r"[A-Za-z0-9_-]+", value),
        "invalid_base64",
    )
    try:
        data = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except ValueError:
        raise WireRefused("invalid_base64") from None
    require(len(data) <= maximum and b64(data) == value, "invalid_base64")
    return data


def message(purpose, data):
    return b"VardrSec.AuthorizationContract.v1\0" + purpose.encode("ascii") + b"\0" + data


@dataclass(frozen=True)
class OperatorAnchor:
    issuer_id: str
    key_id: str
    approver_id: str
    public_key: bytes
    revoked: bool = False


class ContractWire:
    def __init__(self, issuer_id, key_id, contract_key, operators):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        self.issuer_id = identifier(issuer_id)
        self.key_id = identifier(key_id)
        self._signer = Ed25519PrivateKey.from_private_bytes(contract_key)
        self.operators = tuple(operators)
        public = self._signer.public_key().public_bytes_raw()
        require(bool(self.operators), "operator_trust_required")
        require(
            len({(a.issuer_id, a.key_id) for a in self.operators}) == len(self.operators),
            "duplicate_trust",
        )
        for anchor in self.operators:
            identifier(anchor.issuer_id)
            identifier(anchor.key_id)
            identifier(anchor.approver_id)
            require(
                anchor.issuer_id == issuer_id
                and anchor.key_id != key_id
                and anchor.public_key != public
                and len(anchor.public_key) == 32,
                "separate_approval_key_required",
            )

    def approval(self, envelope, context, owner, now):
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        fields(envelope, {"format", "purpose", "payload", "signature"})
        require(
            envelope["format"] == "vardr.authorization-envelope/1"
            and envelope["purpose"] == "approval",
            "envelope_version_or_purpose",
        )
        data = unb64(envelope["payload"], 256 * 1024)
        payload = parse(data, 256 * 1024)
        fields(
            payload,
            {"schema", "issuer", "origin", "approval_id", "approver_id", "approved_at", "context"},
        )
        issuer = fields(payload["issuer"], {"id", "key_id"})
        anchor = next(
            (
                a
                for a in self.operators
                if (a.issuer_id, a.key_id) == (issuer["id"], issuer["key_id"])
            ),
            None,
        )
        require(anchor is not None and not anchor.revoked, "operator_not_trusted")
        require(
            payload["schema"] == "vardr.execution-approval/1" and payload["origin"] == "map",
            "approval_schema_or_origin",
        )
        require(payload["approver_id"] == anchor.approver_id == owner, "operator_owner_mismatch")
        identifier(payload["approval_id"])
        try:
            Ed25519PublicKey.from_public_bytes(anchor.public_key).verify(
                unb64(envelope["signature"], 64), message("approval", data)
            )
        except (InvalidSignature, ValueError):
            raise WireRefused("invalid_signature") from None
        require(canonical(payload["context"]) == canonical(context), "approval_context_changed")
        require(
            context.get("control") == "managed_online"
            and context.get("mode") == "strict"
            and context.get("exceptions") == [],
            "unsupported_managed_mode",
        )
        timestamp(stamp(now))  # Reject naive/untrusted clock input before comparisons.
        require(
            timestamp(payload["approved_at"]) <= now
            and timestamp(context["not_before"]) <= now < timestamp(context["expires_at"])
            and timestamp(context["testing_start"]) <= now < timestamp(context["testing_end"]),
            "approval_expired_or_not_yet_valid",
        )
        integer(context["max_executions"], 1, 1000)
        return payload

    def issue(self, approval, context, owner, now, *, contract_id, attempt_id, fence, ordinal):
        """Server adapter only: construct exact contract fields, never sign a payload.

        The transactional issuer must first match this complete context to current
        stored authority and enrolled principal, and reserve its ordinal/fence.
        """
        receipt = self.approval(approval, context, owner, now)
        payload = {
            "schema": "vardr.authorization/1",
            "issuer": {"id": self.issuer_id, "key_id": self.key_id},
            "origin": "map",
            "contract_id": identifier(contract_id),
            "approval_sha256": digest(approval),
            "approval_id": receipt["approval_id"],
            "execution_index": integer(ordinal, 1, context["max_executions"]),
            "plan_sha256": context["plan_sha256"],
            "runner_id": identifier(context["runner_id"]),
            "engagement_id": identifier(context["engagement_id"]),
            "job_id": identifier(context["job_id"]),
            "attempt_id": identifier(attempt_id),
            "fence": integer(fence, 1),
            "issued_at": stamp(now),
            "expires_at": context["expires_at"],
            "authority_revision": integer(context["authority_revision"]),
        }
        data = canonical(payload)
        require(len(data) <= 256 * 1024, "document_size")
        return {
            "format": "vardr.authorization-envelope/1",
            "purpose": "contract",
            "payload": b64(data),
            "signature": b64(self._signer.sign(message("contract", data))),
        }
