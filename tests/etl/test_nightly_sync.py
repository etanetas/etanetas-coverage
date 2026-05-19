"""Unit tests for nightly_sync — idempotency and staleness check."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch


class TestIdempotency:
    async def test_skips_if_already_synced_today(self):
        today = date.today().isoformat()
        with (
            patch("etl.tasks.nightly_sync.AsyncSessionLocal"),
            patch("etl.tasks.nightly_sync.get_last_nightly_sync_date", return_value=today),
            patch("etl.tasks.nightly_sync.get_last_cid", return_value=100),
            patch("etl.tasks.nightly_sync.SpintaClient") as MockSpinta,
        ):
            from etl.tasks.nightly_sync import run

            await run()
            # SpintaClient should never be used if sync already done today
            MockSpinta.assert_not_called()

    async def test_runs_if_not_synced_today(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        mock_spinta = AsyncMock()
        mock_spinta.fetch_changes = lambda *a, **kw: aiter([])

        fetch_calls = []

        async def fake_fetch_changes(model, cid):
            fetch_calls.append(model)
            return
            yield  # make it an async generator

        mock_spinta.fetch_changes = fake_fetch_changes

        with (
            patch("etl.tasks.nightly_sync.AsyncSessionLocal"),
            patch("etl.tasks.nightly_sync.get_last_nightly_sync_date", return_value=yesterday),
            patch("etl.tasks.nightly_sync.get_last_cid", return_value=100),
            patch("etl.tasks.nightly_sync.SpintaClient", return_value=mock_spinta),
            patch("etl.tasks.nightly_sync.save_nightly_sync_date", new_callable=AsyncMock),
            patch("etl.tasks.nightly_sync.save_cid", new_callable=AsyncMock),
            patch(
                "etl.tasks.nightly_sync.apply_adresas_changes",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "etl.tasks.nightly_sync.apply_pastatas_changes",
                new_callable=AsyncMock,
                return_value=(0, 0),
            ),
        ):
            from etl.tasks.nightly_sync import run

            await run()
            assert len(fetch_calls) == 2  # called for Adresas and Pastatas


class TestStalenessAlert:
    async def test_alert_sent_when_stale(self):
        stale_date = (date.today() - timedelta(days=8)).isoformat()
        with patch("etl.tasks.nightly_sync.send_alert", new_callable=AsyncMock) as mock_alert:
            from etl.tasks.nightly_sync import _check_staleness

            await _check_staleness(stale_date)
            mock_alert.assert_called_once()
            assert "8 days" in mock_alert.call_args[0][0]

    async def test_no_alert_when_recent(self):
        recent = (date.today() - timedelta(days=3)).isoformat()
        with patch("etl.tasks.nightly_sync.send_alert", new_callable=AsyncMock) as mock_alert:
            from etl.tasks.nightly_sync import _check_staleness

            await _check_staleness(recent)
            mock_alert.assert_not_called()

    async def test_no_alert_when_none(self):
        with patch("etl.tasks.nightly_sync.send_alert", new_callable=AsyncMock) as mock_alert:
            from etl.tasks.nightly_sync import _check_staleness

            await _check_staleness(None)
            mock_alert.assert_not_called()


# Helper: async iterator from list
async def aiter(items):
    for item in items:
        yield item
