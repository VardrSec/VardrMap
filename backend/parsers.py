import json
import re
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


_URL_FIELD_MAX = 8192


def _url_field(value: Any) -> str:
    """A URL, host or path kept exactly as the tool reported it.

    Not ``strip_html``: that is a sanitiser for prose, and it HTML-encodes ``&``, so a
    recon URL ``?q=1&page=2`` was stored as ``?q=1&amp;page=2``. Recon URLs are read back
    as scan targets, so a runner then fetched a URL whose second parameter was literally
    named ``amp;page`` -- dalfox tested the wrong parameters, and every URL-keyed dedup
    and lookup was keyed on a string that was never the URL. Data, not markup: control
    characters are removed and the length bounded. Titles and other descriptive text
    still go through ``strip_html``.

    One deliberate change: ``<`` and ``>`` are percent-encoded (``%3C``, ``%3E``), which
    keeps the guarantee that a URL can never be stored as markup without deleting part of
    it. A literal ``<`` is not valid in a URL and every HTTP client sends it encoded
    anyway, so the target still means the same thing.
    """
    return _plain(value, _URL_FIELD_MAX).strip().replace("<", "%3C").replace(">", "%3E")


def parse_ffuf(items: list[dict[str, Any]], program_id: str) -> list[ReconItem]:
    out = []
    for item in items:
        url = item.get("url") or item.get("input", {}).get("FUZZ") or ""
        out.append(ReconItem(
            program_id=program_id,
            source="ffuf",
            url=_url_field(url),
            path=_url_field(item.get("input", {}).get("FUZZ", "")),
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
            url=_url_field(item.get("url")),
            host=_url_field(item.get("host")),
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
            asset=_url_field(item.get("matched-at") or item.get("host")),
            matched_at=_url_field(item.get("matched-at")),
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


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PAYLOAD_MAX = 2000
_EVIDENCE_MAX = 2000
_URL_MAX = 2000


def _plain(value: Any, limit: int) -> str:
    """Scanner evidence kept exactly as reported: control characters out, length capped.

    Deliberately NOT ``strip_html``. That is the right defence for prose, but it is
    lossy by design: ``nh3`` deletes anything shaped like a tag and HTML-encodes
    ``&``, so an XSS payload such as ``<svg onload=alert(1)>`` is destroyed (leaving
    nothing to reproduce the issue with) and a PoC URL ``?a=1&q=x`` is stored as
    ``?a=1&amp;q=x``. For a tool whose entire output is "this input is dangerous",
    the dangerous input *is* the evidence.

    Safe to store raw because it is data, never markup: the API returns it as a JSON
    string, nothing in the frontend renders HTML, and the field is documented as
    untrusted text that must only ever be rendered as text.
    """
    text = "" if value is None else str(value)
    return _CONTROL.sub("", text)[:limit]


def _http_url(value: Any) -> str:
    """An http(s) URL kept exactly, or "" for anything else (javascript:, data:, junk)."""
    text = _plain(value, _URL_MAX).strip()
    try:
        parts = urlsplit(text)
    except ValueError:
        return ""
    return text if parts.scheme.lower() in ("http", "https") and parts.hostname else ""


def parse_dalfox(items: list[dict[str, Any]], program_id: str) -> list[ScanItem]:
    """XSS candidates from dalfox (the objects under its ``findings`` key).

    Everything arrives as ``status="new"``. dalfox's own tier is kept in `type`,
    its detection method and confidence in their own columns. Even its top tier
    is *dalfox asserting* exploitability, not this platform confirming it, so no
    tier maps to a confirmed status — promoting a finding stays an operator's
    act. Response bodies are never stored: `request`/`response` (present with
    ``--include-all``) are ignored.

    The payload, the evidence and the PoC URL are stored **losslessly** (see
    ``_plain``) in their own columns; only the human-readable description goes
    through ``strip_html``.
    """
    out = []
    for item in items:
        url = _http_url(item.get("data"))
        tier = _DALFOX_TIERS.get(str(item.get("type") or "").strip().upper(), "")
        # Identity must not be sanitised: stripping a parameter name shaped like a tag
        # would collapse distinct parameters into one dedup key.
        param = _plain(item.get("param"), 200)
        inject = _plain(item.get("inject_type"), 100)
        severity = str(item.get("severity") or "").strip().lower()
        detection = str(item.get("detection_method") or "").strip().lower()
        confidence = str(item.get("confidence") or "").strip().lower()
        payload = _plain(item.get("payload"), _PAYLOAD_MAX)
        evidence = _plain(item.get("evidence"), _EVIDENCE_MAX)
        title = f"XSS in parameter '{param}'" if param else "XSS candidate"
        if inject:
            title = f"{title} ({inject})"
        # dalfox's message_str quotes the payload inline. The payload has its own
        # column, and strip_html would turn that quotation into a dangling "q=", so
        # the prose points at the column instead of carrying a mangled copy.
        message = str(item.get("message_str") or "")
        if payload:
            message = message.replace(str(item.get("payload")), "[payload]")
        description = " ".join(
            part
            for part in (
                strip_html(str(item.get("type_description") or "")),
                strip_html(message),
                strip_html(str(item.get("confidence_reason") or "")),
            )
            if part
        )
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
            asset=url,
            matched_at=url,
            type=tier,
            description=description,
            payload=payload,
            match_evidence=evidence,
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
            url=_url_field(url),
            host=_url_field(host),
            path=_url_field(path),
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
            url=_url_field(url),
            host=_url_field(host),
            path=_url_field(path),
        ))
    return out
