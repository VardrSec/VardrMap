# Runtime source notices

## SQLite source delivery

The runtime image rebuilds Debian SQLite 3.54.1 source with Trixie's build-only
Tcl 9.0 dependency. Upstream executable source, the legacy `libsqlite3.so.0`
SONAME and Debian feature flags are retained. No unstable repository/binary
package is installed. Only `libsqlite3-0` enters the runtime; its only runtime
dependency is libc6. Existing application roles and privileges are unchanged.

`/usr/share/doc/libsqlite3-0/vardr-source/` contains original and modified Debian
source, build metadata, the image recipe, provenance and `SHA256SUMS`. Existing
package copyright remains installed. The four upstream inputs are hash-pinned
to Debian's immutable snapshot. This covers SQLite, not every image component.
A `sqlite-source-delivery` build target exports the same materials separately.

From the Map checkout, export either recipe's SQLite sources to a new directory
outside the checkout:

```text
docker build --target sqlite-source-delivery --output type=local,dest=../api-sqlite-source -f backend/Dockerfile backend
docker build --target sqlite-source-delivery --output type=local,dest=../web-sqlite-source -f frontend/Dockerfile frontend
```

These commands build only the source-delivery target. Existing source links,
application licenses and other dependency notice obligations remain in effect.

## ncurses source delivery

The image backports the upstream `infocmp` analysis-copy bound for
CVE-2025-69720 to Debian's existing Trixie source. Only `ncurses-bin` is
installed; the existing ncurses and libtinfo libraries remain unchanged.
Original/modified Debian source, the patch, build metadata and checksums are
retained in `/usr/share/doc/ncurses-bin/vardr-source/`. The
`ncurses-source-delivery` build target exports the same source materials.
No unstable binary packages or repositories are introduced. A custom package
version does not itself resolve version-based scanner findings.

## util-linux source delivery

The image rebuilds the existing Trixie util-linux source with the remaining
upstream stable mount-hook, source-resolution and descriptor-close-on-exec
security changes. Existing Debian patches are retained; upstream's missing
header and corrected symlink-resolution flag are included. Runtime ABI and
feature configuration remain unchanged. `mount`, `util-linux` and their five
exact-version sibling libraries are replaced together, preserving Debian
dependency constraints. Other build products remain in the builder.

`/usr/share/doc/util-linux/vardr-source/` retains original/modified Debian
source, patch identities, build metadata, recipe and checksums. Existing
package copyright remains installed. The `util-linux-source-delivery` build
target exports the same materials. A custom package version does not itself
clear vulnerability findings.
