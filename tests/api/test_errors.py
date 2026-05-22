import secrets

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_db
from app.main import app
from app.models.admin import ApiKey, User


@pytest.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def admin(db_session) -> tuple[User, str]:
    raw = "etn_pk_" + secrets.token_urlsafe(32)
    name = f"adm_{secrets.token_hex(4)}"
    user = User(username=name, email=f"{name}@example.com", role="admin", active=True)
    db_session.add(user)
    await db_session.flush()
    hashed = bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=4)).decode()
    db_session.add(ApiKey(user_id=user.id, key_hash=hashed, name="k"))
    await db_session.flush()
    return user, raw


@pytest.mark.integration
async def test_404_returns_envelope(client, admin):
    _, raw = admin
    resp = await client.get("/api/v1/admin/addresses/99999999", headers={"X-API-Key": raw})
    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "NOT_FOUND"
    assert "message" in body["error"]


@pytest.mark.integration
async def test_401_returns_envelope(client):
    resp = await client.get("/api/v1/admin/me", headers={"X-API-Key": "etn_pk_bogus"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.integration
async def test_422_returns_envelope(client, admin):
    _, raw = admin
    resp = await client.get(
        "/api/v1/admin/addresses",
        params={"limit": 9999},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "errors" in body["error"]
