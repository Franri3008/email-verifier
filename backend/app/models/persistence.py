import time
from uuid import uuid4

from sqlalchemy import Boolean, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def uid():
    return uuid4().hex


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password: Mapped[str] = mapped_column(Text)
    admin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    credentials: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class LoginSession(Base):
    __tablename__ = "sessions"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires: Mapped[float] = mapped_column(Float, index=True)


class Invite(Base):
    __tablename__ = "invites"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="invite")
    expires: Mapped[float] = mapped_column(Float)


class RateBucket(Base):
    __tablename__ = "rate_buckets"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    expires: Mapped[float] = mapped_column(Float, index=True)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    created: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    updated: Mapped[float] = mapped_column(Float, default=time.time)
    expires: Mapped[float] = mapped_column(Float, index=True)
    filename: Mapped[str] = mapped_column(String(255), default="")
    payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    upload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    result: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    download: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
