# Etap 5: Higiena długoterminowa — diff importu GIS + raporty w stats — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `import-gis --mode diff` raportuje (i opcjonalnie usuwa, z rollbackiem) oferty osierocone — adresy, które wypadły z zasięgu sieci; `/admin/coverage/stats` dostaje raport „planned po terminie" i raport luk w auto-strefach; `etacoveragestats` w LMS je wyświetla.

**Architecture:** Diff to rozszerzenie istniejącego flow importu: po dopasowaniu adresów dodatkowe zapytanie `NOT ST_DWithin` na tej samej temp-tabeli geometrii znajduje oferty technologii poza zasięgiem. Usuwanie reużywa `_execute_remove_offering` z bulk API — identyczny format `rollback_data`, więc `POST /bulk/{id}/rollback` przywraca skasowane oferty bez żadnego nowego kodu rollbacku. Stats dostaje trzy nowe zapytania (overdue count+list z filtrem scope, luki per aktywna auto-strefa) i cztery nowe pola w `CoverageStats` (z defaultami — kontrakt wstecznie zgodny).

**Tech Stack:** FastAPI + SQLAlchemy async + PostGIS, Typer CLI (rich), pytest integracyjne (PostgreSQL+PostGIS z migracjami); plugin: PHP + Smarty (tylko szablon).

**Repo (Tasks 1-4):** `/home/robertas/workspace/robertas/etanetas-coverage`
**Repo (Task 5):** `/home/robertas/workspace/robertas/lms-etanetas/lms/plugins/LMSEtaCoveragePlugin` (własne repo git)

**Spec:** `docs/superpowers/specs/2026-06-11-coverage-maintenance-model-design.md` (etap 5)

**Kontrakty istniejącego kodu, na których budujemy:**

- `app/gis_import.py`: `ImportOptions` (dataclass), `ImportReport` (dataclass), `_run_db_steps(session, options, wkts, report, progress)` robi całość pracy DB na temp-tabeli `gis_import_geom`, `run_import()` waliduje i zarządza sesją/commitem.
- `app/api/v1/admin/bulk.py`: `_execute_remove_offering(db, bulk_op_id, user_id, op, rc_codes, technology_name) -> (deleted_codes, deleted_data)` — kasuje oferty + audit log per adres; rollback czyta `bulk_op.rollback_data = {type: 'remove_offering', technology_id: str, deleted_offerings: [...]}`.
- `app/schemas/admin.py`: `RemoveOfferingOperation`, `CoverageStats`.
- `app/db/address_labels.py`: `_FULL_ADDRESS` (wyrażenie SQL etykiety adresu, wymaga `_ADDR_JOINS` po `FROM addresses a`).
- `tests/gis/test_db_integration.py`: helpery `_seed_addresses`, `_seed_tech_and_user`, stałe `ADDR_NEAR` (~30 m od `TEST_LINE`), `ADDR_FAR` (~2 km), `TEST_LINE` (WKT w EPSG:3346).
- Testy wymagają działającej bazy PostgreSQL+PostGIS z migracjami (patrz `tests/conftest.py`); `db_session` rollbackuje po każdym teście, ale baza może zawierać realne dane — asercje na stats używają `scope=all` i sprawdzają członkostwo, nie dokładne liczby.

---

### Task 1: Stats — `planned_overdue` + `auto_zone_gaps`

**Files:**
- Modify: `app/schemas/admin.py` (po `UncoveredLocality`, ~linia 436; `CoverageStats` ~linia 438)
- Modify: `app/api/v1/admin/stats.py`
- Create: `tests/api/test_stats_hygiene.py`

- [ ] **Step 1: Napisz failujące testy**

Utwórz `tests/api/test_stats_hygiene.py`:

```python
"""Stats: raport planned-po-terminie i luk w auto-strefach."""

import secrets

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.dependencies import get_db
from app.main import app
from app.models.admin import ApiKey, User

ADDR_OVERDUE = 95199901  # planned z planned_until w przeszlosci, w strefie
ADDR_GAP = 95199902      # w strefie, bez oferty -> luka
ZONE_NAME = "Auto: Hyg A — Hygkaimis"


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
async def hygiene_setup(db_session):
    """Auto-strefa z 2 adresami: jeden ma oferte planned po terminie, drugi to luka."""
    stmts = [
        "INSERT INTO counties (rc_code, name, synced_at) VALUES (95001, 'Hyg Apskritis', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO municipalities (rc_code, county_code, name, type, synced_at) VALUES (95100, 95001, 'Hyg Sav.', 'rajono', NOW()) ON CONFLICT DO NOTHING",
        "INSERT INTO localities (rc_code, muni_code, name, type, synced_at) VALUES (95100, 95100, 'Hygkaimis', 'k.', NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO addresses (rc_code, locality_code, house_no, synced_at, point, address_type) VALUES ({ADDR_OVERDUE}, 95100, '1', NOW(), ST_GeomFromEWKT('SRID=4326;POINT(20.05 55.95)'), 'building') ON CONFLICT DO NOTHING",
        f"INSERT INTO addresses (rc_code, locality_code, house_no, synced_at, point, address_type) VALUES ({ADDR_GAP}, 95100, '2', NOW(), ST_GeomFromEWKT('SRID=4326;POINT(20.06 55.96)'), 'building') ON CONFLICT DO NOTHING",
        "INSERT INTO technology_types (id, code, display_name, public_name, sort_order) VALUES ('aa000000-0000-0000-0000-000000000095', 'HYG_A', 'Hyg A', 'Hyg A', 95) ON CONFLICT DO NOTHING",
        "INSERT INTO technologies (id, type_id, variant_code, display_name, sort_order) VALUES ('bb000000-0000-0000-0000-000000000095', 'aa000000-0000-0000-0000-000000000095', 'hyg_a', 'Hyg A', 95) ON CONFLICT DO NOTHING",
        "INSERT INTO users (id, username, email, role, active, created_at) VALUES ('cc000000-0000-0000-0000-000000000095', 'hyg_user', 'hyg@test.lt', 'admin', true, NOW()) ON CONFLICT DO NOTHING",
        # planned z data 1990 -> sortuje sie na poczatek listy overdue
        f"INSERT INTO address_offerings (id, address_code, technology_id, status, max_download_mbps, max_upload_mbps, status_since, planned_until, created_by, created_at, updated_at) VALUES ('ff000000-0000-0000-0000-000000000095', {ADDR_OVERDUE}, 'bb000000-0000-0000-0000-000000000095', 'planned', 1000, 500, '1989-01-01', '1990-01-01', 'cc000000-0000-0000-0000-000000000095', NOW(), NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO service_zones (id, name, polygon, priority, source, created_at) VALUES ('dd000000-0000-0000-0000-000000000095', '{ZONE_NAME}', ST_GeomFromEWKT('SRID=4326;MULTIPOLYGON(((20.0 55.9, 20.1 55.9, 20.1 56.0, 20.0 56.0, 20.0 55.9)))'), 100, 'auto', NOW()) ON CONFLICT DO NOTHING",
        f"INSERT INTO zone_offerings (id, zone_id, technology_id, status, max_download_mbps, max_upload_mbps, status_since, created_at, updated_at) VALUES ('ee000000-0000-0000-0000-000000000095', 'dd000000-0000-0000-0000-000000000095', 'bb000000-0000-0000-0000-000000000095', 'available', 1000, 500, CURRENT_DATE, NOW(), NOW()) ON CONFLICT DO NOTHING",
    ]
    for stmt in stmts:
        await db_session.execute(text(stmt))


@pytest.mark.integration
async def test_stats_reports_planned_overdue(client, admin_user, hygiene_setup):
    _, raw = admin_user
    resp = await client.get("/api/v1/admin/coverage/stats?scope=all", headers={"X-API-Key": raw})
    assert resp.status_code == 200
    body = resp.json()
    assert body["planned_overdue_count"] >= 1
    ours = [i for i in body["planned_overdue"] if i["address_code"] == ADDR_OVERDUE]
    assert len(ours) == 1
    assert ours[0]["technology"] == "Hyg A"
    assert ours[0]["planned_until"] == "1990-01-01"
    assert "Hygkaimis" in ours[0]["full_address"]


@pytest.mark.integration
async def test_stats_reports_auto_zone_gaps(client, admin_user, hygiene_setup):
    _, raw = admin_user
    resp = await client.get("/api/v1/admin/coverage/stats?scope=all", headers={"X-API-Key": raw})
    assert resp.status_code == 200
    body = resp.json()
    ours = [z for z in body["auto_zone_gaps"] if z["zone_name"] == ZONE_NAME]
    assert len(ours) == 1
    # ADDR_OVERDUE ma oferte technologii strefy (planned tez liczy sie jako oferta),
    # ADDR_GAP nie ma zadnej -> 1 luka z 2 adresow.
    assert ours[0]["gap_count"] == 1
    assert ours[0]["address_count"] == 2
    assert ours[0]["technology"] == "Hyg A"
    assert body["auto_zone_gaps_total"] >= 1
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `cd /home/robertas/workspace/robertas/etanetas-coverage && uv run pytest tests/api/test_stats_hygiene.py -v`
Expected: FAIL — `KeyError: 'planned_overdue_count'` (pól nie ma w odpowiedzi).

- [ ] **Step 3: Schematy**

W `app/schemas/admin.py`, po klasie `UncoveredLocality`, dodaj:

```python
class PlannedOverdueItem(BaseModel):
    address_code: int
    full_address: str
    technology: str
    planned_until: date


class AutoZoneGapItem(BaseModel):
    zone_name: str
    technology: str
    gap_count: int
    address_count: int
```

(`date` jest już importowane w tym pliku.)

W `CoverageStats` dodaj na końcu pól (defaulty = wsteczna zgodność kontraktu):

```python
    planned_overdue_count: int = 0
    planned_overdue: list[PlannedOverdueItem] = []
    auto_zone_gaps_total: int = 0
    auto_zone_gaps: list[AutoZoneGapItem] = []
```

- [ ] **Step 4: Zapytania w stats**

W `app/api/v1/admin/stats.py`:

a) Rozszerz importy:

```python
from app.db.address_labels import _ADDR_JOINS, _FULL_ADDRESS
from app.schemas.admin import (
    AutoZoneGapItem,
    CoverageStats,
    PlannedOverdueItem,
    StatusBreakdown,
    UncoveredLocality,
)
```

b) W `get_coverage_stats`, po zapytaniu `uncov_rows` a przed `return CoverageStats(...)`, dodaj:

```python
    planned_overdue_count = await db.scalar(
        text(f"""
        SELECT COUNT(*)
        FROM address_offerings ao
        JOIN addresses a ON a.rc_code = ao.address_code
        WHERE ao.status = 'planned'
          AND ao.planned_until IS NOT NULL
          AND ao.planned_until < CURRENT_DATE
          AND a.deleted_at IS NULL
          {address_filter}
    """),
        address_params,
    ) or 0

    overdue_rows = (
        await db.execute(
            text(f"""
        SELECT
            ao.address_code,
            ({_FULL_ADDRESS}) AS full_address,
            tt.public_name AS technology,
            ao.planned_until
        FROM address_offerings ao
        JOIN addresses a ON a.rc_code = ao.address_code
        {_ADDR_JOINS}
        JOIN technologies t ON t.id = ao.technology_id
        JOIN technology_types tt ON tt.id = t.type_id
        WHERE ao.status = 'planned'
          AND ao.planned_until IS NOT NULL
          AND ao.planned_until < CURRENT_DATE
          AND a.deleted_at IS NULL
          {address_filter}
        ORDER BY ao.planned_until
        LIMIT 50
    """),
            address_params,
        )
    ).mappings().all()

    # Luki per aktywna auto-strefa (bez filtra scope — strefy pokrywaja sie z siecia).
    gap_rows = (
        await db.execute(
            text("""
        SELECT
            COALESCE(z.custom_name, z.name) AS zone_name,
            t.display_name AS technology,
            COUNT(a.rc_code) AS address_count,
            COUNT(a.rc_code) FILTER (WHERE NOT EXISTS(
                SELECT 1 FROM address_offerings ao
                WHERE ao.address_code = a.rc_code
                  AND ao.technology_id = zo.technology_id
            )) AS gap_count
        FROM service_zones z
        JOIN zone_offerings zo ON zo.zone_id = z.id
        JOIN technologies t ON t.id = zo.technology_id
        LEFT JOIN addresses a
          ON a.deleted_at IS NULL
         AND a.address_type = 'building'
         AND a.point IS NOT NULL
         AND ST_Contains(z.polygon::geometry, a.point::geometry)
        WHERE z.source = 'auto'
          AND z.deleted_at IS NULL
          AND z.polygon IS NOT NULL
        GROUP BY z.id, z.custom_name, z.name, t.display_name
        ORDER BY gap_count DESC
    """)
        )
    ).mappings().all()
```

c) W `return CoverageStats(...)` dodaj cztery argumenty:

```python
        planned_overdue_count=int(planned_overdue_count),
        planned_overdue=[PlannedOverdueItem(**r) for r in overdue_rows],
        auto_zone_gaps_total=sum(int(r["gap_count"]) for r in gap_rows),
        auto_zone_gaps=[AutoZoneGapItem(**r) for r in gap_rows],
```

- [ ] **Step 5: Testy przechodzą**

Run: `uv run pytest tests/api/test_stats_hygiene.py tests/api/test_stats.py -v`
Expected: all PASS (test_stats.py = regresja istniejących pól).

- [ ] **Step 6: Commit**

```bash
git add app/schemas/admin.py app/api/v1/admin/stats.py tests/api/test_stats_hygiene.py
git commit -m "feat: stats - raport planned po terminie i luk w auto-strefach"
```

---

### Task 2: `import-gis --mode diff` — wykrywanie osieroconych ofert

**Files:**
- Modify: `app/gis_import.py`
- Modify: `app/cli.py` (opcja `--mode`, raport)
- Create: `tests/gis/test_gis_diff.py`

- [ ] **Step 1: Napisz failujące testy**

Utwórz `tests/gis/test_gis_diff.py`:

```python
"""Tryb diff importu GIS: wykrywanie ofert osieroconych (adres poza zasiegiem sieci)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.gis_import import (
    ImportOptions,
    ImportReport,
    _run_db_steps,
    find_orphans,
    load_temp_geometries,
)
from app.models.service import AddressOffering
from app.time import now
from tests.gis.test_db_integration import (
    ADDR_FAR,
    ADDR_NEAR,
    TEST_LINE,
    _seed_addresses,
    _seed_tech_and_user,
)


async def _add_offering(session: AsyncSession, address_code, tech_id, user_id) -> AddressOffering:
    offering = AddressOffering(
        address_code=address_code,
        technology_id=tech_id,
        status="available",
        max_download_mbps=1000,
        max_upload_mbps=500,
        status_since=now().date(),
        created_by=user_id,
    )
    session.add(offering)
    await session.flush()
    return offering


def _options(**overrides) -> ImportOptions:
    defaults = {
        "shapefiles": [],
        "technology": "test_gpon",
        "distance": 50.0,
        "username": "gis_tester",
        "mode": "diff",
    }
    defaults.update(overrides)
    return ImportOptions(**defaults)


async def test_find_orphans_reports_far_offering(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    await _add_offering(db_session, ADDR_FAR, tech.id, user.id)   # ~2 km od linii
    await _add_offering(db_session, ADDR_NEAR, tech.id, user.id)  # ~30 m od linii
    await load_temp_geometries(db_session, [TEST_LINE])

    orphans = await find_orphans(db_session, tech.id, distance=50.0)

    codes = [o.rc_code for o in orphans]
    assert ADDR_FAR in codes
    assert ADDR_NEAR not in codes
    far = next(o for o in orphans if o.rc_code == ADDR_FAR)
    assert "Testkaimis" in far.full_address


async def test_diff_mode_reports_orphans_without_removing(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    await _add_offering(db_session, ADDR_FAR, tech.id, user.id)

    report = await _run_db_steps(
        db_session, _options(), [TEST_LINE], ImportReport(), lambda s: None
    )

    assert [o.rc_code for o in report.orphans] == [ADDR_FAR]
    assert report.orphans_removed == 0
    # Oferta NIE zostala usunieta — diff tylko raportuje.
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM address_offerings WHERE address_code = :rc"),
            {"rc": ADDR_FAR},
        )
    ).scalar()
    assert count == 1
    # Import nadal dziala: ADDR_NEAR dostal oferte.
    count_near = (
        await db_session.execute(
            text("SELECT count(*) FROM address_offerings WHERE address_code = :rc"),
            {"rc": ADDR_NEAR},
        )
    ).scalar()
    assert count_near == 1


async def test_import_mode_skips_orphan_detection(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    await _add_offering(db_session, ADDR_FAR, tech.id, user.id)

    report = await _run_db_steps(
        db_session, _options(mode="import"), [TEST_LINE], ImportReport(), lambda s: None
    )

    assert report.orphans == []
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `uv run pytest tests/gis/test_gis_diff.py -v`
Expected: FAIL — `ImportError: cannot import name 'find_orphans'` / `TypeError: ImportOptions.__init__() got an unexpected keyword argument 'mode'`.

- [ ] **Step 3: Rozszerz `app/gis_import.py`**

a) Importy — dodaj do istniejących:

```python
from app.db.address_labels import _ADDR_JOINS, _FULL_ADDRESS  # noqa: F401
```

b) `ImportOptions` — dodaj dwa pola na końcu:

```python
    mode: str = "import"          # 'import' | 'diff'
    remove_orphans: bool = False  # tylko z mode='diff'
```

c) Po `ImportOptions`, dodaj dataclass i rozszerz `ImportReport`:

```python
@dataclass
class OrphanItem:
    rc_code: int
    full_address: str
```

W `ImportReport` dodaj pola:

```python
    orphans: list[OrphanItem] = field(default_factory=list)
    orphans_removed: int = 0
    remove_op_id: str | None = None
```

d) Po funkcji `match_addresses` dodaj:

```python
async def find_orphans(
    session: AsyncSession, tech_id: uuid.UUID, distance: float
) -> list[OrphanItem]:
    """Oferty technologii, ktorych adres lezy DALEJ niz `distance` od sieci.

    Wymaga zaladowanej temp-tabeli gis_import_geom (load_temp_geometries).
    Siec sie skurczyla albo adres nigdy nie byl w zasiegu — do recznej decyzji.
    """
    result = await session.execute(
        text(
            f"""
            SELECT a.rc_code, ({_FULL_ADDRESS}) AS full_address
            FROM address_offerings ao
            JOIN addresses a ON a.rc_code = ao.address_code
            {_ADDR_JOINS}
            WHERE ao.technology_id = :tech_id
              AND a.deleted_at IS NULL
              AND a.point IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM gis_import_geom g
                WHERE ST_DWithin(ST_Transform(a.point, 3346), g.geom, :distance)
              )
            ORDER BY a.rc_code
            """
        ),
        {"tech_id": str(tech_id), "distance": distance},
    )
    return [OrphanItem(rc_code=int(r[0]), full_address=str(r[1])) for r in result]
```

e) W `_run_db_steps`, po linii `bulk_op.affected_count = report.offerings_created` i jej `await session.flush()` + `log.info(...)`, a PRZED `progress("Rebuilding auto zones")`, dodaj:

```python
    if options.mode == "diff":
        progress("Finding orphaned offerings")
        report.orphans = await find_orphans(session, tech.id, options.distance)
        log.info("Found %d orphaned offerings", len(report.orphans))
        if options.remove_orphans and report.orphans:
            progress("Removing orphaned offerings")
            report.orphans_removed, report.remove_op_id = await remove_orphan_offerings(
                session, tech, user.id, report.orphans, options
            )
```

(`remove_orphan_offerings` powstaje w Task 3 — na razie dodaj pustą implementację, żeby moduł się importował:)

```python
async def remove_orphan_offerings(
    session: AsyncSession,
    tech: Technology,
    user_id: uuid.UUID,
    orphans: list[OrphanItem],
    options: ImportOptions,
) -> tuple[int, str]:
    """Usuwa osierocone oferty jako wycofywalna operacje bulk. Patrz Task 3."""
    raise NotImplementedError
```

f) W `run_import`, po walidacji statusu a przed `progress("Reading shapefiles")`, dodaj:

```python
    if options.mode not in ("import", "diff"):
        raise GisImportError(f"Invalid mode '{options.mode}'. Valid: import, diff")
    if options.remove_orphans and options.mode != "diff":
        raise GisImportError("--remove-orphans requires --mode diff")
```

- [ ] **Step 4: CLI — opcje i raport**

W `app/cli.py`, w komendzie `import_gis`, po parametrze `dry_run` dodaj:

```python
    mode: str = typer.Option(
        "import", help="import = tylko dodawanie; diff = dodatkowo raport ofert osieroconych"
    ),
    remove_orphans: bool = typer.Option(
        False, "--remove-orphans",
        help="Z --mode diff: usun osierocone oferty (wycofywalna operacja bulk)",
    ),
```

i przekaż do `ImportOptions(...)`:

```python
        mode=mode,
        remove_orphans=remove_orphans,
```

W `_print_report`, przed `console.print(table)`, dodaj wiersze:

```python
    if options.mode == "diff":
        table.add_row("Orphaned offerings", f"[yellow]{len(report.orphans)}[/yellow]")
        if options.remove_orphans:
            table.add_row("Orphans removed", f"[red]{report.orphans_removed}[/red]")
            if report.remove_op_id:
                table.add_row("Rollback op id", report.remove_op_id)
```

a PO `console.print(table)` dodaj listing:

```python
    if options.mode == "diff" and report.orphans and not options.remove_orphans:
        console.print("[yellow]Orphaned offerings (address no longer near the network):[/yellow]")
        for o in report.orphans[:20]:
            console.print(f"  {o.rc_code}  {o.full_address}")
        if len(report.orphans) > 20:
            console.print(f"  … and {len(report.orphans) - 20} more")
```

- [ ] **Step 5: Testy przechodzą**

Run: `uv run pytest tests/gis/test_gis_diff.py tests/gis/test_db_integration.py -v`
Expected: all PASS (3 nowe + regresja importu).

- [ ] **Step 6: Commit**

```bash
git add app/gis_import.py app/cli.py tests/gis/test_gis_diff.py
git commit -m "feat: import-gis --mode diff - raport ofert osieroconych poza zasiegiem sieci"
```

---

### Task 3: `--remove-orphans` — usuwanie z rollbackiem

**Files:**
- Modify: `app/gis_import.py` (implementacja `remove_orphan_offerings`)
- Modify: `tests/gis/test_gis_diff.py` (2 nowe testy)

- [ ] **Step 1: Napisz failujące testy**

Dopisz do `tests/gis/test_gis_diff.py`:

```python
async def test_remove_orphans_deletes_with_rollback_data(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    await _add_offering(db_session, ADDR_FAR, tech.id, user.id)

    report = await _run_db_steps(
        db_session, _options(remove_orphans=True), [TEST_LINE], ImportReport(), lambda s: None
    )

    assert report.orphans_removed == 1
    assert report.remove_op_id is not None
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM address_offerings WHERE address_code = :rc"),
            {"rc": ADDR_FAR},
        )
    ).scalar()
    assert count == 0
    # Operacja bulk w formacie zgodnym z POST /bulk/{id}/rollback.
    row = (
        await db_session.execute(
            text(
                "SELECT operation_type, affected_count, rollback_data "
                "FROM bulk_operations WHERE id = CAST(:id AS uuid)"
            ),
            {"id": report.remove_op_id},
        )
    ).one()
    assert row.operation_type == "gis_import_remove_orphans"
    assert row.affected_count == 1
    assert row.rollback_data["type"] == "remove_offering"
    assert row.rollback_data["technology_id"] == str(tech.id)
    deleted = row.rollback_data["deleted_offerings"]
    assert len(deleted) == 1
    assert deleted[0]["address_code"] == ADDR_FAR
    assert deleted[0]["status"] == "available"


async def test_remove_orphans_requires_diff_mode() -> None:
    import pytest

    from app.gis_import import GisImportError, run_import

    with pytest.raises(GisImportError, match="remove-orphans"):
        await run_import(_options(mode="import", remove_orphans=True))
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `uv run pytest tests/gis/test_gis_diff.py -v`
Expected: `test_remove_orphans_deletes_with_rollback_data` FAIL z `NotImplementedError`; `test_remove_orphans_requires_diff_mode` PASS (walidacja z Task 2).

- [ ] **Step 3: Zaimplementuj `remove_orphan_offerings`**

W `app/gis_import.py` zastąp stub z Task 2 (krok 3e) pełną implementacją:

```python
async def remove_orphan_offerings(
    session: AsyncSession,
    tech: Technology,
    user_id: uuid.UUID,
    orphans: list[OrphanItem],
    options: ImportOptions,
) -> tuple[int, str]:
    """Usuwa osierocone oferty jako wycofywalna operacje bulk.

    Reuzywa sciezki remove z bulk API — identyczny rollback_data, wiec
    POST /api/v1/admin/bulk/{id}/rollback przywraca skasowane oferty.
    Importy na poziomie funkcji: bulk.py ciagnie caly stack FastAPI,
    niepotrzebny przy zwyklym imporcie CLI.
    """
    from app.api.v1.admin.bulk import _execute_remove_offering
    from app.schemas.admin import RemoveOfferingOperation

    bulk_op = BulkOperations(
        user_id=user_id,
        operation_type="gis_import_remove_orphans",
        filter_criteria={
            "shapefiles": [str(p) for p in options.shapefiles],
            "technology": options.technology,
            "distance_m": options.distance,
            "orphan_count": len(orphans),
        },
        affected_count=0,
        rollback_data=None,
    )
    session.add(bulk_op)
    await session.flush()

    op = RemoveOfferingOperation(type="remove_offering", technology_id=tech.id)
    deleted_codes, deleted_data = await _execute_remove_offering(
        session, bulk_op.id, user_id, op, [o.rc_code for o in orphans], tech.display_name
    )
    bulk_op.rollback_data = {
        "type": "remove_offering",
        "technology_id": str(tech.id),
        "deleted_offerings": deleted_data,
    }
    bulk_op.affected_count = len(deleted_codes)
    await session.flush()
    log.info("Removed %d orphaned offerings (bulk op %s)", len(deleted_codes), bulk_op.id)
    return len(deleted_codes), str(bulk_op.id)
```

UWAGA: `BulkOperations` jest już importowane na górze `gis_import.py`. Jeśli model `BulkOperations` nie przyjmuje `rollback_data=None` w konstruktorze (sprawdź `app/models/admin.py`), pomiń ten argument — kolumna ma default NULL.

- [ ] **Step 4: Testy przechodzą**

Run: `uv run pytest tests/gis/ -v`
Expected: all PASS (diff + remove + cała regresja GIS, w tym auto-zony — usunięcie ofert triggeruje rebuild w `_run_db_steps`, strefa się kurczy zgodnie z istniejącymi testami).

- [ ] **Step 5: Commit**

```bash
git add app/gis_import.py tests/gis/test_gis_diff.py
git commit -m "feat: import-gis --remove-orphans - usuwanie osieroconych ofert jako wycofywalna operacja bulk"
```

---

### Task 4: Pełna regresja API

**Files:** brak nowych zmian (chyba że regresja coś wykryje).

- [ ] **Step 1: Cały suite**

Run: `uv run pytest tests/ -v 2>&1 | tail -20`
Expected: all PASS. Szczególna uwaga: `tests/api/test_stats.py` (istniejące pola CoverageStats nietknięte), `tests/api/test_bulk.py` (format rollback_data wspólny z `--remove-orphans`).

- [ ] **Step 2: Commit poprawek (tylko jeśli były)**

```bash
git add -A && git commit -m "test: poprawki regresji po etapie 5"
```

---

### Task 5: Plugin LMS — raporty w `etacoveragestats`

**Repo:** `/home/robertas/workspace/robertas/lms-etanetas/lms/plugins/LMSEtaCoveragePlugin` (osobne repo git — commit tam).

**Files:**
- Modify: `templates/eta/etacoveragestats.html`

Moduł PHP (`modules/etacoveragestats.php`) NIE wymaga zmian — przekazuje cały payload stats do szablonu. Nowe pola mają defaulty po stronie API, a szablon używa `isset()`, więc działa z każdą wersją API.

- [ ] **Step 1: Liczniki**

W `templates/eta/etacoveragestats.html`, w kontenerze liczników (`<div style="display:flex;gap:12px;...">`), po ostatnim boxie („Zones"), dodaj:

```smarty
    {if isset($stats.planned_overdue_count)}
    <div class="lmsbox" style="padding:12px 20px;min-width:140px;text-align:center;{if $stats.planned_overdue_count > 0}border-left:3px solid #f59e0b;{/if}">
        <div style="font-size:28px;font-weight:bold;">{$stats.planned_overdue_count}</div>
        <div style="color:#666;font-size:12px;">{trans("Planned overdue")}</div>
    </div>
    {/if}
    {if isset($stats.auto_zone_gaps_total)}
    <div class="lmsbox" style="padding:12px 20px;min-width:140px;text-align:center;{if $stats.auto_zone_gaps_total > 0}border-left:3px solid #c0392b;{/if}">
        <div style="font-size:28px;font-weight:bold;">{$stats.auto_zone_gaps_total}</div>
        <div style="color:#666;font-size:12px;">{trans("Coverage gaps in zones")}</div>
    </div>
    {/if}
```

- [ ] **Step 2: Tabele**

W tym samym pliku, wewnątrz kontenera `<div style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start;">`, po tabeli „Top uncovered localities" (po jej `{/if}`), dodaj:

```smarty
{if !empty($stats.planned_overdue)}
<table class="lmsbox lms-ui-background-cycle" style="min-width:360px;">
    <thead>
        <tr><td colspan="3" class="lms-ui-box-header">{trans("Planned overdue")}</td></tr>
        <tr>
            <td class="bold">{trans("Address")}</td>
            <td class="bold">{trans("Technology")}</td>
            <td class="bold">{trans("Planned until")}</td>
        </tr>
    </thead>
    <tbody>
    {foreach $stats.planned_overdue as $po}
        <tr class="highlight">
            <td><a href="?m=etacoverageaddress&rc_code={$po.address_code}">{$po.full_address|escape}</a></td>
            <td>{$po.technology|escape}</td>
            <td style="color:#c0392b;">{$po.planned_until|escape}</td>
        </tr>
    {/foreach}
    </tbody>
</table>
{/if}

{if !empty($stats.auto_zone_gaps)}
<table class="lmsbox lms-ui-background-cycle" style="min-width:360px;">
    <thead>
        <tr><td colspan="4" class="lms-ui-box-header">{trans("Coverage gaps in zones")} — <a href="?m=etacoveragemap" style="font-weight:normal;">{trans("Map")} →</a></td></tr>
        <tr>
            <td class="bold">{trans("Zone")}</td>
            <td class="bold">{trans("Technology")}</td>
            <td class="bold">{trans("Gaps")}</td>
            <td class="bold">{trans("Addresses")}</td>
        </tr>
    </thead>
    <tbody>
    {foreach $stats.auto_zone_gaps as $zg}
        <tr class="highlight">
            <td>{$zg.zone_name|escape}</td>
            <td>{$zg.technology|escape}</td>
            <td style="{if $zg.gap_count > 0}color:#c0392b;font-weight:bold;{/if}">{$zg.gap_count}</td>
            <td>{$zg.address_count}</td>
        </tr>
    {/foreach}
    </tbody>
</table>
{/if}
```

- [ ] **Step 3: Commit (w repo pluginu)**

```bash
cd /home/robertas/workspace/robertas/lms-etanetas/lms/plugins/LMSEtaCoveragePlugin
git add templates/eta/etacoveragestats.html
git commit -m "feat: stats - tabele planned po terminie i luk w auto-strefach"
```

---

## Checklisty QA (człowiek, po wdrożeniu)

**Stats API:** `GET /api/v1/admin/coverage/stats?scope=all` zwraca `planned_overdue_count`, `planned_overdue[]`, `auto_zone_gaps_total`, `auto_zone_gaps[]`; stare pola bez zmian.

**Diff CLI:** `uv run python -m app.cli import-gis --shapefile ... --technology gpon --distance 60 --username X --mode diff --dry-run` → tabela raportu zawiera „Orphaned offerings" + listing do 20 adresów; nic nie usunięte (dry-run i tak rollbackuje). Bez `--mode diff` flaga `--remove-orphans` → czerwony błąd.

**Remove + rollback:** `--mode diff --remove-orphans` (bez dry-run, na danych testowych) → raport pokazuje „Rollback op id"; `POST /api/v1/admin/bulk/{id}/rollback` przywraca oferty; operacja widoczna w panelu „Ostatnie operacje" na mapie LMS z przyciskiem Rollback.

**Plugin stats:** `?m=etacoveragestats` pokazuje dwa nowe liczniki (z kolorową ramką gdy > 0) i dwie tabele; adres w „Planned overdue" linkuje do `etacoverageaddress`; nagłówek tabeli luk linkuje do mapy.
