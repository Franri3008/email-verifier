import asyncio
import logging
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

import httpx


logger = logging.getLogger(__name__)
NOT_SENT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
MAX_RETRY_WAIT_SECONDS = 20.0
DEFAULT_RETRY_WAIT_SECONDS = 2.0


async def send_paid(
    request: Callable[[], Awaitable[httpx.Response]], provider: str
) -> httpx.Response:
    try:
        response = await request()
    except NOT_SENT_ERRORS as exc:
        logger.warning(
            "%s request not sent (%s); retrying once", provider, type(exc).__name__
        )
        await asyncio.sleep(DEFAULT_RETRY_WAIT_SECONDS)
        return await request()
    if response.status_code != 429:
        return response
    logger.warning("%s rate limited the request; retrying once", provider)
    await asyncio.sleep(retry_wait(response))
    return await request()


async def send_free(
    request: Callable[[], Awaitable[httpx.Response]], provider: str, attempts: int = 3
) -> httpx.Response:
    for attempt in range(1, attempts):
        try:
            response = await request()
        except httpx.TransportError as exc:
            logger.warning(
                "%s poll failed (%s); retrying", provider, type(exc).__name__
            )
            await asyncio.sleep(DEFAULT_RETRY_WAIT_SECONDS * attempt)
            continue
        if response.status_code != 429 and response.status_code < 500:
            return response
        logger.warning(
            "%s poll returned HTTP %s; retrying", provider, response.status_code
        )
        await asyncio.sleep(retry_wait(response, DEFAULT_RETRY_WAIT_SECONDS * attempt))
    return await request()


def retry_wait(
    response: httpx.Response, default: float = DEFAULT_RETRY_WAIT_SECONDS
) -> float:
    value = (response.headers.get("retry-after") or "").strip()
    if not value:
        return min(default, MAX_RETRY_WAIT_SECONDS)
    try:
        seconds = float(value)
    except ValueError:
        try:
            moment = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return min(default, MAX_RETRY_WAIT_SECONDS)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        seconds = (moment - datetime.now(timezone.utc)).total_seconds()
    return min(max(seconds, 0.0), MAX_RETRY_WAIT_SECONDS)
