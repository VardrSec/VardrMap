"""Purpose-separated wire checks with public test seeds, never operator keys."""

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from managed_wire import (
    ContractWire,
    OperatorAnchor,
    WireRefused,
    b64,
    canonical,
    message,
    parse,
    unb64,
)

NOW = datetime(2026, 11, 2, 18, tzinfo=timezone.utc)
APPROVAL_SEED = bytes(range(32))
CONTRACT_SEED = bytes(range(32, 64))


def fixture():
    vector = json.loads((Path(__file__).parent / "fixtures" / "managed-wire-v1.json").read_text())
    anchor = OperatorAnchor(
        "managed-fixture",
        "operator-1",
        "owner-1",
        Ed25519PrivateKey.from_private_bytes(APPROVAL_SEED).public_key().public_bytes_raw(),
    )
    return vector, ContractWire("managed-fixture", "contract-1", CONTRACT_SEED, (anchor,))


def resign(envelope, change, seed=APPROVAL_SEED):
    payload = parse(unb64(envelope["payload"], 256 * 1024))
    change(payload)
    data = canonical(payload)
    return {
        **envelope,
        "payload": b64(data),
        "signature": b64(
            Ed25519PrivateKey.from_private_bytes(seed).sign(message("approval", data))
        ),
    }


def test_exact_v1_cross_repository_vector():
    vector, wire = fixture()
    assert (
        wire.approval(vector["approval"], vector["context"], "owner-1", NOW)["approver_id"]
        == "owner-1"
    )
    assert (
        wire.issue(
            vector["approval"],
            vector["context"],
            "owner-1",
            NOW,
            contract_id="contract-1",
            attempt_id="attempt-1",
            fence=1,
            ordinal=1,
        )
        == vector["contract"]
    )


@pytest.mark.parametrize(
    "change",
    [
        "purpose",
        "format",
        "signature",
        "issuer",
        "key",
        "origin",
        "owner",
        "context",
        "extra",
        "unknown_context",
    ],
)
def test_forged_or_changed_approval_cannot_issue(change):
    vector, wire = fixture()
    approval = copy.deepcopy(vector["approval"])
    if change in {"purpose", "format"}:
        approval[change] = "untrusted"
    elif change == "signature":
        approval["signature"] = b64(b"x" * 64)
    elif change == "extra":
        approval["reviewed"] = True
    else:

        def edit(p):
            if change == "issuer":
                p["issuer"]["id"] = "other"
            elif change == "key":
                p["issuer"]["key_id"] = "contract-1"
            elif change == "origin":
                p["origin"] = "standalone"
            elif change == "owner":
                p["approver_id"] = "other"
            elif change == "context":
                p["context"]["runner_id"] = "other"
            else:
                p["context"]["reviewed"] = True

        approval = resign(approval, edit)
    with pytest.raises(WireRefused):
        wire.issue(
            approval,
            vector["context"],
            "owner-1",
            NOW,
            contract_id="c",
            attempt_id="a",
            fence=1,
            ordinal=1,
        )


@pytest.mark.parametrize("offset", [-7200, 7200])
def test_approval_time_bounds(offset):
    vector, wire = fixture()
    with pytest.raises(WireRefused):
        wire.approval(
            vector["approval"], vector["context"], "owner-1", NOW + timedelta(seconds=offset)
        )


def test_revocation_and_key_purpose_separation():
    vector, _ = fixture()
    public = Ed25519PrivateKey.from_private_bytes(APPROVAL_SEED).public_key().public_bytes_raw()
    with pytest.raises(WireRefused, match="separate_approval_key"):
        ContractWire(
            "managed-fixture",
            "contract-1",
            APPROVAL_SEED,
            (OperatorAnchor("managed-fixture", "operator-1", "owner-1", public),),
        )
    revoked = ContractWire(
        "managed-fixture",
        "contract-1",
        CONTRACT_SEED,
        (OperatorAnchor("managed-fixture", "operator-1", "owner-1", public, True),),
    )
    with pytest.raises(WireRefused, match="operator_not_trusted"):
        revoked.approval(vector["approval"], vector["context"], "owner-1", NOW)
    with pytest.raises(WireRefused, match="operator_owner_mismatch"):
        fixture()[1].approval(vector["approval"], vector["context"], "another-owner", NOW)


@pytest.mark.parametrize(
    "data",
    [b'{"a":1,"a":2}', b'{"a":NaN}', b"\xff", b"[" * 34 + b"0" + b"]" * 34, b"{}" * 600000],
    ids=["duplicate", "nonfinite", "utf8", "depth", "size"],
)
def test_strict_bounded_wire_parsing(data):
    with pytest.raises(WireRefused):
        parse(data)


@pytest.mark.parametrize("value", ["Zg==", "Zh", "+/", "A" * 1000])
def test_base64_canonical_and_bounded(value):
    with pytest.raises(WireRefused):
        unb64(value, 64)


@pytest.mark.parametrize(
    "data",
    [b'{"a":1e400}', b'{"a":-1e400}', b'{"a":[0,{"b":1e400}]}'],
    ids=["positive", "negative", "nested"],
)
def test_exponent_overflow_is_nonfinite_and_refused(data):
    with pytest.raises(WireRefused):
        parse(data)


def test_finite_exponent_keeps_v1_number_compatibility():
    assert parse(b'{"a":[1e2,-2.5e1]}') == {"a": [100.0, -25.0]}
