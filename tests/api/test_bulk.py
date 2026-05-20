import secrets

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


def _make_user(role: str):
    async def fx(db_session):
        raw = "etn_pk_" + secrets.token_urlsafe(32)
        name = f"{role}_{secrets.token_hex(4)}"
        user = User(username=name, email=f"{name}@example.com", role=role, active=True)
        db_session.add(user)
        await db_session.flush()
        hashed = bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=4)).decode()
        db_session.add(ApiKey(user_id=user.id, key_hash=hashed, name="k"))
        await db_session.flush()
        return user, raw
    fx.__name__ = f"{role}_user"
    return fx


admin_user = pytest.fixture(_make_user("admin"))
editor_user = pytest.fixture(_make_user("editor"))
viewer_user = pytest.fixture(_make_user("viewer"))


@pytest.fixture
async def locality_code(db_session) -> int:
    code = 82100
    stmts = [
        "INSERT INTO counties (rc_code, name, synced_at) VALUES (82001, 'Bulk Apskritis', NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO municipalities (rc_code, county_code, name, type, synced_at) VALUES (82100, 82001, 'Bulk Sav.', 'rajono', NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO localities (rc_code, muni_code, name, type, synced_at) VALUES ({code}, 82100, 'Bulkinkai', 'miestas', NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO streets (rc_code, locality_code, name, full_name, synced_at) VALUES (821001, {code}, 'Bulk g.', 'Bulk g., Bulkinkai', NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO addresses (rc_code, street_code, locality_code, house_no, postal_code, synced_at, point, address_type) VALUES (82199901, 821001, {code}, '1', '00001', NOW(), ST_GeomFromEWKT('SRID=4326;POINT(25.6 54.6)'), 'building') ON CONFLICT DO NOTHING",
        f"INSERT INTO addresses (rc_code, street_code, locality_code, house_no, postal_code, synced_at, point, address_type) VALUES (82199902, 821001, {code}, '2', '00001', NOW(), ST_GeomFromEWKT('SRID=4326;POINT(25.6 54.6)'), 'building') ON CONFLICT DO NOTHING",
        f"INSERT INTO addresses (rc_code, street_code, locality_code, house_no, postal_code, synced_at, point, address_type) VALUES (82199903, 821001, {code}, '3', '00001', NOW(), ST_GeomFromEWKT('SRID=4326;POINT(25.6 54.6)'), 'building') ON CONFLICT DO NOTHING",
    ]
    for s in stmts:
        await db_session.execute(text(s))
    return code


@pytest.fixture
async def tech(db_session) -> Technology:
    code = f"BULK_{secrets.token_hex(3).upper()}"
    tt = TechnologyType(code=code, display_name="BulkType", public_name="BT", sort_order=997, active=True)
    db_session.add(tt)
    await db_session.flush()
    t = Technology(type_id=tt.id, variant_code=f"BTV_{secrets.token_hex(3).upper()}",
                   display_name="BulkVariant", sort_order=997, active=True)
    db_session.add(t)
    await db_session.flush()
    return t


def _op(tech_id) -> dict:
    return {
        "type": "add_offering",
        "technology_id": str(tech_id),
        "status": "available",
        "max_dl_mbps": 1000,
        "max_ul_mbps": 500,
        "status_since": "2026-01-01",
    }


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_preview_returns_count_and_token(client, editor_user, locality_code, tech):
    _, raw = editor_user
    resp = await client.post(
        "/api/v1/admin/bulk/preview",
        json={"operation": _op(tech.id), "filter": {"locality_code": locality_code}},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["affected_count"] == 3
    assert data["preview_token"].startswith("tmp_")
    assert len(data["sample"]) == 3


@pytest.mark.integration
async def test_preview_empty_filter_rejected(client, editor_user, tech):
    _, raw = editor_user
    resp = await client.post(
        "/api/v1/admin/bulk/preview",
        json={"operation": _op(tech.id), "filter": {}},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_preview_no_match_returns_null_token(client, editor_user, tech):
    _, raw = editor_user
    resp = await client.post(
        "/api/v1/admin/bulk/preview",
        json={"operation": _op(tech.id), "filter": {"locality_code": 999999}},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    assert resp.json()["preview_token"] is None
    assert resp.json()["affected_count"] == 0


@pytest.mark.integration
async def test_preview_forbidden_for_viewer(client, viewer_user, locality_code, tech):
    _, raw = viewer_user
    resp = await client.post(
        "/api/v1/admin/bulk/preview",
        json={"operation": _op(tech.id), "filter": {"locality_code": locality_code}},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_execute_creates_offerings(client, editor_user, locality_code, tech):
    _, raw = editor_user

    preview = await client.post(
        "/api/v1/admin/bulk/preview",
        json={"operation": _op(tech.id), "filter": {"locality_code": locality_code}},
        headers={"X-API-Key": raw},
    )
    token = preview.json()["preview_token"]

    exec_resp = await client.post(
        "/api/v1/admin/bulk/execute",
        json={"preview_token": token},
        headers={"X-API-Key": raw},
    )
    assert exec_resp.status_code == 201
    data = exec_resp.json()
    assert data["modified_count"] == 3
    assert "bulk_operation_id" in data


@pytest.mark.integration
async def test_execute_skips_existing_offerings(client, editor_user, locality_code, tech):
    _, raw = editor_user

    # First execute
    p1 = await client.post(
        "/api/v1/admin/bulk/preview",
        json={"operation": _op(tech.id), "filter": {"locality_code": locality_code}},
        headers={"X-API-Key": raw},
    )
    await client.post("/api/v1/admin/bulk/execute",
                      json={"preview_token": p1.json()["preview_token"]},
                      headers={"X-API-Key": raw})

    # Second execute — all already exist
    p2 = await client.post(
        "/api/v1/admin/bulk/preview",
        json={"operation": _op(tech.id), "filter": {"locality_code": locality_code}},
        headers={"X-API-Key": raw},
    )
    exec2 = await client.post("/api/v1/admin/bulk/execute",
                               json={"preview_token": p2.json()["preview_token"]},
                               headers={"X-API-Key": raw})
    assert exec2.json()["modified_count"] == 0


@pytest.mark.integration
async def test_execute_invalid_token(client, editor_user):
    _, raw = editor_user
    resp = await client.post(
        "/api/v1/admin/bulk/execute",
        json={"preview_token": "tmp_invalid"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_execute_token_single_use(client, editor_user, locality_code, tech):
    _, raw = editor_user
    preview = await client.post(
        "/api/v1/admin/bulk/preview",
        json={"operation": _op(tech.id), "filter": {"locality_code": locality_code}},
        headers={"X-API-Key": raw},
    )
    token = preview.json()["preview_token"]

    await client.post("/api/v1/admin/bulk/execute",
                      json={"preview_token": token}, headers={"X-API-Key": raw})

    # Second use of same token
    resp2 = await client.post("/api/v1/admin/bulk/execute",
                               json={"preview_token": token}, headers={"X-API-Key": raw})
    assert resp2.status_code == 422


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_rollback_removes_offerings(client, editor_user, locality_code, tech):
    _, raw = editor_user

    preview = await client.post(
        "/api/v1/admin/bulk/preview",
        json={"operation": _op(tech.id), "filter": {"locality_code": locality_code}},
        headers={"X-API-Key": raw},
    )
    exec_resp = await client.post(
        "/api/v1/admin/bulk/execute",
        json={"preview_token": preview.json()["preview_token"]},
        headers={"X-API-Key": raw},
    )
    bulk_op_id = exec_resp.json()["bulk_operation_id"]

    rollback_resp = await client.post(
        f"/api/v1/admin/bulk/{bulk_op_id}/rollback",
        headers={"X-API-Key": raw},
    )
    assert rollback_resp.status_code == 204

    # Verify offerings removed
    for rc in [82199901, 82199902, 82199903]:
        offerings = await client.get(
            f"/api/v1/admin/addresses/{rc}/offerings",
            headers={"X-API-Key": raw},
        )
        assert not any(o["technology_id"] == str(tech.id) for o in offerings.json())


@pytest.mark.integration
async def test_rollback_twice_rejected(client, editor_user, locality_code, tech):
    _, raw = editor_user
    preview = await client.post(
        "/api/v1/admin/bulk/preview",
        json={"operation": _op(tech.id), "filter": {"locality_code": locality_code}},
        headers={"X-API-Key": raw},
    )
    exec_resp = await client.post(
        "/api/v1/admin/bulk/execute",
        json={"preview_token": preview.json()["preview_token"]},
        headers={"X-API-Key": raw},
    )
    bulk_op_id = exec_resp.json()["bulk_operation_id"]

    await client.post(f"/api/v1/admin/bulk/{bulk_op_id}/rollback", headers={"X-API-Key": raw})
    resp2 = await client.post(f"/api/v1/admin/bulk/{bulk_op_id}/rollback", headers={"X-API-Key": raw})
    assert resp2.status_code == 409


# ---------------------------------------------------------------------------
# List bulk operations
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_list_bulk_operations(client, editor_user, admin_user, locality_code, tech):
    _, editor_raw = editor_user
    _, admin_raw = admin_user

    preview = await client.post(
        "/api/v1/admin/bulk/preview",
        json={"operation": _op(tech.id), "filter": {"locality_code": locality_code}},
        headers={"X-API-Key": editor_raw},
    )
    await client.post("/api/v1/admin/bulk/execute",
                      json={"preview_token": preview.json()["preview_token"]},
                      headers={"X-API-Key": editor_raw})

    resp = await client.get("/api/v1/admin/bulk-operations", headers={"X-API-Key": admin_raw})
    assert resp.status_code == 200
    ops = resp.json()
    assert any(o["operation_type"] == "add_offering" for o in ops)


@pytest.mark.integration
async def test_list_bulk_operations_viewer_allowed(client, viewer_user):
    _, raw = viewer_user
    resp = await client.get("/api/v1/admin/bulk-operations", headers={"X-API-Key": raw})
    assert resp.status_code == 200
