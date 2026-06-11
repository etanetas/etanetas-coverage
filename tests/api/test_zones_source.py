"""ZoneOut.source/custom_name + PATCH-guard stref auto."""

import secrets
import uuid

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

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
async def admin_user(db_session):
    raw = "etn_pk_" + secrets.token_urlsafe(32)
    name = f"admin_{secrets.token_hex(4)}"
    user = User(username=name, email=f"{name}@example.com", role="admin", active=True)
    db_session.add(user)
    await db_session.flush()
    hashed = bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=4)).decode()
    db_session.add(ApiKey(user_id=user.id, key_hash=hashed, key_prefix=raw[:11], name="k"))
    await db_session.flush()
    return user, raw


@pytest.fixture
async def auto_zone(db_session):
    zone_id = uuid.uuid4()
    await db_session.execute(text(
        "INSERT INTO service_zones (id, name, polygon, priority, source, created_at) "
        "VALUES (CAST(:id AS uuid), 'Auto: T — X', "
        "ST_GeomFromEWKT('SRID=4326;MULTIPOLYGON(((25.0 54.0, 25.1 54.0, 25.1 54.1, 25.0 54.1, 25.0 54.0)))'), "
        "100, 'auto', NOW())"
    ), {"id": str(zone_id)})
    return zone_id


@pytest.mark.integration
async def test_created_zone_has_source_manual(client, admin_user):
    _, raw = admin_user
    resp = await client.post(
        "/api/v1/admin/zones",
        json={"name": "Reczna testowa"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["source"] == "manual"
    assert body["custom_name"] is None


@pytest.mark.integration
async def test_patch_auto_zone_rejects_non_custom_name(client, admin_user, auto_zone):
    _, raw = admin_user
    resp = await client.patch(
        f"/api/v1/admin/zones/{auto_zone}",
        json={"priority": 50},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_patch_auto_zone_accepts_custom_name(client, admin_user, auto_zone):
    _, raw = admin_user
    resp = await client.patch(
        f"/api/v1/admin/zones/{auto_zone}",
        json={"custom_name": "Centrum"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["custom_name"] == "Centrum"
    assert body["source"] == "auto"


@pytest.mark.integration
async def test_patch_manual_zone_still_accepts_name(client, admin_user):
    _, raw = admin_user
    created = await client.post(
        "/api/v1/admin/zones",
        json={"name": "Do zmiany"},
        headers={"X-API-Key": raw},
    )
    zone_id = created.json()["id"]
    resp = await client.patch(
        f"/api/v1/admin/zones/{zone_id}",
        json={"name": "Zmieniona"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Zmieniona"
