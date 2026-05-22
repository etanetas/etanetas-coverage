import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.dependencies import get_db
from app.main import app


@pytest.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def seed_address(db_session):
    stmts = [
        "INSERT INTO counties (rc_code, name, synced_at) VALUES (90001, 'Test Apskritis', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO municipalities (rc_code, county_code, name, type, synced_at) VALUES (90100, 90001, 'Test Savivaldybė', 'rajono', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO localities (rc_code, muni_code, name, type, synced_at) VALUES (90100, 90100, 'Testinkai', 'miestas', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO streets (rc_code, locality_code, name, full_name, synced_at) VALUES (901001, 90100, 'Testinė g.', 'Testinė g., Testinkai', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO addresses (rc_code, street_code, locality_code, house_no, postal_code, synced_at, point) VALUES (90199901, 901001, 90100, '12', '00001', NOW(), ST_GeomFromEWKT('SRID=4326;POINT(25.3 54.3)')) ON CONFLICT DO NOTHING",
    ]
    for stmt in stmts:
        await db_session.execute(text(stmt))
    return 90199901


@pytest.mark.integration
async def test_search_returns_list(client, seed_address):
    resp = await client.get("/api/v1/public/addresses/search?q=Testinė")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(r["rc_code"] == seed_address for r in data)


@pytest.mark.integration
async def test_search_missing_q_returns_422(client):
    resp = await client.get("/api/v1/public/addresses/search")
    assert resp.status_code == 422


@pytest.mark.integration
async def test_search_short_q_returns_422(client):
    resp = await client.get("/api/v1/public/addresses/search?q=a")
    assert resp.status_code == 422


@pytest.mark.integration
async def test_search_huge_q_returns_422(client):
    resp = await client.get("/api/v1/public/addresses/search", params={"q": "x" * 101})
    assert resp.status_code == 422


@pytest.mark.integration
async def test_availability_not_found(client):
    resp = await client.get("/api/v1/public/addresses/1/availability")
    assert resp.status_code == 404


@pytest.mark.integration
async def test_availability_structure(client, seed_address):
    resp = await client.get(f"/api/v1/public/addresses/{seed_address}/availability")
    assert resp.status_code == 200
    data = resp.json()
    assert data["address"]["rc_code"] == seed_address
    assert "full_address" in data["address"]
    assert isinstance(data["available"], list)
    assert isinstance(data["planned"], list)


@pytest.mark.integration
async def test_availability_with_zone_offering(client, db_session, seed_address):
    stmts = [
        "INSERT INTO technology_types (id, code, display_name, public_name, sort_order) VALUES ('aa000000-0000-0000-0000-000000000001', 'TEST_FIBER', 'Test Fiber', 'Test Fiber', 99) ON CONFLICT DO NOTHING",
        "INSERT INTO technologies (id, type_id, variant_code, display_name, sort_order) VALUES ('bb000000-0000-0000-0000-000000000001', 'aa000000-0000-0000-0000-000000000001', 'test_gpon', 'Test GPON', 99) ON CONFLICT DO NOTHING",
        "INSERT INTO users (id, username, email, role, active, created_at) VALUES ('cc000000-0000-0000-0000-000000000001', 'testuser_zone', 'testzone@test.lt', 'admin', true, NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO service_zones (id, name, polygon, priority, created_by, created_at) VALUES ('dd000000-0000-0000-0000-000000000001', 'Test Zone', ST_GeomFromEWKT('SRID=4326;MULTIPOLYGON(((24.0 53.0, 26.0 53.0, 26.0 55.0, 24.0 55.0, 24.0 53.0)))'), 100, 'cc000000-0000-0000-0000-000000000001', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO zone_offerings (id, zone_id, technology_id, status, max_download_mbps, max_upload_mbps, status_since, created_at, updated_at) VALUES ('ee000000-0000-0000-0000-000000000001', 'dd000000-0000-0000-0000-000000000001', 'bb000000-0000-0000-0000-000000000001', 'available', 1000, 500, CURRENT_DATE, NOW(), NOW()) ON CONFLICT DO NOTHING",
    ]
    for stmt in stmts:
        await db_session.execute(text(stmt))

    resp = await client.get(f"/api/v1/public/addresses/{seed_address}/availability")
    assert resp.status_code == 200
    data = resp.json()
    techs = [t["technology"] for t in data["available"]]
    assert "Test Fiber" in techs
