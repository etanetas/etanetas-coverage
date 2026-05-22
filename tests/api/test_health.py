import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.integration
async def test_health_returns_ok_when_db_up(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "up"


@pytest.mark.integration
async def test_health_degraded_returns_503_envelope(client, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    from app import main as main_mod

    async def _broken_check():
        raise SQLAlchemyError("connection refused")

    monkeypatch.setattr(main_mod, "_db_ping", _broken_check)
    resp = await client.get("/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"
