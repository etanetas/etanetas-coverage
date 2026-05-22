import secrets

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

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


@pytest.fixture
async def admin(db_session) -> tuple[User, str]:
    raw = "etn_pk_" + secrets.token_urlsafe(32)
    name = f"adm_{secrets.token_hex(4)}"
    user = User(username=name, email=f"{name}@example.com", role="admin", active=True)
    db_session.add(user)
    await db_session.flush()
    hashed = bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=4)).decode()
    db_session.add(ApiKey(user_id=user.id, key_hash=hashed, key_prefix=raw[:11], name="k"))
    await db_session.flush()
    return user, raw


@pytest.mark.integration
async def test_api_key_create_is_audited(client, admin, db_session):
    _, raw = admin
    target = User(
        username=f"auditme_{secrets.token_hex(4)}",
        email=f"auditme_{secrets.token_hex(4)}@example.com",
        role="viewer",
        active=True,
    )
    db_session.add(target)
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/admin/users/{target.id}/api-keys",
        json={"name": "test"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 201

    rows = (
        await db_session.execute(
            text(
                "SELECT action, entity_type FROM audit_log WHERE entity_type='api_key' AND action='create' ORDER BY at DESC LIMIT 5"
            )
        )
    ).all()
    assert len(rows) >= 1


@pytest.mark.integration
async def test_api_key_revoke_is_audited(client, admin, db_session):
    _, raw = admin
    target = User(
        username=f"rev_{secrets.token_hex(4)}",
        email=f"rev_{secrets.token_hex(4)}@example.com",
        role="viewer",
        active=True,
    )
    db_session.add(target)
    await db_session.flush()

    create_resp = await client.post(
        f"/api/v1/admin/users/{target.id}/api-keys",
        json={"name": "tok"},
        headers={"X-API-Key": raw},
    )
    assert create_resp.status_code == 201
    key_id = create_resp.json()["id"]

    del_resp = await client.delete(
        f"/api/v1/admin/api-keys/{key_id}", headers={"X-API-Key": raw}
    )
    assert del_resp.status_code == 204

    rows = (
        await db_session.execute(
            text(
                "SELECT action FROM audit_log WHERE entity_type='api_key' AND entity_id=:id ORDER BY at DESC"
            ),
            {"id": str(key_id)},
        )
    ).all()
    actions = [r[0] for r in rows]
    assert "create" in actions
    assert "revoke" in actions
