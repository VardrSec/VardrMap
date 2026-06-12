import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, Text
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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    programs = relationship("Program", back_populates="owner", cascade="all, delete-orphan")
    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")


class Program(Base):
    __tablename__ = "programs"

    id = Column(String, primary_key=True, default=new_uuid)
    owner_github_id = Column(String, ForeignKey("users.github_id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    platform = Column(String(80), default="")
    program_url = Column(String(500), default="")
    scope_summary = Column(Text, default="")
    severity_guidance = Column(Text, default="")
    safe_harbor_notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    owner = relationship("User", back_populates="programs")
    scope_items = relationship("ScopeItem", back_populates="program", cascade="all, delete-orphan")
    manual_tests = relationship("ManualTest", back_populates="program", cascade="all, delete-orphan")
    findings = relationship("Finding", back_populates="program", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="program", cascade="all, delete-orphan")
    recon_items = relationship("ReconItem", back_populates="program", cascade="all, delete-orphan")
    scan_items = relationship("ScanItem", back_populates="program", cascade="all, delete-orphan")
    import_records = relationship("ImportRecord", back_populates="program", cascade="all, delete-orphan")
    scan_jobs   = relationship("ScanJob",    back_populates="program", cascade="all, delete-orphan")
    services    = relationship("Service",    back_populates="program", cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="program", cascade="all, delete-orphan")


class ScopeItem(Base):
    __tablename__ = "scope_items"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id"), nullable=False)
    scope_type = Column(String(3), nullable=False)  # "in" or "out"
    value = Column(String(500), nullable=False)
    kind = Column(String(20), default="domain")
    notes = Column(Text, default="")
    created_at = Column(DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))

    program = relationship("Program", back_populates="scope_items")


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

    program = relationship("Program", back_populates="manual_tests")


class Finding(Base):
    __tablename__ = "findings"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id"), nullable=False)
    title = Column(String(200), nullable=False)
    severity = Column(String(20), default="info")
    asset = Column(String(500), default="")
    status = Column(String(20), default="new")
    summary = Column(Text, default="")
    steps = Column(Text, default="")
    impact = Column(Text, default="")
    remediation = Column(Text, default="")
    created_at = Column(DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))

    program = relationship("Program", back_populates="findings")


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

    program = relationship("Program", back_populates="reports")


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
    created_at = Column(DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))

    program = relationship("Program", back_populates="recon_items")


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
    created_at = Column(DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))

    program = relationship("Program", back_populates="scan_items")


class ImportRecord(Base):
    __tablename__ = "import_records"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id"), nullable=False)
    tool_type = Column(String(20), default="")
    filename = Column(String(200), default="redacted")
    imported_count = Column(Integer, default=0)
    created_at = Column(DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))

    program = relationship("Program", back_populates="import_records")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=new_uuid)
    # No FK constraints — audit records are kept even if the user/program is deleted
    github_id = Column(String, nullable=False, index=True)
    action = Column(String(20), nullable=False)        # "create" | "update" | "delete"
    resource_type = Column(String(50), nullable=False)  # "program" | "finding" | etc.
    resource_id = Column(String, nullable=False)
    program_id = Column(String, default="")             # context only, no FK
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class ScanJob(Base):
    __tablename__ = "scan_jobs"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_github_id = Column(String, nullable=False, index=True)
    tool_type = Column(String(20), nullable=False)          # "httpx", "nuclei", or "subfinder"
    target_source = Column(String(20), nullable=False)      # "scope" or "recon"
    config = Column(JSON, nullable=True)                    # tool-specific options
    status = Column(String(20), default="pending")          # pending | running | done | failed
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, default="")

    program = relationship("Program", back_populates="scan_jobs")
    events = relationship("JobEvent", back_populates="job", cascade="all, delete-orphan", order_by="JobEvent.created_at")


class RunnerHeartbeat(Base):
    __tablename__ = "runner_heartbeats"

    id = Column(String, primary_key=True, default=new_uuid)
    # One row per user — upserted on every heartbeat POST
    owner_github_id = Column(String, nullable=False, unique=True, index=True)
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
    last_scanned_at = Column(DateTime, nullable=True)   # stamped on every upsert

    program = relationship("Program", back_populates="services")


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


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_github_id = Column(String, nullable=False, index=True)
    # Soft references — no FK constraints so records survive finding/report deletion
    finding_id = Column(String, default="")
    report_id = Column(String, default="")
    platform = Column(String(50), default="")            # "HackerOne" | "Bugcrowd" | etc.
    platform_reference = Column(String(200), default="") # report ID / slug on the platform
    title = Column(String(200), default="")
    status = Column(String(30), default="submitted")     # submitted | triaged | accepted | duplicate | na | paid | rejected
    payout_usd = Column(Float, nullable=True)
    severity = Column(String(20), default="")            # copied from finding for quick display
    submitted_at = Column(DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime, nullable=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    program = relationship("Program", back_populates="submissions")
