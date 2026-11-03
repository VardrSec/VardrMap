# ADR 0006 — Small Map-local v1 crypto wire boundary

Owner-authorized local implementation and isolated synthetic verification,
2026-11-02. This first increment is unregistered; it grants no executable queue
permission by itself.

Keep HTTP-only component independence. Map verifies a separately operator-signed
approval, using enrolled issuer/key/owner public-key tuples, and signs only
server-constructed execution-contract fields. Approval private keys stay outside
Map/agents/workers. Map has no approval-signing or arbitrary-payload signing API.
The contract key must differ in both key identifier and public material from every
operator approval key. Explicit revocation denies verification.

Use the maintained cryptography package, declared at 50.0.2, fixed Ed25519,
approved v1 domain/purpose separation and canonical ASCII JSON. Bound document
size/depth and base64 decoding before allocation; reject unknown envelope/payload
fields, duplicates and nonfinite numbers. Approval context must exactly equal
the trusted projection. Float exponent overflow is rejected explicitly, including
nested positive/negative overflow; rejecting only NaN/Infinity literals is insufficient.
Approval context includes
plan, authority/scope, grants, limits,
count and validity. Ordinary API credentials cannot originate such a receipt.

The wire helper is deliberately not a second plan/scope policy validator. Future
transactional issuance must authenticate the real principal/Runner enrollment,
recompute the current authority projection and obtain monotonic ordinal/fence
ownership before invoking it. Runner alone reconstructs the full actual plan and
validates execution policy. No direct imports, shared-service extraction or sidecar.

Identical public synthetic vectors live in both repositories. Map verifies and
reproduces the exact signed contract bytes; Runner's existing validator and ledger
consume that contract once. This is conformance, not actual managed control,
request dispatch, PostgreSQL race proof or NM-2 acceptance.

Tests use disposable databases and synthetic keys only. Crypto 50.0.2 is read from
existing Runner test dependencies in an isolated Map test process; no retained
package installation is changed. Child environments allow only required OS/tool
variables and synthetic settings, with dotenv file discovery disabled. Private
raw failed logs are excluded from distributable evidence; sanitized summaries
retain honest failure provenance. No production key/trust/enrollment is provisioned.

Rollback removes this unregistered adapter/dependency and its fixtures; existing
engagement behavior/data is unchanged. No migration or default HTTP path exists
in this increment. Do not enable signing or managed execution by assumption.
