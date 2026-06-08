"""Tests for coverage stats endpoint."""

import secrets

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.config import settings
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
async def seed_operational_area(db_session, monkeypatch):
    """Seed one municipality + locality and point settings at them."""
    for stmt in [
        "INSERT INTO counties (rc_code, name, synced_at) VALUES (99001, 'Test County', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO municipalities (rc_code, county_code, name, type, synced_at) VALUES (99100, 99001, 'Test Municipality', 'rajono', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO localities (rc_code, muni_code, name, type, synced_at) VALUES (99200, 99100, 'Test Locality', 'miestas', NOW()) ON CONFLICT DO NOTHING",
    ]:
        await db_session.execute(text(stmt))
    monkeypatch.setattr(settings, "stats_locality_codes", [])
    monkeypatch.setattr(settings, "stats_locality_names", ["Test Locality"])
    return {"muni_code": 99100, "locality_code": 99200}


@pytest.mark.asyncio
async def test_coverage_stats_operational_scope(client: AsyncClient, admin_user: tuple, seed_operational_area) -> None:
    _, raw = admin_user
    resp = await client.get(
        "/api/v1/admin/coverage/stats",
        params={"scope": "operational"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["scope"] == "operational"
    assert data["scope_label"] == "Operational area"
    assert len(data["scope_municipalities"]) >= 1
    assert data["total_buildings"] >= 0


@pytest.mark.asyncio
async def test_coverage_stats_all_scope(client: AsyncClient, admin_user: tuple) -> None:
    _, raw = admin_user
    resp = await client.get(
        "/api/v1/admin/coverage/stats",
        params={"scope": "all"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["scope"] == "all"
    assert data["scope_municipalities"] == []


@pytest.mark.asyncio
async def test_coverage_stats_operational_muni_codes_match_rc(client: AsyncClient, admin_user: tuple, seed_operational_area, monkeypatch) -> None:
    muni_code = seed_operational_area["muni_code"]
    monkeypatch.setattr(settings, "stats_locality_names", [])
    monkeypatch.setattr(settings, "stats_locality_codes", [])
    _, raw = admin_user
    resp = await client.get(
        "/api/v1/admin/coverage/stats",
        params={"scope": "operational", "muni_codes": [muni_code]},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200, resp.text
