import logging

import httpx

from etl.config import settings

log = logging.getLogger(__name__)

_TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"


async def send_alert(message: str) -> None:
    """Send a Telegram alert. Silently skips if credentials are not configured."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        log.debug("Telegram not configured — skipping alert: %s", message)
        return

    url = _TELEGRAM_URL.format(token=settings.telegram_bot_token)
    payload = {"chat_id": settings.telegram_chat_id, "text": message, "parse_mode": "HTML"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            log.info("Telegram alert sent: %s", message[:80])
    except Exception as e:
        log.error("Failed to send Telegram alert: %s", e)
