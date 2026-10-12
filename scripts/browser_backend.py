"""Disposable loopback backend for browser acceptance; no production auth changes."""

import os
from pathlib import Path
import sys
import tempfile


def main() -> None:
    import uvicorn

    with tempfile.TemporaryDirectory(prefix="vardrmap-browser-") as scratch:
        # Do not inherit a developer's database, OAuth secret or provider keys.
        os.environ.update({
            "ENV": "test",
            "DATABASE_URL": "sqlite:///" + str(Path(scratch) / "browser.db"),
            "BACKEND_JWT_SECRET": "browser-fixture-signing-key-only-32-characters",
            "ALLOWED_ORIGINS": "http://127.0.0.1:3006",
        })
        os.environ.pop("ANTHROPIC_API_KEY", None)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        uvicorn.run("main:app", host="127.0.0.1", port=8765, log_level="warning")


if __name__ == "__main__":
    main()
