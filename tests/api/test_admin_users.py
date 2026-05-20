import secrets
import uuid
from datetime import datetime

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient

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


def _hash(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=4)).decode()


def _unique(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


@pytest.fixture
async def admin(db_session) -> tuple[User, str]:
    raw = "etn_pk_" + secrets.token_urlsafe(32)
    name = _unique("admin")
    user = User(username=name, email=f"{name}@example.com", role="admin", active=True)
    db_session.add(user)
    await db_session.flush()
    db_session.add(ApiKey(user_id=user.id, key_hash=_hash(raw), name="k"))
    await db_session.flush()
    return user, raw


@pytest.fixture
async def viewer(db_session) -> tuple[User, str]:
    raw = "etn_pk_" + secrets.token_urlsafe(32)
    name = _unique("viewer")
    user = User(username=name, email=f"{name}@example.com", role="viewer", active=True)
    db_session.add(user)
    await db_session.flush()
    db_session.add(ApiKey(user_id=user.id, key_hash=_hash(raw), name="k"))
    await db_session.flush()
    return user, raw


@pytest.mark.integration
async def test_list_users(client, admin):
    _, raw = admin
    resp = await client.get("/api/v1/admin/users", headers={"X-API-Key": raw})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.integration
async def test_list_users_forbidden_for_viewer(client, viewer):
    _, raw = viewer
    resp = await client.get("/api/v1/admin/users", headers={"X-API-Key": raw})
    assert resp.status_code == 403


@pytest.mark.integration
async def test_create_user(client, admin):
    _, raw = admin
    resp = await client.post(
        "/api/v1/admin/users",
        json={"username": "neweditor", "email": "neweditor@example.com", "role": "editor"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "neweditor"
    assert data["role"] == "editor"
    assert data["active"] is True


@pytest.mark.integration
async def test_create_user_duplicate(client, admin):
    _, raw = admin
    payload = {"username": "dup", "email": "dup@example.com", "role": "viewer"}
    await client.post("/api/v1/admin/users", json=payload, headers={"X-API-Key": raw})
    resp = await client.post("/api/v1/admin/users", json=payload, headers={"X-API-Key": raw})
    assert resp.status_code == 409


@pytest.mark.integration
async def test_update_user(client, admin, db_session):
    admin_user, raw = admin
    other = User(username="other", email="other@example.com", role="viewer", active=True)
    db_session.add(other)
    await db_session.flush()

    resp = await client.put(
        f"/api/v1/admin/users/{other.id}",
        json={"role": "editor"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "editor"


@pytest.mark.integration
async def test_delete_user_deactivates(client, admin, db_session):
    _, raw = admin
    target = User(username="todelete", email="del@example.com", role="viewer", active=True)
    db_session.add(target)
    await db_session.flush()

    resp = await client.delete(f"/api/v1/admin/users/{target.id}", headers={"X-API-Key": raw})
    assert resp.status_code == 204

    await db_session.refresh(target)
    assert target.active is False


@pytest.mark.integration
async def test_delete_own_account_forbidden(client, admin):
    admin_user, raw = admin
    resp = await client.delete(f"/api/v1/admin/users/{admin_user.id}", headers={"X-API-Key": raw})
    assert resp.status_code == 400


@pytest.mark.integration
async def test_create_and_list_api_keys(client, admin, db_session):
    _, raw = admin
    target = User(username="keyuser", email="keyuser@example.com", role="editor", active=True)
    db_session.add(target)
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/admin/users/{target.id}/api-keys",
        json={"name": "main"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["raw_key"].startswith("etn_pk_")
    assert data["name"] == "main"

    list_resp = await client.get(
        f"/api/v1/admin/users/{target.id}/api-keys",
        headers={"X-API-Key": raw},
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


@pytest.mark.integration
async def test_revoke_api_key(client, admin, db_session):
    _, raw = admin
    target = User(username="revokeuser", email="revoke@example.com", role="viewer", active=True)
    db_session.add(target)
    await db_session.flush()

    create_resp = await client.post(
        f"/api/v1/admin/users/{target.id}/api-keys",
        json={"name": "tok"},
        headers={"X-API-Key": raw},
    )
    key_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/v1/admin/api-keys/{key_id}", headers={"X-API-Key": raw})
    assert resp.status_code == 204

    resp2 = await client.delete(f"/api/v1/admin/api-keys/{key_id}", headers={"X-API-Key": raw})
    assert resp2.status_code == 409


@pytest.mark.integration
async def test_user_not_found(client, admin):
    _, raw = admin
    resp = await client.get(f"/api/v1/admin/users/{uuid.uuid4()}/api-keys", headers={"X-API-Key": raw})
    assert resp.status_code == 404
