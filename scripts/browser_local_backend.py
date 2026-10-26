"""Disposable HTTPS acceptance fixture; never connects to an installed platform."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main() -> None:
    import uvicorn

    root = Path(__file__).resolve().parents[1]
    certificates = root / "frontend" / ".local-auth-e2e"
    certificates.mkdir(exist_ok=True)
    certificates.chmod(0o700)
    openssl = shutil.which("openssl")
    if openssl is None and os.name == "nt":
        candidate = Path("C:/Program Files/Git/mingw64/bin/openssl.exe")
        openssl = str(candidate) if candidate.is_file() else None
    if openssl is None:
        raise RuntimeError("HTTPS browser acceptance requires OpenSSL")
    key, certificate = certificates / "key.pem", certificates / "cert.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
        ],
        check=True,
        capture_output=True,
    )
    key.chmod(0o600)
    try:
        with tempfile.TemporaryDirectory(
            prefix="vardrmap-local-browser-", dir=certificates
        ) as scratch:
            os.environ.update(
                {
                    "ENV": "test",
                    "DATABASE_URL": "sqlite:///" + str(Path(scratch) / "browser.db"),
                    "BACKEND_JWT_SECRET": "browser-fixture-signing-key-only-32-characters",
                    "ALLOWED_ORIGINS": "https://127.0.0.1:3007",
                    "VARDRMAP_AUTH_METHODS": "github,local",
                    "ANTHROPIC_API_KEY": "",
                    "SENTRY_DSN": "",
                }
            )
            sys.path.insert(0, str(root / "backend"))
            from main import app
            from db import SessionLocal, engine
            from local_auth import bootstrap

            with SessionLocal() as db:
                bootstrap(db, "operator", "local-browser-fixture-passphrase")
            try:
                uvicorn.run(
                    app,
                    host="127.0.0.1",
                    port=8766,
                    ssl_keyfile=str(key),
                    ssl_certfile=str(certificate),
                    log_level="warning",
                )
            finally:
                engine.dispose()
    finally:
        key.unlink(missing_ok=True)
        certificate.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
