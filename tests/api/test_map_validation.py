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
    db_session.add(ApiKey(user_id=user.id, key_hash=hashed, key_prefix=raw[:11], name="k"))
    await db_session.flush()
    return user, raw


@pytest.mark.integration
async def test_map_addresses_rejects_excessive_limit(client, admin):
    _, raw = admin
    resp = await client.get(
        "/api/v1/admin/map/addresses",
        params={"bbox": "25.0,54.0,26.0,55.0", "limit": 5001},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_map_addresses_rejects_zero_limit(client, admin):
    _, raw = admin
    resp = await client.get(
        "/api/v1/admin/map/addresses",
        params={"bbox": "25.0,54.0,26.0,55.0", "limit": 0},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_map_addresses_accepts_max_limit(client, admin):
    _, raw = admin
    resp = await client.get(
        "/api/v1/admin/map/addresses",
        params={"bbox": "25.0,54.0,26.0,55.0", "limit": 5000},
        headers={"X-API-Key": raw},
    )
    # Should not be rejected for limit (may be 200 or other error unrelated to limit)
    assert resp.status_code != 422


@pytest.mark.integration
async def test_map_addresses_accepts_gzip_encoding(client, admin):
    _, raw = admin
    resp = await client.get(
        "/api/v1/admin/map/addresses",
        params={"bbox": "25.0,54.0,26.0,55.0"},
        headers={"X-API-Key": raw, "Accept-Encoding": "gzip"},
    )
    # Middleware must not break the endpoint; empty bbox = small response = no compression
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]


@pytest.mark.integration
async def test_map_addresses_has_cache_control(client, admin):
    _, raw = admin
    resp = await client.get(
        "/api/v1/admin/map/addresses",
        params={"bbox": "25.0,54.0,26.0,55.0"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == "max-age=300"
