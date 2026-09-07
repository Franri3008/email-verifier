import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import session
from app.core.security import bootstrap_admin, password_matches
from app.models.persistence import User

LONG_ENOUGH = "a-long-enough-password"


@pytest.fixture
def configure(monkeypatch):
    """Build settings from environment values without poisoning the global cache."""

    def apply(**values):
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        settings = get_settings()
        monkeypatch.setattr("app.core.security.get_settings", lambda: settings)

    yield apply
    get_settings.cache_clear()


def users():
    with session() as db:
        return list(db.scalars(select(User)))


def test_seeds_an_administrator_from_the_environment(configure):
    configure(
        INITIAL_ADMIN_EMAIL="Owner@Example.org", INITIAL_ADMIN_PASSWORD=LONG_ENOUGH
    )
    bootstrap_admin()

    seeded = next(user for user in users() if user.email == "owner@example.org")
    assert seeded.admin
    assert password_matches(LONG_ENOUGH, seeded.password)


def test_never_overwrites_an_existing_account(configure):
    configure(
        INITIAL_ADMIN_EMAIL="admin@example.org", INITIAL_ADMIN_PASSWORD=LONG_ENOUGH
    )
    before = users()[0].password

    bootstrap_admin()

    remaining = users()
    assert [user.email for user in remaining] == ["admin@example.org"]
    assert remaining[0].password == before


def test_does_nothing_when_unset(configure):
    configure()
    bootstrap_admin()

    assert [user.email for user in users()] == ["admin@example.org"]


@pytest.mark.parametrize(
    "email,password",
    [("not-an-email", LONG_ENOUGH), ("owner@example.org", "too-short")],
)
def test_refuses_unusable_values(configure, email, password):
    configure(INITIAL_ADMIN_EMAIL=email, INITIAL_ADMIN_PASSWORD=password)
    with pytest.raises(RuntimeError):
        bootstrap_admin()

    assert [user.email for user in users()] == ["admin@example.org"]
