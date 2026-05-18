from typing import AsyncIterator
from urllib.parse import quote

import httpx

from etl.config import settings


class SpintaClient:
    def __init__(self, base_url: str = settings.spinta_base_url):
        self.base_url = base_url

    async def fetch_all(self, model: str, limit: int = 500) -> AsyncIterator[dict]:
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/{model}?limit({limit})"
            while url:
                response = await client.get(url)
                response.raise_for_status()
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

    async def fetch_changes(self, model: str, since_cid: int, limit: int = 500) -> AsyncIterator[dict]:
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/{model}/:changes/{since_cid}?limit({limit})"
            while url:
                response = await client.get(url)
                response.raise_for_status()
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

    async def count(self, model: str) -> int:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/{model}?count()")
            response.raise_for_status()
            data = response.json()
            return data["_data"][0]["count()"]
