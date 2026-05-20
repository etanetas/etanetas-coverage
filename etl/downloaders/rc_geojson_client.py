"""Downloader for RC (registrucentras.lt) monthly GeoJSON files.

Used to load locality boundaries (MULTIPOLYGON) and street axes (MULTILINESTRING).
Source coordinates are in LKS-94 (EPSG:3346); ST_Transform converts to WGS84 in DB.
"""

import logging
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

RC_GEOJSON_URLS = {
    "localities_boundary": "https://www.registrucentras.lt/aduomenys/?byla=adr_gra_gyvenamosios_vietoves.json",
    "streets_axis": "https://www.registrucentras.lt/aduomenys/?byla=adr_gra_gatves.json",
}


class RCGeoJsonClient:
    """Downloads named RC GeoJSON files to a local cache dir, streams features via ijson."""

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or Path(settings.etl_cache_dir)

    async def download(self, name: str) -> Path:
        """Download :name: GeoJSON to cache (re-use existing file if present)."""
        url = RC_GEOJSON_URLS[name]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        dest = self.cache_dir / f"rc_{name}.json"

        if dest.exists():
            log.info("using cached %s", dest.name)
            return dest

        log.info("downloading %s from RC ...", name)

        async def _download() -> None:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
                await stream_to_file(client, url, dest)

        await with_exponential_backoff(
            _download,
            max_retries=_MAX_RETRIES,
            retryable_exceptions=_RETRYABLE_DOWNLOAD,
            operation_name=f"download {name}",
        )
        return dest

    def iter_features(self, path: Path) -> Iterator[dict[str, Any]]:
        """Stream GeoJSON ``features[]`` array using ijson (constant memory)."""
        log.info("parsing %s ...", path.name)
        try:
            with path.open("rb") as fp:
                yield from ijson.items(fp, "features.item", use_float=True)
        except FileNotFoundError:
            log.error("GeoJSON file not found: %s", path)
            raise
        except ijson.JSONError as exc:
            log.error("GeoJSON %s parse error: %s", path, exc)
            raise
