import secrets
from datetime import datetime, timedelta

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


def _make_key() -> tuple[str, str]:
    raw = "etn_pk_" + secrets.token_urlsafe(32)
    hashed = bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=4)).decode()
    return raw, hashed


@pytest.fixture
async def active_user(db_session) -> User:
    name = "u_" + secrets.token_hex(4)
    user = User(username=name, email=f"{name}@example.com", role="admin", active=True)
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def valid_key(db_session, active_user) -> tuple[User, ApiKey, str]:
    raw, hashed = _make_key()
    key = ApiKey(user_id=active_user.id, key_hash=hashed, key_prefix=raw[:11], name="valid")
    db_session.add(key)
    await db_session.flush()
    return active_user, key, raw


@pytest.mark.integration
async def test_me_valid_key(client, valid_key):
    user, _, raw = valid_key
    resp = await client.get("/api/v1/admin/me", headers={"X-API-Key": raw})
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == user.username
    assert data["role"] == "admin"
    assert data["active"] is True


@pytest.mark.integration
async def test_me_missing_key(client):
    resp = await client.get("/api/v1/admin/me")
    assert resp.status_code in (401, 403)


@pytest.mark.integration
async def test_me_invalid_key(client, valid_key):
    resp = await client.get("/api/v1/admin/me", headers={"X-API-Key": "etn_pk_wrong"})
    assert resp.status_code == 401


@pytest.mark.integration
async def test_me_revoked_key(client, db_session, active_user):
    raw, hashed = _make_key()
    key = ApiKey(
        user_id=active_user.id,
        key_hash=hashed,
        key_prefix=raw[:11],
        name="revoked",
        revoked_at=datetime.now(),
    )
    db_session.add(key)
    await db_session.flush()

    resp = await client.get("/api/v1/admin/me", headers={"X-API-Key": raw})
    assert resp.status_code == 401


@pytest.mark.integration
async def test_me_expired_key(client, db_session, active_user):
    raw, hashed = _make_key()
    key = ApiKey(
        user_id=active_user.id,
        key_hash=hashed,
        key_prefix=raw[:11],
        name="expired",
        expires_at=datetime.now() - timedelta(days=1),
    )
    db_session.add(key)
    await db_session.flush()

    resp = await client.get("/api/v1/admin/me", headers={"X-API-Key": raw})
    assert resp.status_code == 401


@pytest.mark.integration
async def test_me_inactive_user(client, db_session):
    raw, hashed = _make_key()
    name = "inactive_" + secrets.token_hex(4)
    user = User(username=name, email=f"{name}@example.com", role="viewer", active=False)
    db_session.add(user)
    await db_session.flush()

    key = ApiKey(user_id=user.id, key_hash=hashed, key_prefix=raw[:11], name="inactive-user-key")
    db_session.add(key)
    await db_session.flush()

    resp = await client.get("/api/v1/admin/me", headers={"X-API-Key": raw})
    assert resp.status_code == 401
