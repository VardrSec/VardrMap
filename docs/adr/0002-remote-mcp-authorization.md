# ADR 0002 — Authorization for a remote MCP server

**Status:** **Proposed — not implemented.** · **Date:** 2026-10-09 · **Supersedes:** none

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
`runner` scope. Tenancy is keyed on `github_id`, enforced at the DB query level,
and a cross-tenant read returns `404` rather than `403`.

Neither existing token is a legitimate credential for a remote MCP client. The
browser JWT is minted by our own frontend for our own frontend. The `vmap_` key
is a long-lived bearer secret with near-total authority and no consent step —
handing one to a hosted third party would be the worst option available.

## What the MCP specification requires

The MCP authorization spec is explicit that the server is a **resource server**,
not an authorization server, and the requirements that shape this design are:

- The MCP server **MUST** implement OAuth 2.0 Protected Resource Metadata
  (RFC 9728) at `/.well-known/oauth-protected-resource`, and advertise its
  authorization server there.
- The authorization server **MUST** implement OAuth 2.1, and **MUST** expose
  either RFC 8414 metadata or OIDC Discovery.
- Clients **MUST** send a `resource` parameter (RFC 8707) identifying the server,
  and the server **MUST** validate that an access token was issued **for it** as
  the intended audience.
- The server **MUST NOT** accept or transit any other tokens.
- `401` carries `WWW-Authenticate: Bearer resource_metadata="…", scope="…"`;
  insufficient scope is `403` with `error="insufficient_scope"` and the scopes
  the operation needs.

The audience requirement is the load-bearing one for us: it rules out the
obvious shortcut of letting a client present a GitHub token, because a GitHub
token is not issued for VardrMap and forwarding it would be exactly the token
passthrough the spec forbids.

## Decision

### 1. VardrMap is a resource server. It does not become an authorization server.

Identity and token issuance are delegated to an external OAuth 2.1
authorization server that federates GitHub login, so `github_id` remains the
tenancy key and the operator signs in as the same identity they already use.

The alternative — implementing the AS ourselves — means owning an authorization
endpoint, a token endpoint, PKCE, a consent screen, client registration, key
management, token rotation and revocation. That is a large security surface, it
is not what this project is for, and a subtle mistake in it is a critical
authentication bug rather than a scanning inconvenience. We would be writing the
most security-sensitive component in the product in order to avoid a dependency.

**Consequence to accept openly:** this adds a hosted dependency to the
deployment, and a remote MCP endpoint cannot be stood up without choosing and
configuring one. That cost is the point of the trade.

### 2. Token validation is stateless; reach is stateful.

The server validates the JWT's signature, issuer, expiry and — critically —
that its `aud` is the canonical MCP resource URI. Nothing about the token is
stored.

Authority is then narrowed by a stored **MCP connection** record: which user,
which engagements, which scopes, when it was created and last used. Every
request checks it.

This split is deliberate. Stateless validation keeps the hot path cheap, and the
connection record gives **immediate revocation** without token introspection or
waiting for a token to expire: the operator revokes a connection in the UI and
the next request fails, whatever the token's remaining lifetime.

### 3. Scopes mirror the capability split that already exists.

Three scopes, mapping onto the tool surface VardrRunner ADR 0015 already
settled:

| Scope | Covers |
|---|---|
| `engagement:read` | Every read tool: scope, authorizations, findings and history, assets, API surface, recon, jobs, reports, deliverables, methodologies |
| `job:write` | `queue_job`, `queue_pipeline` |
| `finding:write` | `create_finding`, `draft_report` |

**The remote surface is a subset of the local one, never a superset.** Nothing
is exposed remotely that the stdio server withholds: no scope or authorization
editing, no stop-work, no deletes, no member/API-key/settings management, no
saving a VardrGate test case, no writing a client deliverable. The two
withholding rationales from ADR 0015 both still hold, and the second applies
harder here — a remote agent is even further from the human whose review a saved
test case asserts.

Scope checks are **additional to**, not instead of, the existing `github_id`
query-level scoping. A scope says what kind of operation is allowed; it never
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

- Tenancy stays keyed on `github_id`, enforced in the DB query, with
  cross-tenant access returning `404`.
- The subject claim is mapped to a user on a **verified, immutable** claim —
  never on email, which is mutable and re-assignable.
- An unmapped subject is refused. The remote endpoint does not provision
  accounts: a person who has never signed in to VardrMap has no tenant, and
  silently creating one for a token-bearer is not a behaviour worth having.
- A token whose `aud` is not this server is refused, so a token minted for
  another relying party on the same IdP cannot be replayed here.

### 6. A remote agent cannot generate traffic at a target.

Worth stating because it bounds the blast radius more than any scope does. The
remote server can read an engagement and **enqueue** work. It cannot execute a
tool: jobs are claimed and run by a VardrRunner the operator installed, on
hardware the operator controls, which heartbeats and can simply be stopped.
Stop-work remains absent from the tool surface and available in the UI.

So the worst case for a compromised or manipulated remote agent is reading one
tenant's engagement data and queueing jobs that the operator's own runner will
pick up — bad, and bounded by the scopes and engagements the operator granted.
It is not remote code execution and it is not traffic at a client's estate
without a runner consenting to run it.

## Consequences

- A hosted IdP becomes part of the deployment. Self-hosters who do not want one
  keep the stdio path, which remains the recommended and fully-featured route.
- The stdio server stays the primary integration. Remote MCP is a convenience
  for claude.ai, and it is strictly more exposed, so it gets a strictly smaller
  surface.
- Two new persisted concepts: the MCP connection record and its audit trail.
  Both are additive.
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
2. **Is a hosted IdP acceptable at all**, given the product's self-hosting
   posture? A defensible answer is "no, and Phase 7 is therefore declined" —
   the stdio server already does everything the remote one would, for operators
   willing to run VardrRunner.
3. **Should `job:write` exist remotely in the first release?** A read-only
   remote MCP is a much smaller thing to get right, and it covers `brief`,
   `triage` and most of `untested`.
4. **Default connection lifetime.** Short-lived connections requiring periodic
   re-consent, versus long-lived ones revocable in the UI.
5. **Organizations.** The scopes above are per-user. How a connection interacts
   with org membership and the member write role needs settling before anything
   multi-user is built on it.

## Alternatives considered

- **Reuse the `vmap_` API key.** Rejected: a long-lived bearer secret with
  `full` authority, no audience binding, no consent step and no per-engagement
  reach. It is also the credential VardrRunner uses, so a leak from a hosted
  client would compromise the operator's runners too. The spec's audience
  requirement independently forbids it.
- **Let clients present a GitHub token.** Rejected: not issued for VardrMap, so
  accepting it is the token passthrough the spec prohibits, and it would make
  VardrMap a confused deputy for every GitHub scope the token carried.
- **Implement the authorization server in VardrMap.** Rejected for now, per
  Decision 1 — the surface is large and the failure mode is critical. Worth
  revisiting only if the hosted-dependency cost is judged unacceptable *and*
  there is appetite to own an AS properly.
- **Tunnel the stdio server instead.** Expose the operator's local MCP server
  through a tunnel rather than building a remote one. Rejected: it moves the
  authorization problem to the tunnel, where it is usually solved with a shared
  secret, and it requires the operator's machine to be reachable and running
  anyway — which is the condition under which stdio already works.
