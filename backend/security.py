import re
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
