"""Soft-deleted zones must not leak into address availability (admin endpoints).

Regression tests: zone queries in admin addresses/map endpoints must filter
service_zones.deleted_at IS NULL like the public availability endpoint does.
"""

import secrets
import uuid

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.dependencies import get_db
from app.main import app
from app.models.admin import ApiKey, User
from app.models.service import ServiceZone, ZoneOffering
from app.models.technology import Technology, TechnologyType

# Skuodas region — far away from any real zone polygon in the dev DB.
RC_ADDRESS = 82199901
LON, LAT = 21.0, 56.2


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
async def seed_address(db_session) -> int:
    stmts = [
        "INSERT INTO counties (rc_code, name, synced_at) VALUES (82001, 'Del Apskritis', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO municipalities (rc_code, county_code, name, type, synced_at) VALUES (82100, 82001, 'Del Sav', 'rajono', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO localities (rc_code, muni_code, name, type, synced_at) VALUES (82100, 82100, 'Delinkai', 'miestas', NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO addresses (rc_code, locality_code, house_no, synced_at, point, address_type) "
        f"VALUES ({RC_ADDRESS}, 82100, '8', NOW(), ST_GeomFromEWKT('SRID=4326;POINT({LON} {LAT})'), 'building') "
        "ON CONFLICT DO NOTHING",
    ]
    for s in stmts:
        await db_session.execute(text(s))
    return RC_ADDRESS


@pytest.fixture
async def deleted_zone_over_address(db_session, admin_user) -> uuid.UUID:
    """An (initially active) zone whose polygon contains the seeded address."""
    user, _ = admin_user
    code = f"DELZ_{secrets.token_hex(3).upper()}"
    tt = TechnologyType(code=code, display_name="DelZ", public_name="DelZ")
    db_session.add(tt)
    await db_session.flush()
    tech = Technology(type_id=tt.id, variant_code=f"delz_{secrets.token_hex(3)}", display_name="DelZ Tech")
    zone = ServiceZone(name=f"Del Zone {code}", created_by=user.id)
    db_session.add_all([tech, zone])
    await db_session.flush()
    await db_session.execute(
        text(
            "UPDATE service_zones SET polygon = ST_SetSRID(ST_GeomFromText("
            f"'MULTIPOLYGON((({LON - 0.05} {LAT - 0.05}, {LON + 0.05} {LAT - 0.05}, "
            f"{LON + 0.05} {LAT + 0.05}, {LON - 0.05} {LAT + 0.05}, {LON - 0.05} {LAT - 0.05})))'), 4326) "
            "WHERE id = :id"
        ),
        {"id": str(zone.id)},
    )
    db_session.add(
        ZoneOffering(
            zone_id=zone.id,
            technology_id=tech.id,
            status="available",
            max_download_mbps=100,
            max_upload_mbps=50,
            status_since=__import__("datetime").date(2026, 6, 1),
        )
    )
    await db_session.flush()
    return zone.id


async def _soft_delete(db_session, zone_id: uuid.UUID) -> None:
    await db_session.execute(
        text("UPDATE service_zones SET deleted_at = NOW() WHERE id = :id"),
        {"id": str(zone_id)},
    )


@pytest.mark.integration
async def test_zone_coverage_excludes_deleted_zone(client, admin_user, seed_address, deleted_zone_over_address, db_session):
    _, raw = admin_user
    headers = {"X-API-Key": raw}
    url = f"/api/v1/admin/addresses/{seed_address}/zone-coverage"

    # Control: active zone is visible.
    before = (await client.get(url, headers=headers)).json()
    assert any("Del Zone" in item["zone_name"] for item in before["items"])

    await _soft_delete(db_session, deleted_zone_over_address)

    after = (await client.get(url, headers=headers)).json()
    assert not any("Del Zone" in item["zone_name"] for item in after["items"])


@pytest.mark.integration
async def test_search_has_offering_excludes_deleted_zone(client, admin_user, seed_address, deleted_zone_over_address, db_session):
    _, raw = admin_user
    headers = {"X-API-Key": raw}
    params = {"locality_code": 82100, "has_offering": "true"}

    before = (await client.get("/api/v1/admin/addresses", params=params, headers=headers)).json()
    assert any(r["rc_code"] == seed_address for r in before["items"])

    await _soft_delete(db_session, deleted_zone_over_address)

    after = (await client.get("/api/v1/admin/addresses", params=params, headers=headers)).json()
    assert not any(r["rc_code"] == seed_address for r in after["items"])


@pytest.mark.integration
async def test_map_has_zone_offering_excludes_deleted_zone(client, admin_user, seed_address, deleted_zone_over_address, db_session):
    _, raw = admin_user
    headers = {"X-API-Key": raw}
    bbox = f"{LON - 0.01},{LAT - 0.01},{LON + 0.01},{LAT + 0.01}"

    def _feature(payload):
        return next(
            (f for f in payload["features"] if f["properties"]["rc_code"] == seed_address), None
        )

    before = (await client.get("/api/v1/admin/map/addresses", params={"bbox": bbox}, headers=headers)).json()
    feat = _feature(before)
    assert feat is not None
    assert feat["properties"]["has_zone_offering"] is True

    await _soft_delete(db_session, deleted_zone_over_address)

    after = (await client.get("/api/v1/admin/map/addresses", params={"bbox": bbox}, headers=headers)).json()
    assert _feature(after)["properties"]["has_zone_offering"] is False
