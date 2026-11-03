# NM-2 read-only observation HTTP composition

Add an explicit router factory around the existing observation service. It is
unregistered in production and returns no capability or execution permission.
Reuse actual API-key enrollment/ownership and immutable receipt checks; bound
strict JSON bodies and body-read wait, return fixed non-cacheable errors. Synthetic
ASGI/TLS verification only; no key provisioning, migrations, worker or activation.
See ADR 0012. The canonical Docker Desktop worker exit and review gates stay open.
