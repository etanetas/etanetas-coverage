# Etap 1-2: Availability bez stref + auto-zony per obszar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dostępność liczona wyłącznie z ofert adresowych; auto-zony rozbite na spójne obszary z trwałą tożsamością, nazwami z miejscowości i `custom_name`; raport luk (adresy w strefie bez oferty).

**Architecture:** Publiczny SQL availability traci CTE stref. Rebuild auto-zon robi `ST_Dump` unii buforów → po jednym rekordzie `service_zones` na komponent, dopasowanie do istniejących stref po największym przecięciu (greedy), nazwa z dominującej miejscowości (`mode()`), kolizje z sufiksem. `custom_name` (nowa kolumna) przeżywa rebuild. PATCH na strefie auto przyjmuje wyłącznie `custom_name`. `zones/{id}/addresses` dostaje `without_offering` i poprawną semantykę `has_override` (per technologia strefy); `ZoneDetail` dostaje `gap_count`.

**Tech Stack:** FastAPI + SQLAlchemy async + PostGIS, Alembic, pytest (integracyjne, wymagają PostgreSQL+PostGIS z migracjami — patrz `tests/conftest.py`).

**Repo:** `/home/robertas/workspace/robertas/etanetas-coverage` (wszystkie ścieżki względem tego katalogu).

**Spec:** `docs/superpowers/specs/2026-06-11-coverage-maintenance-model-design.md`

---

### Task 1: Availability liczy tylko oferty adresowe

**Files:**
- Modify: `app/api/v1/public/addresses.py:59-105` (`_AVAILABILITY_SQL`)
- Test: `tests/api/test_public_addresses.py:78-95`

- [ ] **Step 1: Przepisz test strefowy na negatywny + dodaj test oferty adresowej**

W `tests/api/test_public_addresses.py` zastąp cały `test_availability_with_zone_offering` (linie 78-95) dwoma testami:

```python
@pytest.mark.integration
async def test_availability_ignores_zone_offerings(client, db_session, seed_address):
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
    # Strefy (auto i reczne) nie wplywaja na dostepnosc — tylko oferty adresowe.
    assert "Test Fiber" not in techs


@pytest.mark.integration
async def test_availability_returns_address_offering(client, db_session, seed_address):
    stmts = [
        "INSERT INTO technology_types (id, code, display_name, public_name, sort_order) VALUES ('aa000000-0000-0000-0000-000000000001', 'TEST_FIBER', 'Test Fiber', 'Test Fiber', 99) ON CONFLICT DO NOTHING",
        "INSERT INTO technologies (id, type_id, variant_code, display_name, sort_order) VALUES ('bb000000-0000-0000-0000-000000000001', 'aa000000-0000-0000-0000-000000000001', 'test_gpon', 'Test GPON', 99) ON CONFLICT DO NOTHING",
        "INSERT INTO users (id, username, email, role, active, created_at) VALUES ('cc000000-0000-0000-0000-000000000001', 'testuser_zone', 'testzone@test.lt', 'admin', true, NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO address_offerings (id, address_code, technology_id, status, max_download_mbps, max_upload_mbps, status_since, created_by, created_at, updated_at) VALUES ('ff000000-0000-0000-0000-000000000001', 90199901, 'bb000000-0000-0000-0000-000000000001', 'available', 300, 100, CURRENT_DATE, 'cc000000-0000-0000-0000-000000000001', NOW(), NOW()) ON CONFLICT DO NOTHING",
    ]
    for stmt in stmts:
        await db_session.execute(text(stmt))

    resp = await client.get(f"/api/v1/public/addresses/{seed_address}/availability")
    assert resp.status_code == 200
    data = resp.json()
    rows = {t["technology"]: t for t in data["available"]}
    assert "Test Fiber" in rows
    assert rows["Test Fiber"]["max_dl_mbps"] == 300
    assert rows["Test Fiber"]["max_ul_mbps"] == 100
```

- [ ] **Step 2: Uruchom testy — nowy negatywny ma FAILOWAĆ**

Run: `uv run pytest tests/api/test_public_addresses.py -v`
Expected: `test_availability_ignores_zone_offerings` FAIL (asercja `not in` — stary SQL dolicza strefę), `test_availability_returns_address_offering` PASS.

- [ ] **Step 3: Zastąp `_AVAILABILITY_SQL`**

W `app/api/v1/public/addresses.py` zastąp całą definicję `_AVAILABILITY_SQL` (linie 59-105):

```python
# Dostepnosc liczy sie WYLACZNIE z ofert adresowych. Strefy (w tym auto-zony
# generowane z tych samych ofert) sa czysta wizualizacja — patrz spec
# docs/superpowers/specs/2026-06-11-coverage-maintenance-model-design.md
_AVAILABILITY_SQL = text("""
    SELECT
        tt.public_name            AS technology,
        MAX(ao.max_download_mbps) AS max_dl_mbps,
        MAX(ao.max_upload_mbps)   AS max_ul_mbps,
        ao.status,
        MIN(ao.planned_until)     AS planned_until
    FROM address_offerings ao
    JOIN technologies t ON t.id = ao.technology_id
    JOIN technology_types tt ON tt.id = t.type_id
    WHERE ao.address_code = :rc_code
      AND ao.status IN ('available', 'planned')
      AND tt.deleted_at IS NULL
      AND t.deleted_at IS NULL
    GROUP BY tt.id, tt.public_name, tt.sort_order, ao.status
    ORDER BY tt.sort_order
""")
```

- [ ] **Step 4: Testy przechodzą**

Run: `uv run pytest tests/api/test_public_addresses.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/v1/public/addresses.py tests/api/test_public_addresses.py
git commit -m "fix: availability liczy wylacznie oferty adresowe, strefy to czysta wizualizacja"
```

---

### Task 2: Migracja + model — `service_zones.custom_name`

**Files:**
- Create: `alembic/versions/<autogen>_add_service_zones_custom_name.py`
- Modify: `app/models/service.py:23-38` (klasa `ServiceZone`)

- [ ] **Step 1: Dodaj pole do modelu**

W `app/models/service.py`, w klasie `ServiceZone`, po linii `source: ...` dodaj:

```python
    # Nazwa wlasna nadana przez uzytkownika strefie auto; przezywa rebuildy.
    # Nazwa efektywna = COALESCE(custom_name, name).
    custom_name: Mapped[str | None] = mapped_column(Text)
```

- [ ] **Step 2: Wygeneruj migrację**

Run: `uv run alembic revision -m "add service_zones custom_name"`
Expected: nowy plik w `alembic/versions/`. Wypełnij go (wzorzec: `alembic/versions/c76434df3e06_add_service_zones_source_column.py`):

```python
def upgrade() -> None:
    op.add_column(
        "service_zones",
        sa.Column("custom_name", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("service_zones", "custom_name")
```

(import `sqlalchemy as sa` i `from alembic import op` zostawia szablon.)

- [ ] **Step 3: Zastosuj migrację**

Run: `uv run alembic upgrade head`
Expected: `Running upgrade ... add service_zones custom_name` bez błędów.

- [ ] **Step 4: Commit**

```bash
git add app/models/service.py alembic/versions/
git commit -m "feat: kolumna service_zones.custom_name - nazwa wlasna strefy auto przezywajaca rebuild"
```

---

### Task 3: `source` + `custom_name` w API stref, PATCH-guard dla stref auto

**Files:**
- Modify: `app/schemas/admin.py:180-222` (`ZoneOut`, `ZoneUpdate`)
- Modify: `app/api/v1/admin/zones.py` (wszystkie konstrukcje `ZoneOut` + `update_zone`)
- Create: `tests/api/test_zones_source.py`

- [ ] **Step 1: Napisz failujące testy**

Utwórz `tests/api/test_zones_source.py`:

```python
"""ZoneOut.source/custom_name + PATCH-guard stref auto."""

import secrets
import uuid

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
async def auto_zone(db_session):
    zone_id = uuid.uuid4()
    await db_session.execute(text(
        "INSERT INTO service_zones (id, name, polygon, priority, source, created_at) "
        "VALUES (CAST(:id AS uuid), 'Auto: T — X', "
        "ST_GeomFromEWKT('SRID=4326;MULTIPOLYGON(((25.0 54.0, 25.1 54.0, 25.1 54.1, 25.0 54.1, 25.0 54.0)))'), "
        "100, 'auto', NOW())"
    ), {"id": str(zone_id)})
    return zone_id


@pytest.mark.integration
async def test_created_zone_has_source_manual(client, admin_user):
    _, raw = admin_user
    resp = await client.post(
        "/api/v1/admin/zones",
        json={"name": "Reczna testowa"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["source"] == "manual"
    assert body["custom_name"] is None


@pytest.mark.integration
async def test_patch_auto_zone_rejects_non_custom_name(client, admin_user, auto_zone):
    _, raw = admin_user
    resp = await client.patch(
        f"/api/v1/admin/zones/{auto_zone}",
        json={"priority": 50},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 422


@pytest.mark.integration
async def test_patch_auto_zone_accepts_custom_name(client, admin_user, auto_zone):
    _, raw = admin_user
    resp = await client.patch(
        f"/api/v1/admin/zones/{auto_zone}",
        json={"custom_name": "Centrum"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["custom_name"] == "Centrum"
    assert body["source"] == "auto"


@pytest.mark.integration
async def test_patch_manual_zone_still_accepts_name(client, admin_user):
    _, raw = admin_user
    created = await client.post(
        "/api/v1/admin/zones",
        json={"name": "Do zmiany"},
        headers={"X-API-Key": raw},
    )
    zone_id = created.json()["id"]
    resp = await client.patch(
        f"/api/v1/admin/zones/{zone_id}",
        json={"name": "Zmieniona"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Zmieniona"
```

- [ ] **Step 2: Uruchom — mają FAILOWAĆ**

Run: `uv run pytest tests/api/test_zones_source.py -v`
Expected: FAIL — `KeyError: 'source'` / brak pola w odpowiedzi, PATCH priority na auto zwraca 200 zamiast 422.

- [ ] **Step 3: Rozszerz schematy**

W `app/schemas/admin.py`:

`ZoneOut` (linie 180-202) — dodaj dwa pola po `name`:

```python
class ZoneOut(BaseModel):
    id: uuid.UUID
    name: str
    custom_name: str | None = None
    source: str = "manual"
    description: str | None
    priority: int
    has_polygon: bool
    polygon_geojson: dict | None  # simplified GeoJSON for map rendering (may be None)
    created_at: datetime
```

(`json_schema_extra` bez zmian.)

`ZoneUpdate` (linie 218-222) — dodaj `custom_name`:

```python
class ZoneUpdate(BaseModel):
    name: str | None = None
    custom_name: str | None = None
    description: str | None = None
    priority: int | None = None
    polygon_geojson: PolygonGeoJSON | None = None
```

- [ ] **Step 4: Zaktualizuj wszystkie konstrukcje `ZoneOut` w `app/api/v1/admin/zones.py`**

a) `list_zones` — w SQL (linie 52-64) dodaj kolumny do SELECT:

```sql
        SELECT
            id, name, custom_name, source, description, priority, created_at,
            polygon IS NOT NULL AS has_polygon,
            ...
```

i w konstruktorze (linie 65-73) dodaj:

```python
    items = [ZoneOut(
        id=r["id"],
        name=r["name"],
        custom_name=r["custom_name"],
        source=r["source"],
        description=r["description"],
        priority=r["priority"],
        has_polygon=r["has_polygon"],
        polygon_geojson=r["polygon_geojson"],
        created_at=r["created_at"],
    ) for r in rows]
```

b) `get_zone` — w OBU gałęziach (`ZoneDetail` linia 114, `ZoneOut` linia 126) dodaj `custom_name=zone.custom_name, source=zone.source,` po `name=zone.name,`.

c) `create_zone` (linia 164) — dodaj `custom_name=None, source=zone.source,` po `name=zone.name,`.

d) `update_zone` (linia 214) — dodaj `custom_name=zone.custom_name, source=zone.source,` po `name=zone.name,`.

- [ ] **Step 5: PATCH-guard + obsługa `custom_name` w `update_zone`**

W `update_zone` (linie 178-222): zmień docstring i dodaj guard + przypisanie na początku, zaraz po `fields = body.model_fields_set`:

```python
    """Update a zone. Auto zones (source='auto') accept only custom_name; other fields are managed by the rebuild."""
    zone = await _require_zone(db, zone_id)

    fields = body.model_fields_set

    if zone.source == "auto" and (fields - {"custom_name"}):
        raise HTTPException(
            status_code=422,
            detail="Auto zones accept only custom_name updates; polygon/name/priority are managed by the rebuild",
        )

    if "custom_name" in fields:
        zone.custom_name = body.custom_name
```

(reszta funkcji bez zmian; `changes` w `log_action` automatycznie złapie `custom_name` przez `model_dump(exclude_none=True, ...)`).

- [ ] **Step 6: Testy przechodzą**

Run: `uv run pytest tests/api/test_zones_source.py tests/api/test_admin_crud.py -v`
Expected: all PASS (test_admin_crud.py to regresja istniejącego CRUD stref).

- [ ] **Step 7: Commit**

```bash
git add app/schemas/admin.py app/api/v1/admin/zones.py tests/api/test_zones_source.py
git commit -m "feat: source i custom_name w API stref, PATCH stref auto tylko dla custom_name"
```

---

### Task 4: `source` + nazwa efektywna w GeoJSON mapy

**Files:**
- Modify: `app/api/v1/admin/map.py:115-130` (properties w `map_zones_geojson`)
- Test: dopisz do `tests/api/test_zones_source.py`

- [ ] **Step 1: Failujący test**

Dopisz na końcu `tests/api/test_zones_source.py`:

```python
@pytest.mark.integration
async def test_zones_geojson_has_source_and_effective_name(client, admin_user, auto_zone, db_session):
    _, raw = admin_user
    await db_session.execute(
        text("UPDATE service_zones SET custom_name = 'Moja nazwa' WHERE id = CAST(:id AS uuid)"),
        {"id": str(auto_zone)},
    )
    resp = await client.get("/api/v1/admin/map/zones/geojson", headers={"X-API-Key": raw})
    assert resp.status_code == 200
    features = resp.json()["features"]
    props = next(f["properties"] for f in features if f["properties"]["id"] == str(auto_zone))
    assert props["source"] == "auto"
    assert props["name"] == "Moja nazwa"  # nazwa efektywna = COALESCE(custom_name, name)
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `uv run pytest tests/api/test_zones_source.py::test_zones_geojson_has_source_and_effective_name -v`
Expected: FAIL — `KeyError: 'source'`.

- [ ] **Step 3: Zmień properties w SQL**

W `app/api/v1/admin/map.py`, w `map_zones_geojson`, w `json_build_object` properties (linie ~123-126) zamień:

```sql
                    'properties', json_build_object(
                        'id', z.id,
                        'name', COALESCE(z.custom_name, z.name),
                        'source', z.source,
                        'priority', z.priority,
```

(reszta — `offerings` — bez zmian).

- [ ] **Step 4: Testy przechodzą**

Run: `uv run pytest tests/api/test_zones_source.py tests/api/test_map_validation.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/v1/admin/map.py tests/api/test_zones_source.py
git commit -m "feat: GeoJSON stref niesie source i nazwe efektywna (custom_name)"
```

---

### Task 5: Rebuild auto-zon per spójny obszar

**Files:**
- Modify: `app/auto_zones.py` (pełne przepisanie `_rebuild_for_technology` + nowe SQL)
- Modify: `tests/gis/test_auto_zones.py` (nazwy w istniejących asercjach + 3 nowe testy)

- [ ] **Step 1: Zaktualizuj istniejące testy + dodaj nowe (failujące)**

W `tests/gis/test_auto_zones.py`:

a) Wszystkie wystąpienia nazwy `"Auto: Test GPON"` zamień na `"Auto: Test GPON — Testkaimis"` (5 testów: asercje `rebuilt == [...]`, `_zone_row(...)`, `count(*)` i `in rebuilt`). Seedowane adresy leżą w miejscowości `Testkaimis`, więc nazwa dostaje człon miejscowości.

b) Dodaj importy i helper na górze pliku (po istniejących importach):

```python
from app.models.address import Address
from tests.gis.test_db_integration import LOCALITY


async def _add_building(session: AsyncSession, rc_code: int, x: float, y: float) -> None:
    """Building address at LKS94 (x, y) in the test locality."""
    session.add(Address(rc_code=rc_code, locality_code=LOCALITY, house_no=str(rc_code)[-3:], address_type="building"))
    await session.flush()
    await session.execute(
        text(
            "UPDATE addresses SET point = ST_Transform(ST_SetSRID(ST_MakePoint(:x, :y), 3346), 4326) "
            "WHERE rc_code = :code"
        ),
        {"code": rc_code, "x": x, "y": y},
    )


# Most laczacy ADDR_NEAR (y=6050030) z ADDR_FAR (y=6052000): punkty co 250 m
# (bufor 150 m -> sasiednie kola nachodza na siebie), ostatni 220 m od ADDR_FAR.
BRIDGE_YS = [6050280, 6050530, 6050780, 6051030, 6051280, 6051530, 6051780]
BRIDGE_RC = [99000000020 + i for i in range(len(BRIDGE_YS))]


async def _add_bridge(session: AsyncSession, tech_id: uuid.UUID, user_id: uuid.UUID) -> None:
    for rc, y in zip(BRIDGE_RC, BRIDGE_YS):
        await _add_building(session, rc, 580050, y)
        await _add_offering(session, rc, tech_id, user_id)
```

c) Dodaj trzy nowe testy na końcu pliku:

```python
async def test_two_disconnected_areas_get_two_zones(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    # Klaster NEAR: 2 budynki (100 m od siebie) -> wiekszy obszar, bez sufiksu.
    await _add_offering(db_session, ADDR_NEAR, tech.id, user.id, download=2000, upload=900)
    await _add_building(db_session, 99000000010, 580050, 6050130)
    await _add_offering(db_session, 99000000010, tech.id, user.id, download=1000, upload=500)
    # Klaster FAR: 1 budynek 2 km dalej -> osobny obszar, sufiks (2).
    await _add_offering(db_session, ADDR_FAR, tech.id, user.id, download=300, upload=100)

    rebuilt = await rebuild_auto_zones(db_session, tech.id)

    assert sorted(rebuilt) == [
        "Auto: Test GPON — Testkaimis",
        "Auto: Test GPON — Testkaimis (2)",
    ]
    rows = (
        await db_session.execute(
            text(
                """
                SELECT z.name, zo.max_download_mbps AS dl, zo.max_upload_mbps AS ul
                FROM service_zones z JOIN zone_offerings zo ON zo.zone_id = z.id
                WHERE z.source = 'auto' AND z.deleted_at IS NULL
                ORDER BY z.name
                """
            )
        )
    ).all()
    # Predkosci agregowane per obszar, nie globalnie.
    assert [(r.name, r.dl, r.ul) for r in rows] == [
        ("Auto: Test GPON — Testkaimis", 2000, 900),
        ("Auto: Test GPON — Testkaimis (2)", 300, 100),
    ]


async def test_merge_preserves_custom_name_of_larger_area(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    await _add_offering(db_session, ADDR_NEAR, tech.id, user.id)
    await _add_building(db_session, 99000000010, 580050, 6050130)
    await _add_offering(db_session, 99000000010, tech.id, user.id)
    await _add_offering(db_session, ADDR_FAR, tech.id, user.id)
    await rebuild_auto_zones(db_session, tech.id)

    near_zone_id = (
        await db_session.execute(
            text(
                "SELECT id FROM service_zones "
                "WHERE source = 'auto' AND name = 'Auto: Test GPON — Testkaimis'"
            )
        )
    ).scalar_one()
    await db_session.execute(
        text("UPDATE service_zones SET custom_name = 'Centrum' WHERE id = :id"),
        {"id": near_zone_id},
    )

    await _add_bridge(db_session, tech.id, user.id)  # laczy oba obszary w jeden
    await rebuild_auto_zones(db_session, tech.id)

    rows = (
        await db_session.execute(
            text(
                "SELECT id, custom_name, deleted_at FROM service_zones "
                "WHERE source = 'auto' ORDER BY created_at"
            )
        )
    ).all()
    active = [r for r in rows if r.deleted_at is None]
    hidden = [r for r in rows if r.deleted_at is not None]
    assert len(active) == 1
    assert active[0].id == near_zone_id        # wieksze przeciecie wygrywa
    assert active[0].custom_name == "Centrum"  # nazwa wlasna przezyla merge
    assert len(hidden) == 1                    # strefa FAR ukryta


async def test_split_keeps_id_on_largest_component(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    await _add_offering(db_session, ADDR_NEAR, tech.id, user.id)
    await _add_bridge(db_session, tech.id, user.id)
    await _add_offering(db_session, ADDR_FAR, tech.id, user.id)
    await rebuild_auto_zones(db_session, tech.id)

    orig_id = (
        await db_session.execute(
            text("SELECT id FROM service_zones WHERE source = 'auto' AND deleted_at IS NULL")
        )
    ).scalar_one()
    await db_session.execute(
        text("UPDATE service_zones SET custom_name = 'Magistrala' WHERE id = :id"),
        {"id": orig_id},
    )

    # Przerwij most: strona NEAR zostaje z 4 punktami, strona FAR z 3.
    await db_session.execute(
        text("DELETE FROM address_offerings WHERE address_code IN (99000000023, 99000000024)")
    )
    await rebuild_auto_zones(db_session, tech.id)

    rows = (
        await db_session.execute(
            text(
                "SELECT id, custom_name FROM service_zones "
                "WHERE source = 'auto' AND deleted_at IS NULL ORDER BY created_at"
            )
        )
    ).all()
    assert len(rows) == 2
    survivor = next(r for r in rows if r.id == orig_id)
    assert survivor.custom_name == "Magistrala"  # najwiekszy kawalek dziedziczy ID i nazwe
    newcomer = next(r for r in rows if r.id != orig_id)
    assert newcomer.custom_name is None
```

- [ ] **Step 2: Uruchom — nowe FAILUJĄ, stare też (zmienione nazwy)**

Run: `uv run pytest tests/gis/test_auto_zones.py -v`
Expected: FAIL na wszystkich — stary kod generuje nazwę bez członu miejscowości i jedną strefę na technologię.

- [ ] **Step 3: Przepisz `app/auto_zones.py`**

Zastąp całą zawartość pliku:

```python
"""Auto-zones: ServiceZone polygons derived from address offerings.

One zone per CONNECTED coverage area per technology (`source='auto'`):
polygon = union of 150 m buffers around addresses holding an `available`
offering, split into connected components (ST_Dump). Rebuilt after every
offering change. Address offerings are the source of truth; auto-zones are
pure visualization and never feed availability.

Identity across rebuilds: each new component is matched to an existing auto
zone of the technology by largest intersection area (greedy). Merge -> the
larger-overlap zone survives (its custom_name with it); split -> the largest
piece inherits the zone id, the rest get fresh rows. Hidden zones
(deleted_at) take part in matching and are revived on match.

Design: docs/superpowers/specs/2026-06-11-coverage-maintenance-model-design.md
"""

import logging
import uuid

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.service import ServiceZone, ZoneOffering
from app.models.technology import Technology
from app.time import now

log = logging.getLogger(__name__)

AUTO_ZONE_RADIUS_M = 150.0

# Spojne komponenty pokrycia technologii: bufory w LKS94 (metry), unia,
# ST_Dump na komponenty; per komponent MAX predkosci i dominujaca miejscowosc.
# Kolejnosc: najwiekszy obszar pierwszy (stabilne sufiksy nazw).
_COMPONENTS_SQL = text("""
    WITH pts AS (
        SELECT ST_Transform(a.point, 3346) AS p,
               ao.max_download_mbps AS dl,
               ao.max_upload_mbps AS ul,
               l.name AS locality
        FROM addresses a
        JOIN address_offerings ao ON ao.address_code = a.rc_code
        JOIN localities l ON l.rc_code = a.locality_code
        WHERE ao.technology_id = :tid
          AND ao.status = 'available'
          AND a.deleted_at IS NULL
          AND a.point IS NOT NULL
    ),
    comps AS (
        SELECT (ST_Dump(ST_Union(ST_Buffer(p, :radius)))).geom AS g
        FROM pts
    )
    SELECT
        ST_Multi(ST_Transform(ST_SimplifyPreserveTopology(c.g, 1.0), 4326)) AS poly,
        ST_AsEWKT(ST_Multi(ST_Transform(ST_SimplifyPreserveTopology(c.g, 1.0), 4326))) AS poly_ewkt,
        MAX(pt.dl) AS dl,
        MAX(pt.ul) AS ul,
        mode() WITHIN GROUP (ORDER BY pt.locality) AS locality
    FROM comps c
    JOIN pts pt ON ST_Covers(c.g, pt.p)
    GROUP BY c.g
    ORDER BY ST_Area(c.g) DESC
""")

# Powierzchnia przeciecia istniejacej strefy z komponentem (do dopasowania
# tozsamosci; porownujemy tylko miedzy soba, wiec jednostki 4326 wystarcza).
_OVERLAP_SQL = text("""
    SELECT ST_Area(ST_Intersection(z.polygon::geometry, ST_GeomFromEWKT(:comp)))
    FROM service_zones z
    WHERE z.id = CAST(:zid AS uuid)
""")


async def rebuild_auto_zones(
    session: AsyncSession,
    technology_id: uuid.UUID | None = None,
    radius_m: float = AUTO_ZONE_RADIUS_M,
) -> list[str]:
    """Rebuild auto-zones for one technology (or all with offerings).

    Returns effective names of zones rebuilt or hidden.
    """
    if technology_id is not None:
        tech_ids = [technology_id]
    else:
        rows = await session.execute(text("SELECT DISTINCT technology_id FROM address_offerings"))
        tech_ids = [row[0] for row in rows]

    touched: list[str] = []
    for tech_id in tech_ids:
        touched.extend(await _rebuild_for_technology(session, tech_id, radius_m))
    return touched


async def _rebuild_for_technology(
    session: AsyncSession, tech_id: uuid.UUID, radius_m: float
) -> list[str]:
    """Rebuild one technology's auto-zones. Returns touched zone names."""
    # Serialize concurrent rebuilds of the same technology (no duplicate zones).
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('auto_zone:' || :tid))"),
        {"tid": str(tech_id)},
    )

    tech = await session.get(Technology, tech_id)
    if tech is None:
        log.warning("Auto-zone rebuild skipped: technology %s not found", tech_id)
        return []

    comps = (
        await session.execute(_COMPONENTS_SQL, {"tid": str(tech_id), "radius": radius_m})
    ).all()

    # All auto zones of this technology, hidden included — matching a hidden
    # zone revives it, so custom_name survives a temporary outage.
    zones = list(
        (
            await session.execute(
                select(ServiceZone)
                .join(ZoneOffering, ZoneOffering.zone_id == ServiceZone.id)
                .where(ServiceZone.source == "auto", ZoneOffering.technology_id == tech_id)
                .order_by(ServiceZone.created_at)
            )
        ).scalars().all()
    )

    touched: list[str] = []
    current = now()

    if not comps:
        for zone in zones:
            if zone.deleted_at is None:
                zone.deleted_at = current
                touched.append(zone.custom_name or zone.name)
                log.info("Auto zone '%s' hidden (no available offerings)", zone.name)
        await session.flush()
        return touched

    # Pairwise overlap zone x component, greedy largest-overlap matching.
    pairs: list[tuple[float, ServiceZone, int]] = []
    for zone in zones:
        for ci, comp in enumerate(comps):
            overlap = (
                await session.execute(
                    _OVERLAP_SQL, {"zid": str(zone.id), "comp": comp.poly_ewkt}
                )
            ).scalar()
            if overlap and overlap > 0:
                pairs.append((overlap, zone, ci))
    pairs.sort(key=lambda t: t[0], reverse=True)

    comp_zone: dict[int, ServiceZone] = {}
    used_zone_ids: set[uuid.UUID] = set()
    for _, zone, ci in pairs:
        if ci in comp_zone or zone.id in used_zone_ids:
            continue
        comp_zone[ci] = zone
        used_zone_ids.add(zone.id)

    # Components come ordered by area DESC; name collisions get " (2)", " (3)"...
    name_counts: dict[str, int] = {}
    for ci, comp in enumerate(comps):
        base = f"Auto: {tech.display_name} — {comp.locality}"
        name_counts[base] = name_counts.get(base, 0) + 1
        name = base if name_counts[base] == 1 else f"{base} ({name_counts[base]})"

        zone = comp_zone.get(ci)
        if zone is None:
            zone = ServiceZone(
                name=name,
                description="Strefa generowana automatycznie z ofert adresowych",
                polygon=comp.poly,
                source="auto",
                created_by=None,
            )
            session.add(zone)
            comp_zone[ci] = zone
        else:
            zone.polygon = comp.poly
            zone.name = name
            zone.deleted_at = None
        touched.append(zone.custom_name or name)
    await session.flush()

    for ci, comp in enumerate(comps):
        zone = comp_zone[ci]
        offering_stmt = (
            pg_insert(ZoneOffering)
            .values(
                id=uuid.uuid4(),
                zone_id=zone.id,
                technology_id=tech_id,
                status="available",
                max_download_mbps=comp.dl,
                max_upload_mbps=comp.ul,
                status_since=current.date(),
                created_at=current,
                updated_at=current,
            )
            .on_conflict_do_update(
                index_elements=["zone_id", "technology_id"],
                set_={
                    "status": "available",
                    "max_download_mbps": comp.dl,
                    "max_upload_mbps": comp.ul,
                    "updated_at": current,
                },
            )
        )
        await session.execute(offering_stmt)

    for zone in zones:
        if zone.id not in used_zone_ids and zone.deleted_at is None:
            zone.deleted_at = current
            touched.append(zone.custom_name or zone.name)
            log.info("Auto zone '%s' hidden (area merged or gone)", zone.name)

    await session.flush()
    log.info("Auto zones for '%s' rebuilt: %d area(s)", tech.display_name, len(comps))
    return touched


async def rebuild_auto_zones_background(technology_id: uuid.UUID | None = None) -> None:
    """For FastAPI BackgroundTasks: own session, commits, never raises."""
    try:
        async with AsyncSessionLocal() as session:
            await rebuild_auto_zones(session, technology_id)
            await session.commit()
    except Exception:
        log.exception("Auto-zone background rebuild failed (technology_id=%s)", technology_id)
```

- [ ] **Step 4: Testy auto-zon przechodzą**

Run: `uv run pytest tests/gis/ -v`
Expected: all PASS (w tym `test_auto_zones.py` z nowymi nazwami i 3 nowymi testami oraz regresja `import-gis` end-to-end).

- [ ] **Step 5: Regresja triggerów i CLI**

Run: `uv run pytest tests/api/test_auto_zone_triggers.py -v`
Expected: all PASS (kontrakt `rebuild_auto_zones_background(technology_id)` bez zmian — CLI `rebuild-zones` też działa bez modyfikacji, bo `rebuild_auto_zones` dalej zwraca `list[str]`).

- [ ] **Step 6: Commit**

```bash
git add app/auto_zones.py tests/gis/test_auto_zones.py
git commit -m "feat: auto-zony per spojny obszar - tozsamosc po przecieciu, nazwy z miejscowosci, custom_name"
```

---

### Task 6: Luki w pokryciu — `without_offering`, `has_override` per technologia, `gap_count`

**Files:**
- Modify: `app/api/v1/admin/zones.py:339-387` (`ZoneAddressItem`, `list_zone_addresses`) i `get_zone` (gałąź detail, linie 92-124)
- Modify: `app/schemas/admin.py:205-208` (`ZoneDetail`)
- Create: `tests/api/test_zone_gaps.py`

- [ ] **Step 1: Failujące testy**

Utwórz `tests/api/test_zone_gaps.py`:

```python
"""Luki w pokryciu: adresy w strefie bez oferty technologii strefy."""

import secrets

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.dependencies import get_db
from app.main import app
from app.models.admin import ApiKey, User

ZONE_ID = "dd000000-0000-0000-0000-000000000099"
ADDR_COVERED = 93199901   # oferta technologii strefy -> has_override
ADDR_GAP = 93199902       # oferta INNEJ technologii -> nadal luka


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
async def gap_setup(db_session):
    """Strefa z technologia A; ADDR_COVERED ma oferte A, ADDR_GAP tylko B."""
    stmts = [
        "INSERT INTO counties (rc_code, name, synced_at) VALUES (93001, 'Gap Apskritis', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO municipalities (rc_code, county_code, name, type, synced_at) VALUES (93100, 93001, 'Gap Sav.', 'rajono', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO localities (rc_code, muni_code, name, type, synced_at) VALUES (93100, 93100, 'Gapkaimis', 'k.', NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO addresses (rc_code, locality_code, house_no, synced_at, point, address_type) VALUES ({ADDR_COVERED}, 93100, '1', NOW(), ST_GeomFromEWKT('SRID=4326;POINT(25.05 54.05)'), 'building') ON CONFLICT DO NOTHING",
        f"INSERT INTO addresses (rc_code, locality_code, house_no, synced_at, point, address_type) VALUES ({ADDR_GAP}, 93100, '2', NOW(), ST_GeomFromEWKT('SRID=4326;POINT(25.06 54.06)'), 'building') ON CONFLICT DO NOTHING",
        "INSERT INTO technology_types (id, code, display_name, public_name, sort_order) VALUES ('aa000000-0000-0000-0000-000000000093', 'GAP_A', 'Gap A', 'Gap A', 93) ON CONFLICT DO NOTHING",
        "INSERT INTO technologies (id, type_id, variant_code, display_name, sort_order) VALUES ('bb000000-0000-0000-0000-000000000093', 'aa000000-0000-0000-0000-000000000093', 'gap_a', 'Gap A', 93) ON CONFLICT DO NOTHING",
        "INSERT INTO technology_types (id, code, display_name, public_name, sort_order) VALUES ('aa000000-0000-0000-0000-000000000094', 'GAP_B', 'Gap B', 'Gap B', 94) ON CONFLICT DO NOTHING",
        "INSERT INTO technologies (id, type_id, variant_code, display_name, sort_order) VALUES ('bb000000-0000-0000-0000-000000000094', 'aa000000-0000-0000-0000-000000000094', 'gap_b', 'Gap B', 94) ON CONFLICT DO NOTHING",
        "INSERT INTO users (id, username, email, role, active, created_at) VALUES ('cc000000-0000-0000-0000-000000000093', 'gap_user', 'gap@test.lt', 'admin', true, NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO service_zones (id, name, polygon, priority, source, created_at) VALUES ('{ZONE_ID}', 'Auto: Gap A — Gapkaimis', ST_GeomFromEWKT('SRID=4326;MULTIPOLYGON(((25.0 54.0, 25.1 54.0, 25.1 54.1, 25.0 54.1, 25.0 54.0)))'), 100, 'auto', NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO zone_offerings (id, zone_id, technology_id, status, max_download_mbps, max_upload_mbps, status_since, created_at, updated_at) VALUES ('ee000000-0000-0000-0000-000000000093', '{ZONE_ID}', 'bb000000-0000-0000-0000-000000000093', 'available', 1000, 500, CURRENT_DATE, NOW(), NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO address_offerings (id, address_code, technology_id, status, max_download_mbps, max_upload_mbps, status_since, created_by, created_at, updated_at) VALUES ('ff000000-0000-0000-0000-000000000093', {ADDR_COVERED}, 'bb000000-0000-0000-0000-000000000093', 'available', 1000, 500, CURRENT_DATE, 'cc000000-0000-0000-0000-000000000093', NOW(), NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO address_offerings (id, address_code, technology_id, status, max_download_mbps, max_upload_mbps, status_since, created_by, created_at, updated_at) VALUES ('ff000000-0000-0000-0000-000000000094', {ADDR_GAP}, 'bb000000-0000-0000-0000-000000000094', 'available', 100, 50, CURRENT_DATE, 'cc000000-0000-0000-0000-000000000093', NOW(), NOW()) ON CONFLICT DO NOTHING",
    ]
    for stmt in stmts:
        await db_session.execute(text(stmt))


@pytest.mark.integration
async def test_has_override_is_per_zone_technology(client, admin_user, gap_setup):
    _, raw = admin_user
    resp = await client.get(f"/api/v1/admin/zones/{ZONE_ID}/addresses", headers={"X-API-Key": raw})
    assert resp.status_code == 200
    by_rc = {i["rc_code"]: i for i in resp.json()["items"]}
    assert by_rc[ADDR_COVERED]["has_override"] is True
    # Oferta innej technologii (Gap B) nie liczy sie jako pokrycie strefy Gap A.
    assert by_rc[ADDR_GAP]["has_override"] is False


@pytest.mark.integration
async def test_without_offering_returns_only_gaps(client, admin_user, gap_setup):
    _, raw = admin_user
    resp = await client.get(
        f"/api/v1/admin/zones/{ZONE_ID}/addresses",
        params={"without_offering": "true"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert [i["rc_code"] for i in body["items"]] == [ADDR_GAP]


@pytest.mark.integration
async def test_zone_detail_has_gap_count(client, admin_user, gap_setup):
    _, raw = admin_user
    resp = await client.get(
        f"/api/v1/admin/zones/{ZONE_ID}",
        params={"expand": "detail"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["address_count"] == 2
    assert body["gap_count"] == 1
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `uv run pytest tests/api/test_zone_gaps.py -v`
Expected: FAIL — `has_override` jest `True` dla ADDR_GAP (stara semantyka „jakakolwiek oferta"), brak parametru `without_offering` (jest ignorowany → total 2), `KeyError: 'gap_count'`.

- [ ] **Step 3: `ZoneDetail.gap_count` w schemacie**

W `app/schemas/admin.py` (linie 205-208):

```python
class ZoneDetail(ZoneOut):
    """Full zone detail including offerings, address count and coverage gaps."""
    offerings: list[ZoneOfferingOut]
    address_count: int
    gap_count: int  # buildings inside the polygon lacking an offering for the zone's technologies
```

- [ ] **Step 4: Przepisz `list_zone_addresses` i komentarz `ZoneAddressItem`**

W `app/api/v1/admin/zones.py` zastąp `ZoneAddressItem` i `list_zone_addresses` (linie 339-387):

```python
class ZoneAddressItem(BaseModel):
    rc_code: int
    full_address: str
    postal_code: str | None
    has_override: bool  # True if this address has an offering for the zone's technology


# Oferta adresowa dla ktorejkolwiek technologii TEJ strefy.
_ZONE_TECH_OFFERING_EXISTS = """EXISTS(
            SELECT 1 FROM address_offerings ao
            JOIN zone_offerings zo ON zo.technology_id = ao.technology_id
            WHERE zo.zone_id = z.id AND ao.address_code = a.rc_code
        )"""


@router.get("/{zone_id}/addresses", response_model=Page[ZoneAddressItem], summary="List addresses in zone", operation_id="admin.zones.addresses.list")
async def list_zone_addresses(
    zone_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
    without_offering: Annotated[
        bool, Query(description="only addresses lacking an offering for the zone's technologies (coverage gaps)")
    ] = False,
) -> Page[ZoneAddressItem]:
    """List addresses (buildings) inside a zone's polygon. Paginated."""
    await _require_zone(db, zone_id)

    gap_clause = f"AND NOT {_ZONE_TECH_OFFERING_EXISTS}" if without_offering else ""

    total_row = await db.execute(text(f"""
        SELECT COUNT(*) FROM addresses a
        JOIN service_zones z ON ST_Contains(z.polygon::geometry, a.point::geometry)
        WHERE z.id = CAST(:zid AS uuid)
          AND z.deleted_at IS NULL
          AND a.deleted_at IS NULL
          AND a.address_type = 'building'
          {gap_clause}
    """), {"zid": str(zone_id)})
    total = int(total_row.scalar() or 0)

    rows = (await db.execute(text(f"""
        SELECT
            a.rc_code,
            (COALESCE(s.name || ' ', '') || a.house_no || ', ' || l.name) AS full_address,
            a.postal_code,
            {_ZONE_TECH_OFFERING_EXISTS} AS has_override
        FROM addresses a
        JOIN service_zones z ON ST_Contains(z.polygon::geometry, a.point::geometry)
        JOIN localities l ON l.rc_code = a.locality_code
        LEFT JOIN streets s ON s.rc_code = a.street_code
        WHERE z.id = CAST(:zid AS uuid)
          AND z.deleted_at IS NULL
          AND a.deleted_at IS NULL
          AND a.address_type = 'building'
          {gap_clause}
        ORDER BY a.rc_code
        LIMIT :limit OFFSET :offset
    """), {"zid": str(zone_id), "limit": page.limit, "offset": page.offset})).mappings().all()

    return Page[ZoneAddressItem](
        total=total,
        items=[ZoneAddressItem(**r) for r in rows],
    )
```

- [ ] **Step 5: `gap_count` (i spójny `address_count`) w `get_zone` detail**

W `app/api/v1/admin/zones.py`, w gałęzi `expand == "detail"` (linie 102-124), zastąp zapytanie `count_row` i konstrukcję `ZoneDetail`:

```python
        count_row = (await db.execute(text("""
            SELECT
                COUNT(*) AS cnt,
                COUNT(*) FILTER (WHERE NOT EXISTS(
                    SELECT 1 FROM address_offerings ao
                    JOIN zone_offerings zo ON zo.technology_id = ao.technology_id
                    WHERE zo.zone_id = z.id AND ao.address_code = a.rc_code
                )) AS gaps
            FROM addresses a
            JOIN service_zones z ON ST_Contains(z.polygon::geometry, a.point::geometry)
            WHERE z.id = CAST(:id AS uuid)
              AND a.deleted_at IS NULL
              AND a.address_type = 'building'
        """), {"id": str(zone_id)})).first()
```

(uwaga: dochodzi filtr `address_type = 'building'` — `address_count` liczy teraz to samo uniwersum co lista adresów i `gap_count`).

W `return ZoneDetail(...)` dodaj po `address_count=...`:

```python
            address_count=int(count_row[0]) if count_row and zone.polygon is not None else 0,
            gap_count=int(count_row[1]) if count_row and zone.polygon is not None else 0,
```

(pamiętaj o dodanym w Task 3 `custom_name=zone.custom_name, source=zone.source` — zostają).

- [ ] **Step 6: Testy przechodzą**

Run: `uv run pytest tests/api/test_zone_gaps.py tests/api/test_admin_crud.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add app/schemas/admin.py app/api/v1/admin/zones.py tests/api/test_zone_gaps.py
git commit -m "feat: raport luk - without_offering, has_override per technologia strefy, gap_count w detalu"
```

---

### Task 7: Pełna regresja

**Files:** brak nowych zmian (chyba że regresja coś wykryje).

- [ ] **Step 1: Cały suite**

Run: `uv run pytest tests/ -v`
Expected: all PASS. Szczególna uwaga na `tests/api/test_zone_coverage_deleted.py` (endpoint zone-coverage — nieruszany, ma przejść bez zmian) i `tests/gis/test_db_integration.py` (import-gis end-to-end woła rebuild — nazwy stref w raporcie mają teraz człon miejscowości; jeśli któryś test asercjonuje starą nazwę, zaktualizuj analogicznie do Task 5a).

- [ ] **Step 2: Commit poprawek regresji (jeśli były)**

```bash
git add -A && git commit -m "test: poprawki regresji po auto-zonach per obszar"
```

(pomiń, jeśli Step 1 przeszedł bez zmian w kodzie).

---

## Po planie (poza zakresem tych tasków)

- Etapy 3-4 (plugin LMS: filtry mapy, panel strefy z lukami, edycja rysowaniem) — osobny plan w repo pluginu, po wdrożeniu tego.
- Etap 5 (`import-gis --mode diff`, raporty w stats) — osobny plan.
- Po deployu: usunąć ręcznie pozostałą strefę „GPON tinklas" (admin API), zgodnie ze spec auto-zon z 2026-06-11.
