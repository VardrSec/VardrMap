# VardrMap — Domain Model

Target model, what exists today, and how each gap closes. Entity names in
`code font` are implemented; **bold** entities are designed but not yet built.

## Central relationship

```
Organization (Phase 1b)
  └── Engagement                      [programs table — see naming note]
        ├── AuthorizationRecord       [authorizations]
        │     └── RuleOfEngagement / EmergencyContact
        ├── ScopeRule ── Exclusion    [scope_items, scope_type in/out]
        ├── Asset ── AssetRelationship (Phase 2)
        │     └── Identity ── CredentialReference
        ├── Objective ── TestPlan ── TestCase (Phase 2)
        ├── ExecutionJob ── Runner ── Observation   [scan_jobs, recon/scan items]
        ├── Finding ── FindingOccurrence ── Evidence
        ├── Retest (Phase 2)
        ├── Report                    [reports]
        └── AuditEvent                [audit_logs]
```

## Naming note — `programs` is `Engagement`

The entity is `Engagement`. The table is still `programs` and its foreign keys
are still `program_id`. This is deliberate and documented in `CLAUDE.md`:
renaming a live table means `ALTER TABLE` against production Postgres while
`start.sh` brings uvicorn up, with zero user-visible benefit.

**New tables FK to `programs.id`** to match existing convention. Introducing a
parallel `engagements` table would create exactly the data silo this
architecture prohibits.

`RadarProgram` is unrelated — those are real HackerOne/Bugcrowd programmes and
must never be renamed.

## Entity status

### Implemented

| Entity | Table | Notes |
|---|---|---|
| `Engagement` | `programs` | `engagement_type`, `engagement_status`, dates, client FK |
| `Client` | `clients` | Owner-scoped; becomes org-scoped in Phase 1b |
| `Authorization` | `authorizations` | `window_start`, `window_end`, `status`, `permits`, `reference` |
| `ScopeItem` | `scope_items` | `scope_type` in/out, `kind`, `value` — serves ScopeRule + Exclusion |
| `Finding` | `findings` | Text-only; no evidence, no asset FK |
| `Report` | `reports` | Per-finding, not per-engagement |
| `ScanJob` | `scan_jobs` | `depends_on` pipelines, atomic claim |
| `AuditLog` | `audit_logs` | No FKs by design — survives subject deletion |
| `EngagementMember` | `engagement_members` | Per-engagement membership |
| `ReconItem` / `ScanItem` / `Service` | — | Observation precursors |

### Designed, not yet built

**Organization / Team / Membership** (Phase 1b) — the current tenancy anchor is
a GitHub user id. `owner_github_id` is denormalized across `Client`,
`ScanJob`, `ScheduledScan`, `Authorization`, `Service`. Consequence: a teammate
invited to an engagement cannot operate its jobs, and a firm cannot share a
client record. See `architecture.md` § Tenancy.

**Asset / AssetRelationship / Identity / CredentialReference** (Phase 2) — the
single largest structural gap. Today a host exists as five unrelated free-text
columns with no foreign keys between them:

| Table | Column | Type |
|---|---|---|
| `ReconItem` | `host`, `url` | `Text` |
| `Service` | `host` | `String(500)` |
| `ScanItem` | `asset` | `Text` |
| `Finding` | `asset` | `String(500)` |

Identity resolution is string comparison (`_dedup_recon`: "url when present,
else host"). `api.acme.com`, `https://api.acme.com/`, and `api.acme.com:443`
are three different assets. Nothing can be correlated, aggregated, or diffed
over time.

**Objective / TestPlan / TestCase**, **Observation** as a first-class entity,
**Evidence**, **FindingOccurrence**, **Retest**, **Integration** — Phase 2+.

## Finding lifecycle

Current: `new | candidate | triaged | in_progress | closed`

Target:

```
draft → needs_validation → confirmed → reported → accepted_risk
     → remediated → retest_pending → verified_fixed
     → reopened → false_positive
```

Migrating requires mapping existing values and is scheduled with the Retest
slice (Phase 2), since `retest_pending` and `verified_fixed` are meaningless
without a retest entity.

## Lifecycle states and invariants

| Entity | States | Invariant |
|---|---|---|
| Engagement | `planned \| active \| reporting \| closed` | CHECK constraint (migration 0014) |
| Engagement type | `bug_bounty \| pentest \| red_team \| internal` | CHECK constraint (0014) |
| Authorization | `draft \| pending \| active \| suspended \| expired \| closed` | CHECK constraint (0016) |
| ScanJob | `pending \| running \| done \| failed` | Atomic claim via conditional UPDATE |

Important invariants live in database constraints, not application code alone.
No entity relationship is stored only inside an unvalidated JSON blob —
`ScanJob.config` is tool options only and never carries a relationship.

## Assumptions (conservative, documented)

1. **`programs` stays.** Renaming is a scheduled maintenance-window change.
2. **Engagement membership stays per-engagement** until Organization lands.
   Phase 1b converts it, rather than building both.
3. **Bug bounty engagements have no client and no authorization document.** The
   programme's public policy is the authority. The policy engine therefore
   treats a missing authorization as allowed *only* for `bug_bounty`, and
   denies for every other type.
4. **ScopeItem serves ScopeRule, ScopeTarget, and Exclusion.** Three tables
   where one discriminated table suffices would be a speculative abstraction.
