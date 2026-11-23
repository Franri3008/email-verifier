import asyncio

import httpx
import pytest

from app.core.config import Settings
from app.services import retry
from app.services.verifalia_service import VerifaliaService


def test_maps_verifalia_classifications_to_plain_results() -> None:
    service = VerifaliaService(Settings())

    deliverable = service._to_result(
        "ada@example.org",
        {"classification": "Deliverable", "status": "Success"},
    )
    risky = service._to_result(
        "ada@example.org",
        {"classification": "Risky", "status": "ServerIsCatchAll"},
    )
    unknown = service._to_result(
        "ada@example.org",
        {"classification": "FutureClassification", "status": "NewStatus"},
    )

    assert deliverable.result == "Exists"
    assert risky.result == "Risky / unconfirmed"
    assert unknown.result == "Unverified"


def test_builds_job_url_from_snapshot() -> None:
    service = VerifaliaService(Settings(verifalia_base_url="https://example.test/v2.7"))
    snapshot = {"overview": {"id": "job-123", "status": "InProgress"}}

    assert (
        service._job_url(snapshot)
        == "https://example.test/v2.7/email-validations/job-123"
    )


def test_polling_retries_freely_and_paid_submit_does_not(monkeypatch) -> None:
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(retry.asyncio, "sleep", sleep)
    request = httpx.Request("GET", "https://api.verifalia.com/v2.7/email-validations/x")
    outcomes = [
        httpx.ReadTimeout("slow"),
        httpx.Response(503, request=request),
        httpx.Response(200, request=request),
    ]

    async def poll():
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    response = asyncio.run(retry.send_free(poll, "Verifalia"))
    assert response.status_code == 200
    assert outcomes == []

    sent = []

    async def submit():
        sent.append(True)
        raise httpx.ReadTimeout("slow")

    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(retry.send_paid(submit, "Verifalia"))
    assert len(sent) == 1

    async def server_error():
        sent.append(True)
        return httpx.Response(500, request=request)

    sent.clear()
    assert asyncio.run(retry.send_paid(server_error, "Verifalia")).status_code == 500
    assert len(sent) == 1


def test_retry_after_is_capped() -> None:
    request = httpx.Request("POST", "https://api.verifalia.com")
    assert (
        retry.retry_wait(
            httpx.Response(429, headers={"Retry-After": "3"}, request=request)
        )
        == 3.0
    )
    assert (
        retry.retry_wait(
            httpx.Response(429, headers={"Retry-After": "600"}, request=request)
        )
        == 20.0
    )
    assert (
        retry.retry_wait(
            httpx.Response(429, headers={"Retry-After": "soon"}, request=request)
        )
        == 2.0
    )
    assert retry.retry_wait(httpx.Response(429, request=request)) == 2.0
