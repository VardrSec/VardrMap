# ADR 0008 — Retained one-shot managed consumption acknowledgement

Status: unregistered local prototype; independent acceptance remains open.

`Issuer.consume` shares the current-authority transaction and existing ownership,
principal, Runner, origin, capability and contract/attempt/fence validation. It
checks the exact canonical signed-contract envelope SHA-256 and performs a
conditional `consumed=false` update on the retained `ManagedContract`. Only one
caller can receive an ACK, including independent connections. Replays are refused;
an identical retry is not granted new launch permission. Existing schema and
migration history already retain this bit; no new migration is needed.

The exact ACK fields are schema `vardr.managed-consumption/1`, literal
`consumed=true`, job/Runner/origin, contract/attempt/fence, authority revision/hash
and contract hash. The final trusted clock, approval and live-lease checks occur
after the write so delayed or failed writes roll back consumption. The operation
renews no lease and releases no reservation, target charge, duration or approval
ordinal. Runner reserves locally and journals intent before its single request;
unknown replies remain held without retry or automatic reconciliation.

No production route is registered. Test-only ASGI, real loopback TLS and Windows/TLS entry adapters
exercise this operation, with synthetic keys and disposable data only. Neither ACK
nor successful local execution uploads evidence, completes a job, proves process
termination or releases capacity. Managed evidence/completion, reviewed
reconciliation, real Windows containment, exact-candidate CI and independent
review remain separate gates. No exactly-once physical execution is claimed.
