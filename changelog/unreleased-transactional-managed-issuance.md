# Unreleased — Transactional managed issuance prototype

Add retained approval/contract/association/clock state (`0036managedauth`) with
existing owned claim and budget transactions, exact signed snapshot binding,
current principal checks and global one-shot ordinal/fence ownership. Lock and
revision changes close authority/scope/key-revocation and stale-cache races.
Trusted expiry survives denials and lock delays.

Explicit required jobs refuse legacy execution even while approval is missing;
required pipelines are unsupported. Ordinary jobs remain unchanged. The issuer
is unregistered, provisions no real keys/enrollment and enables no managed queue
execution. Do not roll back to an unaware backend with marked work reachable.
See [ADR 0007](../docs/adr/0007-transactional-managed-issuance.md).
