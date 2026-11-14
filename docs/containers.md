# Development containers

For an operator installation, use the distribution’s
[Full setup](https://github.com/VardrSec/VardrSec/blob/main/docs/installation.md),
which selects compatible component pins and manages PostgreSQL, HTTPS and state.
For CLI-only use without Map, choose
[Mapless](https://github.com/VardrSec/VardrSec/blob/main/docs/mapless.md).
The image-build instructions here are for component development, not a second
installation path.

The backend Python 3.12 and frontend Node 24 bases use reviewed Debian Trixie
digests. The API and final web runtime upgrade only apt/libapt and zlib from the
existing signed Trixie repositories, refusing versions below the reviewed
security floors (apt/libapt 3.0.4 and zlib 1:1.3.dfsg+really1.3.1-1+deb13u1).
Base-image identity is pinned; dependency resolution and application release
publication remain separate concerns. Native development commands are
unchanged. The web runtime removes npm/npx and their global dependency tree;
Next starts through Node directly. Use the build stage or native checkout for
package-manager operations, rather than changing a retained runtime container.

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
[local HTTPS requirements](local-authentication.md).

Package security references: [Debian apt status](https://security-tracker.debian.org/tracker/source-package/apt)
and [zlib DSA-6613-1](https://lists.debian.org/debian-security-announce/2026/msg00532.html).
Rebuilt image reports must verify the correction; this does not clear other findings.

## Source access

The sign-in screen and Settings offer a public source link. Supply the actual
40-character Git commit through the `NEXT_PUBLIC_VARDRMAP_REVISION` build argument
to point to that exact revision. Without valid revision metadata, the link is
explicitly labeled as the source repository. Source access alone does not
establish complete corresponding-source delivery or transitive license review.

## License files

Both build contexts include an unchanged copy of the repository's AGPL-3.0
license. The backend retains it at `/app/LICENSE`; the frontend runtime retains
it at `/usr/share/licenses/vardrmap/LICENSE`. Retaining the license text does
not replace applicable corresponding-source and dependency-notice obligations.
