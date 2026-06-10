# GIS Import Zone Creation (`--zone-name`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `import-gis --zone-name "X"` additionally creates/refreshes a `ServiceZone` polygon (buffer around the imported network) + `ZoneOffering`, making coverage visible on the map.

**Architecture:** One new function `upsert_zone` in `app/gis_import.py` computes the polygon with a single PostGIS query over the existing `gis_import_geom` temp table (buffer+union+simplify in EPSG:3346 → WGS84 MULTIPOLYGON), upserts `ServiceZone` by name and `ZoneOffering` by `(zone_id, technology_id)`. Wired into `_run_db_steps` after `insert_offerings` (same transaction → dry-run covers it). CLI gains `--zone-name` and a report row. Spec: `docs/superpowers/specs/2026-06-10-gis-import-zones-design.md`.

**Tech Stack:** existing stack only — SQLAlchemy 2.0 async, PostGIS, GeoAlchemy2, typer/rich, pytest with rolled-back `db_session` fixture (PostGIS must be running: `docker compose up -d db`).

**Conventions (CLAUDE.md):** type hints, `logging`, async-only, ruff clean (`env -u VIRTUAL_ENV uv run ruff check app/ tests/gis/`). Prefix uv with `env -u VIRTUAL_ENV ` if a stale VIRTUAL_ENV breaks it.

**State of the code today:** `app/gis_import.py` contains `read_geometries`, `GisImportError`, `ImportOptions`, `ImportReport`, `BATCH_SIZE`, `VALID_STATUSES`, `load_temp_geometries`, `match_addresses`, `resolve_technology`, `resolve_user`, `insert_offerings`, `_run_db_steps`, `run_import`. `tests/gis/test_db_integration.py` has helpers `_seed_addresses`, `_seed_tech_and_user`, `_options`, constants `ADDR_NEAR`/`ADDR_FAR`/`ADDR_FLAT`, `TEST_LINE`, 10 tests. `tests/gis/test_reader.py` has 5 tests (15 total).

---

### Task 1: Make `load_temp_geometries` re-runnable within one transaction

Calling `_run_db_steps` twice on one session (needed for zone-rerun tests, and
harmless robustness) currently fails: `CREATE TEMP TABLE` collides because
`ON COMMIT DROP` only fires at commit.

**Files:**
- Modify: `app/gis_import.py` (function `load_temp_geometries`)
- Modify: `tests/gis/test_db_integration.py` (add one test)

- [ ] **Step 1: Write the failing test**

Append to `tests/gis/test_db_integration.py`:

```python
async def test_load_temp_geometries_rerun_same_transaction(db_session: AsyncSession) -> None:
    await load_temp_geometries(db_session, [TEST_LINE])
    # second call in the same transaction must not collide with the first table
    await load_temp_geometries(db_session, ["POINT(580050 6050000)"])

    count = (await db_session.execute(text("SELECT count(*) FROM gis_import_geom"))).scalar()
    assert count == 1  # table was replaced, not appended to
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env -u VIRTUAL_ENV uv run pytest tests/gis/test_db_integration.py::test_load_temp_geometries_rerun_same_transaction -v`
Expected: FAIL with `DuplicateTableError`/`ProgrammingError: relation "gis_import_geom" already exists`

- [ ] **Step 3: Implement**

In `app/gis_import.py`, `load_temp_geometries`, add a DROP before the CREATE:

```python
    await session.execute(text("DROP TABLE IF EXISTS gis_import_geom"))
    await session.execute(
        text("CREATE TEMP TABLE gis_import_geom (geom geometry(Geometry, 3346)) ON COMMIT DROP")
    )
```

(the CREATE line already exists — only the DROP line is new).

- [ ] **Step 4: Run tests to verify they pass**

Run: `env -u VIRTUAL_ENV uv run pytest tests/gis/ -v`
Expected: 16 passed

- [ ] **Step 5: Commit**

```bash
git add app/gis_import.py tests/gis/test_db_integration.py
git commit -m "fix: allow gis_import temp table reload within one transaction"
```

---

### Task 2: `upsert_zone` + speed-defaults helper

**Files:**
- Modify: `app/gis_import.py`
- Modify: `tests/gis/test_db_integration.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/gis/test_db_integration.py` (extend the existing
`from app.gis_import import (...)` block with `upsert_zone`; add
`from app.models.service import ServiceZone` to the imports):

```python
async def test_upsert_zone_creates_zone_with_coverage_polygon(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    await load_temp_geometries(db_session, [TEST_LINE])

    action = await upsert_zone(
        db_session, _options(zone_name="Test zona", distance=100.0), tech, user.id
    )

    assert action == "created"
    row = (
        await db_session.execute(
            text(
                """
                SELECT z.name,
                       ST_SRID(z.polygon::geometry) AS srid,
                       GeometryType(z.polygon::geometry) AS gtype,
                       ST_Contains(z.polygon::geometry,
                                   (SELECT point::geometry FROM addresses WHERE rc_code = :near)) AS has_near,
                       ST_Contains(z.polygon::geometry,
                                   (SELECT point::geometry FROM addresses WHERE rc_code = :far)) AS has_far,
                       zo.status, zo.max_download_mbps
                FROM service_zones z
                JOIN zone_offerings zo ON zo.zone_id = z.id
                WHERE z.name = 'Test zona' AND z.deleted_at IS NULL
                """
            ),
            {"near": ADDR_NEAR, "far": ADDR_FAR},
        )
    ).one()
    assert row.srid == 4326
    assert row.gtype == "MULTIPOLYGON"
    assert row.has_near is True   # ~30 m from line, buffer 100 m
    assert row.has_far is False   # ~2 km away
    assert row.status == "available"
    assert row.max_download_mbps == 2500


async def test_upsert_zone_rejects_ambiguous_name(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    db_session.add_all(
        [
            ServiceZone(name="Dup zona", created_by=user.id),
            ServiceZone(name="Dup zona", created_by=user.id),
        ]
    )
    await db_session.flush()
    await load_temp_geometries(db_session, [TEST_LINE])

    with pytest.raises(GisImportError, match="Multiple active zones"):
        await upsert_zone(db_session, _options(zone_name="Dup zona"), tech, user.id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `env -u VIRTUAL_ENV uv run pytest tests/gis/test_db_integration.py -v`
Expected: ERROR with `ImportError: cannot import name 'upsert_zone'`

- [ ] **Step 3: Implement**

In `app/gis_import.py`:

(a) add `ServiceZone, ZoneOffering` to the existing service-models import:

```python
from app.models.service import AddressOffering, ServiceZone, ZoneOffering
```

(b) add the speed helper right above `insert_offerings` and use it there (DRY):

```python
def _offering_speeds(options: ImportOptions, tech: Technology) -> tuple[int, int]:
    """Download/upload for offerings: CLI override wins, else technology maxima."""
    download = options.download if options.download is not None else (tech.theoretical_max_dl_mbps or 0)
    upload = options.upload if options.upload is not None else (tech.theoretical_max_ul_mbps or 0)
    return download, upload
```

In `insert_offerings`, replace the two `download = ...` / `upload = ...` lines with:

```python
    download, upload = _offering_speeds(options, tech)
```

(c) append `upsert_zone` after `insert_offerings`:

```python
async def upsert_zone(
    session: AsyncSession,
    options: ImportOptions,
    tech: Technology,
    user_id: uuid.UUID,
) -> str:
    """Create or refresh the coverage ServiceZone + ZoneOffering from the temp table.

    Polygon = network geometries buffered by `options.distance` meters,
    dissolved, simplified (1 m) and transformed to WGS84. Returns
    ``"created"`` or ``"updated"``.
    """
    polygon = (
        await session.execute(
            text(
                """
                SELECT ST_Multi(ST_Transform(
                         ST_SimplifyPreserveTopology(
                           ST_Union(ST_Buffer(geom, :distance)), 1.0),
                         4326))
                FROM gis_import_geom
                """
            ),
            {"distance": options.distance},
        )
    ).scalar_one()
    if polygon is None:
        raise GisImportError("Cannot build zone polygon: no geometries loaded")

    result = await session.execute(
        select(ServiceZone).where(
            ServiceZone.name == options.zone_name, ServiceZone.deleted_at.is_(None)
        )
    )
    zones = result.scalars().all()
    if len(zones) > 1:
        raise GisImportError(
            f"Multiple active zones named '{options.zone_name}' — clean up duplicates first"
        )

    if zones:
        zone = zones[0]
        zone.polygon = polygon
        action = "updated"
    else:
        zone = ServiceZone(
            name=options.zone_name,
            description=f"Imported from GIS shapefiles (distance {options.distance:g} m)",
            polygon=polygon,
            created_by=user_id,
        )
        session.add(zone)
        action = "created"
    await session.flush()

    current = now()
    download, upload = _offering_speeds(options, tech)
    offering_stmt = (
        pg_insert(ZoneOffering)
        .values(
            id=uuid.uuid4(),
            zone_id=zone.id,
            technology_id=tech.id,
            status=options.status,
            max_download_mbps=download,
            max_upload_mbps=upload,
            status_since=current.date(),
            created_at=current,
            updated_at=current,
        )
        .on_conflict_do_update(
            index_elements=["zone_id", "technology_id"],
            set_={
                "status": options.status,
                "max_download_mbps": download,
                "max_upload_mbps": upload,
                "status_since": current.date(),
                "updated_at": current,
            },
        )
    )
    await session.execute(offering_stmt)
    return action
```

(d) extend the dataclasses:

```python
@dataclass
class ImportOptions:
    shapefiles: list[Path]
    technology: str
    distance: float
    username: str
    status: str = "available"
    download: int | None = None
    upload: int | None = None
    dry_run: bool = False
    zone_name: str | None = None


@dataclass
class ImportReport:
    geometries_loaded: int = 0
    inactive_skipped: int = 0
    addresses_matched: int = 0
    offerings_created: int = 0
    existing_skipped: int = 0
    zone_name: str | None = None
    zone_action: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `env -u VIRTUAL_ENV uv run pytest tests/gis/ -v`
Expected: 18 passed

- [ ] **Step 5: Commit**

```bash
git add app/gis_import.py tests/gis/test_db_integration.py
git commit -m "feat: upsert_zone — coverage ServiceZone + ZoneOffering from GIS import"
```

---

### Task 3: Wire zone into `_run_db_steps`

**Files:**
- Modify: `app/gis_import.py` (function `_run_db_steps`)
- Modify: `tests/gis/test_db_integration.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/gis/test_db_integration.py`:

```python
async def test_run_db_steps_creates_zone_when_requested(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    await _seed_tech_and_user(db_session)

    report = await _run_db_steps(
        db_session,
        _options(zone_name="Zona A"),
        [TEST_LINE],
        ImportReport(geometries_loaded=1),
        progress=lambda stage: None,
    )

    assert report.zone_name == "Zona A"
    assert report.zone_action == "created"
    zones = (
        await db_session.execute(text("SELECT count(*) FROM service_zones WHERE name = 'Zona A'"))
    ).scalar()
    assert zones == 1


async def test_run_db_steps_zone_rerun_updates_in_place(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    await _seed_tech_and_user(db_session)

    first = await _run_db_steps(
        db_session, _options(zone_name="Zona B"), [TEST_LINE],
        ImportReport(), progress=lambda stage: None,
    )
    second = await _run_db_steps(
        db_session, _options(zone_name="Zona B", status="planned"), [TEST_LINE],
        ImportReport(), progress=lambda stage: None,
    )

    assert first.zone_action == "created"
    assert second.zone_action == "updated"
    row = (
        await db_session.execute(
            text(
                """
                SELECT count(*) AS zones,
                       (SELECT count(*) FROM zone_offerings) AS offerings,
                       (SELECT status FROM zone_offerings LIMIT 1) AS status
                FROM service_zones WHERE name = 'Zona B' AND deleted_at IS NULL
                """
            )
        )
    ).one()
    assert row.zones == 1
    assert row.offerings == 1       # upserted, not duplicated
    assert row.status == "planned"  # rerun updates the zone offering


async def test_run_db_steps_no_zone_without_zone_name(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    await _seed_tech_and_user(db_session)

    report = await _run_db_steps(
        db_session, _options(), [TEST_LINE], ImportReport(), progress=lambda stage: None
    )

    assert report.zone_name is None
    assert report.zone_action is None
    zones = (await db_session.execute(text("SELECT count(*) FROM service_zones"))).scalar()
    assert zones == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `env -u VIRTUAL_ENV uv run pytest tests/gis/test_db_integration.py -v -k zone`
Expected: the two new `_run_db_steps` zone tests FAIL on `report.zone_action` being `None` (and `no_zone_without_zone_name` may already pass — that's fine).

- [ ] **Step 3: Implement**

In `app/gis_import.py`, `_run_db_steps`:

(a) add `"zone_name": options.zone_name,` to the `filter_criteria` dict of the
`BulkOperations` row.

(b) after the `log.info("Created %d offerings ...")` call and before
`return report`, add:

```python
    if options.zone_name:
        progress("Creating coverage zone")
        report.zone_name = options.zone_name
        report.zone_action = await upsert_zone(session, options, tech, user.id)
        log.info("Zone '%s' %s", options.zone_name, report.zone_action)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `env -u VIRTUAL_ENV uv run pytest tests/gis/ -v`
Expected: 21 passed

- [ ] **Step 5: Commit**

```bash
git add app/gis_import.py tests/gis/test_db_integration.py
git commit -m "feat: optional coverage zone creation in GIS import pipeline"
```

---

### Task 4: CLI `--zone-name`, report row, real dry-run, docs

**Files:**
- Modify: `app/cli.py`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the CLI option**

In `app/cli.py`, `import_gis` command — add parameter after `dry_run`:

```python
    zone_name: str | None = typer.Option(
        None, "--zone-name", help="Also create/refresh a coverage ServiceZone with this name"
    ),
```

and pass it into `ImportOptions`:

```python
        zone_name=zone_name,
```

In `_print_report`, after the `"Existing skipped"` row, add:

```python
    if report.zone_name:
        table.add_row("Zone", f'"{report.zone_name}" ({report.zone_action})')
```

- [ ] **Step 2: Smoke-test help + lint + full gis tests**

```bash
env -u VIRTUAL_ENV uv run python -m app.cli import-gis --help
env -u VIRTUAL_ENV uv run ruff check app/ tests/gis/
env -u VIRTUAL_ENV uv run pytest tests/gis/ -q
```

Expected: `--zone-name` listed in help; ruff clean; 21 passed.

- [ ] **Step 3: Real-data dry run with zone**

```bash
env -u VIRTUAL_ENV uv run python -m app.cli import-gis \
  --shapefile /home/robertas/Downloads/etanetas/Rys_tinkl \
  --shapefile /home/robertas/Downloads/etanetas/Rys_t \
  --technology gpon --distance 100 --username robert \
  --zone-name "GPON tinklas" --dry-run
```

Expected: summary table includes `Zone | "GPON tinklas" (created)`; addresses
matched ~4644 (same as before — zone must not change matching). Verify nothing
persisted:

```bash
env -u VIRTUAL_ENV uv run python - <<'EOF'
import asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as s:
        z = (await s.execute(text("SELECT count(*) FROM service_zones"))).scalar()
        print("service_zones:", z)

asyncio.run(main())
EOF
```

Expected: `service_zones: 0` (unless pre-existing zones exist — compare with the count before the dry run if unsure).

- [ ] **Step 4: Update CLAUDE.md**

In the `## Commands` section, replace the import-gis lines with:

```bash
# Import GIS network shapefiles as address offerings (dry-run first!)
uv run python -m app.cli import-gis --shapefile X.shp [--shapefile Y.shp] \
  --technology gpon --distance 100 --username U [--zone-name "Zone"] [--dry-run]
```

- [ ] **Step 5: Full suite + commit**

```bash
env -u VIRTUAL_ENV uv run pytest -q
env -u VIRTUAL_ENV uv run ruff check .
git add app/cli.py CLAUDE.md
git commit -m "feat: --zone-name option for import-gis with report row"
```

Expected: 237 passed (231 + 6 new), ruff clean.

The **real import** with `--zone-name` (no `--dry-run`) is run by the user
after reviewing the dry-run output.
