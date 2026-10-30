"""Route-level authorization inventory.

Handlers apply access control themselves (`get_engagement_or_404`,
`require_member_write`, `require_full_scope`), and runner-key access depends on
which routers skip the full-scope dependency. These tests read every route from
the app, so a new route cannot silently miss a check:

- a runner-scoped API key gets 403 everywhere except the listed runner routes;
- a user with no access to the engagement gets 404 on every engagement or job
  read, and never a success on any engagement or job route;
- every engagement or job write applies a write guard, so a viewer is refused.

A route the lists below do not account for fails the relevant test.
"""
import inspect
import uuid

import pytest

from main import app
from tests.route_inventory import app_routes

ROUTES = app_routes(app)

# Reachable without authentication.
PUBLIC = {
    ("GET", "/"),
    ("GET", "/health"),
    ("GET", "/ready"),
    ("GET", "/openapi.json"),
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
}

# Authentication endpoints accept any caller and authenticate the request themselves.
AUTHENTICATION = {
    ("GET", "/auth/methods"),
    ("POST", "/auth/local/login"),
    ("GET", "/auth/local/session"),
    ("POST", "/auth/local/logout"),
    ("POST", "/auth/local/password"),
}

# Routes a runner-scoped key may call: the job queue and result transport that
# `vardrrunner jobs run` uses, the engagement and scope reads it needs, heartbeat,
# and the job, preview, pipeline and proposal calls its MCP server makes.
# Everything else must answer a runner key with 403.
RUNNER_ROUTES = {
    ("GET", "/me"),
    ("GET", "/engagements/{program_id}"),
    ("GET", "/engagements/{program_id}/scope"),
    ("GET", "/engagements/{program_id}/jobs"),
    ("GET", "/engagements/{program_id}/jobs/stream"),
    ("POST", "/engagements/{program_id}/jobs"),
    ("POST", "/engagements/{program_id}/jobs/preview"),
    ("POST", "/engagements/{program_id}/pipelines"),
    ("POST", "/engagements/{program_id}/imports"),
    ("POST", "/engagements/{program_id}/services"),
    ("GET", "/engagements/{program_id}/proposals"),
    ("POST", "/engagements/{program_id}/proposals"),
    ("GET", "/jobs/pending"),
    ("POST", "/jobs/{job_id}/claim"),
    ("PATCH", "/jobs/{job_id}"),
    ("GET", "/jobs/{job_id}/events"),
    ("POST", "/jobs/{job_id}/events"),
    ("POST", "/jobs/{job_id}/upload"),
    ("POST", "/runner/heartbeat"),
    ("GET", "/runner/status"),
}

# Engagement or job POSTs that only compute a preview and store nothing, so a
# viewer, who may read the engagement, may call them.
VIEWER_WRITES = {
    ("POST", "/engagements/{program_id}/jobs/preview"),  # resolves targets; queues nothing
    ("POST", "/engagements/{program_id}/test-cases/preview"),  # drafts cases; saves nothing
}

# Path parameters validated against a fixed set before any lookup. They get a
# valid value so the request reaches the access check.
_FIXED_PARAMS = {"{scope_type}": "in", "{revision}": "1"}

_WRITE_GUARDS = ("require_member_write", "_writable_engagement", "require_engagement_owner")
_ENGAGEMENT_PREFIXES = ("/engagements/{program_id}", "/jobs/{job_id}")


def _key(route, method):
    return (method, route.path)


def _routes(methods=None, scoped=False):
    for route in ROUTES:
        if scoped and not route.path.startswith(_ENGAGEMENT_PREFIXES):
            continue
        for method in sorted(route.methods):
            if method == "HEAD" or (methods and method not in methods):
                continue
            yield route, method


@pytest.fixture(scope="module")
def engagement_and_job(client):
    from tests.conftest import mint_token

    owner = {"Authorization": f"Bearer {mint_token('gh_inventory_owner', 'inventory')}"}
    assert client.post("/auth/sync", headers=owner).status_code == 200
    pid = client.post("/programs", json={"name": "Inventory"}, headers=owner).json()["id"]
    job = client.post(
        f"/programs/{pid}/jobs",
        json={"tool_type": "httpx", "target_source": "scope", "config": {}},
        headers=owner,
    )
    assert job.status_code == 200, job.text
    yield pid, job.json()["id"], owner
    client.delete(f"/programs/{pid}", headers=owner)


def _url(route, engagement_and_job):
    pid, job_id, _owner = engagement_and_job
    path = route.path.replace("{program_id}", pid).replace("{job_id}", job_id)
    for param, value in _FIXED_PARAMS.items():
        path = path.replace(param, value)
    while "{" in path:
        start = path.index("{")
        path = path[:start] + str(uuid.uuid4()) + path[path.index("}", start) + 1 :]
    return path


@pytest.fixture(scope="module")
def runner_headers(client, engagement_and_job):
    _pid, _job, owner = engagement_and_job
    key = client.post(
        "/auth/apikeys", json={"label": "inventory", "scope": "runner"}, headers=owner
    ).json()
    yield {"Authorization": f"Bearer {key['token']}"}
    client.delete(f"/auth/apikeys/{key['id']}", headers=owner)


def test_every_route_is_accounted_for():
    """The lists name real routes, so a renamed route cannot leave a stale exemption."""
    served = {_key(route, method) for route, method in _routes()}
    for listed in (PUBLIC, AUTHENTICATION, RUNNER_ROUTES, VIEWER_WRITES):
        assert listed <= served, sorted(listed - served)


def test_runner_keys_reach_only_runner_routes(client, engagement_and_job, runner_headers):
    reachable = []
    for route, method in _routes():
        key = _key(route, method)
        if key in PUBLIC or key in AUTHENTICATION or key in RUNNER_ROUTES:
            continue
        res = client.request(method, _url(route, engagement_and_job), headers=runner_headers, json={})
        if res.status_code != 403:
            reachable.append(f"{method} {route.path} -> {res.status_code}")
    assert not reachable, (
        "A runner-scoped key reached these routes. Add require_full_scope, or list the "
        "route in RUNNER_ROUTES if runners need it:\n  " + "\n  ".join(reachable)
    )


def test_outsiders_never_reach_engagement_routes(client, engagement_and_job, other_headers):
    leaks = []
    for route, method in _routes(scoped=True):
        res = client.request(method, _url(route, engagement_and_job), headers=other_headers, json={})
        expected = {404} if method == "GET" else {404, 422}
        if res.status_code not in expected:
            leaks.append(f"{method} {route.path} -> {res.status_code}")
    assert not leaks, (
        "A user with no access to the engagement got an unexpected answer (reads must be "
        "404; writes 404, or 422 before any lookup):\n  " + "\n  ".join(leaks)
    )


def test_engagement_writes_apply_a_write_guard():
    unguarded = []
    for route, method in _routes(methods={"POST", "PUT", "PATCH", "DELETE"}, scoped=True):
        if _key(route, method) in VIEWER_WRITES:
            continue
        source = inspect.getsource(route.endpoint)
        if not any(guard in source for guard in _WRITE_GUARDS):
            unguarded.append(f"{method} {route.path} ({route.endpoint.__name__})")
    assert not unguarded, (
        "These engagement or job writes apply no write guard, so a viewer could call them. "
        "Call require_member_write, or list the route in VIEWER_WRITES with a reason:\n  "
        + "\n  ".join(unguarded)
    )
