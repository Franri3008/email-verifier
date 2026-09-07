import secrets
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.core.database import session
from app.core.security import (
    COOKIE,
    administrator,
    authenticate,
    digest,
    password_hash,
    password_matches,
    rate_limit,
    revoke_sessions,
    seal,
    set_session,
    unseal,
)
from app.models.persistence import Invite, Job, LoginSession, User

router = APIRouter(prefix="/api")


class EmailInput(BaseModel):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        value = value.strip().lower()
        if (
            value.count("@") != 1
            or "." not in value.split("@")[-1]
            or any(c.isspace() for c in value)
        ):
            raise ValueError("Enter a valid email address.")
        return value


class LoginInput(EmailInput):
    password: str = Field(min_length=1, max_length=128)


class AcceptInput(EmailInput):
    token: str = Field(min_length=20, max_length=128)
    password: str = Field(min_length=12, max_length=128)


class InviteInput(EmailInput):
    kind: Literal["invite", "reset"] = "invite"


class CredentialsInput(BaseModel):
    openrouter_api_key: str | None = Field(default=None, max_length=512)
    verifalia_username: str | None = Field(default=None, max_length=512)
    verifalia_password: str | None = Field(default=None, max_length=512)
    verifalia_bearer_token: str | None = Field(default=None, max_length=8192)


def public_user(user):
    return {
        "id": user.id,
        "email": user.email,
        "admin": user.admin,
        "active": user.active,
    }


@router.get("/account")
def account(user=Depends(authenticate)):
    return public_user(user)


@router.post("/auth/login")
def login(body: LoginInput, request: Request, response: Response):
    rate_limit("login-ip:" + request.client.host, 30)
    rate_limit("login-email:" + body.email, 10)
    with session() as db, db.begin():
        user = db.scalar(select(User).where(User.email == body.email))
        # Equal-cost verification for unknown email addresses.
        dummy = "00" * 16 + ":" + "00" * 64
        valid = password_matches(body.password, user.password if user else dummy)
        if not user or not user.active or not valid:
            raise HTTPException(401, "Incorrect email or password.")
        set_session(db, response, user)
        return public_user(user)


@router.post("/auth/accept")
def accept(body: AcceptInput, request: Request, response: Response):
    rate_limit("accept:" + request.client.host, 20)
    with session() as db, db.begin():
        invitation = db.execute(
            delete(Invite)
            .where(
                Invite.token == digest(body.token),
                Invite.email == body.email,
                Invite.expires > time.time(),
            )
            .returning(Invite.email, Invite.kind)
        ).first()
        if not invitation:
            raise HTTPException(
                400, "The invitation or reset link is invalid or expired."
            )
        user = db.scalar(select(User).where(User.email == body.email).with_for_update())
        if invitation.kind == "invite":
            if user:
                raise HTTPException(
                    409, "This account already exists. Sign in instead."
                )
            user = User(email=body.email, password=password_hash(body.password))
            db.add(user)
            db.flush()
        else:
            if not user or not user.active:
                raise HTTPException(400, "Account is unavailable.")
            user.password = password_hash(body.password)
            revoke_sessions(db, user.id)
        set_session(db, response, user)
        return public_user(user)


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    with session() as db, db.begin():
        db.execute(
            delete(LoginSession).where(
                LoginSession.token == digest(request.cookies.get(COOKIE, ""))
            )
        )
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/credentials")
def credential_status(user=Depends(authenticate)):
    values = unseal(user.credentials) if user.credentials else {}
    return {key: bool(values.get(key)) for key in CredentialsInput.model_fields}


@router.put("/credentials")
def credentials(body: CredentialsInput, user=Depends(authenticate)):
    with session() as db, db.begin():
        current = db.scalar(select(User).where(User.id == user.id).with_for_update())
        values = unseal(current.credentials) if current.credentials else {}
        for key, value in body.model_dump(exclude_unset=True).items():
            if value:
                values[key] = value.strip()
            else:
                values.pop(key, None)
        current.credentials = seal(values) if values else None
    return {"ok": True}


@router.delete("/credentials")
def clear_credentials(user=Depends(authenticate)):
    with session() as db, db.begin():
        db.execute(update(User).where(User.id == user.id).values(credentials=None))
    return {"ok": True}


@router.get("/admin/users")
def users(user=Depends(administrator)):
    with session() as db:
        return [
            public_user(item) for item in db.scalars(select(User).order_by(User.email))
        ]


@router.post("/admin/invites")
def invite(body: InviteInput, user=Depends(administrator)):
    token = secrets.token_urlsafe(32)
    with session() as db, db.begin():
        existing = db.scalar(select(User).where(User.email == body.email))
        if body.kind == "invite" and existing:
            raise HTTPException(409, "Account already exists.")
        if body.kind == "reset" and (not existing or not existing.active):
            raise HTTPException(404, "Active account not found.")
        db.execute(delete(Invite).where(Invite.email == body.email))
        db.add(
            Invite(
                token=digest(token),
                email=body.email,
                kind=body.kind,
                expires=time.time() + 48 * 3600,
            )
        )
    from urllib.parse import urlencode

    return {
        "url": get_settings().public_url.rstrip("/")
        + "/#"
        + urlencode({"token": token, "email": body.email, "kind": body.kind}),
        "expires_hours": 48,
    }


@router.delete("/admin/invites")
def revoke_invite(body: EmailInput, user=Depends(administrator)):
    with session() as db, db.begin():
        db.execute(delete(Invite).where(Invite.email == body.email))
    return {"ok": True}


class AccessInput(BaseModel):
    active: bool


@router.patch("/admin/users/{user_id}")
def access(user_id: str, body: AccessInput, user=Depends(administrator)):
    with session() as db, db.begin():
        target = db.get(User, user_id)
        if not target:
            raise HTTPException(404, "Account not found.")
        if target.admin:
            raise HTTPException(400, "Administrator access cannot be disabled here.")
        target.active = body.active
        if not body.active:
            revoke_sessions(db, user_id)
            db.execute(delete(Invite).where(Invite.email == target.email))
            db.execute(
                update(Job)
                .where(Job.user_id == user_id, Job.status == "queued")
                .values(status="cancelled", upload=None, payload=None)
            )
    return {"ok": True}
