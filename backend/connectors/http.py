"""Shared HTTP fetching for connectors: retries, exponential backoff, rate limits.

Phase 1's World Bank connector grew its own retry loop; Phase 2 has five sources, so
that logic lives here once. Feature 1.1 requires that a 429 causes *backoff*, not
failure — so rate limiting is a retryable condition, and a provider-supplied
``Retry-After`` is honoured in preference to our own backoff schedule.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_ATTEMPTS = 4
DEFAULT_INITIAL_BACKOFF_S = 0.5
#: Never sleep longer than this on a Retry-After; a provider asking for an hour should
#: fail the run so the scheduler retries on its own cadence instead of pinning a worker.
MAX_RETRY_AFTER_S = 60.0


class SourceAPIError(Exception):
    """A data source was unreachable or kept returning a retryable error."""


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return min(float(raw.strip()), MAX_RETRY_AFTER_S)
    except ValueError:
        return None  # HTTP-date form; fall back to our own backoff


async def get_with_backoff(
    client: httpx.AsyncClient,
    url: str,
    *,
    source: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
    initial_backoff: float = DEFAULT_INITIAL_BACKOFF_S,
) -> httpx.Response:
    """GET with exponential backoff on transport errors, 429, and 5xx.

    4xx responses other than 429 are *not* retried — they signal a bad request, and
    hammering the provider will not fix it. Raises SourceAPIError once attempts run out.
    """
    delay = initial_backoff
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = await client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            last_error = exc
        else:
            if response.status_code == 429:
                last_error = SourceAPIError(f"HTTP 429 rate limited for {response.url}")
                retry_after = _retry_after_seconds(response)
                if retry_after is not None:
                    delay = retry_after
            elif response.status_code >= 500:
                last_error = SourceAPIError(f"HTTP {response.status_code} for {response.url}")
            else:
                response.raise_for_status()
                return response

        if attempt < attempts:
            logger.warning(
                "[%s] retry %d/%d in %.1fs after error: %s",
                source,
                attempt,
                attempts,
                delay,
                last_error,
            )
            await asyncio.sleep(delay)
            delay *= 2

    raise SourceAPIError(
        f"{source} request failed after {attempts} attempts: {url}"
    ) from last_error


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    source: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> Any:
    response = await get_with_backoff(
        client, url, source=source, params=params, headers=headers, **kwargs
    )
    return response.json()


async def get_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    source: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> str:
    response = await get_with_backoff(
        client, url, source=source, params=params, headers=headers, **kwargs
    )
    return response.text
