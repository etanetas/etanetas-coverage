"""Downloader for RC (registrucentras.lt) monthly CSV files.

These files are the primary source for full_import (counties, municipalities,
localities, streets, stat-addresses, premises-addresses). The data is identical
to what Spinta exposes but delivered as static files — far more reliable.
"""

import csv
import logging
from collections.abc import Iterator
from pathlib import Path

import httpx

from etl.config import RC_CSV_URLS, settings
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


class RCCsvClient:
    """Downloads named RC CSV files to a local cache dir, iterates rows as dicts."""

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or Path(settings.etl_cache_dir)

    async def download(self, name: str) -> Path:
        """Download :name: CSV to cache (re-use existing file if present)."""
        url = RC_CSV_URLS[name]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        dest = self.cache_dir / f"rc_{name}.csv"

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

    def iter_rows(self, csv_path: Path) -> Iterator[dict[str, str]]:
        """Yield CSV rows as dicts. Logs and re-raises on parse/encoding errors."""
        try:
            with csv_path.open(encoding="utf-8-sig") as f:
                reader = csv.DictReader(f, delimiter="|")
                yield from reader
        except FileNotFoundError:
            log.error("CSV file not found: %s", csv_path)
            raise
        except UnicodeDecodeError as exc:
            log.error("CSV %s has encoding issues: %s", csv_path, exc)
            raise
        except csv.Error as exc:
            log.error("CSV %s parse error: %s", csv_path, exc)
            raise
