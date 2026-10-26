# Development containers

Build the backend with `docker build -t vardrmap-api:local backend`. It runs as
UID 10001 and preserves the existing wait-for-database, Alembic and Uvicorn startup
sequence. Supply DATABASE_URL, BACKEND_JWT_SECRET, ENV=production, authentication
methods and allowed origins at runtime. No database file or credentials enter the
image. Keep its port private and set FORWARDED_ALLOW_IPS to the exact proxy address
when terminating HTTPS upstream; never trust arbitrary forwarded headers.

Build the browser with:

```sh
docker build --build-arg NEXT_PUBLIC_API_URL=https://localhost:8443/backend -t vardrmap-web:local frontend
```

The build runs lint, typecheck, unit tests and the production build. The runtime
runs Next as the non-root node user. NEXT_PUBLIC_API_URL is public build-time
configuration: rebuild if the installation URL changes. Supply AUTH_SECRET,
BACKEND_JWT_SECRET and VARDRMAP_AUTH_METHODS at runtime, matching the backend. The
Dockerfiles do not change the hosted GitHub default. The VardrSec Compose example
explicitly selects local authentication and provides HTTPS and persistence.

Build contexts use allowlists to exclude local environment files, databases,
dependency caches and test artifacts. These source builds are development images;
image publication, immutable application release digests, trusted browser setup
and distribution acceptance remain separate steps. See the
[local HTTPS requirements](local-https-acceptance.md).
