"""Verify offering mutations schedule an auto-zone rebuild (wiring tests)."""

import secrets
import uuid

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.dependencies import get_db
from app.main import app
from app.models.admin import ApiKey, User
from app.models.technology import Technology, TechnologyType


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
async def seed_address(db_session):
    stmts = [
        "INSERT INTO counties (rc_code, name, synced_at) VALUES (81001, 'AZ Apskritis', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO municipalities (rc_code, county_code, name, type, synced_at) VALUES (81100, 81001, 'AZ Savivaldybė', 'rajono', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO localities (rc_code, muni_code, name, type, synced_at) VALUES (81100, 81100, 'AZinkai', 'miestas', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO streets (rc_code, locality_code, name, full_name, synced_at) VALUES (811001, 81100, 'AZ g.', 'AZ g., AZinkai', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO addresses (rc_code, street_code, locality_code, house_no, postal_code, synced_at, point, address_type) VALUES (81199901, 811001, 81100, '1', '99001', NOW(), ST_GeomFromEWKT('SRID=4326;POINT(25.3 54.3)'), 'building') ON CONFLICT DO NOTHING",
    ]
    for s in stmts:
        await db_session.execute(text(s))
    return 81199901


@pytest.fixture
async def seed_tech(db_session) -> tuple[TechnologyType, Technology]:
    code = f"TEST_{secrets.token_hex(3).upper()}"
    tt = TechnologyType(
        code=code,
        display_name="AZ Test Type",
        public_name="AZNet",
        sort_order=998,
    )
    db_session.add(tt)
    await db_session.flush()

    tech = Technology(
        type_id=tt.id,
        variant_code=f"AZ_V_{secrets.token_hex(3).upper()}",
        display_name="AZ Test Variant",
        sort_order=998,
    )
    db_session.add(tech)
    await db_session.flush()
    return tt, tech


@pytest.fixture
def rebuild_recorder(monkeypatch):
    calls: list[uuid.UUID | None] = []

    async def _record(technology_id=None):
        calls.append(technology_id)

    monkeypatch.setattr("app.api.v1.admin.addresses.rebuild_auto_zones_background", _record)
    monkeypatch.setattr("app.api.v1.admin.bulk.rebuild_auto_zones_background", _record)
    return calls


@pytest.mark.integration
async def test_create_offering_schedules_rebuild(client, admin_user, seed_address, seed_tech, rebuild_recorder):
    _, raw = admin_user
    _, tech = seed_tech
    resp = await client.post(
        f"/api/v1/admin/addresses/{seed_address}/offerings",
        json={
            "technology_id": str(tech.id),
            "status": "available",
            "max_download_mbps": 1000,
            "max_upload_mbps": 500,
            "status_since": "2026-06-11",
        },
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 201
    assert rebuild_recorder == [tech.id]


@pytest.mark.integration
async def test_update_offering_schedules_rebuild(client, admin_user, seed_address, seed_tech, rebuild_recorder):
    _, raw = admin_user
    _, tech = seed_tech
    created = await client.post(
        f"/api/v1/admin/addresses/{seed_address}/offerings",
        json={
            "technology_id": str(tech.id),
            "status": "available",
            "max_download_mbps": 1000,
            "max_upload_mbps": 500,
            "status_since": "2026-06-11",
        },
        headers={"X-API-Key": raw},
    )
    offering_id = created.json()["id"]
    # Reset recorder after create
    rebuild_recorder.clear()

    resp = await client.patch(
        f"/api/v1/admin/addresses/offerings/{offering_id}",
        json={"max_download_mbps": 500},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    assert rebuild_recorder == [tech.id]


@pytest.mark.integration
async def test_delete_offering_schedules_rebuild(client, admin_user, seed_address, seed_tech, rebuild_recorder):
    _, raw = admin_user
    _, tech = seed_tech
    created = await client.post(
        f"/api/v1/admin/addresses/{seed_address}/offerings",
        json={
            "technology_id": str(tech.id),
            "status": "available",
            "max_download_mbps": 1000,
            "max_upload_mbps": 500,
            "status_since": "2026-06-11",
        },
        headers={"X-API-Key": raw},
    )
    offering_id = created.json()["id"]
    rebuild_recorder.clear()

    resp = await client.delete(
        f"/api/v1/admin/addresses/offerings/{offering_id}", headers={"X-API-Key": raw}
    )
    assert resp.status_code == 204
    assert rebuild_recorder == [tech.id]


@pytest.mark.integration
async def test_bulk_execute_schedules_rebuild(client, admin_user, seed_address, seed_tech, rebuild_recorder):
    _, raw = admin_user
    _, tech = seed_tech

    preview = await client.post(
        "/api/v1/admin/bulk/preview",
        json={
            "operation": {
                "type": "add_offering",
                "technology_id": str(tech.id),
                "status": "available",
                "max_dl_mbps": 1000,
                "max_ul_mbps": 500,
                "status_since": "2026-06-11",
            },
            "filter": {"rc_codes": [seed_address]},
        },
        headers={"X-API-Key": raw},
    )
    assert preview.status_code == 200
    token = preview.json()["preview_token"]

    rebuild_recorder.clear()

    exec_resp = await client.post(
        "/api/v1/admin/bulk/execute",
        json={"preview_token": token},
        headers={"X-API-Key": raw},
    )
    assert exec_resp.status_code == 201
    assert rebuild_recorder == [tech.id]
