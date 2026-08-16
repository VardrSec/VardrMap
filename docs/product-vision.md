# VardrMap — Product Vision

## What this is

VardrMap is the control plane for authorized security testing. One engagement
model covers a penetration test, an adversary simulation, a continuous
assessment, or bug bounty research. The discipline changes what the work looks
like; it does not change the data model, the interface, or the product.

## The unified operating model

Every assessment is an **engagement**. An engagement accumulates structure as
the work demands it, and never requires a migration or a product switch to do
so:

| Layer | Present in a lightweight engagement | Added as work deepens |
|---|---|---|
| Authorization and rules of engagement | Minimal — a bounty programme's public policy | Signed SOW, testing windows, emergency contacts, stop-work |
| Scope | A domain | CIDRs, API routes, cloud resource IDs, explicit exclusions |
| Assets | Whatever recon found | A typed graph with relationships and provenance |
| Objectives | None | Success criteria tied to client risk |
| Test plan | None | WSTG / API Top 10 / ATT&CK-mapped cases |
| Findings and evidence | Always | Retest lifecycle, SLA, recurrence |
| Reporting | Export | Executive and technical deliverables |

An analyst starts by pointing VardrMap at a domain. Nothing forces them to fill
in a client record, an authorization document, or a test plan. When the same
target later becomes a contracted pentest, the assets, observations, evidence,
and findings already gathered stay exactly where they are and acquire the
structure around them.

**A single asset, observation, evidence item, or finding is reusable across the
entire lifecycle.** There are no per-discipline silos, no duplicate interfaces,
and no "bounty mode" versus "pentest mode".

## What we deliberately are not

- **Not an autonomous attack agent.** AI drafts, correlates, and summarizes.
  A human approves anything intrusive.
- **Not a C2 framework.** Campaigns are a planning and reporting taxonomy over
  ATT&CK, not an implant or a payload host.
- **Not a remote shell.** Runners execute declared, bounded job types. They do
  not accept arbitrary commands from ordinary users.
- **Not a scanner.** VardrMap orchestrates and reasons over tools; it does not
  reimplement them. Tool adapters are replaceable.

## Product family

| Component | Role | Language |
|---|---|---|
| **VardrMap** | Control plane, data model, product experience | FastAPI + Next.js |
| **VardrRunner** | Private execution plane — customer network, CI, workstation | Python |
| **VardrGate** | API authorization-testing engine (BOLA, cross-tenant, BFLA, privilege escalation) | Go |

The control plane never links against a security tool. It emits versioned JSON
job envelopes and consumes versioned JSON results. VardrGate is one executor
behind that contract, not a dependency.

## The thesis

Most security tooling stores tool output. The differentiator here is that
VardrMap models the **target** and the **authority to test it**:

1. **Authorization is modelled and surfaced.** Scope, the testing window, and the
   permission to test are first-class records, and every job is evaluated
   against them — so the operator is told, at the moment it matters, when a
   target falls outside what was agreed. VardrMap does not refuse the work:
   staying in scope is the operator's responsibility, as it is with every other
   tool in the kit. The exception is stop-work, the operator's own halt switch,
   which is honoured absolutely.
2. **Assets are a graph, not rows.** A finding correlates to the service that
   exposed it, which correlates to the host, which correlates to the domain.
   That chain is what makes risk aggregation, retest, and attack-path analysis
   possible.
3. **Evidence is first-class and redacted by construction.** Secrets never reach
   a finding, an API response, a log, or a report.

## Success criteria

- An analyst can run an engagement end to end without leaving the product.
- A client-ready report generates from structured findings, not prose.
- A scan cannot execute outside its authorization — provably, with tests.
- The same engagement supports one researcher or a consulting team.
