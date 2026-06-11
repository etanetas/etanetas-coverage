"""Luki w pokryciu: adresy w strefie bez oferty technologii strefy."""

import secrets

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.dependencies import get_db
from app.main import app
from app.models.admin import ApiKey, User

ZONE_ID = "dd000000-0000-0000-0000-000000000099"
ADDR_COVERED = 93199901   # oferta technologii strefy -> has_override
ADDR_GAP = 93199902       # oferta INNEJ technologii -> nadal luka


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
async def gap_setup(db_session):
    """Strefa z technologia A; ADDR_COVERED ma oferte A, ADDR_GAP tylko B."""
    stmts = [
        "INSERT INTO counties (rc_code, name, synced_at) VALUES (93001, 'Gap Apskritis', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO municipalities (rc_code, county_code, name, type, synced_at) VALUES (93100, 93001, 'Gap Sav.', 'rajono', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO localities (rc_code, muni_code, name, type, synced_at) VALUES (93100, 93100, 'Gapkaimis', 'k.', NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO addresses (rc_code, locality_code, house_no, synced_at, point, address_type) VALUES ({ADDR_COVERED}, 93100, '1', NOW(), ST_GeomFromEWKT('SRID=4326;POINT(25.05 54.05)'), 'building') ON CONFLICT DO NOTHING",
        f"INSERT INTO addresses (rc_code, locality_code, house_no, synced_at, point, address_type) VALUES ({ADDR_GAP}, 93100, '2', NOW(), ST_GeomFromEWKT('SRID=4326;POINT(25.06 54.06)'), 'building') ON CONFLICT DO NOTHING",
        "INSERT INTO technology_types (id, code, display_name, public_name, sort_order) VALUES ('aa000000-0000-0000-0000-000000000093', 'GAP_A', 'Gap A', 'Gap A', 93) ON CONFLICT DO NOTHING",
        "INSERT INTO technologies (id, type_id, variant_code, display_name, sort_order) VALUES ('bb000000-0000-0000-0000-000000000093', 'aa000000-0000-0000-0000-000000000093', 'gap_a', 'Gap A', 93) ON CONFLICT DO NOTHING",
        "INSERT INTO technology_types (id, code, display_name, public_name, sort_order) VALUES ('aa000000-0000-0000-0000-000000000094', 'GAP_B', 'Gap B', 'Gap B', 94) ON CONFLICT DO NOTHING",
        "INSERT INTO technologies (id, type_id, variant_code, display_name, sort_order) VALUES ('bb000000-0000-0000-0000-000000000094', 'aa000000-0000-0000-0000-000000000094', 'gap_b', 'Gap B', 94) ON CONFLICT DO NOTHING",
        "INSERT INTO users (id, username, email, role, active, created_at) VALUES ('cc000000-0000-0000-0000-000000000093', 'gap_user', 'gap@test.lt', 'admin', true, NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO service_zones (id, name, polygon, priority, source, created_at) VALUES ('{ZONE_ID}', 'Auto: Gap A — Gapkaimis', ST_GeomFromEWKT('SRID=4326;MULTIPOLYGON(((25.0 54.0, 25.1 54.0, 25.1 54.1, 25.0 54.1, 25.0 54.0)))'), 100, 'auto', NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO zone_offerings (id, zone_id, technology_id, status, max_download_mbps, max_upload_mbps, status_since, created_at, updated_at) VALUES ('ee000000-0000-0000-0000-000000000093', '{ZONE_ID}', 'bb000000-0000-0000-0000-000000000093', 'available', 1000, 500, CURRENT_DATE, NOW(), NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO address_offerings (id, address_code, technology_id, status, max_download_mbps, max_upload_mbps, status_since, created_by, created_at, updated_at) VALUES ('ff000000-0000-0000-0000-000000000093', {ADDR_COVERED}, 'bb000000-0000-0000-0000-000000000093', 'available', 1000, 500, CURRENT_DATE, 'cc000000-0000-0000-0000-000000000093', NOW(), NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO address_offerings (id, address_code, technology_id, status, max_download_mbps, max_upload_mbps, status_since, created_by, created_at, updated_at) VALUES ('ff000000-0000-0000-0000-000000000094', {ADDR_GAP}, 'bb000000-0000-0000-0000-000000000094', 'available', 100, 50, CURRENT_DATE, 'cc000000-0000-0000-0000-000000000093', NOW(), NOW()) ON CONFLICT DO NOTHING",
    ]
    for stmt in stmts:
        await db_session.execute(text(stmt))


@pytest.mark.integration
async def test_has_override_is_per_zone_technology(client, admin_user, gap_setup):
    _, raw = admin_user
    resp = await client.get(f"/api/v1/admin/zones/{ZONE_ID}/addresses", headers={"X-API-Key": raw})
    assert resp.status_code == 200
    by_rc = {i["rc_code"]: i for i in resp.json()["items"]}
    assert by_rc[ADDR_COVERED]["has_override"] is True
    # Oferta innej technologii (Gap B) nie liczy sie jako pokrycie strefy Gap A.
    assert by_rc[ADDR_GAP]["has_override"] is False


@pytest.mark.integration
async def test_without_offering_returns_only_gaps(client, admin_user, gap_setup):
    _, raw = admin_user
    resp = await client.get(
        f"/api/v1/admin/zones/{ZONE_ID}/addresses",
        params={"without_offering": "true"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert [i["rc_code"] for i in body["items"]] == [ADDR_GAP]


@pytest.mark.integration
async def test_zone_detail_has_gap_count(client, admin_user, gap_setup):
    _, raw = admin_user
    resp = await client.get(
        f"/api/v1/admin/zones/{ZONE_ID}",
        params={"expand": "detail"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["address_count"] == 2
    assert body["gap_count"] == 1
