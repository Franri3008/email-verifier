"""Administrative operations; run from backend with python -m app.manage."""

import argparse
import getpass

from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.database import initialize, session
from app.core.security import cipher, password_hash, revoke_sessions
from app.models.persistence import User


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["key", "init-db", "admin", "reset-password", "import-credentials"],
    )
    parser.add_argument("--email")
    args = parser.parse_args()
    if args.command == "key":
        print(Fernet.generate_key().decode())
        return
    cipher()
    initialize()
    if args.command == "init-db":
        return
    if not args.email or "@" not in args.email:
        parser.error("--email is required")
    if args.command == "import-credentials":
        from dotenv import dotenv_values
        from app.core.config import ROOT_DIR
        from app.core.security import seal

        legacy = ROOT_DIR / ".env.legacy"
        if not legacy.exists():
            parser.error("No .env.legacy file exists.")
        values = dotenv_values(legacy)
        fields = [
            "openrouter_api_key",
            "verifalia_username",
            "verifalia_password",
            "verifalia_bearer_token",
        ]
        credentials = {
            field: values[field.upper()]
            for field in fields
            if values.get(field.upper())
        }
        with session() as db, db.begin():
            user = db.scalar(
                select(User).where(User.email == args.email.strip().lower())
            )
            if not user or user.credentials:
                parser.error(
                    "Create the account first; import only supports accounts with no saved credentials."
                )
            user.credentials = seal(credentials)
        return
    password = getpass.getpass("Password (at least 12 characters): ")
    if (
        len(password) < 12
        or len(password) > 128
        or password != getpass.getpass("Confirm password: ")
    ):
        parser.error("Passwords must match and be 12–128 characters.")
    with session() as db, db.begin():
        user = db.scalar(select(User).where(User.email == args.email.strip().lower()))
        if args.command == "admin":
            if user:
                parser.error("Account already exists; use reset-password if needed.")
            db.add(
                User(
                    email=args.email.strip().lower(),
                    password=password_hash(password),
                    admin=True,
                )
            )
        else:
            if not user:
                parser.error("Account does not exist.")
            user.password = password_hash(password)
            revoke_sessions(db, user.id)


if __name__ == "__main__":
    main()
