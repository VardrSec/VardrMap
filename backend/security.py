import re
import urllib.parse

import bleach

# Raw injection patterns checked BEFORE any stripping.
# Detecting on raw input (not post-strip) catches obfuscated payloads
# like <scr<script>ipt> that survive naive regex stripping first.
_INJECT_RE = re.compile(
    r"""(
        <script           |
        <iframe           |
        <object           |
        <embed            |
        <svg              |
        <img              |
        javascript\s*:    |
        data\s*:.*text/html
    )""",
    re.IGNORECASE | re.VERBOSE,
)

_EVENT_HANDLER_RE = re.compile(r'on\w+\s*=', re.IGNORECASE)


def _remove_null_bytes(value: str) -> str:
    return value.replace(chr(0), "")


def strip_html(value: str | None) -> str:
    """Strip all HTML tags using bleach. Safe for long-form markdown fields.
    Allows no tags — markdown syntax (**, `code`, #) is plain text and passes
    through untouched. bleach handles obfuscated/nested tags that fool regex.
    """
    if not value:
        return value or ""
    value = _remove_null_bytes(value)
    return bleach.clean(value, tags=[], attributes={}, strip=True).strip()


def sanitize_identifier(value: str | None) -> str:
    """Strict sanitizer for short identifier fields: name, title, asset.

    Detection runs on RAW input FIRST — before any stripping — to catch
    obfuscated payloads like <scr<script>ipt>. After detection, bleach strips
    any remaining tags.
    """
    if not value:
        return value or ""
    raw = _remove_null_bytes(value)
    if _INJECT_RE.search(raw) or _EVENT_HANDLER_RE.search(raw):
        raise ValueError("Invalid characters in field")
    return bleach.clean(raw, tags=[], attributes={}, strip=True).strip()


_ALLOWED_URL_SCHEMES = {"http", "https"}
# Any ASCII control char or whitespace can obfuscate a scheme (e.g. "java\tscript:")
# or smuggle log/header injection — reject it before parsing the URL.
_URL_BAD_CHARS_RE = re.compile(r"[\x00-\x20\x7f-\x9f]")


def validate_safe_url(value: str | None) -> str:
    """Return a cleaned URL if it is a safe http(s) link, else raise ValueError.

    Use this for any field that is rendered as a clickable link (program_url,
    Radar program URLs, future platform references). `strip_html` is *not* enough
    for URLs: it leaves `javascript:`, `data:`, and `vbscript:` schemes intact,
    which become live XSS the moment the value lands in an `href`. This allows
    only http/https, rejects every other scheme, and rejects control-character /
    whitespace obfuscation such as ``java\\tscript:`` or `` javascript:``. Empty
    input is allowed and returned as ``""``.
    """
    if not value:
        return ""
    cleaned = _remove_null_bytes(value).strip()
    if not cleaned:
        return ""
    if _URL_BAD_CHARS_RE.search(cleaned):
        raise ValueError("URL must not contain control characters or whitespace")
    parsed = urllib.parse.urlparse(cleaned)
    if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
        raise ValueError("URL must use http:// or https://")
    if not parsed.netloc:
        raise ValueError("URL must include a host")
    return cleaned
