# Coordinated ACL/caller build; no runtime suite or glibc migration.
FROM debian:trixie-slim@sha256:7378260c0a098d27ac206225db5e7d92b8c7c84ea7afccc86eeb513756bbd392 AS acl-callers-build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential debhelper dh-exec gettext libattr1-dev libacl1-dev libselinux1-dev libgmp3-dev libssl-dev libsystemd-dev gperf bison autoconf automake autopoint texinfo fakeroot acl attr python3 ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /build/inputs
ADD --checksum=sha256:b987ebbeb3d498794bad29cd65301b77384978493d8765c94dba8bad8fa325b6 https://deb.debian.org/debian/pool/main/a/acl/acl_2.4.0-1.dsc acl_2.4.0-1.dsc
ADD --checksum=sha256:e661131456d2708a01c614a0f400e11d7d1bfaeb6f3e74b75bb980b72f0161a3 https://deb.debian.org/debian/pool/main/a/acl/acl_2.4.0.orig.tar.xz acl_2.4.0.orig.tar.xz
ADD --checksum=sha256:65931c2fb3e821bda67f8d8d72d77e99ac61502748dcdf38b6805fe89339085e https://deb.debian.org/debian/pool/main/a/acl/acl_2.4.0-1.debian.tar.xz acl_2.4.0-1.debian.tar.xz
ADD --checksum=sha256:c3a207e3aaad165765c7a6fab89045f5fd20035fea6830b9f9ebbb92ebfbff89 https://deb.debian.org/debian/pool/main/c/coreutils/coreutils_9.7-3.dsc coreutils_9.7-3.dsc
ADD --checksum=sha256:e8bb26ad0293f9b5a1fc43fb42ba970e312c66ce92c1b0b16713d7500db251bf https://deb.debian.org/debian/pool/main/c/coreutils/coreutils_9.7.orig.tar.xz coreutils_9.7.orig.tar.xz
ADD --checksum=sha256:483f77876a080577f63da1d004cc1cf17d16df65d6925aefdd3294c6101eccfb https://deb.debian.org/debian/pool/main/c/coreutils/coreutils_9.7-3.debian.tar.xz coreutils_9.7-3.debian.tar.xz
ADD --checksum=sha256:5bb58d4966d94c99a9f1b182676089ecc05058d62fdb927f5c07539d9cda4077 https://deb.debian.org/debian/pool/main/t/tar/tar_1.35+dfsg-3.1.dsc tar_1.35+dfsg-3.1.dsc
ADD --checksum=sha256:9ae57e981c1e73c0eebc2b26c9b0c4497fe310ef1d516ea430efb5470b71f7a8 https://deb.debian.org/debian/pool/main/t/tar/tar_1.35+dfsg.orig.tar.xz tar_1.35+dfsg.orig.tar.xz
ADD --checksum=sha256:0d0278034b82ed84dce04a461879b6e1871e4cb416a0ff04d3d35ff05fc30a53 https://deb.debian.org/debian/pool/main/t/tar/tar_1.35+dfsg-3.1.debian.tar.xz tar_1.35+dfsg-3.1.debian.tar.xz
ADD --checksum=sha256:5f4f0b9b78821764fe6b88e32aef6ec519628522c211c36706bcb78d6f3f036b https://deb.debian.org/debian/pool/main/a/acl/acl_2.4.0.orig.tar.xz.asc acl_2.4.0.orig.tar.xz.asc
ADD --checksum=sha256:5070e9428bd372a7fa1f66b395b81092bb40c98f9f56a2e2bc55c47fd387e901 https://deb.debian.org/debian/pool/main/c/coreutils/coreutils_9.7.orig.tar.xz.asc coreutils_9.7.orig.tar.xz.asc
COPY acl/ /recipe/
RUN mkdir -p /out && chown -R 65534:65534 /build /out
USER 65534:65534
RUN --network=none sh /recipe/build.sh acl
USER root
RUN --network=none dpkg --install /out/packages/libacl1_*.deb /out/packages/libacl1-dev_*.deb /out/packages/acl_*.deb && apt-get check
USER 65534:65534
RUN --network=none sh /recipe/build.sh callers

FROM debian:trixie-slim@sha256:7378260c0a098d27ac206225db5e7d92b8c7c84ea7afccc86eeb513756bbd392 AS openssl-build
WORKDIR /work
ADD --checksum=sha256:a8c0d28a529ca480f9f36cf5792e2cd21984552a3c8e4aa11a24aa31aeac98e8 https://deb.debian.org/debian-security/pool/updates/main/o/openssl/openssl_3.5.7.orig.tar.gz ./
ADD --checksum=sha256:d3d082bee3f658c31db53af625eceecf29d777c7010394bed5787ebcc98abdf2 https://deb.debian.org/debian-security/pool/updates/main/o/openssl/openssl_3.5.7.orig.tar.gz.asc ./
COPY openssl/ ./
RUN echo '4f069d916c8d0ba5ad594880b52edbf082332b9c93326bbbf12949bee5893010  openssl_3.5.7-1~deb13u3+vardr2.dsc' | sha256sum -c - \
    && apt-get update && apt-get install -y --no-install-recommends build-essential dpkg-dev fakeroot debhelper libzstd-dev zlib1g-dev ca-certificates \
    && dpkg-source -x openssl_3.5.7-1~deb13u3+vardr2.dsc src \
    && useradd -m builduser && chown -R builduser:builduser /work
WORKDIR /work/src
RUN --network=none { runuser -u builduser -- dpkg-buildpackage -us -uc -B -j4 > /tmp/openssl-build.log 2>&1 || { tail -100 /tmp/openssl-build.log; exit 1; }; } \
    && mkdir -p /out/packages /out/source \
    && cp ../libssl3t64_*.deb ../openssl-provider-legacy_*.deb ../openssl_*.deb /out/packages/ \
    && cd /out/packages && sha256sum -c /work/qualified-packages.sha256 \
    && cp /work/openssl_*.dsc /work/openssl_*.tar.* /work/openssl_*.buildinfo /work/openssl_*.changes /out/source/ \
    && cp /work/qualified-packages.sha256 /out/source/ && chmod 0644 /out/source/* \
    && cd /out/source && sha256sum ./* > SHA256SUMS

FROM debian:trixie-slim@sha256:7378260c0a098d27ac206225db5e7d92b8c7c84ea7afccc86eeb513756bbd392 AS glibc-build
WORKDIR /work
ADD --checksum=sha256:f24aa441021121a79266f0d75242706cab8843a47901fefe74527491807f1998 https://deb.debian.org/debian/pool/main/g/glibc/glibc_2.41.orig.tar.xz ./
COPY glibc/ ./
RUN echo '09999489e728062c43f24b2c45f04ee66a148ca138216c609372e16bfa07c21f  glibc_2.41-12+deb13u4+vardr3.dsc' | sha256sum -c - \
    && apt-get update && apt-get install -y --no-install-recommends build-essential dpkg-dev fakeroot \
    && dpkg-source -x glibc_2.41-12+deb13u4+vardr3.dsc src \
    && apt-get build-dep -y --no-install-recommends ./src \
    && useradd -m builduser && chown -R builduser:builduser /work
WORKDIR /work/src
# Reproduce the previously tested amd64 packages; reject any byte difference.
RUN --network=none { runuser -u builduser -- env DEB_BUILD_OPTIONS=nocheck dpkg-buildpackage -us -uc -b -Pnobiarch -j4 > /tmp/glibc-build.log 2>&1 || { tail -100 /tmp/glibc-build.log; exit 1; }; } \
    && mkdir -p /out/packages /out/source \
    && cp ../libc6_*_amd64.deb ../libc-bin_*_amd64.deb ../libc-l10n_*_all.deb ../locales_*_all.deb /out/packages/ \
    && cp ../glibc_*.dsc ../glibc_*.tar.xz ../glibc_*.buildinfo ../glibc_*.changes /out/source/ \
    && cd /out/packages && sha256sum -c /work/qualified-packages.sha256 \
    && cd /out/source && sha256sum glibc_* > SHA256SUMS \
    && rm -rf /work/src /work/*.deb

FROM debian:trixie-slim@sha256:7378260c0a098d27ac206225db5e7d92b8c7c84ea7afccc86eeb513756bbd392 AS util-linux-build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential debhelper dh-exec dh-package-notes dh-sequence-installsysusers dh-debputy asciidoctor bc bison flex gettext libaudit-dev libcap-ng-dev libcrypt-dev libcryptsetup-dev libncurses-dev libpam0g-dev libreadline-dev libselinux1-dev libsqlite3-dev libsystemd-dev libtool libudev-dev netbase pkgconf po-debconf po4a socat systemd systemd-dev zlib1g-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /work
ADD --checksum=sha256:5b327ccd22f0f4ed28a389870aa51d04ecedb8693e52a1d122850f2b3188cbf6 https://deb.debian.org/debian/pool/main/u/util-linux/util-linux_2.41.5-0+deb13u1.debian.tar.xz util-linux_2.41.5-0+deb13u1.debian.tar.xz
ADD --checksum=sha256:43e9b2cbebd10fdc598c4ad10217c8202c28de53af6eafc892c8e9b5cbf3a3a5 https://deb.debian.org/debian/pool/main/u/util-linux/util-linux_2.41.5-0+deb13u1.dsc util-linux_2.41.5-0+deb13u1.dsc
ADD --checksum=sha256:f586e35d320ff537aab3ffeca37e9ecd482ccbe013590db4429a414d8aa6a728 https://deb.debian.org/debian/pool/main/u/util-linux/util-linux_2.41.5.orig.tar.xz util-linux_2.41.5.orig.tar.xz
RUN --network=none dpkg-source --no-check -x util-linux_2.41.5-0+deb13u1.dsc source
COPY util-linux/*.patch /work/source/debian/patches/
WORKDIR /work/source
RUN for p in debian/patches/vardr-*.patch; do basename "$p" >> debian/patches/series; done && dpkg-source --before-build . && { printf 'util-linux (2.41.5-0+deb13u1+vardr2) trixie; urgency=high\n\n  * Backport upstream stable 485dbb67f1b6 for CVE-2026-78408.\n\n -- VardrSec Qualification <local@invalid>  Tue, 17 Nov 2026 00:00:00 +0000\n\n'; cat debian/changelog; } > /tmp/changelog && mv /tmp/changelog debian/changelog
RUN --network=none dpkg-source --build .
ENV DEB_BUILD_OPTIONS='nocheck parallel=2'
RUN --network=none dpkg-buildpackage -us -uc -B > /work/package-build.log 2>&1 || (grep -n -i -B 4 -A 5 -E "error:|fatal|undefined|not found|No such" /work/package-build.log | head -n 100; tail -n 15 /work/package-build.log; exit 1)
RUN mkdir -p /out/packages /out/source && cp ../libmount1_*.deb ../libblkid1_*.deb ../libsmartcols1_*.deb ../libuuid1_*.deb ../liblastlog2-2_*.deb ../mount_*.deb ../util-linux_*.deb /out/packages/ && cp ../util-linux_*.dsc ../util-linux_*.tar.* ../util-linux_*.buildinfo ../util-linux_*.changes /out/source/ || (tail -n 50 /work/package-build.log; ls -l /work; exit 1)
COPY Dockerfile /out/source/Dockerfile
COPY util-linux/source.txt /out/source/util-linux-source.txt
COPY util-linux/qualified-packages.sha256 /out/source/qualified-packages.sha256
RUN cd /out/packages && sha256sum -c /out/source/qualified-packages.sha256
RUN chmod 0644 /out/source/* && cd /out/source && sha256sum ./* > SHA256SUMS

FROM scratch AS util-linux-source-delivery
COPY --from=util-linux-build /out/source/ /

FROM golang:1.27.4@sha256:08bcb99a38f85a265f9a93d1d3323e2440eec333380f3ea26ee0dec9264bb41c AS ncurses-build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential debhelper libgpm-dev pkgconf autoconf-dickey && rm -rf /var/lib/apt/lists/*
WORKDIR /build
ADD --checksum=sha256:546930a8992ae3325d8c38378f290265d969cf6333cfae9648ac6d69e1e8a8a6 https://deb.debian.org/debian/pool/main/n/ncurses/ncurses_6.5+20250216-2.debian.tar.xz ncurses_6.5+20250216-2.debian.tar.xz
ADD --checksum=sha256:00539cc2bc6bb84be1b8a8a5decf606682e14b6f39b76b9aa090e65d2c2d4580 https://deb.debian.org/debian/pool/main/n/ncurses/ncurses_6.5+20250216-2.dsc ncurses_6.5+20250216-2.dsc
ADD --checksum=sha256:b37baafa436e7133bb12a185cb8f60e1599b1947e9f0181c76f3190acf28b6eb https://deb.debian.org/debian/pool/main/n/ncurses/ncurses_6.5+20250216.orig.tar.gz ncurses_6.5+20250216.orig.tar.gz
ADD --checksum=sha256:64f4d17923322176c44079f18f170e2164a59d551d7e4e9c1a6e4eebedc5dd6f https://deb.debian.org/debian/pool/main/n/ncurses/ncurses_6.5+20250216.orig.tar.gz.asc ncurses_6.5+20250216.orig.tar.gz.asc
RUN --network=none dpkg-source --no-check -x ncurses_6.5+20250216-2.dsc source
COPY infocmp-bound.patch /build/source/debian/patches/vardr-infocmp-bound.patch
WORKDIR /build/source
RUN printf '\nvardr-infocmp-bound.patch\n' >> debian/patches/series && dpkg-source --before-build . && { printf 'ncurses (6.5+20250216-2+vardr1) trixie; urgency=high\n\n  * Bound infocmp analysis copy (CVE-2025-69720).\n\n -- VardrSec local build <local@invalid>  Wed, 11 Nov 2026 00:00:00 +0000\n\n'; cat debian/changelog; } > /tmp/changelog && mv /tmp/changelog debian/changelog
ENV DEB_BUILD_OPTIONS='nocheck parallel=2'
ENV DEB_BUILD_PROFILES='nobiarch'
RUN --network=none dpkg-buildpackage -us -uc -B > /build/package-build.log 2>&1 || (tail -n 70 /build/package-build.log; exit 1)
RUN mkdir -p /out/packages /out/source && cp ../ncurses-bin_*.deb /out/packages/ && debian/rules clean >> /build/package-build.log 2>&1 && dpkg-source --build . >> /build/package-build.log 2>&1 && cp ../ncurses_*.dsc ../ncurses_*.tar.* ../ncurses_*.buildinfo ../ncurses_*.changes /out/source/
COPY Dockerfile /out/source/Dockerfile
COPY ncurses-source.txt /out/source/ncurses-source.txt
RUN chmod 0644 /out/source/* && cd /out/source && sha256sum ./* > SHA256SUMS

FROM scratch AS ncurses-source-delivery
COPY --from=ncurses-build /out/source/ /

# Rebuild the fixed SQLite source on Trixie; build tools are discarded.
FROM golang:1.27.4@sha256:08bcb99a38f85a265f9a93d1d3323e2440eec333380f3ea26ee0dec9264bb41c AS sqlite-build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential debhelper autoconf libtool automake pkgconf chrpath lynx \
    libreadline-dev tcl8.6-dev tcl9.0-dev libtommath-dev libicu-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
ADD --checksum=sha256:d3b2efbeb509dfac38a0653112a400d48eaa86f14432c255a6fea8569df407f1 https://snapshot.debian.org/file/adad8188a1de9f6403ff70b3e41ea62465d3ae22 sqlite3_3.54.1-1.dsc
ADD --checksum=sha256:67906ee141109bebe43cdcf197892806397dabc79f5cd7f05f1278f47b0c5e25 https://snapshot.debian.org/file/8bc602b0433a4cc92fe095627afe1c89e1335cb5 sqlite3_3.54.1.orig-www.tar.xz
ADD --checksum=sha256:faeff7682200b3dd58c8f0f229892a7271c73c1fdabc86e7315eb31eb7cb6e83 https://snapshot.debian.org/file/c49acf244fe87e12aa11698a792dd6090c1b4eb9 sqlite3_3.54.1.orig.tar.xz
ADD --checksum=sha256:3f05602b0f4e1441b88f92e9afb2980e148659842565b1f1e27012988433a1d9 https://snapshot.debian.org/file/a8d6dc71abece0bd8f04fc52c793728ef7340a4d sqlite3_3.54.1-1.debian.tar.xz
RUN --network=none dpkg-source --no-check -x sqlite3_3.54.1-1.dsc source
WORKDIR /build/source
RUN sed -i 's/tcl9.1-dev/tcl9.0-dev/' debian/control \
    && sed -i 's/TCLV_SECONDARY = 9.1/TCLV_SECONDARY = 9.0/' debian/rules \
    && { printf 'sqlite3 (3.54.1-1+vardr1) trixie; urgency=high\n\n  * Rebuild the upstream security release with Trixie Tcl 9.0.\n\n -- VardrSec local build <local@invalid>  Wed, 11 Nov 2026 00:00:00 +0000\n\n'; cat debian/changelog; } > /tmp/changelog \
    && mv /tmp/changelog debian/changelog
ENV DEB_BUILD_OPTIONS='nocheck parallel=2'
RUN --network=none mkdir -p /out/packages /out/source \
    && (dpkg-buildpackage -us -uc -B > /tmp/package-build.log 2>&1 || (tail -n 75 /tmp/package-build.log; exit 1)) \
    && cp ../libsqlite3-0_*.deb /out/packages/ \
    && debian/rules clean >> /tmp/package-build.log 2>&1 \
    && dpkg-source --build . >> /tmp/package-build.log 2>&1 \
    && cp ../sqlite3_*.dsc ../sqlite3_*.tar.xz ../sqlite3_*.buildinfo ../sqlite3_*.changes /out/source/
COPY Dockerfile /out/source/Dockerfile
COPY sqlite-source.txt /out/source/sqlite-source.txt
RUN chmod 0644 /out/source/* && cd /out/source && sha256sum ./* > SHA256SUMS

FROM scratch AS sqlite-source-delivery
COPY --from=sqlite-build /out/source/ /

FROM node:24-trixie-slim@sha256:43b9ba1142b8dcf33fa8f922ca1be85714adc444e0586c7cf7726daaeabc1bea AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_VARDRMAP_REVISION
ENV NEXT_PUBLIC_VARDRMAP_REVISION=$NEXT_PUBLIC_VARDRMAP_REVISION
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN test -n "$NEXT_PUBLIC_API_URL" \
    && npm run lint && npm run typecheck && npm test -- --runInBand \
    && npm run build && npm prune --omit=dev

FROM node:24-trixie-slim@sha256:43b9ba1142b8dcf33fa8f922ca1be85714adc444e0586c7cf7726daaeabc1bea

# Target reviewed Trixie security fixes without changing the base or suite.
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade apt libapt-pkg7.0 zlib1g \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' apt)" ge 3.0.4 \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' libapt-pkg7.0)" ge 3.0.4 \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' zlib1g)" ge '1:1.3.dfsg+really1.3.1-1+deb13u1' \
    && rm -rf /var/lib/apt/lists/*
COPY --from=acl-callers-build /out/runtime/ /tmp/acl-security/
RUN --network=none dpkg --install /tmp/acl-security/libacl1_*.deb \
    && dpkg --install /tmp/acl-security/coreutils_*.deb /tmp/acl-security/tar_*.deb \
    && apt-get check && rm -rf /tmp/acl-security
COPY --from=acl-callers-build /out/source/ /usr/share/doc/libacl1/vardr-source/
# Public corresponding sources must remain readable by the non-root runtime user.
RUN find /usr/share/doc/libacl1/vardr-source -type d -exec chmod 0755 {} + \
    && find /usr/share/doc/libacl1/vardr-source -type f -exec chmod 0644 {} +
COPY --from=sqlite-build /out/packages/ /tmp/sqlite-security/
RUN --network=none dpkg --install /tmp/sqlite-security/*.deb \
    && apt-get check && rm -rf /tmp/sqlite-security
COPY --from=sqlite-build /out/source/ /usr/share/doc/libsqlite3-0/vardr-source/
COPY --from=ncurses-build /out/packages/ /tmp/ncurses-security/
RUN --network=none dpkg --install /tmp/ncurses-security/*.deb \
    && apt-get check && rm -rf /tmp/ncurses-security
COPY --from=ncurses-build /out/source/ /usr/share/doc/ncurses-bin/vardr-source/
COPY --from=glibc-build /out/packages/libc6_*_amd64.deb /out/packages/libc-bin_*_amd64.deb /tmp/glibc-security/
RUN --network=none dpkg -i /tmp/glibc-security/*.deb && apt-get check && rm -rf /tmp/glibc-security
COPY --from=glibc-build /out/source/ /usr/share/doc/libc6/vardr-source/
COPY --from=util-linux-build /out/packages/ /tmp/util-linux-security/
RUN --network=none dpkg --install /tmp/util-linux-security/lib*.deb \
    && dpkg --install /tmp/util-linux-security/mount_*.deb /tmp/util-linux-security/util-linux_*.deb \
    && apt-get check && rm -rf /tmp/util-linux-security
COPY --from=util-linux-build /out/source/ /usr/share/doc/util-linux/vardr-source/
COPY --from=openssl-build /out/packages/libssl3t64_*.deb /out/packages/openssl-provider-legacy_*.deb /tmp/openssl-security/
RUN --network=none dpkg --install /tmp/openssl-security/*.deb && apt-get check && rm -rf /tmp/openssl-security
COPY --from=openssl-build /out/source/ /usr/share/doc/libssl3t64/vardr-source/
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build --chown=node:node /app/package.json /app/package-lock.json ./
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/.next ./.next
COPY --from=build --chown=node:node /app/public ./public
COPY --from=build /app/LICENSE /usr/share/licenses/vardrmap/LICENSE
# Startup uses node directly; package-manager dependencies are build-only.
RUN rm -rf /usr/local/lib/node_modules/npm \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx
USER node
EXPOSE 3000
CMD ["node", "node_modules/next/dist/bin/next", "start", "--hostname", "0.0.0.0"]
