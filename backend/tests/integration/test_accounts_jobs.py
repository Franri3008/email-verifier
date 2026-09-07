import asyncio
import time
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.core.database import session
from app.core.security import cipher, digest, seal, user_settings
from app.main import app
from app.models.persistence import Invite, Job, User
from app.worker import cleanup, run_once
from app.worker import claim
from app.models.schemas.verification import Candidate, VerificationResult
from app.services.openrouter_service import OpenRouterService
from app.services.verifalia_service import VerifaliaService


def invite_user(admin, email="person@example.org"):
    response = admin.post("/api/admin/invites", json={"email": email})
    assert response.status_code == 200
    return parse_qs(urlparse(response.json()["url"]).fragment)["token"][0]


def other_client():
    return TestClient(
        app,
        headers={
            "Origin": "http://localhost:3000",
            "X-Requested-With": "email-checker",
        },
    )


def test_anonymous_access_and_csrf(client):
    for path in ("/api/account", "/api/models", "/api/credentials", "/api/jobs"):
        assert client.get(path).status_code == 401
    assert client.post("/api/check", json={"query": "x@y.org"}).status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={}, headers={"Origin": "https://evil.test"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/auth/login", json={}, headers={"X-Requested-With": ""}
        ).status_code
        == 403
    )


def test_invites_are_bound_to_email_single_use_and_hashed(signed_in):
    token = invite_user(signed_in)
    with session() as db:
        assert db.get(Invite, token) is None
        assert db.get(Invite, digest(token)) is not None
    person = other_client()
    body = {
        "email": "wrong@example.org",
        "password": "long enough password",
        "token": token,
    }
    assert person.post("/api/auth/accept", json=body).status_code == 400
    body["email"] = "person@example.org"
    assert person.post("/api/auth/accept", json=body).status_code == 200
    assert person.post("/api/auth/accept", json=body).status_code == 400
    assert person.get("/api/admin/users").status_code == 403
    assert (
        person.post("/api/admin/invites", json={"email": "x@example.org"}).status_code
        == 403
    )


def test_credential_encryption_and_no_global_fallback(signed_in):
    assert not user_settings("admin").has_verifalia_credentials
    secret = "private-example-key"
    assert (
        signed_in.put(
            "/api/credentials", json={"openrouter_api_key": secret}
        ).status_code
        == 200
    )
    assert secret not in signed_in.get("/api/credentials").text
    with session() as db:
        assert secret.encode() not in db.get(User, "admin").credentials
    assert user_settings("admin").openrouter_api_key == secret
    signed_in.put("/api/credentials", json={"openrouter_api_key": None})
    assert user_settings("admin").openrouter_api_key is None


def test_disable_account_revokes_existing_session(signed_in):
    token = invite_user(signed_in)
    person = other_client()
    account = person.post(
        "/api/auth/accept",
        json={
            "email": "person@example.org",
            "password": "long enough password",
            "token": token,
        },
    ).json()
    assert (
        signed_in.patch(
            f"/api/admin/users/{account['id']}", json={"active": False}
        ).status_code
        == 200
    )
    assert person.get("/api/account").status_code == 401
    assert (
        signed_in.patch("/api/admin/users/admin", json={"active": False}).status_code
        == 400
    )


def test_private_jobs_downloads_and_deletion(signed_in):
    token = invite_user(signed_in)
    person = other_client()
    person.post(
        "/api/auth/accept",
        json={
            "email": "person@example.org",
            "password": "long enough password",
            "token": token,
        },
    )
    with session() as db, db.begin():
        db.add(
            Job(
                id="private",
                user_id="admin",
                kind="batch",
                status="completed",
                expires=time.time() + 3600,
                filename="example.xlsx",
                download=cipher().encrypt(b"xlsx"),
            )
        )
    for path in ("/api/jobs/private", "/api/batch/private/download"):
        assert person.get(path).status_code == 404
    assert person.delete("/api/jobs/private").status_code == 404
    assert person.get("/api/jobs").json() == []
    assert signed_in.get("/api/batch/private/download").content == b"xlsx"
    assert signed_in.delete("/api/jobs/private").status_code == 200
    assert signed_in.get("/api/batch/private/download").status_code == 404


def test_worker_uses_user_credentials_and_persists_results(signed_in, monkeypatch):
    signed_in.put(
        "/api/credentials",
        json={
            "openrouter_api_key": "user-key",
            "verifalia_username": "own-user",
            "verifalia_password": "own-pass",
        },
    )

    async def lookup(self, names, model, context):
        assert self._settings.openrouter_api_key == "user-key"
        return {
            "simple": [
                Candidate(email="a@example.org"),
                Candidate(email="b@example.org"),
            ]
        }

    async def verify(self, emails, quality):
        assert self._settings.verifalia_username == "own-user"
        assert emails == ["a@example.org", "b@example.org"]
        return {
            email: VerificationResult(
                email=email,
                result="Exists",
                classification="Deliverable",
                status="Success",
            )
            for email in emails
        }

    monkeypatch.setattr(OpenRouterService, "find_candidates", lookup)
    monkeypatch.setattr(VerifaliaService, "verify_many", verify)
    queued = signed_in.post("/api/check", json={"query": "Test Person"})
    assert queued.status_code == 202
    assert queued.json()["status"] == "queued"
    assert asyncio.run(run_once()) is True
    job = signed_in.get("/api/jobs/" + queued.json()["id"]).json()
    assert job["status"] == "completed"
    assert len(job["result"]["results"]) == 2
    assert asyncio.run(run_once()) is False
    with session() as db:
        stored = db.get(Job, job["id"])
        assert stored.payload is None
        assert b"example.org" not in stored.result


def test_expiry_and_interruption_do_not_retry(signed_in):
    with session() as db, db.begin():
        db.add(
            Job(
                id="stale",
                user_id="admin",
                kind="simple",
                status="running",
                updated=time.time() - 120,
                expires=time.time() + 1000,
                payload=seal({}),
            )
        )
        db.add(
            Job(
                id="expired",
                user_id="admin",
                kind="simple",
                status="completed",
                expires=time.time() - 1,
            )
        )
    cleanup()
    assert signed_in.get("/api/jobs/stale").json()["status"] == "interrupted"
    assert signed_in.get("/api/jobs/expired").status_code == 404
    assert asyncio.run(run_once()) is False


def test_limits_and_cookie_flags(signed_in):
    signed_in.put(
        "/api/credentials", json={"verifalia_username": "u", "verifalia_password": "p"}
    )
    for _ in range(2):
        assert (
            signed_in.post("/api/check", json={"query": "x@example.org"}).status_code
            == 202
        )
    assert (
        signed_in.post("/api/check", json={"query": "x@example.org"}).status_code == 429
    )
    response = signed_in.post(
        "/api/auth/login",
        json={"email": "admin@example.org", "password": "correct password 123"},
    )
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]


def test_reset_revokes_sessions(signed_in):
    token = invite_user(signed_in)
    person = other_client()
    person.post(
        "/api/auth/accept",
        json={
            "email": "person@example.org",
            "password": "long enough password",
            "token": token,
        },
    )
    reset = signed_in.post(
        "/api/admin/invites", json={"email": "person@example.org", "kind": "reset"}
    ).json()
    reset_token = parse_qs(urlparse(reset["url"]).fragment)["token"][0]
    new_session = other_client()
    assert (
        new_session.post(
            "/api/auth/accept",
            json={
                "email": "person@example.org",
                "password": "new long password",
                "token": reset_token,
            },
        ).status_code
        == 200
    )
    assert person.get("/api/account").status_code == 401
    assert new_session.get("/api/account").status_code == 200


def test_concurrent_workers_cannot_claim_the_same_job():
    from concurrent.futures import ThreadPoolExecutor

    with session() as db, db.begin():
        db.add(
            Job(id="once", user_id="admin", kind="simple", expires=time.time() + 3600)
        )
    with ThreadPoolExecutor(max_workers=4) as pool:
        claimed = list(pool.map(lambda _: claim(), range(4)))
    assert sum(job is not None for job in claimed) == 1


def test_upload_request_is_bounded_before_parsing(signed_in):
    response = signed_in.post("/api/batch", content=b"x" * (6 * 1024 * 1024))
    assert response.status_code == 413


def test_expired_invitation_cannot_create_account(signed_in):
    token = invite_user(signed_in)
    with session() as db, db.begin():
        db.get(Invite, digest(token)).expires = time.time() - 1
    assert (
        other_client()
        .post(
            "/api/auth/accept",
            json={
                "email": "person@example.org",
                "password": "long enough password",
                "token": token,
            },
        )
        .status_code
        == 400
    )


def test_provider_failure_does_not_leak_secrets_or_retry(signed_in, monkeypatch):
    signed_in.put(
        "/api/credentials", json={"verifalia_username": "u", "verifalia_password": "p"}
    )

    async def fail(self, emails, quality):
        raise RuntimeError("sensitive-provider-response")

    monkeypatch.setattr(VerifaliaService, "verify_many", fail)
    queued = signed_in.post("/api/check", json={"query": "x@example.org"}).json()
    asyncio.run(run_once())
    response = signed_in.get("/api/jobs/" + queued["id"])
    assert response.json()["status"] == "failed"
    assert "sensitive-provider-response" not in response.text
    assert asyncio.run(run_once()) is False
