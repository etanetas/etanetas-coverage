import asyncio
import logging
from collections.abc import Iterator
from pathlib import Path

import httpx
import ijson

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(300.0, connect=10.0)
_MAX_RETRIES = 5
_CHUNK_SIZE = 65536

RC_GEOJSON_URLS = {
    "localities_boundary": "https://www.registrucentras.lt/aduomenys/?byla=adr_gra_gyvenamosios_vietoves.json",
    "streets_axis": "https://www.registrucentras.lt/aduomenys/?byla=adr_gra_gatves.json",
}


class RCGeoJsonClient:
    def __init__(self, cache_dir: Path = Path("etl/state/cache")):
        self.cache_dir = cache_dir

    async def download(self, name: str) -> Path:
        url = RC_GEOJSON_URLS[name]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        dest = self.cache_dir / f"rc_{name}.json"
        if dest.exists():
            log.info("using cached %s", dest.name)
            return dest

        log.info("downloading %s from RC ...", name)
        for attempt in range(_MAX_RETRIES):
            try:
                await self._stream_to_file(url, dest)
                return dest
            except (httpx.TimeoutException, httpx.ReadError, httpx.RemoteProtocolError) as e:
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
                        if total and downloaded % (10 * 1024 * 1024) < _CHUNK_SIZE:
                            pct = 100 * downloaded // total
                            log.info(
                                "%s: %d MB / %d MB (%d%%)",
                                dest.name,
                                downloaded // (1024 * 1024),
                                total // (1024 * 1024),
                                pct,
                            )

    def iter_features(self, path: Path) -> Iterator[dict]:
        log.info("parsing %s ...", path.name)
        with path.open("rb") as fp:
            yield from ijson.items(fp, "features.item", use_float=True)
