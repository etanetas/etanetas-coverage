import asyncio
import logging
import zipfile
from collections.abc import Iterator
from pathlib import Path

import httpx
import ijson

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(300.0, connect=10.0)
_MAX_RETRIES = 5
_CHUNK_SIZE = 65536


class RCZipFallback:
    def __init__(self, url: str, cache_dir: Path = Path("etl/state/cache")):
        self.url = url
        self.cache_dir = cache_dir

    async def download(self) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        zip_path = self.cache_dir / "adr_gra_adresai_LT.zip"
        if zip_path.exists():
            log.info("using cached ZIP: %s", zip_path)
            return zip_path

        log.info("downloading %s ...", self.url)
        for attempt in range(_MAX_RETRIES):
            try:
                await self._stream_to_file(zip_path)
                return zip_path
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

    async def _stream_to_file(self, dest: Path) -> None:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            async with client.stream("GET", self.url) as response:
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
                                "download: %d MB / %d MB (%d%%)",
                                downloaded // (1024 * 1024),
                                total // (1024 * 1024),
                                pct,
                            )

    def iter_features(self, zip_path: Path) -> Iterator[dict]:
        with zipfile.ZipFile(zip_path) as zf:
            geojson_name = next(
                (n for n in zf.namelist() if n.lower().endswith((".geojson", ".json"))), None
            )
            if geojson_name is None:
                raise FileNotFoundError(f"no .geojson/.json found in {zip_path}")
            log.info("parsing %s ...", geojson_name)
            with zf.open(geojson_name) as fp:
                yield from ijson.items(fp, "features.item")
