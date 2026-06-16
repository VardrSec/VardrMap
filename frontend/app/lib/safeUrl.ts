/**
 * Explicit URL policy for rendered Markdown links.
 *
 * react-markdown is safe by default, but for a security tool we don't rely on
 * library defaults: this transform allows only http/https/mailto and relative
 * URLs and drops everything else (javascript:, data:, vbscript:, ...) by
 * returning an empty string. Control characters and whitespace are stripped
 * first so obfuscated schemes cannot slip through.
 *
 * The scheme is whatever precedes the first ":" — but only when that colon comes
 * before the first "/", "?", or "#", so a path segment containing a colon (e.g.
 * "/a:b") is correctly treated as relative.
 */
const SAFE_SCHEMES = ["http", "https", "mailto"];

export function safeMarkdownUrl(url: string): string {
  // Drop control chars + whitespace (code point <= 0x20) so obfuscated schemes
  // such as a tab-broken "javascript:" cannot slip through.
  const value = Array.from(url ?? "")
    .filter((c) => c.charCodeAt(0) > 0x20)
    .join("");
  const colon = value.indexOf(":");
  const pathStart = value.search(/[/?#]/);

  // No scheme (relative / anchor), or the colon belongs to a path segment.
  if (colon === -1 || (pathStart !== -1 && colon > pathStart)) {
    return value;
  }

  const scheme = value.slice(0, colon).toLowerCase();
  return SAFE_SCHEMES.includes(scheme) ? value : "";
}
