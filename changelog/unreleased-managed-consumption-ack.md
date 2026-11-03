Add the unregistered one-shot managed consumption ACK transaction. Validate current
owned permission and exact signed-contract hash; conditionally consume once, reject
replays, and roll back delayed/failed writes. Do not renew leases, release charges,
complete jobs or register production routes. Add SQLite and PostgreSQL race tests
and authenticated JSON/Runner parser conformance fixtures.

Keep the PostgreSQL bootstrap rollback test's refusal assertion case-insensitive
so later retained-state migrations can refuse downgrade with the same message.
Its data/schema retention checks and the runtime refusal remain unchanged.
