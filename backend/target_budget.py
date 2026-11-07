"""Monotonic represented-origin attempts; callers hold the engagement lock."""
from fastapi import HTTPException
import ipaddress
from assessments import case_hash
from routers.test_cases import _case_identities, _preflight_origin


class TargetBudgetExhausted(HTTPException):
    def __init__(self):
        super().__init__(409, "engagement target allowance exhausted")


def binding(case):
    try:
        requests = [case["request"]]
        requests.extend(step["request"] for step in case.get("setup") or [])
        requests.extend(identity["preflight"] for identity in _case_identities(case) if identity.get("preflight") is not None)
        verification = case.get("write_verification")
        if verification is not None:
            requests.append(verification["request"])
            if verification.get("reset") is not None:
                requests.append(verification["reset"]["request"])
        origins = set()
        for request in requests:
            scheme, host, port = _preflight_origin(request["url"])
            if not host.isascii() or host.endswith(".") or "%" in host:
                raise ValueError()
            if ":" in host:
                host = "[" + str(ipaddress.IPv6Address(host)) + "]"
            origins.add(f"{scheme}://{host}:{port}")
        if not origins or len(origins) > 100:
            raise ValueError()
        return {"profile": "gate-fixed-http/1", "case_sha256": case_hash(case), "origins": sorted(origins)}
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(409, "unsupported target budget case") from None


def charge(engagement, job, case, body):
    supplied = body.target_binding if body is not None else None
    if engagement.target_limit is None:
        if supplied is not None:
            raise HTTPException(409, "explicit engagement target policy required")
        return None
    if supplied is None or job.tool_type != "vardrgate_api_test" or case is None:
        raise HTTPException(409, "target policy requires bound fixed Gate owned execution")
    expected = binding(case)
    if supplied.model_dump() != expected:
        raise HTTPException(409, "target binding mismatch")
    count = len(expected["origins"])
    if engagement.targets_spent + count > engagement.target_limit:
        raise TargetBudgetExhausted()
    engagement.targets_spent += count
    return {"binding": expected, "charged": count, "spent": engagement.targets_spent, "limit": engagement.target_limit}
