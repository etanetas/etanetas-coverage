# Auto-Zones Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ServiceZone polygons derived automatically from `available` address offerings (one auto-zone per technology), rebuilt on every offering change; `--zone-name` GIS-buffer zones removed.

**Architecture:** New `app/auto_zones.py` with `rebuild_auto_zones()` (advisory-lock per technology → one PostGIS buffer+union query over offering addresses → upsert/soft-hide `source='auto'` zone + ZoneOffering) and `rebuild_auto_zones_background()` (own session, never raises) for FastAPI `BackgroundTasks`. Triggers: end of `import-gis`, offering CRUD endpoints, bulk execute/rollback, CLI `rebuild-zones`. Spec: `docs/superpowers/specs/2026-06-11-auto-zones-design.md`.

**Tech Stack:** existing only — SQLAlchemy 2.0 async, PostGIS, Alembic (manual migrations — GeoAlchemy2), FastAPI BackgroundTasks, typer/rich, pytest (`db_session` rolled-back fixture; PostGIS must run: `docker compose up -d db`).

**Conventions:** type hints, `logging`, async-only, ruff clean (`env -u VIRTUAL_ENV uv run ruff check app/ tests/`). Prefix uv commands with `env -u VIRTUAL_ENV ` if a stale VIRTUAL_ENV breaks them.

**Code state:** `app/gis_import.py` has `upsert_zone`, `ImportOptions.zone_name`, `ImportReport.zone_name/zone_action`, a zone block in `_run_db_steps`, `_offering_speeds`, etc. `tests/gis/` has 21 tests (5 reader + 16 integration incl. 5 zone tests). Alembic head: `75bf647fc397`; versions dir: `alembic/versions/`. `ServiceZone.created_by` is nullable.

---

### Task 1: Migration — `service_zones.source`

**Files:**
- Create: `alembic/versions/<generated>_add_service_zones_source.py` (via alembic CLI)
- Modify: `app/models/service.py` (ServiceZone)

- [ ] **Step 1: Generate the migration file**

```bash
env -u VIRTUAL_ENV uv run alembic revision -m "add service_zones source column"
```

- [ ] **Step 2: Fill in the migration**

In the generated file, implement:

```python
def upgrade() -> None:
    op.add_column(
        "service_zones",
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
    )
    op.create_check_constraint(
        "ck_service_zones_source", "service_zones", "source IN ('manual', 'auto')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_service_zones_source", "service_zones", type_="check")
    op.drop_column("service_zones", "source")
```

(plain columns — no geospatial helpers needed here).

- [ ] **Step 3: Add the model field**

In `app/models/service.py`, class `ServiceZone`, after `priority`:

```python
    source: Mapped[str] = mapped_column(Text, default="manual", server_default="manual")
```

- [ ] **Step 4: Apply and verify**

```bash
env -u VIRTUAL_ENV uv run alembic upgrade head
env -u VIRTUAL_ENV uv run python -c "
import asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal
async def main():
    async with AsyncSessionLocal() as s:
        r = (await s.execute(text(\"SELECT source FROM service_zones LIMIT 1\"))).scalar()
        print('existing zone source:', r)
asyncio.run(main())
"
env -u VIRTUAL_ENV uv run pytest -q
```

Expected: `existing zone source: manual` (the "GPON tinklas" zone), 237 passed.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/ app/models/service.py
git commit -m "feat: service_zones.source column (manual|auto)"
```

---

### Task 2: `app/auto_zones.py` — `rebuild_auto_zones`

**Files:**
- Create: `app/auto_zones.py`
- Create: `tests/gis/test_auto_zones.py`

- [ ] **Step 1: Write the failing tests**

`tests/gis/test_auto_zones.py`:

```python
"""Integration tests for auto-zone rebuild — require PostgreSQL+PostGIS."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auto_zones import rebuild_auto_zones
from app.models.service import AddressOffering, ServiceZone
from app.time import now
from tests.gis.test_db_integration import (
    ADDR_FAR,
    ADDR_NEAR,
    _seed_addresses,
    _seed_tech_and_user,
)


async def _add_offering(
    session: AsyncSession, address_code: int, tech_id: uuid.UUID, user_id: uuid.UUID,
    status: str = "available", download: int = 1000, upload: int = 500,
) -> AddressOffering:
    offering = AddressOffering(
        address_code=address_code,
        technology_id=tech_id,
        status=status,
        max_download_mbps=download,
        max_upload_mbps=upload,
        status_since=now().date(),
        created_by=user_id,
    )
    session.add(offering)
    await session.flush()
    return offering


async def _zone_row(session: AsyncSession, name: str):
    return (
        await session.execute(
            text(
                """
                SELECT z.id, z.source, z.deleted_at,
                       ST_SRID(z.polygon::geometry) AS srid,
                       GeometryType(z.polygon::geometry) AS gtype,
                       ST_Contains(z.polygon::geometry,
                                   (SELECT point::geometry FROM addresses WHERE rc_code = :near)) AS has_near,
                       ST_Contains(z.polygon::geometry,
                                   (SELECT point::geometry FROM addresses WHERE rc_code = :far)) AS has_far
                FROM service_zones z WHERE z.name = :name
                """
            ),
            {"near": ADDR_NEAR, "far": ADDR_FAR, "name": name},
        )
    ).one_or_none()


async def test_rebuild_creates_auto_zone_from_available_offerings(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    await _add_offering(db_session, ADDR_NEAR, tech.id, user.id, download=2000, upload=900)
    await _add_offering(db_session, ADDR_FAR, tech.id, user.id, status="planned")

    rebuilt = await rebuild_auto_zones(db_session, tech.id)

    assert rebuilt == ["Auto: Test GPON"]
    row = await _zone_row(db_session, "Auto: Test GPON")
    assert row is not None
    assert row.source == "auto"
    assert row.deleted_at is None
    assert row.srid == 4326
    assert row.gtype == "MULTIPOLYGON"
    assert row.has_near is True   # available offering → in zone
    assert row.has_far is False   # planned only → excluded
    zo = (
        await db_session.execute(
            text("SELECT status, max_download_mbps, max_upload_mbps FROM zone_offerings WHERE zone_id = :z"),
            {"z": row.id},
        )
    ).one()
    assert (zo.status, zo.max_download_mbps, zo.max_upload_mbps) == ("available", 2000, 900)


async def test_rebuild_hides_zone_when_no_available_offerings(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    offering = await _add_offering(db_session, ADDR_NEAR, tech.id, user.id)
    await rebuild_auto_zones(db_session, tech.id)

    offering.status = "unavailable"
    await db_session.flush()
    rebuilt = await rebuild_auto_zones(db_session, tech.id)

    assert rebuilt == ["Auto: Test GPON"]
    row = await _zone_row(db_session, "Auto: Test GPON")
    assert row.deleted_at is not None  # hidden from map


async def test_rebuild_revives_hidden_zone(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    offering = await _add_offering(db_session, ADDR_NEAR, tech.id, user.id)
    await rebuild_auto_zones(db_session, tech.id)
    offering.status = "unavailable"
    await db_session.flush()
    await rebuild_auto_zones(db_session, tech.id)

    offering.status = "available"
    await db_session.flush()
    await rebuild_auto_zones(db_session, tech.id)

    row = await _zone_row(db_session, "Auto: Test GPON")
    assert row.deleted_at is None
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM service_zones WHERE source = 'auto'")
        )
    ).scalar()
    assert count == 1  # revived, not duplicated


async def test_rebuild_leaves_manual_zones_untouched(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    manual = ServiceZone(name="Reczna strefa", created_by=user.id)  # source defaults to 'manual'
    db_session.add(manual)
    await db_session.flush()
    await _add_offering(db_session, ADDR_NEAR, tech.id, user.id)

    await rebuild_auto_zones(db_session, tech.id)

    row = (
        await db_session.execute(
            text("SELECT source, deleted_at, polygon FROM service_zones WHERE name = 'Reczna strefa'")
        )
    ).one()
    assert row.source == "manual"
    assert row.deleted_at is None
    assert row.polygon is None  # untouched


async def test_rebuild_all_technologies(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    await _add_offering(db_session, ADDR_NEAR, tech.id, user.id)

    rebuilt = await rebuild_auto_zones(db_session)  # technology_id=None

    assert "Auto: Test GPON" in rebuilt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `env -u VIRTUAL_ENV uv run pytest tests/gis/test_auto_zones.py -v`
Expected: ERROR `ModuleNotFoundError: No module named 'app.auto_zones'`

- [ ] **Step 3: Implement `app/auto_zones.py`**

```python
"""Auto-zones: ServiceZone polygons derived from address offerings.

One zone per technology (`source='auto'`), polygon = union of buffers around
addresses holding an `available` offering. Rebuilt after every offering
change. Address offerings are the source of truth; auto-zones are pure
visualization.

Design: docs/superpowers/specs/2026-06-11-auto-zones-design.md
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


async def rebuild_auto_zones(
    session: AsyncSession,
    technology_id: uuid.UUID | None = None,
    radius_m: float = AUTO_ZONE_RADIUS_M,
) -> list[str]:
    """Rebuild auto-zones for one technology (or all with offerings).

    Returns names of zones rebuilt or hidden.
    """
    if technology_id is not None:
        tech_ids = [technology_id]
    else:
        rows = await session.execute(text("SELECT DISTINCT technology_id FROM address_offerings"))
        tech_ids = [row[0] for row in rows]

    rebuilt: list[str] = []
    for tech_id in tech_ids:
        name = await _rebuild_for_technology(session, tech_id, radius_m)
        if name is not None:
            rebuilt.append(name)
    return rebuilt


async def _rebuild_for_technology(
    session: AsyncSession, tech_id: uuid.UUID, radius_m: float
) -> str | None:
    """Rebuild one technology's auto-zone. Returns the zone name, or None if no-op."""
    # Serialize concurrent rebuilds of the same technology (no duplicate zones).
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('auto_zone:' || :tid))"),
        {"tid": str(tech_id)},
    )

    tech = await session.get(Technology, tech_id)
    if tech is None:
        log.warning("Auto-zone rebuild skipped: technology %s not found", tech_id)
        return None

    row = (
        await session.execute(
            text(
                """
                SELECT ST_Multi(ST_Transform(
                         ST_SimplifyPreserveTopology(
                           ST_Union(ST_Buffer(ST_Transform(a.point, 3346), :radius)), 1.0),
                         4326)) AS poly,
                       MAX(ao.max_download_mbps) AS dl,
                       MAX(ao.max_upload_mbps) AS ul
                FROM addresses a
                JOIN address_offerings ao ON ao.address_code = a.rc_code
                WHERE ao.technology_id = :tid
                  AND ao.status = 'available'
                  AND a.deleted_at IS NULL
                  AND a.point IS NOT NULL
                """
            ),
            {"radius": radius_m, "tid": tech_id},
        )
    ).one()

    # Auto zone lookup ignores deleted_at: a hidden zone is revived on rebuild.
    zone = (
        await session.execute(
            select(ServiceZone)
            .join(ZoneOffering, ZoneOffering.zone_id == ServiceZone.id)
            .where(ServiceZone.source == "auto", ZoneOffering.technology_id == tech_id)
            .order_by(ServiceZone.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()

    if row.poly is None:
        if zone is not None and zone.deleted_at is None:
            zone.deleted_at = now()
            await session.flush()
            log.info("Auto zone '%s' hidden (no available offerings)", zone.name)
            return zone.name
        return None

    name = f"Auto: {tech.display_name}"
    if zone is None:
        zone = ServiceZone(
            name=name,
            description="Strefa generowana automatycznie z ofert adresowych",
            polygon=row.poly,
            source="auto",
            created_by=None,
        )
        session.add(zone)
    else:
        zone.polygon = row.poly
        zone.name = name
        zone.deleted_at = None
    await session.flush()

    current = now()
    offering_stmt = (
        pg_insert(ZoneOffering)
        .values(
            id=uuid.uuid4(),
            zone_id=zone.id,
            technology_id=tech_id,
            status="available",
            max_download_mbps=row.dl,
            max_upload_mbps=row.ul,
            status_since=current.date(),
            created_at=current,
            updated_at=current,
        )
        .on_conflict_do_update(
            index_elements=["zone_id", "technology_id"],
            set_={
                "status": "available",
                "max_download_mbps": row.dl,
                "max_upload_mbps": row.ul,
                "updated_at": current,
            },
        )
    )
    await session.execute(offering_stmt)
    log.info("Auto zone '%s' rebuilt", name)
    return name


async def rebuild_auto_zones_background(technology_id: uuid.UUID | None = None) -> None:
    """For FastAPI BackgroundTasks: own session, commits, never raises."""
    try:
        async with AsyncSessionLocal() as session:
            await rebuild_auto_zones(session, technology_id)
            await session.commit()
    except Exception:
        log.exception("Auto-zone background rebuild failed (technology_id=%s)", technology_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `env -u VIRTUAL_ENV uv run pytest tests/gis/ -v` → 26 passed.
Run: `env -u VIRTUAL_ENV uv run ruff check app/ tests/gis/` → clean.

- [ ] **Step 5: Commit**

```bash
git add app/auto_zones.py tests/gis/test_auto_zones.py
git commit -m "feat: auto-zones — rebuild ServiceZone polygons from address offerings"
```

---

### Task 3: Remove `--zone-name`, wire rebuild into `import-gis`

**Files:**
- Modify: `app/gis_import.py`
- Modify: `app/cli.py`
- Modify: `tests/gis/test_db_integration.py`

- [ ] **Step 1: Adjust tests first**

In `tests/gis/test_db_integration.py`:

(a) DELETE these 5 tests entirely: `test_upsert_zone_creates_zone_with_coverage_polygon`,
`test_upsert_zone_rejects_ambiguous_name`, `test_run_db_steps_creates_zone_when_requested`,
`test_run_db_steps_zone_rerun_updates_in_place`, `test_run_db_steps_no_zone_without_zone_name`.

(b) Remove `upsert_zone` from the `from app.gis_import import (...)` block.
Keep `from app.models.service import ServiceZone` ONLY if still used (it is —
by `tests/gis/test_auto_zones.py` via its own import; in THIS file remove it
if no remaining test uses it).

(c) ADD this test:

```python
async def test_run_db_steps_rebuilds_auto_zone(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    await _seed_tech_and_user(db_session)

    report = await _run_db_steps(
        db_session, _options(), [TEST_LINE], ImportReport(), progress=lambda stage: None
    )

    assert report.zones_rebuilt == ["Auto: Test GPON"]
    row = (
        await db_session.execute(
            text("SELECT source, deleted_at FROM service_zones WHERE name = 'Auto: Test GPON'")
        )
    ).one()
    assert row.source == "auto"
    assert row.deleted_at is None
```

- [ ] **Step 2: Run to verify failures**

Run: `env -u VIRTUAL_ENV uv run pytest tests/gis/test_db_integration.py -v`
Expected: `test_run_db_steps_rebuilds_auto_zone` fails (`zones_rebuilt` missing); deleted tests gone.

- [ ] **Step 3: Implement removals + wiring**

In `app/gis_import.py`:

(a) top imports: add `from dataclasses import dataclass, field` (extend the
existing dataclass import) and `from app.auto_zones import rebuild_auto_zones`;
remove `ServiceZone, ZoneOffering` from the service-models import (keep
`AddressOffering`).

(b) `ImportOptions`: delete the `zone_name` field.

(c) `ImportReport`: delete `zone_name` and `zone_action`; add as last field:

```python
    zones_rebuilt: list[str] = field(default_factory=list)
```

(d) Delete the whole `upsert_zone` function.

(e) In `_run_db_steps`: delete `"zone_name": options.zone_name,` from
`filter_criteria`; replace the `if options.zone_name:` block with:

```python
    progress("Rebuilding auto zones")
    report.zones_rebuilt = await rebuild_auto_zones(session, tech.id)
```

In `app/cli.py`:

(f) `import_gis` command: delete the `zone_name` parameter and the
`zone_name=zone_name,` line in `ImportOptions(...)`.

(g) `_print_report`: replace the `if report.zone_name:` block with:

```python
    if report.zones_rebuilt:
        table.add_row("Auto zones", ", ".join(report.zones_rebuilt))
```

- [ ] **Step 4: Run tests**

```bash
env -u VIRTUAL_ENV uv run pytest tests/gis/ -v
env -u VIRTUAL_ENV uv run ruff check app/ tests/gis/
env -u VIRTUAL_ENV uv run python -m app.cli import-gis --help
```

Expected: 22 passed (26 − 5 + 1); ruff clean; `--zone-name` gone from help.

- [ ] **Step 5: Commit**

```bash
git add app/gis_import.py app/cli.py tests/gis/test_db_integration.py
git commit -m "feat!: replace import-gis --zone-name with automatic auto-zone rebuild"
```

---

### Task 4: API triggers (offering CRUD + bulk)

**Files:**
- Modify: `app/api/v1/admin/addresses.py` (3 endpoints)
- Modify: `app/api/v1/admin/bulk.py` (2 endpoints)
- Create: `tests/api/test_auto_zone_triggers.py`

- [ ] **Step 1: Write the failing tests**

`tests/api/test_auto_zone_triggers.py` — wiring tests: monkeypatch the
background function **where it's imported** (in the router modules) and assert
it gets scheduled with the right technology. Look at `tests/api/conftest.py`
for the existing authenticated client fixture and follow its naming exactly
(adapt fixture names below if conftest differs — keep assertions identical):

```python
"""Verify offering mutations schedule an auto-zone rebuild (wiring only)."""

import uuid

import pytest


@pytest.fixture
def rebuild_recorder(monkeypatch):
    calls: list[uuid.UUID | None] = []

    async def _record(technology_id=None):
        calls.append(technology_id)

    monkeypatch.setattr("app.api.v1.admin.addresses.rebuild_auto_zones_background", _record)
    monkeypatch.setattr("app.api.v1.admin.bulk.rebuild_auto_zones_background", _record)
    return calls


async def test_create_offering_schedules_rebuild(client, rebuild_recorder, seeded_address, seeded_technology):
    resp = await client.post(
        f"/api/v1/admin/addresses/{seeded_address}/offerings",
        json={
            "technology_id": str(seeded_technology),
            "status": "available",
            "max_download_mbps": 1000,
            "max_upload_mbps": 500,
            "status_since": "2026-06-11",
        },
    )
    assert resp.status_code == 201
    assert rebuild_recorder == [seeded_technology]
```

(One test for create is sufficient as a wiring test for addresses.py — patch
target proves the import path; update/delete use the same import. Add one
analogous test for bulk execute ONLY if the existing bulk test fixtures make
it cheap — i.e. there is already a test that successfully calls
`/bulk/execute`; copy its setup and add the `rebuild_recorder` assertion. If
bulk tests require heavy preview-token setup, skip the bulk test and note it —
the wiring is identical one-liner code.)

If `tests/api/conftest.py` lacks `seeded_address`/`seeded_technology`
fixtures, create them in this test file using the patterns from
`tests/api/test_admin_crud.py` (seed a locality chain + address + technology
through the DB session fixture used there).

- [ ] **Step 2: Run to verify failure**

Run: `env -u VIRTUAL_ENV uv run pytest tests/api/test_auto_zone_triggers.py -v`
Expected: FAIL — `AttributeError: module 'app.api.v1.admin.addresses' has no attribute 'rebuild_auto_zones_background'`

- [ ] **Step 3: Implement triggers**

`app/api/v1/admin/addresses.py`:

(a) imports: `from fastapi import BackgroundTasks` (extend existing fastapi
import) and `from app.auto_zones import rebuild_auto_zones_background`.

(b) `create_address_offering`: add parameter `background_tasks: BackgroundTasks,`
(before the injected dependencies); after `await db.commit()` add:

```python
    background_tasks.add_task(rebuild_auto_zones_background, body.technology_id)
```

(c) `update_address_offering`: same parameter; after commit:

```python
    background_tasks.add_task(rebuild_auto_zones_background, offering.technology_id)
```

(NOTE: capture `technology_id = offering.technology_id` BEFORE the commit if
`db.refresh` isn't called before use — in this endpoint `await db.refresh(offering)`
follows the commit, so reading after refresh is fine; in doubt capture early.)

(d) `delete_address_offering`: same parameter; capture
`technology_id = offering.technology_id` before `await db.delete(offering)`;
after commit:

```python
    background_tasks.add_task(rebuild_auto_zones_background, technology_id)
```

`app/api/v1/admin/bulk.py`:

(e) imports as in (a).

(f) `bulk_execute`: add `background_tasks: BackgroundTasks,` parameter; after
`await db.commit()` (before `return created(...)`):

```python
    background_tasks.add_task(rebuild_auto_zones_background, op.technology_id)
```

(g) `bulk_rollback`: add the parameter; the rolled-back technology comes from
`rollback_data["technology_id"]` (string) — read the endpoint body to find the
variable holding `rollback_data`, then after its `await db.commit()`:

```python
    background_tasks.add_task(
        rebuild_auto_zones_background, uuid.UUID(rollback_data["technology_id"])
    )
```

(adjust the variable name to the actual one in the function; `uuid` is already
imported in bulk.py).

- [ ] **Step 4: Run tests**

```bash
env -u VIRTUAL_ENV uv run pytest tests/api/ tests/gis/ -q
env -u VIRTUAL_ENV uv run ruff check app/ tests/
```

Expected: all pass (previous api tests unaffected — BackgroundTasks param is
injected by FastAPI), ruff clean.

- [ ] **Step 5: Commit**

```bash
git add app/api/v1/admin/addresses.py app/api/v1/admin/bulk.py tests/api/test_auto_zone_triggers.py
git commit -m "feat: schedule auto-zone rebuild after offering and bulk mutations"
```

---

### Task 5: CLI `rebuild-zones`, docs, real run

**Files:**
- Modify: `app/cli.py`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the command**

In `app/cli.py` (imports: add `rebuild_auto_zones` — note: the CLI runs its
own session, so import both; `import uuid` NOT needed — technology is resolved
by variant_code via `resolve_technology` from gis_import):

```python
from app.auto_zones import AUTO_ZONE_RADIUS_M, rebuild_auto_zones
from app.database import AsyncSessionLocal
from app.gis_import import resolve_technology
```

Command (after `import-gis`):

```python
@app.command("rebuild-zones")
def rebuild_zones(
    technology: str | None = typer.Option(
        None, help="Technology variant_code (e.g. gpon); omit to rebuild all"
    ),
    radius: float = typer.Option(AUTO_ZONE_RADIUS_M, help="Buffer radius in meters around addresses"),
):
    """Rebuild auto-zones from address offerings."""
    configure_logging()
    try:
        asyncio.run(_rebuild_zones(technology, radius))
    except GisImportError as e:
        rprint(f"[red]ERROR: {e}[/red]", file=sys.stderr)
        raise typer.Exit(code=1) from None
    except Exception as e:
        rprint(f"[red]ERROR: {type(e).__name__}: {e}[/red]", file=sys.stderr)
        raise typer.Exit(code=1) from None


async def _rebuild_zones(technology: str | None, radius: float) -> None:
    async with AsyncSessionLocal() as session:
        tech_id = None
        if technology is not None:
            tech_id = (await resolve_technology(session, technology)).id
        rebuilt = await rebuild_auto_zones(session, tech_id, radius_m=radius)
        await session.commit()
    if rebuilt:
        rprint(f"[green]Rebuilt {len(rebuilt)} auto zone(s):[/green] " + ", ".join(rebuilt))
    else:
        rprint("[yellow]No auto zones to rebuild (no offerings found).[/yellow]")
```

- [ ] **Step 2: Smoke + full suite**

```bash
env -u VIRTUAL_ENV uv run python -m app.cli rebuild-zones --help
env -u VIRTUAL_ENV uv run python -m app.cli rebuild-zones --technology no_such_tech  # red error, exit 1
env -u VIRTUAL_ENV uv run pytest -q
env -u VIRTUAL_ENV uv run ruff check app/ tests/
```

Expected: help OK; `Technology 'no_such_tech' not found`; full suite passes; ruff clean.

- [ ] **Step 3: Real run on dev data (persists — intended)**

```bash
env -u VIRTUAL_ENV uv run python -m app.cli rebuild-zones --technology gpon
```

Expected: `Rebuilt 1 auto zone(s): Auto: Šviesolaidis GPON` (from the 4644
imported offerings). Authoritative verification via SQL:

```bash
env -u VIRTUAL_ENV uv run python -c "
import asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal
async def main():
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text(\"\"\"SELECT name, source, deleted_at IS NULL AS active,
            ST_NPoints(polygon::geometry) AS npoints FROM service_zones\"\"\"))).all()
        for r in rows: print(r)
asyncio.run(main())
"
```

Expected: the auto zone active with a large `npoints`, plus the old manual
"GPON tinklas" zone. Remind the user they can now delete "GPON tinklas" via
the admin API/panel (it's redundant) — do NOT delete it yourself.

- [ ] **Step 4: Update CLAUDE.md**

In `## Commands`, after the import-gis block, and update the import-gis line
(remove `[--zone-name "Zone"]`):

```bash
# Import GIS network shapefiles as address offerings (dry-run first!)
uv run python -m app.cli import-gis --shapefile X.shp [--shapefile Y.shp] \
  --technology gpon --distance 100 --username U [--dry-run]

# Rebuild auto-zones (ServiceZone derived from address offerings)
uv run python -m app.cli rebuild-zones [--technology gpon] [--radius 150]
```

- [ ] **Step 5: Commit**

```bash
git add app/cli.py CLAUDE.md
git commit -m "feat: rebuild-zones CLI command"
```
