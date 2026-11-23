import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.exceptions.handlers import ServiceError
from app.models.schemas.verification import ModelId
from app.services import retry
from app.services.openrouter_service import OpenRouterService


def test_only_allows_http_source_urls() -> None:
    assert OpenRouterService._safe_source_url("https://example.org/contact") == (
        "https://example.org/contact"
    )
    assert OpenRouterService._safe_source_url("javascript:alert(1)") is None
    assert OpenRouterService._safe_source_url("not a url") is None


def openrouter_reply(request, status=200, headers=None):
    content = json.dumps({"people": [{"row_id": "1", "candidates": []}]})
    return httpx.Response(
        status,
        headers=headers,
        json={"choices": [{"message": {"content": content}}]},
        request=request,
    )


def run_lookup(monkeypatch, outcomes):
    calls = []
    waits = []

    async def post(self, url, **kwargs):
        calls.append(self.timeout)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome(httpx.Request("POST", url))

    async def sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    monkeypatch.setattr(retry.asyncio, "sleep", sleep)
    service = OpenRouterService(Settings(openrouter_api_key="key"))
    result = asyncio.run(service.find_candidates([("1", "Ada")], ModelId.GPT_LUNA))
    return result, calls, waits


def test_lookup_retries_once_after_rate_limit(monkeypatch) -> None:
    result, calls, waits = run_lookup(
        monkeypatch,
        [
            lambda request: openrouter_reply(request, 429, {"Retry-After": "90"}),
            openrouter_reply,
        ],
    )
    assert result == {"1": []}
    assert len(calls) == 2
    assert waits == [20.0]
    assert calls[0].read == 120.0


def test_lookup_retries_connection_errors_before_sending(monkeypatch) -> None:
    result, calls, _ = run_lookup(
        monkeypatch, [httpx.ConnectError("down"), openrouter_reply]
    )
    assert result == {"1": []}
    assert len(calls) == 2


def test_lookup_never_retries_after_request_was_sent(monkeypatch) -> None:
    for outcome in (
        httpx.ReadTimeout("slow"),
        lambda request: openrouter_reply(request, 502),
    ):
        with pytest.raises(ServiceError):
            run_lookup(monkeypatch, [outcome, openrouter_reply])
    for outcome in (
        httpx.ConnectTimeout("down"),
        lambda request: openrouter_reply(request, 429),
    ):
        with pytest.raises(ServiceError):
            run_lookup(monkeypatch, [outcome, outcome])
