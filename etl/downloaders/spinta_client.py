"""Spinta API client (get.data.gov.lt).

Used by nightly_sync to fetch incremental changes via the ``/:changes/<cid>`` endpoint,
and by full_import for the head ``_cid`` lookup.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx

from etl.config import settings
from etl.utils.retry import with_exponential_backoff

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(
    settings.spinta_timeout_seconds,
    connect=settings.spinta_connect_timeout_seconds,
)
_MAX_RETRIES = settings.spinta_max_retries

_RETRYABLE = (
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    httpx.HTTPStatusError,
    asyncio.CancelledError,
)


async def _get_with_retry(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """GET :url: with exponential backoff. Treats 5xx as retryable."""

    async def _attempt() -> httpx.Response:
        response = await client.get(url)
        if response.status_code >= 500:
            raise httpx.HTTPStatusError(
                f"server {response.status_code}",
                request=response.request,
                response=response,
            )
        response.raise_for_status()
        return response

    return await with_exponential_backoff(
        _attempt,
        max_retries=_MAX_RETRIES,
        retryable_exceptions=_RETRYABLE,
        operation_name=f"GET {url}",
    )


class SpintaClient:
    """Async client for the Spinta open data API."""

    def __init__(self, base_url: str = settings.spinta_base_url):
        self.base_url = base_url

    async def fetch_all(
        self, model: str, limit: int = settings.spinta_fetch_limit
    ) -> AsyncIterator[dict]:
        """Yield every record of :model: by paginating with ``page()`` tokens."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            url: str | None = f"{self.base_url}/{model}?limit({limit})"
            while url:
                response = await _get_with_retry(client, url)
                data = response.json()
                for record in data["_data"]:
                    yield record

                if len(data["_data"]) < limit:
                    break

                next_token = data.get("_page", {}).get("next")
                if next_token:
                    url = f"{self.base_url}/{model}?limit({limit})&page('{quote(next_token, safe='')}')"
                else:
                    url = None

    async def fetch_changes(
        self, model: str, since_cid: int, limit: int = settings.spinta_fetch_limit
    ) -> AsyncIterator[dict]:
        """Yield change records of :model: starting from ``_cid >= :since_cid:``."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            url: str | None = f"{self.base_url}/{model}/:changes/{since_cid}?limit({limit})"
            while url:
                response = await _get_with_retry(client, url)
                data = response.json()
                for record in data["_data"]:
                    yield record

                if len(data["_data"]) < limit:
                    break

                next_token = data.get("_page", {}).get("next")
                if next_token:
                    url = f"{self.base_url}/{model}/:changes/{since_cid}?limit({limit})&page('{quote(next_token, safe='')}')"
                else:
                    url = None

    async def fetch_one(self, model: str, uuid: str) -> dict | None:
        """Fetch single record by UUID. Returns ``None`` if not found."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await _get_with_retry(client, f"{self.base_url}/{model}/{uuid}")
            data = response.json()
            return data if data.get("_id") else None

    async def count(self, model: str) -> int:
        """Return total record count of :model:."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await _get_with_retry(client, f"{self.base_url}/{model}?count()")
            data = response.json()
            return data["_data"][0]["count()"]
