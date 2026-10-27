# Platform and Runner observations

Settings displays API/database readiness and account-owned Runner heartbeat
reports. It refreshes read-only observations every 30 seconds, with an eight-second
request deadline and a manual **Refresh status** button. This starts no scans,
worker, installation, repair or update operation. Runner remains explicitly invoked.

The backend card consumes the existing v1 `/ready` contract. **Ready** requires
HTTP 200, a connected database and a current Alembic marker. A valid HTTP 503
contract shows **Not ready**. Failed transport/server responses show **Unreachable**;
malformed, unsupported or inconsistent contracts show **Unknown**. These checks do
not establish UI availability from another machine, component-version compatibility,
target reachability or successful end-to-end execution.

Runner reports use the existing authenticated `/runner/status` endpoint and retain
its account ownership boundary. They show hostname, reported Runner/tool versions,
tool availability and UTC-stamped last-seen times rendered in the browser's local
time zone. **Recent report** means contact within
five minutes, **Stale report** means older contact, and **Unknown** means no report
or uncertain timing. A recent heartbeat does not prove an active worker or every
tool mode. Tool details describe the displayed historical report, including when
that report is stale; they are not independent verification of the host.

Both cards expire fetched observations after 60 seconds. The UI ages timestamps
locally even while another request is pending; a failed refresh replaces previous
success rather than leaving it green. Missing/ambiguous timestamps or more than
five seconds of apparent future clock skew show unknown. The Jobs execution link
also expires old heartbeat contact and clears it after failed status polling.

The additive Runner status metadata is `schema_version: 1`, `checked_at`,
`stale_after_seconds: 300`, and per-row/top-level `freshness`. Responses use
`Cache-Control: no-store`. A future server-side heartbeat timestamp is unknown
and does not set `online`. Existing fields and heartbeat write payloads remain
supported. Older backends without the new observation metadata show unknown in
Settings and the Jobs link; apply the matching backend before the frontend.

No database migration or new environment variable is required. Map owns the
readiness interface and presentation. Operational diagnosis stays in Runner;
Compose lifecycle stays in VardrSec; Gate remains the authorization-testing engine.
Full doctor reports, release manifest compatibility and fresh-host/tool/network
acceptance remain separate work. See [readiness](adr/0003-platform-readiness.md).
