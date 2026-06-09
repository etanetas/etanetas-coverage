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
        db_session.add(ApiKey(user_id=user.id, key_hash=hashed, key_prefix=raw[:11], name="k"))
        await db_session.flush()
        return user, raw
    fx.__name__ = f"{role}_user"
    return fx


admin_user = pytest.fixture(_make_user("admin"))
editor_user = pytest.fixture(_make_user("editor"))


@pytest.fixture
async def seed_address(db_session):
    rc = 81199901
    stmts = [
        "INSERT INTO counties (rc_code, name, synced_at) VALUES (81001, 'Audit Apskritis', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO municipalities (rc_code, county_code, name, type, synced_at) VALUES (81100, 81001, 'Audit Sav.', 'rajono', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO localities (rc_code, muni_code, name, type, synced_at) VALUES (81100, 81100, 'Auditinkai', 'miestas', NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO addresses (rc_code, locality_code, house_no, postal_code, synced_at, point, address_type) VALUES ({rc}, 81100, '1', '00001', NOW(), ST_GeomFromEWKT('SRID=4326;POINT(25.5 54.5)'), 'building') ON CONFLICT DO NOTHING",
    ]
    for s in stmts:
        await db_session.execute(text(s))
    return rc


@pytest.fixture
async def seed_tech(db_session):
    code = f"ATEST_{secrets.token_hex(3).upper()}"
    tt = TechnologyType(code=code, display_name="AuditType", public_name="AT", sort_order=998)
    db_session.add(tt)
    await db_session.flush()
    tech = Technology(type_id=tt.id, variant_code=f"ATV_{secrets.token_hex(3).upper()}",
                      display_name="AuditVariant", sort_order=998)
    db_session.add(tech)
    await db_session.flush()
    return tt, tech


@pytest.mark.integration
async def test_audit_log_created_on_offering_create(client, editor_user, admin_user, seed_address, seed_tech):
    _, editor_raw = editor_user
    _, admin_raw = admin_user
    _, tech = seed_tech

    await client.post(
        f"/api/v1/admin/addresses/{seed_address}/offerings",
        json={"technology_id": str(tech.id), "status": "available",
              "max_download_mbps": 100, "max_upload_mbps": 50, "status_since": "2026-01-01"},
        headers={"X-API-Key": editor_raw},
    )

    resp = await client.get(
        "/api/v1/admin/audit-log",
        params={"entity_type": "address_offering"},
        headers={"X-API-Key": admin_raw},
    )
    assert resp.status_code == 200
    entries = resp.json()["items"]
    assert any(e["action"] == "create" and e["diff"]["address_code"] == seed_address for e in entries)


@pytest.mark.integration
async def test_address_history(client, editor_user, admin_user, seed_address, seed_tech):
    _, editor_raw = editor_user
    _, admin_raw = admin_user
    _, tech = seed_tech

    create_resp = await client.post(
        f"/api/v1/admin/addresses/{seed_address}/offerings",
        json={"technology_id": str(tech.id), "status": "planned",
              "max_download_mbps": 200, "max_upload_mbps": 100, "status_since": "2026-01-01"},
        headers={"X-API-Key": editor_raw},
    )
    offering_id = create_resp.json()["id"]

    await client.patch(
        f"/api/v1/admin/addresses/offerings/{offering_id}",
        json={"status": "available"},
        headers={"X-API-Key": editor_raw},
    )

    resp = await client.get(
        f"/api/v1/admin/addresses/{seed_address}/history",
        headers={"X-API-Key": admin_raw},
    )
    assert resp.status_code == 200
    entries = resp.json()["items"]
    actions = [e["action"] for e in entries]
    assert "create" in actions
    assert "update" in actions


@pytest.mark.integration
async def test_audit_log_viewer_forbidden(client, editor_user):
    _, raw = editor_user
    resp = await client.get("/api/v1/admin/audit-log", headers={"X-API-Key": raw})
    assert resp.status_code == 403


from app.db.audit_helpers import address_label_for_code, technology_display_name
import uuid as _uuid


@pytest.mark.integration
async def test_address_label_for_code_returns_label(db_session, seed_address):
    label = await address_label_for_code(db_session, seed_address)
    assert label is not None
    assert "1" in label        # house_no from seed_address fixture
    assert "Auditinkai" in label


@pytest.mark.integration
async def test_address_label_for_code_unknown_returns_none(db_session):
    label = await address_label_for_code(db_session, 999999999)
    assert label is None


@pytest.mark.integration
async def test_technology_display_name_returns_name(db_session, seed_tech):
    _, tech = seed_tech
    name = await technology_display_name(db_session, tech.id)
    assert name == "AuditVariant"


@pytest.mark.integration
async def test_technology_display_name_unknown_returns_none(db_session):
    name = await technology_display_name(db_session, _uuid.uuid4())
    assert name is None


@pytest.mark.integration
async def test_audit_log_filter_by_entity_type(client, admin_user, seed_tech):
    _, admin_raw = admin_user
    _, tech = seed_tech

    await client.patch(
        f"/api/v1/admin/technologies/{tech.id}",
        json={"display_name": "Updated for audit"},
        headers={"X-API-Key": admin_raw},
    )

    resp = await client.get(
        "/api/v1/admin/audit-log",
        params={"entity_type": "technology", "entity_id": str(tech.id)},
        headers={"X-API-Key": admin_raw},
    )
    assert resp.status_code == 200
    entries = resp.json()["items"]
    assert any(e["action"] == "update" for e in entries)
