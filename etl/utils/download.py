"""Streaming HTTP download to file, with progress logging."""

import logging
from pathlib import Path

import httpx

from etl.config import settings

log = logging.getLogger(__name__)


async def stream_to_file(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    *,
    label: str | None = None,
) -> None:
    """Stream URL response to :dest: file. Logs progress every N MB.

    Raises ``httpx.HTTPError`` on HTTP status >= 400.
    Raises ``OSError`` if the destination file cannot be written.
    """
    display = label or dest.name
    interval_bytes = settings.rc_progress_log_interval_mb * 1024 * 1024
    chunk_size = settings.rc_download_chunk_size_bytes

    async with client.stream("GET", url) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        downloaded = 0
        with dest.open("wb") as f:
            async for chunk in response.aiter_bytes(chunk_size):
                f.write(chunk)
                downloaded += len(chunk)
                if total and downloaded % interval_bytes < chunk_size:
                    pct = 100 * downloaded // total
                    log.info(
                        "%s: %d MB / %d MB (%d%%)",
                        display,
                        downloaded // (1024 * 1024),
                        total // (1024 * 1024),
                        pct,
                    )
