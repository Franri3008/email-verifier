"""Create local configuration without printing keys or overwriting existing files."""

import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]


def create(path, content):
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"Kept existing {path.relative_to(ROOT)}")
        return
    with os.fdopen(descriptor, "w") as handle:
        handle.write(content)
    print(f"Created {path.relative_to(ROOT)}")


if __name__ == "__main__":
    create(
        ROOT / ".env",
        "\n".join(
            [
                "DATABASE_URL=sqlite:///./email_checker.db",
                "ENCRYPTION_KEY=" + Fernet.generate_key().decode(),
                "LOCAL_DATABASE_PASSWORD=" + secrets.token_hex(24),
                "PUBLIC_URL=http://localhost:3000",
                "ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000",
                "SECURE_COOKIES=false",
                "PRODUCTION=false",
                "",
            ]
        ),
    )
    create(
        ROOT / "frontend" / ".env.local", "NEXT_PUBLIC_API_URL=http://localhost:8000\n"
    )
