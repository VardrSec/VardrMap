"""Persistent runtime correlation documents; never execution permission."""

import re

from managed_wire import integer, require

MAX_SEQUENCE = 9223372036854775807
MODE = "persistent"


def sequence(value, minimum=0):
    require(
        type(value) is str
        and re.fullmatch(r"0|[1-9][0-9]{0,18}", value, flags=re.ASCII) is not None,
        "invalid_runtime_sequence",
    )
    return integer(int(value), minimum, MAX_SEQUENCE)


def limits(value):
    require(
        type(value) is dict and set(value) == {"max_attempts", "idle_timeout_seconds"},
        "invalid_runtime_limits",
    )
    maximum = value["max_attempts"]
    idle = value["idle_timeout_seconds"]
    if maximum is not None:
        sequence(maximum, 1)
    if idle is not None:
        integer(idle, 1, 86400)
    return {"max_attempts": maximum, "idle_timeout_seconds": idle}


def cursor(last, active):
    integer(last, 0, MAX_SEQUENCE)
    require(
        active is None or (type(active) is int and active == last and active > 0),
        "runtime_cursor_changed",
    )
    return {
        "last_sequence": str(last),
        "phase": "active" if active is not None else "idle",
    }


def checked_cursor(value):
    require(
        type(value) is dict
        and set(value) == {"last_sequence", "phase"}
        and value["phase"] in {"active", "idle"},
        "invalid_runtime_cursor",
    )
    last = sequence(value["last_sequence"])
    require(value["phase"] != "active" or last > 0, "invalid_runtime_cursor")
    return last, value["phase"]
