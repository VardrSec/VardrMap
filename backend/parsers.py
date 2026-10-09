import json
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException

from models import ReconItem, ScanItem
from security import strip_html


# Try JSONL first (newline-delimited, what most tools produce with -jsonl flags),
# then fall back to a single JSON object/array. Both formats are common in the wild.
def parse_json_or_jsonl(raw: bytes) -> Any:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    if "\n" in text:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        try:
            return [json.loads(line) for line in lines]
        except json.JSONDecodeError:
            pass  # not valid JSONL, fall through and try as a single JSON blob

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON/JSONL: {exc.msg}")


# Different tools wrap their output differently — ffuf wraps results under a
# "results" key, dalfox puts them under "findings" beside a "meta" envelope,
# httpx and nuclei emit a bare array, and sometimes a single-run output is just
# one object. This flattens them all into the same list shape.
_RESULT_KEYS = ("results", "findings")


def normalize_to_list(parsed: Any) -> list[dict[str, Any]]:
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        for key in _RESULT_KEYS:
            if isinstance(parsed.get(key), list):
                return [item for item in parsed[key] if isinstance(item, dict)]
        return [parsed]
    raise HTTPException(status_code=400, detail="Unsupported JSON structure")


def parse_ffuf(items: list[dict[str, Any]], program_id: str) -> list[ReconItem]:
    out = []
    for item in items:
        url = item.get("url") or item.get("input", {}).get("FUZZ") or ""
        out.append(ReconItem(
            program_id=program_id,
            source="ffuf",
            url=strip_html(url),
            path=strip_html(str(item.get("input", {}).get("FUZZ", ""))),
            status_code=item.get("status"),
            length=item.get("length"),
            words=item.get("words"),
            lines=item.get("lines"),
            content_type=strip_html(item.get("content-type") or item.get("content_type") or ""),
        ))
    return out


def parse_httpx(items: list[dict[str, Any]], program_id: str) -> list[ReconItem]:
    out = []
    for item in items:
        tech_value = item.get("tech") or item.get("technologies") or []
        tech_str = ",".join(str(t) for t in tech_value) if isinstance(tech_value, list) else str(tech_value or "")
        out.append(ReconItem(
            program_id=program_id,
            source="httpx",
            url=strip_html(item.get("url") or ""),
            host=strip_html(item.get("host") or ""),
            title=strip_html(item.get("title") or ""),
            status_code=item.get("status-code") or item.get("status_code"),
            webserver=strip_html(item.get("webserver") or ""),
            port=str(item.get("port") or ""),
            tech=strip_html(tech_str),
            content_type=strip_html(item.get("content-type") or item.get("content_type") or ""),
        ))
    return out


def parse_nuclei(items: list[dict[str, Any]], program_id: str) -> list[ScanItem]:
    out = []
    for item in items:
        info = item.get("info") if isinstance(item.get("info"), dict) else {}
        classification = info.get("classification") if isinstance(info.get("classification"), dict) else {}
        out.append(ScanItem(
            program_id=program_id,
            source="nuclei",
            template_id=strip_html(item.get("template-id") or item.get("templateID") or ""),
            title=strip_html(info.get("name") or item.get("matcher-name") or "Untitled Finding"),
            severity=strip_html(info.get("severity") or "info"),
            asset=strip_html(item.get("matched-at") or item.get("host") or ""),
            matched_at=strip_html(item.get("matched-at") or ""),
            type=strip_html(item.get("type") or ""),
            description=strip_html(info.get("description") or ""),
            status="new",
            cwe=strip_html(",".join(classification.get("cwe-id")) if isinstance(classification.get("cwe-id"), list) else str(classification.get("cwe-id") or "")),
            cvss=strip_html(str(classification.get("cvss-score") or "")),
        ))
    return out


# dalfox's tiers, as its own documentation defines them. The tier is the
# scanner's claim about the match, and it is preserved verbatim in `type` rather
# than being collapsed into severity: "V" is dalfox asserting exploitability,
# "R" is a reflection it could not confirm and explicitly asks a human to check.
_DALFOX_TIERS = {
    "V": "vulnerable",
    "R": "reflected",
    "A": "ast",
    "I": "informational",
}
_DALFOX_DETECTION = {"reflection", "dom-verification", "ast", "oob", "library"}
_DALFOX_CONFIDENCE = {"high", "low"}
_SEVERITIES = {"info", "low", "medium", "high", "critical"}


def parse_dalfox(items: list[dict[str, Any]], program_id: str) -> list[ScanItem]:
    """XSS candidates from dalfox (the objects under its ``findings`` key).

    Everything arrives as ``status="new"``. dalfox's own tier is kept in `type`,
    its detection method and confidence in their own columns. Even its top tier
    is *dalfox asserting* exploitability, not this platform confirming it, so no
    tier maps to a confirmed status — promoting a finding stays an operator's
    act. Response bodies are never stored: `request`/`response` (present with
    ``--include-all``) are ignored, and the evidence line is bounded.
    """
    out = []
    for item in items:
        url = item.get("data") or ""
        tier = _DALFOX_TIERS.get(str(item.get("type") or "").strip().upper(), "")
        param = strip_html(str(item.get("param") or ""))
        inject = strip_html(str(item.get("inject_type") or ""))
        severity = str(item.get("severity") or "").strip().lower()
        detection = str(item.get("detection_method") or "").strip().lower()
        confidence = str(item.get("confidence") or "").strip().lower()
        title = f"XSS in parameter '{param}'" if param else "XSS candidate"
        if inject:
            title = f"{title} ({inject})"
        # dalfox's message_str explains the match; evidence is the reflected
        # snippet, which comes from the target, so both are sanitized and capped.
        detail = " ".join(
            part
            for part in (
                strip_html(str(item.get("type_description") or "")),
                strip_html(str(item.get("message_str") or "")),
                strip_html(str(item.get("confidence_reason") or "")),
            )
            if part
        )
        evidence = strip_html(str(item.get("evidence") or ""))[:500]
        payload = strip_html(str(item.get("payload") or ""))[:500]
        out.append(ScanItem(
            program_id=program_id,
            source="dalfox",
            # dalfox has no template id. The injection context plus the affected
            # parameter is the stable identity of a match: it survives a re-run,
            # unlike the payload and the PoC URL, which carry a per-run marker.
            # The importer dedupes on it.
            template_id=":".join(part for part in (inject, param) if part)[:200],
            title=strip_html(title)[:200],
            severity=severity if severity in _SEVERITIES else "info",
            asset=strip_html(url),
            matched_at=strip_html(url),
            type=tier,
            description=" | ".join(
                part
                for part in (detail, f"payload: {payload}" if payload else "",
                             f"evidence: {evidence}" if evidence else "")
                if part
            ),
            status="new",
            cwe=strip_html(str(item.get("cwe") or "")),
            detection_method=detection if detection in _DALFOX_DETECTION else "",
            confidence=confidence if confidence in _DALFOX_CONFIDENCE else "",
        ))
    return out


def _web_url(raw: Any) -> tuple[str, str, str] | None:
    """(url, host, path) for an http(s) URL, or None for anything else.

    Archive and crawler output routinely includes mailto:, javascript:, data: and
    malformed URLs; none of those are recon targets.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    url = raw.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    return url, parts.hostname, parts.path or "/"


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_katana(items: list[dict[str, Any]], program_id: str) -> list[ReconItem]:
    """Crawled endpoints from katana.

    Accepts the compact records VardrRunner uploads (url/status_code/content_length/
    content_type) and katana's own JSONL (request.endpoint, response.*), so a file
    exported straight from katana imports too. Response bodies are never read.
    """
    out = []
    for item in items:
        request = item.get("request") if isinstance(item.get("request"), dict) else {}
        response = item.get("response") if isinstance(item.get("response"), dict) else {}
        web = _web_url(item.get("url") or request.get("endpoint"))
        if web is None:
            continue
        url, host, path = web
        content_type = item.get("content_type")
        if content_type is None:
            headers = response.get("headers") if isinstance(response.get("headers"), dict) else {}
            content_type = next(
                (v for k, v in headers.items() if str(k).lower() == "content-type"), ""
            )
        out.append(ReconItem(
            program_id=program_id,
            source="katana",
            url=strip_html(url),
            host=strip_html(host),
            path=strip_html(path),
            status_code=_as_int(item.get("status_code", response.get("status_code"))),
            length=_as_int(item.get("content_length", response.get("content_length"))),
            content_type=strip_html(str(content_type or ""))[:200],
        ))
    return out


def parse_gau(items: list[dict[str, Any]], program_id: str) -> list[ReconItem]:
    """Archived URLs from gau (``{"url": ...}`` per line)."""
    out = []
    for item in items:
        web = _web_url(item.get("url"))
        if web is None:
            continue
        url, host, path = web
        out.append(ReconItem(
            program_id=program_id,
            source="gau",
            url=strip_html(url),
            host=strip_html(host),
            path=strip_html(path),
        ))
    return out
