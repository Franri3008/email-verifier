from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def engine():
    url = get_settings().database_url
    if url.startswith(("postgres://", "postgresql://")):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
    kwargs = (
        {"connect_args": {"check_same_thread": False}}
        if url.startswith("sqlite:")
        else {}
    )
    return create_engine(url, pool_pre_ping=True, **kwargs)


def session():
    return sessionmaker(bind=engine(), expire_on_commit=False)()


def initialize():
    from app.models import persistence  # noqa: F401

    # Initial schema is additive and serialized for concurrent Railway starts.
    with engine().begin() as connection:
        if connection.dialect.name == "postgresql":
            from sqlalchemy import text

            connection.execute(text("SELECT pg_advisory_xact_lock(71384921)"))
        Base.metadata.create_all(connection)
