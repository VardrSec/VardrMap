"""Explicit opt-in assembly of existing managed services; never key provisioning."""

import os
from pathlib import Path
import stat
from urllib.parse import urlsplit


class ManagedConfigurationRefused(RuntimeError):
    pass


def _require(value):
    if not value:
        raise ManagedConfigurationRefused("managed_worker_configuration_refused")


def _read(path, maximum):
    _require(type(path) is str and len(path) <= 4096 and Path(path).is_absolute())
    _require(stat.S_ISREG(Path(path).lstat().st_mode))
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
        data = source.read(maximum + 1)
    _require(0 < len(data) <= maximum)
    return data


def configure_managed(app, *, environ=None):
    """Omission/0 preserves default routes. Invalid enabled config refuses startup.

    Reads only explicit public operator trust and a distinct Map contract key.
    Does not enroll, migrate, issue approvals, repair state or start queue work.
    """
    environment = os.environ if environ is None else environ
    flag = environment.get("VARDRMAP_MANAGED_WORKER")
    if flag in (None, "0"):
        return False
    try:
        _require(
            flag == "1" and not getattr(app.state, "managed_worker_enabled", False)
        )
        from managed_approval_http import build_approval_router
        from managed_http import build_managed_router
        from managed_issuance import Issuer
        from managed_observation_http import build_observation_router
        from managed_observations import Observations
        from managed_receipt_http import build_receipt_router
        from managed_results import Results
        from managed_runtime import Runtimes
        from managed_runtime_http import build_runtime_router
        from managed_wire import ContractWire, OperatorAnchor, fields, parse, unb64

        origin = environment["VARDRMAP_MANAGED_ORIGIN"]
        _require(
            type(origin) is str
            and len(origin) <= 500
            and urlsplit(origin).scheme == "https"
        )
        public = parse(
            _read(environment["VARDRMAP_MANAGED_OPERATOR_TRUST_FILE"], 32768), 32768
        )
        _require(type(public) is list and 1 <= len(public) <= 100)
        operators = []
        for anchor in public:
            fields(
                anchor, {"issuer_id", "key_id", "approver_id", "public_key", "revoked"}
            )
            _require(type(anchor["revoked"]) is bool)
            operators.append(
                OperatorAnchor(
                    issuer_id=anchor["issuer_id"],
                    key_id=anchor["key_id"],
                    approver_id=anchor["approver_id"],
                    public_key=unb64(anchor["public_key"], 32),
                    revoked=anchor["revoked"],
                )
            )
        key = _read(environment["VARDRMAP_MANAGED_CONTRACT_KEY_FILE"], 32)
        _require(len(key) == 32)
        wire = ContractWire(
            environment["VARDRMAP_MANAGED_ISSUER_ID"],
            environment["VARDRMAP_MANAGED_CONTRACT_KEY_ID"],
            key,
            operators,
        )
        issuer = Issuer(origin, wire)
        results = Results(issuer)
        runtimes = Runtimes(results)
        # Construct and validate the whole graph before exposing any route.
        routers = [
            build_managed_router(issuer, runtimes),
            build_receipt_router(results),
            build_approval_router(issuer),
            build_observation_router(Observations(results)),
            build_runtime_router(runtimes),
        ]
        for router in routers:
            app.include_router(router)
        app.state.managed_worker_enabled = True
        return True
    except Exception:
        raise ManagedConfigurationRefused(
            "managed_worker_configuration_refused"
        ) from None
