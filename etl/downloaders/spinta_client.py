import asyncio
import logging
from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx

from etl.config import settings

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(120.0, connect=10.0)
_MAX_RETRIES = 10


_RETRYABLE = (
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    httpx.HTTPStatusError,
    asyncio.CancelledError,
)


async def _get_with_retry(client: httpx.AsyncClient, url: str) -> httpx.Response:
    for attempt in range(_MAX_RETRIES):
        try:
            response = await client.get(url)
            if response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"server {response.status_code}", request=response.request, response=response
                )
            response.raise_for_status()
            return response
        except _RETRYABLE as e:
            if isinstance(e, asyncio.CancelledError):
                task = asyncio.current_task()
                if task is not None and task.cancelling() > 0:
                    raise  # genuine Ctrl+C / task cancel
            if attempt == _MAX_RETRIES - 1:
                raise
            wait = 2**attempt
            log.warning(
                "retry %d/%d after %s, waiting %ds",
                attempt + 1,
                _MAX_RETRIES,
                type(e).__name__,
                wait,
            )
            await asyncio.sleep(wait)
    raise RuntimeError("unreachable")


class SpintaClient:
    def __init__(self, base_url: str = settings.spinta_base_url):
        self.base_url = base_url

    async def fetch_all(self, model: str, limit: int = 5000) -> AsyncIterator[dict]:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            url = f"{self.base_url}/{model}?limit({limit})"
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
        self, model: str, since_cid: int, limit: int = 5000
    ) -> AsyncIterator[dict]:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            url = f"{self.base_url}/{model}/:changes/{since_cid}?limit({limit})"
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
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await _get_with_retry(client, f"{self.base_url}/{model}/{uuid}")
            data = response.json()
            return data if data.get("_id") else None

    async def count(self, model: str) -> int:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await _get_with_retry(client, f"{self.base_url}/{model}?count()")
            data = response.json()
            return data["_data"][0]["count()"]
