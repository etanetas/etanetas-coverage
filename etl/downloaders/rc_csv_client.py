import asyncio
import csv
import io
from pathlib import Path
from typing import Iterator

import httpx

_TIMEOUT = httpx.Timeout(300.0, connect=10.0)
_MAX_RETRIES = 5
_CHUNK_SIZE = 65536

RC_CSV_URLS = {
    "counties":       "https://www.registrucentras.lt/aduomenys/?byla=adr_apskritys.csv",
    "municipalities": "https://www.registrucentras.lt/aduomenys/?byla=adr_savivaldybes.csv",
    "localities":     "https://www.registrucentras.lt/aduomenys/?byla=adr_gyvenamosios_vietoves.csv",
    "streets":        "https://www.registrucentras.lt/aduomenys/?byla=adr_gatves.csv",
    "addresses":      "https://www.registrucentras.lt/aduomenys/?byla=adr_stat_lr.csv",
}


class RCCsvClient:
    def __init__(self, cache_dir: Path = Path("etl/state/cache")):
        self.cache_dir = cache_dir

    async def download(self, name: str) -> Path:
        url = RC_CSV_URLS[name]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        dest = self.cache_dir / f"rc_{name}.csv"
        if dest.exists():
            print(f"  using cached {dest.name}")
            return dest

        print(f"  downloading {name} from RC ...")
        for attempt in range(_MAX_RETRIES):
            try:
                await self._stream_to_file(url, dest)
                return dest
            except (httpx.TimeoutException, httpx.ReadError, httpx.RemoteProtocolError) as e:
                if attempt == _MAX_RETRIES - 1:
                    raise
                wait = 2 ** attempt
                print(f"  retry {attempt + 1}/{_MAX_RETRIES} after {type(e).__name__}, waiting {wait}s")
                await asyncio.sleep(wait)
        raise RuntimeError("unreachable")

    async def _stream_to_file(self, url: str, dest: Path) -> None:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0))
                downloaded = 0
                with dest.open("wb") as f:
                    async for chunk in response.aiter_bytes(_CHUNK_SIZE):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total and downloaded % (5 * 1024 * 1024) < _CHUNK_SIZE:
                            pct = 100 * downloaded // total
                            print(f"  {dest.name}: {downloaded // (1024*1024)} MB / {total // (1024*1024)} MB ({pct}%)")

    def iter_rows(self, csv_path: Path) -> Iterator[dict]:
        with csv_path.open(encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter="|")
            yield from reader
