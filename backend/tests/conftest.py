# ruff: noqa: E402
from collections.abc import Iterator
import os
import tempfile

from cryptography.fernet import Fernet

# Never read developer credentials or connect to their database during tests.
_test_dir = tempfile.TemporaryDirectory(prefix="email-checker-tests-")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "sqlite:///" + _test_dir.name + "/test.db"
)
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["PRODUCTION"] = "false"
os.environ["SECURE_COOKIES"] = "false"
os.environ["PUBLIC_URL"] = "http://localhost:3000"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000,http://127.0.0.1:3000"
# Tests claim and run jobs explicitly; a live in-process worker would race them.
os.environ["RUN_WORKER"] = "false"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import Base, engine, initialize, session
from app.models.persistence import User
from app.core.security import password_hash


@pytest.fixture(autouse=True)
def database():
    initialize()
    with engine().begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())
    with session() as db, db.begin():
        db.add(
            User(
                id="admin",
                email="admin@example.org",
                password=password_hash("correct password 123"),
                admin=True,
            )
        )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        test_client.headers.update(
            {"Origin": "http://localhost:3000", "X-Requested-With": "email-checker"}
        )
        yield test_client


@pytest.fixture
def signed_in(client):
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "admin@example.org", "password": "correct password 123"},
        ).status_code
        == 200
    )
    return client
