import json
from typing import Any

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
# "results" key, httpx and nuclei emit a bare array, and sometimes a single-run
# output is just one object. This flattens all three into the same list shape.
def normalize_to_list(parsed: Any) -> list[dict[str, Any]]:
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        if isinstance(parsed.get("results"), list):
            return [item for item in parsed["results"] if isinstance(item, dict)]
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
