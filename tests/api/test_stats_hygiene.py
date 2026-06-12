"""Stats: raport planned-po-terminie i luk w auto-strefach."""

import secrets

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.dependencies import get_db
from app.main import app
from app.models.admin import ApiKey, User

ADDR_OVERDUE = 95199901  # planned z planned_until w przeszlosci, w strefie
ADDR_GAP = 95199902      # w strefie, bez oferty -> luka
ZONE_NAME = "Auto: Hyg A — Hygkaimis"


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
async def hygiene_setup(db_session):
    """Auto-strefa z 2 adresami: jeden ma oferte planned po terminie, drugi to luka."""
    stmts = [
        "INSERT INTO counties (rc_code, name, synced_at) VALUES (95001, 'Hyg Apskritis', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO municipalities (rc_code, county_code, name, type, synced_at) VALUES (95100, 95001, 'Hyg Sav.', 'rajono', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO localities (rc_code, muni_code, name, type, synced_at) VALUES (95100, 95100, 'Hygkaimis', 'k.', NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO addresses (rc_code, locality_code, house_no, synced_at, point, address_type) VALUES ({ADDR_OVERDUE}, 95100, '1', NOW(), ST_GeomFromEWKT('SRID=4326;POINT(20.05 55.95)'), 'building') ON CONFLICT DO NOTHING",
        f"INSERT INTO addresses (rc_code, locality_code, house_no, synced_at, point, address_type) VALUES ({ADDR_GAP}, 95100, '2', NOW(), ST_GeomFromEWKT('SRID=4326;POINT(20.06 55.96)'), 'building') ON CONFLICT DO NOTHING",
        "INSERT INTO technology_types (id, code, display_name, public_name, sort_order) VALUES ('aa000000-0000-0000-0000-000000000095', 'HYG_A', 'Hyg A', 'Hyg A', 95) ON CONFLICT DO NOTHING",
        "INSERT INTO technologies (id, type_id, variant_code, display_name, sort_order) VALUES ('bb000000-0000-0000-0000-000000000095', 'aa000000-0000-0000-0000-000000000095', 'hyg_a', 'Hyg A', 95) ON CONFLICT DO NOTHING",
        "INSERT INTO users (id, username, email, role, active, created_at) VALUES ('cc000000-0000-0000-0000-000000000095', 'hyg_user', 'hyg@test.lt', 'admin', true, NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO address_offerings (id, address_code, technology_id, status, max_download_mbps, max_upload_mbps, status_since, planned_until, created_by, created_at, updated_at) VALUES ('ff000000-0000-0000-0000-000000000095', {ADDR_OVERDUE}, 'bb000000-0000-0000-0000-000000000095', 'planned', 1000, 500, '1989-01-01', '1990-01-01', 'cc000000-0000-0000-0000-000000000095', NOW(), NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO service_zones (id, name, polygon, priority, source, created_at) VALUES ('dd000000-0000-0000-0000-000000000095', '{ZONE_NAME}', ST_GeomFromEWKT('SRID=4326;MULTIPOLYGON(((20.0 55.9, 20.1 55.9, 20.1 56.0, 20.0 56.0, 20.0 55.9)))'), 100, 'auto', NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO zone_offerings (id, zone_id, technology_id, status, max_download_mbps, max_upload_mbps, status_since, created_at, updated_at) VALUES ('ee000000-0000-0000-0000-000000000095', 'dd000000-0000-0000-0000-000000000095', 'bb000000-0000-0000-0000-000000000095', 'available', 1000, 500, CURRENT_DATE, NOW(), NOW()) ON CONFLICT DO NOTHING",
    ]
    for stmt in stmts:
        await db_session.execute(text(stmt))


@pytest.mark.integration
async def test_stats_reports_planned_overdue(client, admin_user, hygiene_setup):
    _, raw = admin_user
    resp = await client.get("/api/v1/admin/coverage/stats?scope=all", headers={"X-API-Key": raw})
    assert resp.status_code == 200
    body = resp.json()
    assert body["planned_overdue_count"] >= 1
    ours = [i for i in body["planned_overdue"] if i["address_code"] == ADDR_OVERDUE]
    assert len(ours) == 1
    assert ours[0]["technology"] == "Hyg A"
    assert ours[0]["planned_until"] == "1990-01-01"
    assert "Hygkaimis" in ours[0]["full_address"]


@pytest.mark.integration
async def test_stats_reports_auto_zone_gaps(client, admin_user, hygiene_setup):
    _, raw = admin_user
    resp = await client.get("/api/v1/admin/coverage/stats?scope=all", headers={"X-API-Key": raw})
    assert resp.status_code == 200
    body = resp.json()
    ours = [z for z in body["auto_zone_gaps"] if z["zone_name"] == ZONE_NAME]
    assert len(ours) == 1
    # ADDR_OVERDUE ma oferte technologii strefy (planned tez liczy sie jako oferta),
    # ADDR_GAP nie ma zadnej -> 1 luka z 2 adresow.
    assert ours[0]["gap_count"] == 1
    assert ours[0]["address_count"] == 2
    assert ours[0]["technology"] == "Hyg A"
    assert body["auto_zone_gaps_total"] >= 1
