"""Operator-invoked bootstrap/recovery. Passwords are never command-line arguments."""

import argparse
import getpass
import secrets

from db import SessionLocal
from auth_methods import auth_methods
from local_auth import PASSWORD_HASHER, bootstrap, validate_password
from models import LocalCredential, LocalSession


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "reset-password"))
    parser.add_argument("--username", required=True)
    parser.add_argument(
        "--generate-password",
        action="store_true",
        help="Generate and display a password once in this terminal",
    )
    args = parser.parse_args()
    if "local" not in auth_methods():
        parser.error("Enable local in VARDRMAP_AUTH_METHODS before account setup")
    password = (
        secrets.token_urlsafe(32)
        if args.generate_password
        else getpass.getpass("Password (15–128 characters): ")
    )
    if not args.generate_password and password != getpass.getpass("Confirm password: "):
        parser.error("Passwords do not match")
    try:
        validate_password(password)
        with SessionLocal() as db:
            if args.action == "init":
                bootstrap(db, args.username, password)
            else:
                credential = (
                    db.query(LocalCredential)
                    .filter_by(username=args.username.strip().lower())
                    .with_for_update()
                    .first()
                )
                if credential is None:
                    raise ValueError("Local account not found")
                credential.password_hash = PASSWORD_HASHER.hash(password)
                (
                    credential.failed_attempts,
                    credential.last_failure_at,
                    credential.locked_until,
                ) = 0, None, None
                db.query(LocalSession).filter_by(user_id=credential.user_id).delete()
                db.commit()
    except ValueError as exc:
        parser.error(str(exc))
    print(
        "Local account initialized."
        if args.action == "init"
        else "Password reset; local browser sessions revoked."
    )
    if args.generate_password:
        print("Generated password (store securely; shown once): " + password)


if __name__ == "__main__":
    main()
