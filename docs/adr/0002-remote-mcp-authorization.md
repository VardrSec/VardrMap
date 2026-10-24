# ADR 0002 — Authorization for a remote MCP server

**Status:** **Proposed — not implemented.** · **Date:** 2026-10-09 · **Supersedes:** none

**Reviewed against current platform:** 2026-10-11. Merging this document records a
proposal; it does not accept the open decisions or authorize OAuth implementation.

> This document exists to be argued with before any code is written. It is the
> design half of MCP Phase 7. Nothing in this ADR has been built; the roadmap
> item stays open until the decisions below are agreed or replaced.

## Context

VardrRunner already serves an engagement to an MCP client over stdio
(VardrRunner ADR 0015). That path needs no new authorization: the server runs on
the operator's own machine, as the operator, using the `vmap_` key already in
their keychain. The trust boundary is the one that already existed.

Phase 7 is different. A *remote* MCP server is reachable from claude.ai, which
means:

- the operator's machine is no longer in the request path, so there is no local
  credential to reuse and no local process acting as them;
- an HTTP endpoint on the production backend becomes callable by an agent whose
  model the operator does not run;
- the credential has to be issued, scoped, stored and revoked by somebody.

VardrMap's current auth accepts exactly two bearer tokens (`backend/deps.py`): a
short-lived HS256 JWT minted by the frontend after GitHub OAuth, and an opaque
`vmap_` personal API key stored as a SHA-256 hash with a coarse `full` /
`runner` scope. Database access combines direct ownership, organization membership
and engagement invitations through `deps.py`; inaccessible resources return `404`.
Viewer roles cannot write. API keys remain user-bound, not organization-bound.

Neither existing token is a legitimate credential for a remote MCP client. The
browser JWT is minted by our own frontend for our own frontend. The `vmap_` key
with full scope is a long-lived bearer secret with broad authority and no consent step —
handing one to a hosted third party would be the worst option available.

## What the MCP specification requires

The [MCP authorization specification, edition 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
defines the MCP endpoint as an OAuth **resource server**. It permits an authorization
server to be co-hosted or separate; using a separate service is this proposal's
design choice, not a protocol requirement. The requirements shaping it are:

- The MCP server **MUST** implement OAuth 2.0 Protected Resource Metadata
  (RFC 9728), advertising its authorization server. Discovery uses the advertised
  metadata URL in a 401 challenge or a root/path-specific well-known URI.
- The authorization server **MUST** implement OAuth 2.1, and **MUST** expose
  either RFC 8414 metadata or OIDC Discovery.
- Clients **MUST** send a `resource` parameter (RFC 8707) identifying the server,
  and the server **MUST** validate that an access token was issued **for it** as
  the intended audience.
- The server **MUST NOT** accept tokens issued for other resources or pass through
  a client's access token to another service.
- `401` carries `WWW-Authenticate: Bearer resource_metadata="…", scope="…"`;
  insufficient scope is `403` with `error="insufficient_scope"` and the scopes
  the operation needs.

The audience requirement is the load-bearing one for us: it rules out the
obvious shortcut of letting a client present a GitHub token, because a GitHub
token is not issued for VardrMap and forwarding it would be exactly the token
passthrough the spec forbids.

## Proposed decisions

### 1. VardrMap is a resource server. It does not become an authorization server.

Identity and token issuance would be delegated to an external OAuth 2.1
authorization server that federates GitHub login, so `github_id` remains the
tenancy key and the operator signs in as the same identity they already use.

The alternative — implementing the AS ourselves — means owning an authorization
endpoint, a token endpoint, PKCE, a consent screen, client registration, key
management, token rotation and revocation. That is a large security surface, it
is not what this project is for, and a subtle mistake in it is a critical
authentication bug rather than a scanning inconvenience. We would be writing the
most security-sensitive component in the product in order to avoid a dependency.

**Consequence to decide openly:** this adds an authorization-server dependency.
It could be self-hosted or managed; choosing and operating it is unresolved.
Provider selection must also settle client registration/interoperability, key
rotation, token/refresh-token handling and revocation. Existing stdio remains usable.

### 2. Token validation is stateless; reach is stateful.

The server validates the JWT's signature, issuer, expiry and — critically —
that its `aud` is the canonical MCP resource URI. Nothing about the token is
stored.

Authority is then narrowed by a stored **MCP connection** record: which user,
which engagements, which scopes, when it was created and last used. Every
request checks it together with current engagement access and write-role predicates.
The authenticated grant must be unambiguously bound to that connection using
issuer-verified claims or a server-managed grant mapping. A caller-supplied
connection id or matching user id alone must not let a revoked token select a
different active connection. The provider-specific binding contract is still open.

This split is deliberate. Stateless validation keeps the hot path cheap, and the
bound connection record is intended to give **immediate per-connection revocation** without token introspection or
waiting for a token to expire: the operator revokes a connection in the UI and
the next request fails, whatever the token's remaining lifetime.

### 3. Scopes mirror the capability split that already exists.

Three scopes, mapping onto the tool surface VardrRunner ADR 0015 already
settled:

| Scope | Covers |
|---|---|
| `engagement:read` | Allowed read tools: scope, authorizations, findings/history, assets, API surface, recon, jobs/assessments, reports/deliverables, filtered evidence, versioned playbooks and methodology guidance |
| `job:write` | `queue_job`, `queue_pipeline` |
| `finding:write` | `create_finding`, `draft_report` |

**The remote surface is a subset of the local one, never a superset.** Nothing
is exposed remotely that the stdio server withholds: no scope or authorization
editing, no stop-work, no deletes, no member/API-key/settings management, no
saving a VardrGate test case, no writing a client deliverable. The two
withholding rationales from ADR 0015 both still hold, and the second applies
harder here — a remote agent is even further from the human whose review a saved
test case asserts.

Scope checks are **additional to**, not instead of, the shared database access
predicates in `deps.py` and current write-role checks. A scope says what kind of operation is allowed; it never
decides which rows are visible. Re-deriving visibility in a new code path is how
BOLA regressions happen.

### 4. Engagement reach is granted in the UI, not encoded in scopes.

A connection names the engagements it may touch. Engagement ids are unbounded
and per-tenant, so they do not belong in OAuth scope strings, and "all my
engagements forever" is the wrong default for a platform where each engagement
is someone else's production estate.

So consent is two-layered: the authorization server obtains the user's consent
to issue a token with certain scopes, and VardrMap separately records which
engagements that connection reaches. Both are checked on every request, and
either can be narrowed or revoked without touching the other.

### 5. Tenant isolation is unchanged, and that is the requirement.

- Access stays enforced through the existing ownership/organization/invitation
  database predicates, with inaccessible resources returning `404`. Revoked
  membership or a downgrade to viewer immediately narrows a connection's reach.
- The subject claim is mapped to a user on a **verified, immutable** claim —
  never on email, which is mutable and re-assignable.
- An unmapped subject is refused. The remote endpoint does not provision
  accounts: a person who has never signed in to VardrMap has no tenant, and
  silently creating one for a token-bearer is not a behaviour worth having.
- A token whose `aud` is not this server is refused, so a token minted for
  another relying party on the same IdP cannot be replayed here.

### 6. Queue permission can cause target traffic through a runner.

The remote server does not execute a binary itself, but a runner claims queued
work the next time an operator runs `vardrrunner jobs run` (since Runner 0.48.0 no
daemon claims it automatically). Granting `job:write` therefore grants a path to
active target traffic; there is no separate per-job human consent step today.

A compromised agent can read the engagement data it was granted and enqueue
repeated permitted scans. Scope/window warnings remain advisory. Per-execution
rate/worker limits do not create an engagement-wide traffic budget. Stop-work
blocks new starts, but does not cancel running processes;
remote tools cannot release it. Local target guards and bounded job types remain
in effect, and arbitrary shell execution is not exposed.

Read-only remote MCP should be evaluated as the first-release option. Before any
remote write surface is accepted, its consent, traffic/concurrency budget and
audit/revocation behavior must be explicitly designed and tested.

## Consequences

- An authorization-server dependency would become part of a remote deployment;
  its hosting model is undecided. Operators can retain stdio without that dependency.
- The stdio server stays the primary integration. Remote MCP is a convenience
  for claude.ai, and it is strictly more exposed, so it gets a strictly smaller
  surface.
- Proposed persisted concepts include a grant-bound MCP connection and its audit
  trail. Any implementation needs an additive migration plan; none exists here.
- Prompt injection is unchanged in kind but worse in reach: tool results still
  carry target-controlled text, and the mitigation is still that no tool can
  widen what may be tested. The remote path adds rate limiting as a second
  bound, since the caller is no longer a process on the operator's machine.

## Open questions for review

These are the decisions I do not think I should make alone:

1. **Which authorization server?** The requirement is OAuth 2.1, RFC 8414 or
   OIDC Discovery, RFC 8707 `resource` support, and GitHub federation. Several
   products qualify; the choice has cost, data-residency and lock-in
   consequences that are yours.
2. **Managed or self-hosted authorization server, or no remote MCP**, given the
   product's hosting posture? Declining Phase 7 remains defensible —
   the stdio server already does everything the remote one would, for operators
   willing to run VardrRunner.
3. **Should `job:write` exist remotely in the first release?** A read-only
   remote MCP is a much smaller thing to get right, and it covers `brief`,
   `triage` and most of `untested`.
4. **Default connection lifetime.** Short-lived connections requiring periodic
   re-consent, versus long-lived ones revocable in the UI.
5. **Organizations.** Organization membership and engagement invitations already
   exist. Connections must use those live predicates; settle grant ownership,
   member/viewer changes and organization administration before remote implementation.
6. **Grant binding and token lifecycle.** How does the selected provider bind an
   access token to one connection, prevent reuse after revocation and handle expiry,
   refresh tokens and rotation? Map must never store raw access/refresh tokens.

## Alternatives considered

- **Reuse the `vmap_` API key.** Rejected: a long-lived bearer secret with
  `full` authority, no audience binding, no consent step and no per-engagement
  reach. Reusing the Runner key would expose its shared backend authority,
  including permitted queue operations. The spec's audience
  requirement independently forbids it.
- **Let clients present a GitHub token.** Rejected: not issued for VardrMap, so
  accepting it is the token passthrough the spec prohibits, and it would make
  VardrMap a confused deputy for every GitHub scope the token carried.
- **Implement the authorization server in VardrMap.** Rejected for now, per
  Decision 1 — the surface is large and the failure mode is critical. Worth
  revisiting only if the external-service tradeoff is judged unacceptable *and*
  there is appetite to own an AS properly.
- **Tunnel the stdio server instead.** Expose the operator's local MCP server
  through a tunnel rather than building a remote one. Rejected: it moves the
  authorization problem to the tunnel, where it is usually solved with a shared
  secret, and it requires the operator's machine to be reachable and running
  anyway — which is the condition under which stdio already works.

## Sources and implementation gate

The protocol claims above were checked against the pinned
[MCP authorization edition](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
and [security guidance](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices).
No endpoint, scope, token flow, connection model, migration or OAuth dependency
is implemented by this ADR. Record accepted decisions and a concrete auth test plan
before starting that work; retain stdio and existing engagement access boundaries.
