# Identity preflight for API assessments

An optional `preflight` on an authenticated identity checks a reviewed session
endpoint before Gate sends any authorization requests. A response must match
the declared 2xx status and every declared principal field. This catches stale
credentials and credentials for the wrong account or tenant without mistaking
their denials for a resource authorization defect.

In the case builder's JSON editor, add this to an authenticated identity:

```json
{
  "id": "owner",
  "credential": {"type": "bearer", "value_env": "OWNER_TOKEN"},
  "preflight": {
    "url": "https://api.example.test/session",
    "expected_status": 200,
    "json_fields": {"user.id": "reviewed-owner-id", "user.tenant_id": "tenant-a"}
  }
}
```

Use the actual known-good endpoint and stable public principal metadata. Review
the expected subject, tenant and role yourself; the platform does not infer them.
Never put a token, password or secret in `json_fields`, URLs or other stored case
fields. Credentials still use local `value_env` or `value_keychain` references.
Anonymous identities have no preflight. Add checks to every authenticated
identity whose validity the case depends on, including expected-deny callers.

The check always uses GET, the identity's credential and the normal bounded Gate
HTTP client. It carries none of the authorization request's headers, body, query
parameters or CORS probe configuration. Its absolute HTTP(S) URL must have the
same scheme, hostname and effective port as the request under test; userinfo,
fragments and variable references in the preflight URL are rejected. Default
ports count as the same origin. Private-target access remains a local opt-in;
redirects are observed without following them. Scope/window warnings remain advisory.

`json_fields` holds 1–8 case-sensitive dotted paths and nonempty expected strings
(at most 200 UTF-8 bytes per path/value). JSON string, number and boolean scalars
are compared to those strings exactly; arrays, objects, nulls, missing fields,
HTML and malformed JSON fail. Numbers retain their decimal text without floating
point rounding. The identity id is limited to 200 UTF-8 bytes for this feature.

Gate runs existing reviewed setup steps first, then all configured session checks
once, then the authorization request once per identity. Any failed session check
stops the whole case: no authorization requests, no findings. Setup may already
have spent traffic or mutated an object, so this is not a zero-traffic dry run.
Gate's CLI writes safe diagnostics and exits 3. Runner uploads that artifact and
marks the job failed, including after recoverable interruptions.

Map displays the separate session result and retains evidence bound to the job,
case snapshot and identity. Preflight evidence has `phase: identity_preflight`
in its body; expected/observed resource decisions stay unknown. No session body,
cookies, headers, matched field values or raw network errors are retained. A
passed preflight does not count as an authorization execution or legitimate
resource baseline. Missing, duplicate, unbound or failed required preflights keep
the assessment inconclusive even if other uploaded rows claim success.

Diagnostics distinguish `credential_rejected` (401/403), `identity_mismatch`,
`unexpected_status` and `execution_error`. They do not guess whether rejection
means expiry, revocation or another authentication rule. Restore the intended
credentials locally, review the case and queue a new job. No retries, automatic
login/refresh or background session keeper are added. A successful check is a
point-in-time observation; credentials can expire afterwards.

Deploy the matching Map backend, upgrade Gate and Runner, then author cases with
preflight. New Runner passes `--require-identity-preflight`, which older Gate
binaries reject before contacting a target. Older Runner versions cannot provide
that guard; upgrade them before enabling these cases. Map accepts legacy uploads
but a case declaring preflight cannot become conclusive without its bound results.
Cases without preflight retain existing behavior, and old assessments remain unchanged.

The disposable three-repository acceptance fixture exercises valid/rejected
sessions, wrong principals, login HTML and redirects with real HTTP, retained
evidence and job state. It requires no hosted account or production data. See
[local acceptance](../scripts/integration/README.md).
