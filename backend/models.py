import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from db import Base


# SQLAlchemy's `default=` needs a callable, not a value — passing uuid4 directly
# would reuse the same UUID for every row. Wrapping it in a function fixes that.
def new_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    github_id = Column(String, primary_key=True)
    username = Column(String(100), default="")
    email = Column(String(200), default="")
    # Outbound notification settings — webhook_url is a Discord/Slack-style
    # incoming webhook; empty string = notifications disabled
    webhook_url = Column(String(500), default="")
    notify_min_severity = Column(String(20), default="high")  # info|low|medium|high|critical
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    engagements = relationship("Engagement", back_populates="owner", cascade="all, delete-orphan")
    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    clients = relationship("Client", back_populates="owner", cascade="all, delete-orphan")


class Organization(Base):
    """The tenant. Everything an operator owns hangs off one of these.

    Before this existed the tenancy anchor was a GitHub user id, denormalized
    onto Client, ScanJob, ScheduledScan, Authorization and Service. That made a
    teammate unable to operate an engagement's jobs, and made a consulting firm
    unable to share a client record or a runner fleet between two people.

    Every user gets a personal organization on first sight, so single-operator
    use is unchanged — the org is invisible until someone is invited into it.
    """

    __tablename__ = "organizations"

    id = Column(String, primary_key=True, default=new_uuid)
    name = Column(String(120), nullable=False)
    # The user whose personal org this is, empty for orgs created explicitly.
    # Kept so the backfill is reversible and a personal org is identifiable.
    personal_for_github_id = Column(String, default="", index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    members = relationship("OrganizationMember", back_populates="organization", cascade="all, delete-orphan")


class OrganizationMember(Base):
    """Membership and role. Roles are ordered: owner > admin > member > viewer."""

    __tablename__ = "organization_members"

    id = Column(String, primary_key=True, default=new_uuid)
    org_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    github_id = Column(String, nullable=False, index=True)
    role = Column(String(20), nullable=False, default="member")  # owner|admin|member|viewer
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    organization = relationship("Organization", back_populates="members")

    __table_args__ = (
        # One membership row per person per org — two rows with different roles
        # would make the effective role depend on query order.
        UniqueConstraint("org_id", "github_id", name="uq_org_member"),
    )


class Asset(Base):
    """A node in the engagement's attack surface.

    Replaces five unrelated free-text host columns that had no join key between
    them. `canonical_key` is that key: a pure function of the observed string,
    unique per engagement, so two spellings of the same host converge and two
    different hosts never do.
    """

    __tablename__ = "assets"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)
    canonical_key = Column(String(600), nullable=False)
    asset_type = Column(String(40), nullable=False, default="domain")
    label = Column(String(500), default="")
    hostname = Column(String(400), default="", index=True)
    ip = Column(String(60), default="", index=True)
    port = Column(Integer, nullable=True)
    scheme = Column(String(20), default="")

    # Context an operator sets; nothing infers these.
    environment = Column(String(40), default="")      # production|staging|dev|unknown
    criticality = Column(String(20), default="")      # low|medium|high|critical
    exposure = Column(String(20), default="")         # internal|external|unknown
    owner_note = Column(String(200), default="")
    tags = Column(String(500), default="")

    # Provenance.
    source = Column(String(60), default="")           # httpx|nuclei|nmap|manual|backfill
    confidence = Column(String(20), default="confirmed")  # confirmed|inferred|suspected
    first_seen_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    engagement = relationship("Engagement", back_populates="assets")

    __table_args__ = (
        # The join key is only meaningful if it is unique within an engagement.
        UniqueConstraint("program_id", "canonical_key", name="uq_asset_canonical"),
    )


class AssetRelationship(Base):
    """A directed edge. Relational edge table rather than a graph database —
    the traversals here are shallow and the data already lives in Postgres."""

    __tablename__ = "asset_relationships"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)
    src_asset_id = Column(String, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    dst_asset_id = Column(String, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    relationship = Column(String(40), nullable=False)
    source = Column(String(60), default="")
    confidence = Column(String(20), default="confirmed")
    first_seen_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint(
            "src_asset_id", "dst_asset_id", "relationship", name="uq_asset_edge"
        ),
    )


class Client(Base):
    """An organisation that engagements are performed for.

    Bug bounty work has no client — the engagement *is* the counterparty — so this
    is optional on a Engagement. Consulting and internal work need one: several
    engagements over time belong to the same organisation, and the deliverable
    goes to a named contact.
    """

    __tablename__ = "clients"

    id = Column(String, primary_key=True, default=new_uuid)
    owner_github_id = Column(String, ForeignKey("users.github_id"), nullable=False, index=True)
    # Tenancy. Nullable during the transition: rows predate organizations and
    # are backfilled by migration 0017 to the owner's personal org.
    org_id = Column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    contact_name = Column(String(200), default="")
    contact_email = Column(String(200), default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    owner = relationship("User", back_populates="clients")
    engagements = relationship("Engagement", back_populates="client")


class Engagement(Base):
    __tablename__ = "programs"

    id = Column(String, primary_key=True, default=new_uuid)
    owner_github_id = Column(String, ForeignKey("users.github_id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    platform = Column(String(80), default="")
    program_url = Column(String(500), default="")
    scope_summary = Column(Text, default="")
    severity_guidance = Column(Text, default="")
    safe_harbor_notes = Column(Text, default="")
    # Engagement context. Every field below is optional and defaults to the
    # bug bounty behaviour this table was built for, so existing rows and
    # existing API callers are unaffected — pentest work is opt-in.
    client_id = Column(String, ForeignKey("clients.id"), nullable=True, index=True)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    engagement_type = Column(String(20), default="bug_bounty")  # bug_bounty|pentest|red_team|internal
    engagement_status = Column(String(20), default="active")    # planned|active|reporting|closed
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    # Emergency brake. When set, policy.evaluate denies every execution for this
    # engagement regardless of scope, window, or authorization — the one control
    # that must work when everything else is misconfigured.
    stop_work_at = Column(DateTime, nullable=True)
    stop_work_reason = Column(String(500), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    owner = relationship("User", back_populates="engagements")
    client = relationship("Client", back_populates="engagements")
    authorizations = relationship("Authorization", back_populates="engagement", cascade="all, delete-orphan")
    scope_items = relationship("ScopeItem", back_populates="engagement", cascade="all, delete-orphan")
    assets = relationship("Asset", back_populates="engagement", cascade="all, delete-orphan")
    manual_tests = relationship("ManualTest", back_populates="engagement", cascade="all, delete-orphan")
    findings = relationship("Finding", back_populates="engagement", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="engagement", cascade="all, delete-orphan")
    recon_items = relationship("ReconItem", back_populates="engagement", cascade="all, delete-orphan")
    scan_items = relationship("ScanItem", back_populates="engagement", cascade="all, delete-orphan")
    import_records = relationship("ImportRecord", back_populates="engagement", cascade="all, delete-orphan")
    scan_jobs   = relationship("ScanJob",    back_populates="engagement", cascade="all, delete-orphan")
    services    = relationship("Service",    back_populates="engagement", cascade="all, delete-orphan")
    scheduled_scans = relationship("ScheduledScan", back_populates="engagement", cascade="all, delete-orphan")
    members = relationship("EngagementMember", back_populates="engagement", cascade="all, delete-orphan")
    scan_profiles = relationship("ScanProfile", back_populates="engagement", cascade="all, delete-orphan")
    test_cases = relationship("AuthorizationTestCase", back_populates="engagement", cascade="all, delete-orphan")


class Authorization(Base):
    """The record of permission to test, and the window it covers.

    This is the artifact that distinguishes professional testing from bug
    bounty hunting: a named person authorised named activity against named
    scope, between two dates. For bounty work the equivalent is the engagement's
    safe harbour policy, which is why `reference` and `permits` are free text
    rather than a contract-shaped schema.

    It is deliberately append-mostly. Superseding an authorisation creates a
    new row and marks the old one `expired`, so the history of what was
    permitted when survives — which is the whole point of holding it.
    """

    __tablename__ = "authorizations"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id"), nullable=False, index=True)
    # Denormalised owner for the same fast BOLA filter every other table uses.
    owner_github_id = Column(String, nullable=False, index=True)
    # What the testing is permitted to do, in the authoriser's words.
    permits = Column(Text, default="")
    # Who granted it and how it can be evidenced later.
    authorized_by = Column(String(200), default="")
    authorized_at = Column(DateTime, nullable=True)
    reference = Column(String(500), default="")  # SOW number, ticket, or policy URL
    # The window testing is permitted in. Null end means open-ended, which is
    # normal for a bounty programme and unusual for an engagement.
    window_start = Column(DateTime, nullable=True)
    window_end = Column(DateTime, nullable=True)
    status = Column(String(20), default="active")  # active|expired|revoked
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    engagement = relationship("Engagement", back_populates="authorizations")


class ScopeItem(Base):
    __tablename__ = "scope_items"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id"), nullable=False)
    scope_type = Column(String(3), nullable=False)  # "in" or "out"
    value = Column(String(500), nullable=False)
    kind = Column(String(20), default="domain")
    notes = Column(Text, default="")
    created_at = Column(DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))

    engagement = relationship("Engagement", back_populates="scope_items")


class ManualTest(Base):
    __tablename__ = "manual_tests"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id"), nullable=False)
    title = Column(String(200), nullable=False)
    hypothesis = Column(Text, default="")
    payload = Column(Text, default="")
    evidence = Column(Text, default="")
    status = Column(String(20), default="new")
    created_at = Column(DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))

    engagement = relationship("Engagement", back_populates="manual_tests")


class Finding(Base):
    __tablename__ = "findings"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id"), nullable=False)
    title = Column(String(200), nullable=False)
    severity = Column(String(20), default="info")
    asset = Column(String(500), default="")
    asset_id = Column(String, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(20), default="new")
    summary = Column(Text, default="")
    steps = Column(Text, default="")
    impact = Column(Text, default="")
    remediation = Column(Text, default="")
    created_at = Column(DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))

    engagement = relationship("Engagement", back_populates="findings")


class Report(Base):
    __tablename__ = "reports"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id"), nullable=False)
    finding_id = Column(String, default="")  # soft reference, no FK constraint
    title = Column(String(200), nullable=False)
    summary = Column(Text, default="")
    steps = Column(Text, default="")
    impact = Column(Text, default="")
    remediation = Column(Text, default="")
    cwe = Column(String(50), default="")
    cvss = Column(String(50), default="")
    status = Column(String(20), default="draft")
    created_at = Column(DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))

    engagement = relationship("Engagement", back_populates="reports")


class ReconItem(Base):
    __tablename__ = "recon_items"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id"), nullable=False)
    source = Column(String(20), default="")
    url = Column(Text, default="")
    path = Column(Text, default="")
    host = Column(Text, default="")
    title = Column(Text, default="")
    status_code = Column(Integer, nullable=True)
    webserver = Column(String(200), default="")
    port = Column(String(10), default="")
    tech = Column(Text, default="")
    content_type = Column(String(200), default="")
    length = Column(Integer, nullable=True)
    words = Column(Integer, nullable=True)
    lines = Column(Integer, nullable=True)
    notes = Column(Text, default="")
    # Set once on first discovery — never overwritten on re-import.
    asset_id = Column(String, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True)
    first_seen_at = Column(DateTime, nullable=True)
    job_id = Column(String, nullable=True)  # scan_job that produced this item, if any
    created_at = Column(DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))

    engagement = relationship("Engagement", back_populates="recon_items")


class ScanItem(Base):
    __tablename__ = "scan_items"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id"), nullable=False)
    source = Column(String(20), default="nuclei")
    template_id = Column(String(200), default="")
    title = Column(String(200), default="")
    severity = Column(String(20), default="info")
    asset = Column(Text, default="")
    matched_at = Column(Text, default="")
    type = Column(String(50), default="")
    description = Column(Text, default="")
    status = Column(String(20), default="new")
    cwe = Column(String(50), default="")
    cvss = Column(String(50), default="")
    asset_id = Column(String, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True)
    job_id = Column(String, nullable=True)  # scan_job that produced this item, if any
    created_at = Column(DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))

    engagement = relationship("Engagement", back_populates="scan_items")


class ImportRecord(Base):
    __tablename__ = "import_records"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id"), nullable=False)
    tool_type = Column(String(20), default="")
    filename = Column(String(200), default="redacted")
    imported_count = Column(Integer, default=0)
    created_at = Column(DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))

    engagement = relationship("Engagement", back_populates="import_records")


class Evidence(Base):
    """Proof attached to a finding, redacted before it is stored.

    Redaction happens on write, never on render. Storing a raw Authorization
    header and stripping it in the serializer means one forgotten path — a log
    line, an export, a debug endpoint, an error message — leaks it. What is
    never stored cannot leak from a path nobody remembered.

    `content_hash` is taken over the redacted body, which is what integrity
    means here: the artefact as retained, not as captured.
    """

    __tablename__ = "evidence"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)
    finding_id = Column(String, ForeignKey("findings.id", ondelete="CASCADE"), nullable=True, index=True)
    asset_id = Column(String, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True)

    kind = Column(String(30), nullable=False, default="note")
    # http_request | http_response | terminal_output | tool_result | note | screenshot
    title = Column(String(200), default="")
    body = Column(Text, default="")            # already redacted
    content_hash = Column(String(64), default="")   # sha256 of the stored body

    # Provenance and handling.
    collector = Column(String(100), default="")     # analyst login, tool, or runner id
    source = Column(String(60), default="")
    sensitivity = Column(String(20), default="internal")   # public|internal|confidential|restricted
    retention = Column(String(20), default="engagement")   # engagement|90d|permanent
    redacted = Column(Boolean, nullable=False, default=True)
    collected_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=new_uuid)
    # No FK constraints — audit records are kept even if the user/engagement is deleted
    github_id = Column(String, nullable=False, index=True)
    action = Column(String(20), nullable=False)        # "create" | "update" | "delete" | "deny"
    resource_type = Column(String(50), nullable=False)  # "engagement" | "finding" | etc.
    resource_id = Column(String, nullable=False)
    program_id = Column(String, default="")             # context only, no FK
    # Policy reason code for action="deny" (see policy.py). A refused execution
    # is the security-relevant event, and "why" is the part worth keeping.
    reason = Column(String(50), default="")
    detail = Column(String(500), default="")
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class ScanJob(Base):
    __tablename__ = "scan_jobs"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_github_id = Column(String, nullable=False, index=True)
    tool_type = Column(String(20), nullable=False)          # see routers/jobs.py _VALID_TOOLS
    target_source = Column(String(20), nullable=False)      # "scope" or "recon"
    config = Column(JSON, nullable=True)                    # tool-specific options
    status = Column(String(20), default="pending")          # pending | running | done | failed
    # Soft ref to the scan_job this stage waits on. A dependent job stays out of
    # GET /jobs/pending until its parent is "done"; if the parent "failed" the child
    # is auto-failed so it never hangs. NULL = no dependency (eligible immediately).
    depends_on = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, default="")

    engagement = relationship("Engagement", back_populates="scan_jobs")
    events = relationship("JobEvent", back_populates="job", cascade="all, delete-orphan", order_by="JobEvent.created_at")


class RunnerHeartbeat(Base):
    __tablename__ = "runner_heartbeats"
    # One row per (user, machine) — upserted on every heartbeat POST so
    # multiple runners (laptop + VPS) can report independently
    __table_args__ = (UniqueConstraint("owner_github_id", "hostname", name="uq_runner_heartbeats_owner_host"),)

    id = Column(String, primary_key=True, default=new_uuid)
    owner_github_id = Column(String, nullable=False, index=True)
    hostname = Column(String(200), default="")
    version = Column(String(50), default="")
    os_info = Column(String(200), default="")
    tools = Column(JSON, nullable=False, default=dict)  # {"httpx": {"ok": true, "version": "v1.6.9"}}
    last_seen = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class JobEvent(Base):
    __tablename__ = "job_events"

    id = Column(String, primary_key=True, default=new_uuid)
    job_id = Column(String, ForeignKey("scan_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_github_id = Column(String, nullable=False, index=True)
    kind = Column(String(50), nullable=False)  # started | targets_resolved | running | uploaded | done | failed | log
    text = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    job = relationship("ScanJob", back_populates="events")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=new_uuid)
    github_id = Column(String, ForeignKey("users.github_id"), nullable=False, index=True)
    # SHA-256 hex of the plaintext token — 64 chars. Raw token is never stored.
    key_hash = Column(String(64), nullable=False, unique=True)
    label = Column(String(100), default="")
    # "full" = unrestricted; "runner" = jobs/imports/heartbeat only
    scope = Column(String(20), nullable=False, default="full")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="api_keys")


class Service(Base):
    __tablename__ = "services"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_github_id = Column(String, nullable=False, index=True)
    host = Column(String(500), nullable=False)
    port = Column(Integer, nullable=False)
    protocol = Column(String(10), default="tcp")       # tcp | udp
    service_name = Column(String(100), default="")
    product = Column(String(200), default="")
    version = Column(String(100), default="")
    state = Column(String(20), default="open")         # open | filtered
    source = Column(String(50), default="nmap")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    asset_id = Column(String, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True)
    last_scanned_at = Column(DateTime, nullable=True)   # stamped on every upsert

    engagement = relationship("Engagement", back_populates="services")


class RadarProgram(Base):
    __tablename__ = "radar_programs"

    id = Column(String, primary_key=True, default=new_uuid)
    owner_github_id = Column(String, nullable=False, index=True)
    platform = Column(String(20), nullable=False)   # "bugcrowd" | "hackerone"
    platform_id = Column(String(200), nullable=False)  # unique slug/handle on platform
    name = Column(String(300), nullable=False)
    url = Column(String(500), default="")
    max_payout = Column(Integer, nullable=True)
    is_new = Column(String(1), default="1")  # "1" = unseen since last refresh, "0" = seen
    discovered_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    last_fetched_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class ScheduledScan(Base):
    __tablename__ = "scheduled_scans"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_github_id = Column(String, nullable=False, index=True)
    tool_type = Column(String(20), nullable=False)       # see routers/jobs.py _VALID_TOOLS
    target_source = Column(String(20), nullable=False)   # "scope" | "recon"
    config = Column(JSON, nullable=True)                 # tool-specific options, same shape as ScanJob.config
    interval = Column(String(20), nullable=False)        # "hourly" | "daily" | "weekly"
    enabled = Column(Boolean, nullable=False, default=True)
    last_run_at = Column(DateTime, nullable=True)
    # Due schedules are materialized into scan_jobs when the runner polls
    # GET /jobs/pending — the polling daemon drives the clock, no cron needed
    next_run_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    engagement = relationship("Engagement", back_populates="scheduled_scans")


class EngagementMember(Base):
    """Invited collaborators on an engagement. Members can read and write engagement resources;
    only the owner can delete the engagement or manage membership."""
    __tablename__ = "program_members"
    __table_args__ = (UniqueConstraint("program_id", "member_github_id", name="uq_program_members"),)

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_github_id = Column(String, nullable=False, index=True)   # engagement owner — for fast BOLA checks
    member_github_id = Column(String, nullable=False, index=True)  # the invited collaborator
    role = Column(String(20), nullable=False, default="member")    # "member" (future: "admin")
    invited_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    engagement = relationship("Engagement", back_populates="members")


class ScanProfile(Base):
    """A saved, reusable tool + config preset for an engagement. Lets a hunter queue a
    frequently-used scan (e.g. "nuclei CVE profile") in one click instead of retyping
    config every time. config mirrors ScanJob.config shape and is validated identically."""
    __tablename__ = "scan_profiles"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_github_id = Column(String, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    tool_type = Column(String(20), nullable=False)       # see routers/jobs.py _VALID_TOOLS
    target_source = Column(String(20), nullable=False)   # "scope" | "recon"
    config = Column(JSON, nullable=True)                 # same shape/validation as ScanJob.config
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    engagement = relationship("Engagement", back_populates="scan_profiles")


class AuthorizationTestCase(Base):
    """A stored VardrGate authorization test case, scoped to an engagement.

    The `spec` column holds VardrGate's own `AuthorizationTestCase` JSON verbatim
    — identities, request template, expected access per identity, and optional
    ownership/deny context. Storing it whole rather than shredding it into columns
    keeps VardrGate free to add fields without a migration here; VardrGate is the
    schema authority, this table is storage.

    Jobs reference a row by id (`config = {"test_case_id": ...}`), and the spec is
    inlined when the job is handed to a runner. That keeps `ScanJob.config` flat
    for validation, lets one test case back many runs, and means editing a case
    does not require re-queueing.

    **Credential values are never stored.** Every identity must reference its
    secret with `value_env` or `value_keychain`, which VardrRunner resolves on the
    operator's machine. A literal, non-empty `value` is rejected on write — see
    `routers/test_cases.py`.
    """

    __tablename__ = "authorization_test_cases"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_github_id = Column(String, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    # VardrGate's test case id (spec["id"]) — surfaced so results can be traced
    # back without opening the blob. Not unique: a case may be revised.
    test_case_id = Column(String(200), nullable=False, default="")
    description = Column(Text, default="")
    spec = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=True)

    engagement = relationship("Engagement", back_populates="test_cases")
