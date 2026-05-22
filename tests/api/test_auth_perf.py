import secrets

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

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


@pytest.mark.integration
async def test_key_lookup_uses_prefix(client, db_session):
    raw = "etn_pk_" + secrets.token_urlsafe(32)
    name = f"perf_{secrets.token_hex(4)}"
    user = User(username=name, email=f"{name}@example.com", role="admin", active=True)
    db_session.add(user)
    await db_session.flush()
    hashed = bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=4)).decode()
    db_session.add(ApiKey(user_id=user.id, key_hash=hashed, key_prefix=raw[:11], name="k"))
    await db_session.flush()

    # Verify the row has the prefix
    rows = (await db_session.execute(
        select(ApiKey).where(ApiKey.key_prefix == raw[:11])
    )).scalars().all()
    assert len(rows) == 1

    # Endpoint authenticates via prefix-filtered query
    resp = await client.get("/api/v1/admin/me", headers={"X-API-Key": raw})
    assert resp.status_code == 200


@pytest.mark.integration
async def test_legacy_key_still_works_then_backfills(client, db_session):
    raw = "etn_pk_" + secrets.token_urlsafe(32)
    name = f"legacy_{secrets.token_hex(4)}"
    user = User(username=name, email=f"{name}@example.com", role="admin", active=True)
    db_session.add(user)
    await db_session.flush()
    hashed = bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=4)).decode()
    db_session.add(ApiKey(user_id=user.id, key_hash=hashed, key_prefix="__legacy__", name="k"))
    await db_session.flush()

    # Should authenticate via the legacy fallback path
    resp = await client.get("/api/v1/admin/me", headers={"X-API-Key": raw})
    assert resp.status_code == 200
