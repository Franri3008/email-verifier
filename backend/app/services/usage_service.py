import logging

import httpx

from app.core.config import Settings


logger = logging.getLogger(__name__)
TIMEOUT = 15.0


async def provider_usage(settings: Settings) -> dict[str, dict[str, float] | None]:
    """Best-effort credit snapshot. A provider is None when it cannot be read."""
    return {
        "verifalia": await _verifalia(settings),
        "openrouter": await _openrouter(settings),
    }


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


async def _verifalia(settings: Settings) -> dict[str, float] | None:
    if not settings.has_verifalia_credentials:
        return None
    if settings.verifalia_bearer_token:
        auth, headers = None, {
            "Authorization": f"Bearer {settings.verifalia_bearer_token}"
        }
    else:
        auth, headers = (
            httpx.BasicAuth(
                settings.verifalia_username or "", settings.verifalia_password or ""
            ),
            {},
        )
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, auth=auth, headers=headers, follow_redirects=False
        ) as client:
            balance = await client.get(f"{settings.verifalia_base_url}/credits/balance")
            balance.raise_for_status()
            # ponytail: today only, widen the window if a monthly view is ever asked for.
            daily = await client.get(
                f"{settings.verifalia_base_url}/credits/daily-usage", params={"limit": 1}
            )
            daily.raise_for_status()
            balance_data, daily_data = balance.json(), daily.json()
    except (httpx.HTTPError, ValueError):
        logger.warning("Verifalia credit lookup failed")
        return None
    return shape_verifalia(balance_data, daily_data)


def shape_verifalia(balance: object, daily: object) -> dict[str, float]:
    balance = balance if isinstance(balance, dict) else {}
    entries = daily.get("data") if isinstance(daily, dict) else None
    today = entries[0] if isinstance(entries, list) and entries else {}
    today = today if isinstance(today, dict) else {}
    packs = _number(balance.get("creditPacks"))
    free = _number(balance.get("freeCredits"))
    return {
        "credit_packs": packs,
        "free_credits": free,
        "available": packs + free,
        "used_today": _number(today.get("credits")) + _number(today.get("freeCredits")),
    }


async def _openrouter(settings: Settings) -> dict[str, float] | None:
    if not settings.openrouter_api_key:
        return None
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            follow_redirects=False,
        ) as client:
            response = await client.get(f"{settings.openrouter_base_url}/credits")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        logger.warning("OpenRouter credit lookup failed")
        return None
    return shape_openrouter(payload)


def shape_openrouter(payload: object) -> dict[str, float]:
    data = payload.get("data") if isinstance(payload, dict) else None
    data = data if isinstance(data, dict) else {}
    total = _number(data.get("total_credits"))
    used = _number(data.get("total_usage"))
    return {"total": total, "used": used, "remaining": total - used}
