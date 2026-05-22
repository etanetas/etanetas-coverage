"""Tests for coverage stats endpoint."""

import secrets

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient

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


@pytest.mark.asyncio
async def test_coverage_stats_operational_scope(client: AsyncClient, admin_user: tuple) -> None:
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
async def test_coverage_stats_operational_muni_codes_match_rc(client: AsyncClient, admin_user: tuple) -> None:
    _, raw = admin_user
    resp = await client.get(
        "/api/v1/admin/coverage/stats",
        params={"scope": "operational", "muni_codes": settings.stats_municipality_codes},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200, resp.text
