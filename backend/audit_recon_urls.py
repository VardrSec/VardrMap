"""READ-ONLY audit of recon-URL corruption left by the old importer.

Before the fix, every importer ran URLs through ``strip_html`` (nh3), which HTML-encodes
``&``, ``<`` and ``>`` and deletes anything tag-shaped. This reports how much of a
database that touched, and -- the part that decides what recovery is safe -- how much of
it can be corroborated, because the damage is not reversible by inspection alone: five
different originals (``a&b``, ``a&amp;b``, ``a&#38;b``, ``a&#x26;b``, ``a&ampb``) all
became the same stored ``a&amp;b``.

It changes nothing. Every statement is a SELECT, and the connection is put into the
database's read-only mode first (``SET TRANSACTION READ ONLY`` on Postgres,
``PRAGMA query_only`` on SQLite), so a write would fail rather than succeed.

    python audit_recon_urls.py                       # human summary
    python audit_recon_urls.py --json                # machine-readable
    python audit_recon_urls.py --fixed-since 2026-10-11T00:00:00Z

``--fixed-since`` is when the fix was deployed. A row created after it that contains
``&amp;`` is a genuine literal entity, not corruption; without the cutoff the two look
identical, so every marked row is reported as "suspect".
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import ReconItem, ScanItem
from security import strip_html

# What the old sanitiser leaves behind when it encoded something.
MARKERS = ("&amp;", "&lt;", "&gt;")


def legacy_form(value: str) -> str:
    """What the old importer would have stored for ``value``."""
    return strip_html(value)


def _marked(value: str | None) -> bool:
    return bool(value) and any(m in value for m in MARKERS)


def make_read_only(db: Session) -> None:
    """Refuse writes on this session's connection. Raises if it cannot."""
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        db.execute(text("SET TRANSACTION READ ONLY"))
    elif dialect == "sqlite":
        db.execute(text("PRAGMA query_only = ON"))
    else:  # unknown dialect: do not run an audit that cannot prove it is read-only
        raise RuntimeError(f"cannot enforce read-only mode on dialect {dialect!r}")


def restore_writes(db: Session) -> None:
    """Undo `make_read_only` where it outlives the transaction (SQLite's pragma is per-connection,
    so a pooled connection would otherwise carry it into whatever uses it next)."""
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("PRAGMA query_only = OFF"))
    db.rollback()


def audit(db: Session, fixed_since: datetime | None = None) -> dict[str, Any]:
    make_read_only(db)
    try:
        return _audit(db, fixed_since)
    finally:
        restore_writes(db)


def _audit(db: Session, fixed_since: datetime | None) -> dict[str, Any]:
    report: dict[str, Any] = {"fixed_since": fixed_since.isoformat() if fixed_since else None}

    rows = db.query(ReconItem).all()
    by_key: dict[tuple[str, str], list[ReconItem]] = defaultdict(list)
    for row in rows:
        by_key[(row.program_id, row.source)].append(row)

    sources: dict[str, dict[str, int]] = {}
    for (_, source), group in by_key.items():
        stats = sources.setdefault(
            source,
            {"rows": 0, "marked": 0, "suspect": 0, "corroborated": 0, "unpaired": 0, "collisions": 0},
        )
        stats["rows"] += len(group)

        # Index every URL in the group by the form it would have had under the old importer.
        legacy_index: dict[str, list[ReconItem]] = defaultdict(list)
        for row in group:
            if row.url:
                legacy_index[legacy_form(row.url)].append(row)

        for row in group:
            if not (_marked(row.url) or _marked(row.host) or _marked(row.path)):
                continue
            stats["marked"] += 1
            if fixed_since and row.created_at and row.created_at >= fixed_since:
                continue  # imported after the fix: a literal entity, not corruption
            stats["suspect"] += 1
            # A *different* row that would have produced this one is direct evidence of
            # what the original was. That is the only thing here that justifies a repair.
            peers = [r for r in legacy_index.get(row.url or "", []) if r.id != row.id and r.url != row.url]
            if peers:
                stats["corroborated"] += 1
                if len({p.url for p in peers}) > 1:
                    stats["collisions"] += 1  # two distinct originals share this stored value
            else:
                stats["unpaired"] += 1
    report["recon"] = dict(sorted(sources.items()))

    scan_marked = 0
    for item in db.query(ScanItem).filter(ScanItem.source == "nuclei").all():
        if _marked(item.asset) or _marked(item.matched_at):
            if not (fixed_since and item.created_at and item.created_at >= fixed_since):
                scan_marked += 1
    report["nuclei_scan_items_suspect"] = scan_marked

    totals = {k: sum(s[k] for s in sources.values()) for k in ("rows", "marked", "suspect", "corroborated", "unpaired", "collisions")}
    report["totals"] = totals
    return report


def render(report: dict[str, Any]) -> str:
    t = report["totals"]
    lines = [
        "Recon URL audit (read-only)",
        f"  rows scanned            : {t['rows']}",
        f"  contain an encoded char : {t['marked']}",
        f"  suspect (legacy)        : {t['suspect']}"
        + ("" if report["fixed_since"] else "   [no --fixed-since: every marked row counts as suspect]"),
        f"    corroborated by a row : {t['corroborated']}   (a correct row exists that explains it)",
        f"      of which collisions : {t['collisions']}   (two different originals share this value)",
        f"    unpaired              : {t['unpaired']}   (no evidence: a decode would be a guess)",
        f"  nuclei scan items       : {report['nuclei_scan_items_suspect']} suspect",
        "  per source:",
    ]
    for source, s in report["recon"].items():
        lines.append(
            f"    {source:8s} rows={s['rows']:6d} suspect={s['suspect']:5d} "
            f"corroborated={s['corroborated']:5d} unpaired={s['unpaired']:5d}"
        )
    lines.append("  Irrecoverable and NOT counted: tag-shaped content the sanitiser deleted outright.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a summary")
    parser.add_argument("--fixed-since", help="ISO-8601 time the fix was deployed")
    args = parser.parse_args(argv)
    cutoff = datetime.fromisoformat(args.fixed_since.replace("Z", "+00:00")) if args.fixed_since else None
    if cutoff is not None:
        cutoff = cutoff.replace(tzinfo=None)  # the DB stores naive UTC

    from db import SessionLocal

    db = SessionLocal()
    try:
        report = audit(db, cutoff)
    finally:
        db.rollback()
        db.close()
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
