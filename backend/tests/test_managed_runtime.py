"""Protocol hashes and exact Docker nanosecond identities; no runtime execution."""

import hashlib

import pytest
from managed_runtime import capability_hash, check_identity, normalized_start
from managed_wire import WireRefused, digest


def specimen(started="2026-11-02T17:59:00.1Z"):
    return dict(
        daemon_id="daemon-fixture",
        container_id="1" * 64,
        image_id="sha256:" + "2" * 64,
        project="managed-worker",
        started_at=started,
        owner_nonce="3" * 64,
    )


def test_capability_hash_uses_the_approved_purpose_and_ascii_secret_not_decoded_bytes():
    secret = "0123456789abcdef" * 4
    expected = hashlib.sha256(
        b"VardrSec.WorkerStop.v1\0" + secret.encode("ascii")
    ).hexdigest()
    assert capability_hash(secret) == expected
    assert expected != hashlib.sha256(bytes.fromhex(secret)).hexdigest()
    assert expected != hashlib.sha256(secret.encode()).hexdigest()


def test_physical_uniqueness_normalizes_aliases_but_original_identity_hash_stays_exact():
    first, alias = specimen(), specimen("2026-11-02T17:59:00.100000000Z")
    assert check_identity(first)[1] == check_identity(alias)[1]
    assert check_identity(first)[0] == digest(first) != check_identity(alias)[0]
    assert normalized_start(first["started_at"]) == alias["started_at"]


def test_distinct_nanoseconds_are_never_collapsed_to_datetime_microseconds():
    first, later = (
        specimen("2026-11-02T17:59:00.000000001Z"),
        specimen("2026-11-02T17:59:00.000000002Z"),
    )
    assert check_identity(first)[1] != check_identity(later)[1]
    assert normalized_start(first["started_at"]) < normalized_start(later["started_at"])


@pytest.mark.parametrize(
    "value",
    [
        "0001-01-01T00:00:00Z",
        "2026-02-30T00:00:00Z",
        "2026-11-02T17:59:00.1234567890Z",
        "2026-11-02T17:59:00+00:00",
    ],
)
def test_unset_invalid_or_ambiguous_timestamp_forms_are_refused(value):
    with pytest.raises(WireRefused):
        normalized_start(value)
