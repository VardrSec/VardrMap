package app.vardrmap.burp;

import java.util.regex.Pattern;

/** Conservative first-pass redaction; the backend independently redacts again. */
final class LocalRedactor {
    private static final Pattern SENSITIVE_HEADER = Pattern.compile(
            "(?im)^(authorization|proxy-authorization|cookie|set-cookie|x-api-key|x-auth-token|x-access-token|x-csrf-token|x-session-token|api-key|auth-token|session)\\s*:\\s*.*$");
    private static final Pattern JSON_SECRET = Pattern.compile(
            "(?i)([\\\"']?(?:password|passwd|secret|token|access_token|refresh_token|id_token|api_key|apikey|client_secret|session_id|sessionid|credential)[\\\"']?\\s*[:=]\\s*)[\\\"']?[^\\\"'&,;}\\]\\r\\n ]+[\\\"']?");
    private static final Pattern BEARER = Pattern.compile("(?i)\\b(bearer|basic|token)\\s+[A-Za-z0-9\\-._~+/=]{8,}");
    private static final Pattern JWT = Pattern.compile("\\beyJ[A-Za-z0-9_-]{5,}\\.[A-Za-z0-9_-]{5,}\\.[A-Za-z0-9_-]{5,}\\b");

    private LocalRedactor() {}

    static String redact(String value) {
        if (value == null || value.isEmpty()) return "";
        String result = SENSITIVE_HEADER.matcher(value).replaceAll("$1: [REDACTED]");
        result = JSON_SECRET.matcher(result).replaceAll("$1[REDACTED]");
        result = JWT.matcher(result).replaceAll("[REDACTED]");
        return BEARER.matcher(result).replaceAll("$1 [REDACTED]");
    }
}
