"""
Integration tests for admin CRUD: addresses, technologies, zones.
"""
import secrets
import uuid
from datetime import date

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


def _mk(role: str):
    """Return (User, raw_key) fixture factory for a given role."""
    async def fixture(db_session):
        raw = "etn_pk_" + secrets.token_urlsafe(32)
        name = f"{role}_{secrets.token_hex(4)}"
        user = User(username=name, email=f"{name}@example.com", role=role, active=True)
        db_session.add(user)
        await db_session.flush()
        hashed = bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=4)).decode()
        db_session.add(ApiKey(user_id=user.id, key_hash=hashed, key_prefix=raw[:11], name="k"))
        await db_session.flush()
        return user, raw
    fixture.__name__ = f"{role}_user"
    return fixture


admin_user = pytest.fixture(_mk("admin"))
editor_user = pytest.fixture(_mk("editor"))
viewer_user = pytest.fixture(_mk("viewer"))


@pytest.fixture
async def seed_address(db_session):
    stmts = [
        "INSERT INTO counties (rc_code, name, synced_at) VALUES (80001, 'CRUD Apskritis', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO municipalities (rc_code, county_code, name, type, synced_at) VALUES (80100, 80001, 'CRUD Savivaldybė', 'rajono', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO localities (rc_code, muni_code, name, type, synced_at) VALUES (80100, 80100, 'CRUDinkai', 'miestas', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO streets (rc_code, locality_code, name, full_name, synced_at) VALUES (801001, 80100, 'CRUD g.', 'CRUD g., CRUDinkai', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO addresses (rc_code, street_code, locality_code, house_no, postal_code, synced_at, point, address_type) VALUES (80199901, 801001, 80100, '5', '99999', NOW(), ST_GeomFromEWKT('SRID=4326;POINT(25.4 54.4)'), 'building') ON CONFLICT DO NOTHING",
    ]
    for s in stmts:
        await db_session.execute(text(s))
    return 80199901


@pytest.fixture
async def seed_tech(db_session) -> tuple[TechnologyType, Technology]:
    code = f"TEST_{secrets.token_hex(3).upper()}"
    tt = TechnologyType(
        code=code,
        display_name="Test Type",
        public_name="TestNet",
        sort_order=999,
    )
    db_session.add(tt)
    await db_session.flush()

    tech = Technology(
        type_id=tt.id,
        variant_code=f"TEST_V_{secrets.token_hex(3).upper()}",
        display_name="Test Variant",
        sort_order=999,
    )
    db_session.add(tech)
    await db_session.flush()
    return tt, tech


# ---------------------------------------------------------------------------
# Addresses — search & detail
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_address_search(client, admin_user, seed_address):
    _, raw = admin_user
    resp = await client.get(
        "/api/v1/admin/addresses",
        params={"q": "CRUD g."},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data and "items" in data
    assert any(r["rc_code"] == seed_address for r in data["items"])


@pytest.mark.integration
async def test_address_search_viewer_allowed(client, viewer_user, seed_address):
    _, raw = viewer_user
    resp = await client.get(
        "/api/v1/admin/addresses",
        params={"q": "CRUD g."},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200


@pytest.mark.integration
async def test_address_list_no_q_paginates(client, admin_user, seed_address):
    _, raw = admin_user
    resp = await client.get(
        "/api/v1/admin/addresses",
        params={"limit": 5},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert len(data["items"]) <= 5


@pytest.mark.integration
async def test_address_list_limit_cap(client, admin_user):
    _, raw = admin_user
    resp = await client.get(
        "/api/v1/admin/addresses",
        params={"limit": 101},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_address_detail(client, admin_user, seed_address):
    _, raw = admin_user
    resp = await client.get(f"/api/v1/admin/addresses/{seed_address}", headers={"X-API-Key": raw})
    assert resp.status_code == 200
    data = resp.json()
    assert data["rc_code"] == seed_address
    assert data["house_no"] == "5"
    assert data["lon"] is not None
    assert data["lat"] is not None


@pytest.mark.integration
async def test_address_detail_not_found(client, admin_user):
    _, raw = admin_user
    resp = await client.get("/api/v1/admin/addresses/9999999", headers={"X-API-Key": raw})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Offerings on addresses
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_create_and_list_address_offering(client, editor_user, seed_address, seed_tech):
    _, raw = editor_user
    _, tech = seed_tech
    payload = {
        "technology_id": str(tech.id),
        "status": "available",
        "max_download_mbps": 1000,
        "max_upload_mbps": 200,
        "status_since": "2026-01-01",
    }
    create_resp = await client.post(
        f"/api/v1/admin/addresses/{seed_address}/offerings",
        json=payload,
        headers={"X-API-Key": raw},
    )
    assert create_resp.status_code == 201
    offering_id = create_resp.json()["id"]

    list_resp = await client.get(
        f"/api/v1/admin/addresses/{seed_address}/offerings",
        headers={"X-API-Key": raw},
    )
    assert list_resp.status_code == 200
    assert any(o["id"] == offering_id for o in list_resp.json()["items"])


@pytest.mark.integration
async def test_create_offering_duplicate_409(client, editor_user, seed_address, seed_tech):
    _, raw = editor_user
    _, tech = seed_tech
    payload = {
        "technology_id": str(tech.id),
        "status": "available",
        "max_download_mbps": 100,
        "max_upload_mbps": 50,
        "status_since": "2026-01-01",
    }
    await client.post(f"/api/v1/admin/addresses/{seed_address}/offerings", json=payload, headers={"X-API-Key": raw})
    resp = await client.post(f"/api/v1/admin/addresses/{seed_address}/offerings", json=payload, headers={"X-API-Key": raw})
    assert resp.status_code == 409


@pytest.mark.integration
async def test_update_and_delete_address_offering(client, editor_user, seed_address, seed_tech):
    _, raw = editor_user
    _, tech = seed_tech
    payload = {
        "technology_id": str(tech.id),
        "status": "planned",
        "max_download_mbps": 500,
        "max_upload_mbps": 100,
        "status_since": "2026-01-01",
    }
    create_resp = await client.post(
        f"/api/v1/admin/addresses/{seed_address}/offerings",
        json=payload,
        headers={"X-API-Key": raw},
    )
    offering_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/admin/addresses/offerings/{offering_id}",
        json={"status": "available", "max_download_mbps": 1000},
        headers={"X-API-Key": raw},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "available"
    assert update_resp.json()["max_download_mbps"] == 1000

    del_resp = await client.delete(
        f"/api/v1/admin/addresses/offerings/{offering_id}",
        headers={"X-API-Key": raw},
    )
    assert del_resp.status_code == 204


@pytest.mark.integration
async def test_viewer_cannot_create_offering(client, viewer_user, seed_address, seed_tech):
    _, raw = viewer_user
    _, tech = seed_tech
    payload = {
        "technology_id": str(tech.id),
        "status": "available",
        "max_download_mbps": 100,
        "max_upload_mbps": 50,
        "status_since": "2026-01-01",
    }
    resp = await client.post(
        f"/api/v1/admin/addresses/{seed_address}/offerings",
        json=payload,
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Technologies
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_list_technologies(client, viewer_user, seed_tech):
    _, raw = viewer_user
    resp = await client.get("/api/v1/admin/technologies", headers={"X-API-Key": raw})
    assert resp.status_code == 200
    assert "items" in resp.json()


@pytest.mark.integration
async def test_create_technology(client, admin_user, seed_tech):
    admin, raw = admin_user
    tt, _ = seed_tech
    resp = await client.post(
        "/api/v1/admin/technologies",
        json={
            "type_id": str(tt.id),
            "variant_code": f"NEW_{secrets.token_hex(4).upper()}",
            "display_name": "New Variant",
        },
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 201
    assert resp.json()["display_name"] == "New Variant"


@pytest.mark.integration
async def test_update_technology(client, admin_user, seed_tech):
    _, raw = admin_user
    _, tech = seed_tech
    resp = await client.patch(
        f"/api/v1/admin/technologies/{tech.id}",
        json={"display_name": "Updated Name", "sort_order": 50},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Updated Name"


@pytest.mark.integration
async def test_delete_technology_soft_deletes(client, admin_user, seed_tech):
    _, raw = admin_user
    _, tech = seed_tech
    resp = await client.delete(f"/api/v1/admin/technologies/{tech.id}", headers={"X-API-Key": raw})
    assert resp.status_code == 204

    list_resp = await client.get("/api/v1/admin/technologies", headers={"X-API-Key": raw})
    techs = [t for t in list_resp.json()["items"] if t["id"] == str(tech.id)]
    assert techs == []


@pytest.mark.integration
async def test_editor_cannot_manage_technologies(client, editor_user, seed_tech):
    _, raw = editor_user
    _, tech = seed_tech
    resp = await client.delete(f"/api/v1/admin/technologies/{tech.id}", headers={"X-API-Key": raw})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

@pytest.fixture
async def seed_zone(db_session, admin_user) -> tuple[uuid.UUID, str]:
    from app.models.service import ServiceZone
    user, raw = admin_user
    zone = ServiceZone(name="Test Zone", priority=10, created_by=user.id)
    db_session.add(zone)
    await db_session.flush()
    return zone.id, raw


@pytest.fixture
async def seed_zone_with_polygon(db_session, admin_user) -> tuple[uuid.UUID, str]:
    from app.models.service import ServiceZone
    from sqlalchemy import text
    user, raw = admin_user
    zone = ServiceZone(name="Polygon Zone", priority=5, created_by=user.id)
    db_session.add(zone)
    await db_session.flush()
    # Set a tiny square polygon
    await db_session.execute(
        text("UPDATE service_zones SET polygon = ST_SetSRID(ST_GeomFromText('POLYGON((25 54, 25.1 54, 25.1 54.1, 25 54.1, 25 54))'), 4326) WHERE id = :id"),
        {"id": str(zone.id)},
    )
    return zone.id, raw


@pytest.mark.integration
async def test_list_zones(client, admin_user, seed_zone):
    _, raw = admin_user
    resp = await client.get("/api/v1/admin/zones", headers={"X-API-Key": raw})
    assert resp.status_code == 200
    zone_id, _ = seed_zone
    assert any(z["id"] == str(zone_id) for z in resp.json()["items"])


@pytest.mark.integration
async def test_create_zone(client, editor_user):
    _, raw = editor_user
    resp = await client.post(
        "/api/v1/admin/zones",
        json={"name": "New Zone", "priority": 5},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "New Zone"
    assert resp.json()["has_polygon"] is False


@pytest.mark.integration
async def test_update_zone(client, editor_user, seed_zone):
    _, raw = editor_user
    zone_id, _ = seed_zone
    resp = await client.patch(
        f"/api/v1/admin/zones/{zone_id}",
        json={"name": "Renamed Zone", "priority": 99},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed Zone"
    assert resp.json()["priority"] == 99


@pytest.mark.integration
async def test_delete_zone_admin_only(client, editor_user, seed_zone):
    _, raw = editor_user
    zone_id, _ = seed_zone
    resp = await client.delete(f"/api/v1/admin/zones/{zone_id}", headers={"X-API-Key": raw})
    assert resp.status_code == 403


@pytest.mark.integration
async def test_delete_zone(client, admin_user, seed_zone):
    _, raw = admin_user
    zone_id, _ = seed_zone
    resp = await client.delete(f"/api/v1/admin/zones/{zone_id}", headers={"X-API-Key": raw})
    assert resp.status_code == 204


@pytest.mark.integration
async def test_delete_zone_soft_excludes_from_list(client, admin_user, seed_zone):
    _, raw = admin_user
    zone_id, _ = seed_zone
    del_resp = await client.delete(f"/api/v1/admin/zones/{zone_id}", headers={"X-API-Key": raw})
    assert del_resp.status_code == 204
    list_resp = await client.get("/api/v1/admin/zones", headers={"X-API-Key": raw})
    assert list_resp.status_code == 200
    assert not any(z["id"] == str(zone_id) for z in list_resp.json()["items"])


@pytest.mark.integration
async def test_delete_zone_soft_returns_404_on_detail(client, admin_user, seed_zone):
    _, raw = admin_user
    zone_id, _ = seed_zone
    await client.delete(f"/api/v1/admin/zones/{zone_id}", headers={"X-API-Key": raw})
    detail_resp = await client.get(f"/api/v1/admin/zones/{zone_id}/detail", headers={"X-API-Key": raw})
    assert detail_resp.status_code == 404


@pytest.mark.integration
async def test_delete_zone_soft_cannot_delete_twice(client, admin_user, seed_zone):
    _, raw = admin_user
    zone_id, _ = seed_zone
    await client.delete(f"/api/v1/admin/zones/{zone_id}", headers={"X-API-Key": raw})
    second_resp = await client.delete(f"/api/v1/admin/zones/{zone_id}", headers={"X-API-Key": raw})
    assert second_resp.status_code == 404


@pytest.mark.integration
async def test_create_and_list_zone_offering(client, editor_user, seed_zone, seed_tech):
    _, raw = editor_user
    zone_id, _ = seed_zone
    _, tech = seed_tech
    payload = {
        "technology_id": str(tech.id),
        "status": "available",
        "max_download_mbps": 300,
        "max_upload_mbps": 100,
        "status_since": "2026-01-01",
    }
    create_resp = await client.post(
        f"/api/v1/admin/zones/{zone_id}/offerings",
        json=payload,
        headers={"X-API-Key": raw},
    )
    assert create_resp.status_code == 201

    list_resp = await client.get(
        f"/api/v1/admin/zones/{zone_id}/offerings",
        headers={"X-API-Key": raw},
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 1
    assert len(list_resp.json()["items"]) == 1


@pytest.mark.integration
async def test_zone_offering_duplicate_409(client, editor_user, seed_zone, seed_tech):
    _, raw = editor_user
    zone_id, _ = seed_zone
    _, tech = seed_tech
    payload = {
        "technology_id": str(tech.id),
        "status": "available",
        "max_download_mbps": 300,
        "max_upload_mbps": 100,
        "status_since": "2026-01-01",
    }
    await client.post(f"/api/v1/admin/zones/{zone_id}/offerings", json=payload, headers={"X-API-Key": raw})
    resp = await client.post(f"/api/v1/admin/zones/{zone_id}/offerings", json=payload, headers={"X-API-Key": raw})
    assert resp.status_code == 409


@pytest.mark.integration
async def test_update_zone_offering(client, editor_user, seed_zone, seed_tech):
    _, raw = editor_user
    zone_id, _ = seed_zone
    _, tech = seed_tech
    create_resp = await client.post(
        f"/api/v1/admin/zones/{zone_id}/offerings",
        json={"technology_id": str(tech.id), "status": "planned", "max_download_mbps": 100, "max_upload_mbps": 50, "status_since": "2026-01-01"},
        headers={"X-API-Key": raw},
    )
    assert create_resp.status_code == 201
    offering_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/admin/zones/offerings/{offering_id}",
        json={"status": "available", "max_download_mbps": 500},
        headers={"X-API-Key": raw},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "available"
    assert update_resp.json()["max_download_mbps"] == 500


@pytest.mark.integration
async def test_delete_zone_offering(client, editor_user, seed_zone, seed_tech):
    _, raw = editor_user
    zone_id, _ = seed_zone
    _, tech = seed_tech
    create_resp = await client.post(
        f"/api/v1/admin/zones/{zone_id}/offerings",
        json={"technology_id": str(tech.id), "status": "available", "max_download_mbps": 200, "max_upload_mbps": 100, "status_since": "2026-01-01"},
        headers={"X-API-Key": raw},
    )
    offering_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/v1/admin/zones/offerings/{offering_id}", headers={"X-API-Key": raw})
    assert del_resp.status_code == 204

    list_resp = await client.get(f"/api/v1/admin/zones/{zone_id}/offerings", headers={"X-API-Key": raw})
    assert not any(o["id"] == offering_id for o in list_resp.json()["items"])


@pytest.mark.integration
async def test_list_offerings_returns_404_for_deleted_address(client, admin_user, db_session, seed_tech):
    """list_address_offerings must return 404 if the address is soft-deleted."""
    from sqlalchemy import text
    _, raw = admin_user
    _, tech = seed_tech
    # Seed a building address
    rc = 83199901
    stmts = [
        "INSERT INTO counties (rc_code, name, synced_at) VALUES (83001, 'Del Apskritis', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO municipalities (rc_code, county_code, name, type, synced_at) VALUES (83100, 83001, 'Del Sav.', 'rajono', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO localities (rc_code, muni_code, name, type, synced_at) VALUES (83100, 83100, 'Delinkai', 'miestas', NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO addresses (rc_code, locality_code, house_no, postal_code, synced_at, point, address_type) VALUES ({rc}, 83100, '9', '00001', NOW(), ST_GeomFromEWKT('SRID=4326;POINT(25.7 54.7)'), 'building') ON CONFLICT DO NOTHING",
    ]
    for s in stmts:
        await db_session.execute(text(s))

    # Address exists → 200
    resp = await client.get(f"/api/v1/admin/addresses/{rc}/offerings", headers={"X-API-Key": raw})
    assert resp.status_code == 200

    # Soft-delete the address
    await db_session.execute(text(f"UPDATE addresses SET deleted_at = NOW() WHERE rc_code = {rc}"))

    # Now must return 404
    resp2 = await client.get(f"/api/v1/admin/addresses/{rc}/offerings", headers={"X-API-Key": raw})
    assert resp2.status_code == 404


# ---------------------------------------------------------------------------
# Polygon tri-state update (T7.4 / T7.5)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_update_zone_polygon_omitted_keeps_existing(client, editor_user, seed_zone_with_polygon):
    _, raw = editor_user
    zone_id, _ = seed_zone_with_polygon
    # Patch only name — polygon must be preserved
    resp = await client.patch(
        f"/api/v1/admin/zones/{zone_id}",
        json={"name": "Renamed"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    detail = await client.get(f"/api/v1/admin/zones/{zone_id}/detail", headers={"X-API-Key": raw})
    assert detail.status_code == 200
    assert detail.json()["has_polygon"] is True


@pytest.mark.integration
async def test_update_zone_polygon_null_clears(client, editor_user, seed_zone_with_polygon):
    _, raw = editor_user
    zone_id, _ = seed_zone_with_polygon
    resp = await client.patch(
        f"/api/v1/admin/zones/{zone_id}",
        json={"polygon_geojson": None},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    detail = await client.get(f"/api/v1/admin/zones/{zone_id}/detail", headers={"X-API-Key": raw})
    assert detail.json()["has_polygon"] is False


@pytest.mark.integration
async def test_update_zone_polygon_replace(client, editor_user, seed_zone):
    _, raw = editor_user
    zone_id, _ = seed_zone  # zone without polygon
    new_polygon = {
        "type": "Polygon",
        "coordinates": [[[25, 54], [25.1, 54], [25.1, 54.1], [25, 54.1], [25, 54]]],
    }
    resp = await client.patch(
        f"/api/v1/admin/zones/{zone_id}",
        json={"polygon_geojson": new_polygon},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    detail = await client.get(f"/api/v1/admin/zones/{zone_id}/detail", headers={"X-API-Key": raw})
    assert detail.json()["has_polygon"] is True
