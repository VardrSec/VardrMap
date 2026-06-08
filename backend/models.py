import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
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


class ScopeItem(Base):
    __tablename__ = "scope_items"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id"), nullable=False)
    scope_type = Column(String(3), nullable=False)  # "in" or "out"
    value = Column(String(500), nullable=False)
    kind = Column(String(20), default="domain")
    notes = Column(Text, default="")

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

    program = relationship("Program", back_populates="scan_items")


class ImportRecord(Base):
    __tablename__ = "import_records"

    id = Column(String, primary_key=True, default=new_uuid)
    program_id = Column(String, ForeignKey("programs.id"), nullable=False)
    tool_type = Column(String(20), default="")
    filename = Column(String(200), default="redacted")
    imported_count = Column(Integer, default=0)

    program = relationship("Program", back_populates="import_records")
