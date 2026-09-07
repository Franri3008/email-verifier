import hashlib
import hmac
import json
import logging
import os
import secrets
import time

from cryptography.fernet import Fernet
from fastapi import HTTPException, Request
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.database import session
from app.models.persistence import LoginSession, RateBucket, User

COOKIE = "email_checker_session"


def cipher():
    return Fernet(get_settings().encryption_key.encode())


def seal(value):
    return cipher().encrypt(json.dumps(value).encode())


def unseal(value):
    return json.loads(cipher().decrypt(value))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password):
    salt = os.urandom(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + key.hex()


def password_matches(password, encoded):
    salt, expected = encoded.split(":")
    key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(key.hex(), expected)


def authenticate(request: Request):
    token = request.cookies.get(COOKIE, "")
    with session() as db:
        record = db.get(LoginSession, digest(token))
        user = (
            db.get(User, record.user_id)
            if record and record.expires > time.time()
            else None
        )
        if not user or not user.active:
            raise HTTPException(401, "Please sign in.")
        return user


def administrator(request: Request):
    user = authenticate(request)
    if not user.admin:
        raise HTTPException(403, "Administrator access required.")
    return user


def set_session(db, response, user):
    token = secrets.token_urlsafe(32)
    seconds = get_settings().session_hours * 3600
    db.add(
        LoginSession(
            token=digest(token), user_id=user.id, expires=time.time() + seconds
        )
    )
    response.set_cookie(
        COOKIE,
        token,
        max_age=seconds,
        httponly=True,
        secure=get_settings().secure_cookies,
        samesite="strict",
        path="/",
    )


def bootstrap_admin():
    """Create the first administrator from the environment.

    Hosts without shell access cannot run `python -m app.manage admin`, so the
    account is seeded at startup instead. It never overwrites an existing user,
    so leaving the variables set is harmless.
    """
    settings = get_settings()
    email = (settings.initial_admin_email or "").strip().lower()
    password = settings.initial_admin_password or ""
    if not email and not password:
        return
    if "@" not in email or not 12 <= len(password) <= 128:
        raise RuntimeError(
            "INITIAL_ADMIN_EMAIL must be an email address and "
            "INITIAL_ADMIN_PASSWORD must be 12-128 characters."
        )
    with session() as db, db.begin():
        if db.scalar(select(User).where(User.email == email)):
            return
        db.add(User(email=email, password=password_hash(password), admin=True))
    logging.getLogger(__name__).info("Seeded the initial administrator account.")


def rate_limit(key, limit=10, seconds=900):
    # Atomic database counter, shared across web instances.
    now = time.time()
    bucket_key = digest(f"{key}:{int(now // seconds)}")
    with session() as db, db.begin():
        dialect = db.bind.dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        db.execute(
            insert(RateBucket)
            .values(key=bucket_key, count=0, expires=now + seconds)
            .on_conflict_do_nothing(index_elements=["key"])
        )
        from sqlalchemy import update

        count = db.execute(
            update(RateBucket)
            .where(RateBucket.key == bucket_key)
            .values(count=RateBucket.count + 1)
            .returning(RateBucket.count)
        ).scalar_one()
    if count > limit:
        raise HTTPException(429, "Too many requests. Please try again later.")


def revoke_sessions(db, user_id):
    db.execute(delete(LoginSession).where(LoginSession.user_id == user_id))


def user_settings(user_id):
    with session() as db:
        user = db.get(User, user_id)
        if not user or not user.active:
            raise ValueError("Account is disabled.")
        credentials = unseal(user.credentials) if user.credentials else {}
    # Explicitly clear every global provider secret: no shared credit fallback.
    cleared = dict(
        openrouter_api_key=None,
        verifalia_username=None,
        verifalia_password=None,
        verifalia_bearer_token=None,
    )
    return get_settings().model_copy(update=cleared | credentials)
