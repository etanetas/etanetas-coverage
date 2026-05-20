"""Downloader for the RC nationwide address-points ZIP (``adr_gra_adresai_LT.zip``).

This is the **primary** source of address points (the Spinta ``AdresoTaskas`` endpoint
is empty publicly). The ZIP contains one GeoJSON with WGS84 coords already in
``E_KOORD``/``N_KOORD`` properties — no LKS-94 → WGS84 conversion needed.
"""

import logging
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import ijson

from etl.config import settings
from etl.utils.download import stream_to_file
from etl.utils.retry import with_exponential_backoff

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(
    settings.rc_download_timeout_seconds,
    connect=settings.rc_download_connect_timeout_seconds,
)
_MAX_RETRIES = settings.rc_download_max_retries

_RETRYABLE_DOWNLOAD = (
    httpx.TimeoutException,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)


class RCAddressPointsClient:
    """Downloads the RC address-points ZIP, streams GeoJSON features from inside it."""

    def __init__(self, url: str, cache_dir: Path | None = None):
        self.url = url
        self.cache_dir = cache_dir or Path(settings.etl_cache_dir)

    async def download(self) -> Path:
        """Download address-points ZIP to cache (re-use existing file if present)."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        zip_path = self.cache_dir / "adr_gra_adresai_LT.zip"

        if zip_path.exists():
            log.info("using cached ZIP: %s", zip_path)
            return zip_path

        log.info("downloading %s ...", self.url)

        async def _download() -> None:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
                await stream_to_file(client, self.url, zip_path, label="download")

        await with_exponential_backoff(
            _download,
            max_retries=_MAX_RETRIES,
            retryable_exceptions=_RETRYABLE_DOWNLOAD,
            operation_name="download address-points ZIP",
        )
        return zip_path

    def iter_features(self, zip_path: Path) -> Iterator[dict[str, Any]]:
        """Stream GeoJSON features from the .geojson/.json file inside the ZIP."""
        try:
            with zipfile.ZipFile(zip_path) as zf:
                geojson_name = next(
                    (n for n in zf.namelist() if n.lower().endswith((".geojson", ".json"))),
                    None,
                )
                if geojson_name is None:
                    raise FileNotFoundError(f"no .geojson/.json found in {zip_path}")
                log.info("parsing %s ...", geojson_name)
                with zf.open(geojson_name) as fp:
                    yield from ijson.items(fp, "features.item", use_float=True)
        except zipfile.BadZipFile:
            log.error("ZIP file %s is corrupted", zip_path)
            raise
        except FileNotFoundError:
            log.error("ZIP or inner GeoJSON not found in %s", zip_path)
            raise
