import asyncio

from app.core.config import Settings
from app.services.usage_service import (
    provider_usage,
    shape_openrouter,
    shape_verifalia,
)


def test_shapes_verifalia_balance_and_daily_usage() -> None:
    shaped = shape_verifalia(
        {"creditPacks": 1200.0, "freeCredits": 25.0},
        {"data": [{"credits": 18.0, "freeCredits": 2.0}]},
    )

    assert shaped == {
        "credit_packs": 1200.0,
        "free_credits": 25.0,
        "available": 1225.0,
        "used_today": 20.0,
    }


def test_shapes_missing_or_odd_provider_payloads_as_zero() -> None:
    assert shape_verifalia(None, {"data": []})["available"] == 0.0
    assert shape_verifalia({"creditPacks": "many"}, {})["used_today"] == 0.0
    assert shape_openrouter({"data": {"total_credits": 10.0, "total_usage": 3.25}}) == {
        "total": 10.0,
        "used": 3.25,
        "remaining": 6.75,
    }
    assert shape_openrouter("broken")["remaining"] == 0.0


def test_reports_no_usage_without_credentials() -> None:
    assert asyncio.run(provider_usage(Settings())) == {
        "verifalia": None,
        "openrouter": None,
    }
