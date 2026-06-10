# GIS Import (`import-gis` CLI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CLI command `import-gis` that reads network shapefiles (lines + points, LKS94/EPSG:3346), matches building addresses within `--distance` meters via PostGIS, and creates `AddressOffering` rows for a given technology.

**Architecture:** All logic in new `app/gis_import.py` (pyshp reader → temp PostGIS table with GiST index → one `ST_DWithin` match query → batched `ON CONFLICT DO NOTHING` inserts + `BulkOperations` audit row). `app/cli.py` gets a thin typer command with rich Progress/Table. Spec: `docs/superpowers/specs/2026-06-10-gis-import-design.md`.

**Tech Stack:** Python 3.12, typer, rich, pyshp (new dep), SQLAlchemy 2.0 async, PostGIS, pytest (existing `db_session` rollback fixture in `tests/conftest.py`).

**Conventions reminder (from CLAUDE.md):** type hints everywhere, `logging` not `print` (rich output in CLI layer is the existing exception), async DB only, no bare `except`.

---

### Task 1: Add pyshp dependency

**Files:**
- Modify: `pyproject.toml` (via uv)

- [ ] **Step 1: Add the dependency**

```bash
cd /home/robertas/workspace/robertas/etanetas-coverage
uv add "pyshp>=2.3"
```

- [ ] **Step 2: Verify it imports**

Run: `uv run python -c "import shapefile; print(shapefile.__version__)"`
Expected: a version string ≥ 2.3, exit 0.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add pyshp for GIS shapefile import"
```

---

### Task 2: Shapefile reader (`read_geometries`)

Reads one shapefile into WKT strings, skipping records whose `Busena` (status)
attribute is not `'v'` (operational). PointZ → `POINT(x y)`, PolyLineZ → one
`LINESTRING(...)` per part. Z is dropped (pyshp's `.points` is already 2D).

**Files:**
- Create: `app/gis_import.py`
- Create: `tests/gis/__init__.py` (empty)
- Create: `tests/gis/test_reader.py`

- [ ] **Step 1: Write the failing tests**

`tests/gis/__init__.py`: empty file.

`tests/gis/test_reader.py`:

```python
"""Unit tests for shapefile reading — no DB required."""

from pathlib import Path

import pytest
import shapefile

from app.gis_import import GisImportError, read_geometries


def _write_points(path: Path, records: list[tuple[float, float, str]]) -> None:
    """Write a POINTZ shapefile with a Busena field."""
    with shapefile.Writer(str(path), shapeType=shapefile.POINTZ) as w:
        w.field("Busena", "C", size=10)
        for x, y, busena in records:
            w.pointz(x, y, 0)
            w.record(busena)


def _write_lines(path: Path, lines: list[tuple[list[list[list[float]]], str]]) -> None:
    """Write a POLYLINEZ shapefile. Each entry: (parts, busena)."""
    with shapefile.Writer(str(path), shapeType=shapefile.POLYLINEZ) as w:
        w.field("Busena", "C", size=10)
        for parts, busena in lines:
            w.linez(parts)
            w.record(busena)


def test_reads_points_and_skips_inactive(tmp_path: Path) -> None:
    _write_points(
        tmp_path / "pts",
        [(580000.0, 6050000.0, "v"), (580010.0, 6050010.0, "b"), (580020.0, 6050020.0, "v")],
    )
    wkts, skipped = read_geometries(tmp_path / "pts")
    assert wkts == ["POINT(580000.0 6050000.0)", "POINT(580020.0 6050020.0)"]
    assert skipped == 1


def test_reads_multipart_polyline_as_separate_linestrings(tmp_path: Path) -> None:
    _write_lines(
        tmp_path / "lines",
        [([[[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]], [[20.0, 0.0, 0.0], [30.0, 5.0, 0.0]]], "v")],
    )
    wkts, skipped = read_geometries(tmp_path / "lines")
    assert wkts == ["LINESTRING(0.0 0.0, 10.0 0.0)", "LINESTRING(20.0 0.0, 30.0 5.0)"]
    assert skipped == 0


def test_accepts_path_with_shp_extension(tmp_path: Path) -> None:
    _write_points(tmp_path / "pts", [(1.0, 2.0, "v")])
    wkts, _ = read_geometries(tmp_path / "pts.shp")
    assert wkts == ["POINT(1.0 2.0)"]


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(GisImportError, match="not found"):
        read_geometries(tmp_path / "nope")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gis/test_reader.py -v`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'app.gis_import'`

- [ ] **Step 3: Write the reader**

`app/gis_import.py`:

```python
"""Import network coverage from GIS shapefiles into address_offerings.

Reads ESRI shapefiles (LKS94 / EPSG:3346) with network lines and points,
matches building addresses within a distance using PostGIS ST_DWithin, and
creates AddressOffering rows for a given technology.

Design: docs/superpowers/specs/2026-06-10-gis-import-design.md
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import shapefile

log = logging.getLogger(__name__)

BATCH_SIZE = 500
VALID_STATUSES = {"available", "planned", "under_construction", "unavailable"}


class GisImportError(Exception):
    """Validation or input error — reported to the user, exit code 1."""


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


@dataclass
class ImportReport:
    geometries_loaded: int = 0
    inactive_skipped: int = 0
    addresses_matched: int = 0
    offerings_created: int = 0
    existing_skipped: int = 0


def read_geometries(path: Path) -> tuple[list[str], int]:
    """Read one shapefile into WKT strings (coordinates assumed EPSG:3346).

    Records whose ``Busena`` attribute is not ``'v'`` (operational) are
    skipped. Z coordinates are dropped. Returns ``(wkts, skipped_count)``.
    """
    shp = Path(str(path).removesuffix(".shp") + ".shp")
    if not shp.exists():
        raise GisImportError(f"Shapefile not found: {shp}")

    try:
        reader = shapefile.Reader(str(shp))
    except shapefile.ShapefileException as e:
        raise GisImportError(f"Cannot read shapefile {shp}: {e}") from e

    wkts: list[str] = []
    skipped = 0
    with reader:
        field_names = [f[0] for f in reader.fields[1:]]
        has_busena = "Busena" in field_names
        for shape_rec in reader.iterShapeRecords():
            if has_busena and str(shape_rec.record["Busena"] or "").strip() != "v":
                skipped += 1
                continue
            wkts.extend(_shape_to_wkts(shape_rec.shape, shp))
    return wkts, skipped


def _shape_to_wkts(shape: shapefile.Shape, source: Path) -> list[str]:
    """Convert one pyshp shape to WKT strings (one per part for polylines)."""
    points = shape.points
    if not points:
        return []
    type_name = shape.shapeTypeName
    if type_name.startswith("POINT"):
        return [f"POINT({points[0][0]} {points[0][1]})"]
    if type_name.startswith("POLYLINE"):
        part_bounds = list(shape.parts) + [len(points)]
        wkts: list[str] = []
        for start, end in zip(part_bounds, part_bounds[1:]):
            segment = points[start:end]
            if len(segment) < 2:
                log.warning("Skipping degenerate polyline part (<2 points) in %s", source)
                continue
            coords = ", ".join(f"{p[0]} {p[1]}" for p in segment)
            wkts.append(f"LINESTRING({coords})")
        return wkts
    raise GisImportError(f"Unsupported shape type '{type_name}' in {source}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/gis/test_reader.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/gis_import.py tests/gis/
git commit -m "feat: shapefile reader for GIS import (Busena filter, multipart lines)"
```

---

### Task 3: PostGIS temp-table load and address matching

Temp table `gis_import_geom` (SRID 3346) + GiST index; one `ST_DWithin` query
returns matching building `rc_code`s. Integration tests use the rolled-back
`db_session` fixture (requires running PostGIS, like `tests/etl/*_integration.py`).

**Files:**
- Modify: `app/gis_import.py` (append functions)
- Create: `tests/gis/test_db_integration.py`

- [ ] **Step 1: Write the failing tests**

`tests/gis/test_db_integration.py`:

```python
"""Integration tests for GIS import DB steps — require PostgreSQL+PostGIS."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.gis_import import load_temp_geometries, match_addresses
from app.models.address import Address, County, Locality, Municipality

# Synthetic RC codes far outside real ranges to avoid clashing with imported data.
COUNTY = 990001
MUNI = 990002
LOCALITY = 990003
ADDR_NEAR = 99000000001
ADDR_FAR = 99000000002
ADDR_FLAT = 99000000003


async def _seed_addresses(session: AsyncSession) -> None:
    """Three addresses: building ~30 m from the test line, building ~2 km away,
    and a flat at the near location (must be ignored by matching)."""
    session.add(County(rc_code=COUNTY, name="Test apskr."))
    session.add(Municipality(rc_code=MUNI, county_code=COUNTY, name="Test sav.", type="r. sav."))
    session.add(
        Locality(rc_code=LOCALITY, muni_code=MUNI, name="Testkaimis", type="k.")
    )
    session.add(
        Address(rc_code=ADDR_NEAR, locality_code=LOCALITY, house_no="1", address_type="building")
    )
    session.add(
        Address(rc_code=ADDR_FAR, locality_code=LOCALITY, house_no="2", address_type="building")
    )
    session.add(
        Address(rc_code=ADDR_FLAT, locality_code=LOCALITY, house_no="1", flat_no="3", address_type="flat")
    )
    await session.flush()
    # Set points via PostGIS so LKS94 coords are what we reason about.
    await session.execute(
        text(
            "UPDATE addresses SET point = ST_Transform(ST_SetSRID(ST_MakePoint(:x, :y), 3346), 4326) "
            "WHERE rc_code = :code"
        ),
        [
            {"code": ADDR_NEAR, "x": 580050, "y": 6050030},
            {"code": ADDR_FAR, "x": 580050, "y": 6052000},
            {"code": ADDR_FLAT, "x": 580050, "y": 6050030},
        ],
    )


TEST_LINE = "LINESTRING(580000 6050000, 580100 6050000)"


async def test_match_finds_only_nearby_buildings(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    await load_temp_geometries(db_session, [TEST_LINE])

    matched = await match_addresses(db_session, distance=50)

    assert ADDR_NEAR in matched      # ~30 m from the line
    assert ADDR_FAR not in matched   # ~2 km away
    assert ADDR_FLAT not in matched  # flats excluded


async def test_match_respects_distance(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    await load_temp_geometries(db_session, [TEST_LINE])

    assert ADDR_NEAR not in await match_addresses(db_session, distance=10)


async def test_match_works_with_points(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    await load_temp_geometries(db_session, ["POINT(580050 6050000)"])

    matched = await match_addresses(db_session, distance=50)
    assert ADDR_NEAR in matched
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gis/test_db_integration.py -v`
Expected: ERROR with `ImportError: cannot import name 'load_temp_geometries'`
(If it errors with a DB connection failure instead: `docker compose up -d db` first.)

- [ ] **Step 3: Implement the DB steps**

Append to `app/gis_import.py` (add imports at top: `from sqlalchemy import select, text` and `from sqlalchemy.ext.asyncio import AsyncSession`):

```python
async def load_temp_geometries(session: AsyncSession, wkts: list[str]) -> None:
    """Load WKT geometries into a session-local temp table with a GiST index."""
    await session.execute(
        text("CREATE TEMP TABLE gis_import_geom (geom geometry(Geometry, 3346))")
    )
    insert_stmt = text("INSERT INTO gis_import_geom (geom) VALUES (ST_GeomFromText(:wkt, 3346))")
    for i in range(0, len(wkts), BATCH_SIZE):
        await session.execute(insert_stmt, [{"wkt": w} for w in wkts[i : i + BATCH_SIZE]])
    await session.execute(
        text("CREATE INDEX ix_gis_import_geom ON gis_import_geom USING gist (geom)")
    )
    await session.execute(text("ANALYZE gis_import_geom"))
    log.info("Loaded %d geometries into temp table", len(wkts))


async def match_addresses(session: AsyncSession, distance: float) -> list[int]:
    """Return rc_codes of building addresses within `distance` meters of the network."""
    result = await session.execute(
        text(
            """
            SELECT a.rc_code
            FROM addresses a
            WHERE a.address_type = 'building'
              AND a.deleted_at IS NULL
              AND a.point IS NOT NULL
              AND EXISTS (
                SELECT 1 FROM gis_import_geom g
                WHERE ST_DWithin(ST_Transform(a.point, 3346), g.geom, :distance)
              )
            """
        ),
        {"distance": distance},
    )
    return [row[0] for row in result]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/gis/ -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add app/gis_import.py tests/gis/test_db_integration.py
git commit -m "feat: PostGIS temp-table load and ST_DWithin address matching"
```

---

### Task 4: Offering insertion with conflict skip + validation resolvers

Batched `INSERT ... ON CONFLICT (address_code, technology_id) DO NOTHING`;
defaults from the technology's theoretical maxima; resolvers raise
`GisImportError` for unknown technology/user.

**Files:**
- Modify: `app/gis_import.py` (append functions)
- Modify: `tests/gis/test_db_integration.py` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/gis/test_db_integration.py`:

```python
import pytest

from app.gis_import import (
    GisImportError,
    ImportOptions,
    insert_offerings,
    resolve_technology,
    resolve_user,
)
from app.models.admin import BulkOperations, User
from app.models.technology import Technology, TechnologyType


def _options(**overrides) -> ImportOptions:
    defaults = dict(
        shapefiles=[],
        technology="test_gpon",
        distance=50.0,
        username="gis_tester",
        status="available",
    )
    defaults.update(overrides)
    return ImportOptions(**defaults)


async def _seed_tech_and_user(session: AsyncSession) -> tuple[Technology, User]:
    tech_type = TechnologyType(code="TEST_FIBER", display_name="Test", public_name="Test")
    session.add(tech_type)
    await session.flush()
    tech = Technology(
        type_id=tech_type.id,
        variant_code="test_gpon",
        display_name="Test GPON",
        theoretical_max_dl_mbps=2500,
        theoretical_max_ul_mbps=1250,
    )
    user = User(username="gis_tester", email="gis@test.local", role="admin", active=True)
    session.add_all([tech, user])
    await session.flush()
    return tech, user


async def test_insert_offerings_uses_technology_speeds(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    bulk_op = BulkOperations(
        user_id=user.id, operation_type="gis_import", filter_criteria={}, affected_count=0
    )
    db_session.add(bulk_op)
    await db_session.flush()

    created = await insert_offerings(
        db_session, [ADDR_NEAR, ADDR_FAR], tech, user.id, _options(), bulk_op.id
    )

    assert created == 2
    row = (
        await db_session.execute(
            text(
                "SELECT status, max_download_mbps, max_upload_mbps, bulk_operation_id "
                "FROM address_offerings WHERE address_code = :c"
            ),
            {"c": ADDR_NEAR},
        )
    ).one()
    assert row.status == "available"
    assert row.max_download_mbps == 2500
    assert row.max_upload_mbps == 1250
    assert row.bulk_operation_id == bulk_op.id


async def test_insert_offerings_skips_existing(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    bulk_op = BulkOperations(
        user_id=user.id, operation_type="gis_import", filter_criteria={}, affected_count=0
    )
    db_session.add(bulk_op)
    await db_session.flush()

    first = await insert_offerings(db_session, [ADDR_NEAR], tech, user.id, _options(), bulk_op.id)
    second = await insert_offerings(
        db_session, [ADDR_NEAR, ADDR_FAR], tech, user.id, _options(), bulk_op.id
    )

    assert first == 1
    assert second == 1  # ADDR_NEAR already has an offering — only ADDR_FAR inserted


async def test_insert_offerings_respects_overrides(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    bulk_op = BulkOperations(
        user_id=user.id, operation_type="gis_import", filter_criteria={}, affected_count=0
    )
    db_session.add(bulk_op)
    await db_session.flush()

    await insert_offerings(
        db_session,
        [ADDR_NEAR],
        tech,
        user.id,
        _options(status="planned", download=1000, upload=500),
        bulk_op.id,
    )

    row = (
        await db_session.execute(
            text(
                "SELECT status, max_download_mbps, max_upload_mbps "
                "FROM address_offerings WHERE address_code = :c"
            ),
            {"c": ADDR_NEAR},
        )
    ).one()
    assert (row.status, row.max_download_mbps, row.max_upload_mbps) == ("planned", 1000, 500)


async def test_resolvers_raise_for_unknown(db_session: AsyncSession) -> None:
    with pytest.raises(GisImportError, match="Technology"):
        await resolve_technology(db_session, "no_such_tech")
    with pytest.raises(GisImportError, match="User"):
        await resolve_user(db_session, "no_such_user")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/gis/test_db_integration.py -v`
Expected: ERROR `ImportError: cannot import name 'insert_offerings'`

- [ ] **Step 3: Implement**

Append to `app/gis_import.py` (add imports at top: `import uuid`,
`from app.models.admin import BulkOperations, User`,
`from app.models.service import AddressOffering`,
`from app.models.technology import Technology`, `from app.time import now`,
`from sqlalchemy.dialects.postgresql import insert as pg_insert`):

```python
async def resolve_technology(session: AsyncSession, variant_code: str) -> Technology:
    result = await session.execute(
        select(Technology).where(
            Technology.variant_code == variant_code, Technology.deleted_at.is_(None)
        )
    )
    tech = result.scalar_one_or_none()
    if tech is None:
        raise GisImportError(
            f"Technology '{variant_code}' not found (use variant_code, e.g. gpon)"
        )
    return tech


async def resolve_user(session: AsyncSession, username: str) -> User:
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise GisImportError(f"User '{username}' not found")
    return user


async def insert_offerings(
    session: AsyncSession,
    rc_codes: list[int],
    tech: Technology,
    user_id: uuid.UUID,
    options: ImportOptions,
    bulk_operation_id: uuid.UUID,
) -> int:
    """Insert offerings batched; existing (address, technology) pairs are skipped.

    Returns the number of rows actually inserted.
    """
    current = now()
    download = options.download if options.download is not None else (tech.theoretical_max_dl_mbps or 0)
    upload = options.upload if options.upload is not None else (tech.theoretical_max_ul_mbps or 0)
    created = 0
    for i in range(0, len(rc_codes), BATCH_SIZE):
        rows = [
            {
                "id": uuid.uuid4(),
                "address_code": code,
                "technology_id": tech.id,
                "status": options.status,
                "max_download_mbps": download,
                "max_upload_mbps": upload,
                "status_since": current.date(),
                "created_by": user_id,
                "bulk_operation_id": bulk_operation_id,
                "created_at": current,
                "updated_at": current,
            }
            for code in rc_codes[i : i + BATCH_SIZE]
        ]
        stmt = pg_insert(AddressOffering).values(rows).on_conflict_do_nothing(
            index_elements=["address_code", "technology_id"]
        )
        result = await session.execute(stmt)
        created += result.rowcount
    return created
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/gis/ -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add app/gis_import.py tests/gis/test_db_integration.py
git commit -m "feat: GIS import offering insertion with conflict skip and resolvers"
```

---

### Task 5: `run_import` orchestration (incl. dry-run)

Glues the pieces: read files → validate → temp table → match → audit row →
insert → commit or rollback. Takes a `progress` callback so the CLI layer owns
rich. DB steps are extracted into `_run_db_steps(session, ...)` so the
integration test can drive them on the rolled-back `db_session`.

**Files:**
- Modify: `app/gis_import.py` (append functions)
- Modify: `tests/gis/test_db_integration.py` (append test)

- [ ] **Step 1: Write the failing test**

Append to `tests/gis/test_db_integration.py`:

```python
from app.gis_import import _run_db_steps, ImportReport


async def test_run_db_steps_end_to_end(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    await _seed_tech_and_user(db_session)

    report = ImportReport(geometries_loaded=1)
    report = await _run_db_steps(
        db_session, _options(), [TEST_LINE], report, progress=lambda stage: None
    )

    assert report.addresses_matched == 1
    assert report.offerings_created == 1
    assert report.existing_skipped == 0
    bulk_op = (
        await db_session.execute(
            text("SELECT operation_type, affected_count FROM bulk_operations")
        )
    ).one()
    assert bulk_op.operation_type == "gis_import"
    assert bulk_op.affected_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gis/test_db_integration.py::test_run_db_steps_end_to_end -v`
Expected: ERROR `ImportError: cannot import name '_run_db_steps'`

- [ ] **Step 3: Implement**

Append to `app/gis_import.py` (add imports at top:
`from collections.abc import Callable`, `from app.database import AsyncSessionLocal`):

```python
async def _run_db_steps(
    session: AsyncSession,
    options: ImportOptions,
    wkts: list[str],
    report: ImportReport,
    progress: Callable[[str], None],
) -> ImportReport:
    """All DB work for one import, on a caller-managed session (no commit here)."""
    tech = await resolve_technology(session, options.technology)
    user = await resolve_user(session, options.username)

    progress("Loading geometries into PostGIS")
    await load_temp_geometries(session, wkts)

    progress("Matching addresses")
    matched = await match_addresses(session, options.distance)
    report.addresses_matched = len(matched)
    log.info("Matched %d building addresses within %.0f m", len(matched), options.distance)

    progress("Creating offerings")
    bulk_op = BulkOperations(
        user_id=user.id,
        operation_type="gis_import",
        filter_criteria={
            "shapefiles": [str(p) for p in options.shapefiles],
            "technology": options.technology,
            "distance_m": options.distance,
            "status": options.status,
            "dry_run": options.dry_run,
        },
        affected_count=0,
    )
    session.add(bulk_op)
    await session.flush()

    report.offerings_created = await insert_offerings(
        session, matched, tech, user.id, options, bulk_op.id
    )
    report.existing_skipped = report.addresses_matched - report.offerings_created
    bulk_op.affected_count = report.offerings_created
    return report


async def run_import(
    options: ImportOptions, progress: Callable[[str], None] = lambda stage: None
) -> ImportReport:
    """Run the full import. Dry-run executes everything and rolls back."""
    if options.status not in VALID_STATUSES:
        raise GisImportError(
            f"Invalid status '{options.status}'. Valid: {', '.join(sorted(VALID_STATUSES))}"
        )

    progress("Reading shapefiles")
    report = ImportReport()
    wkts: list[str] = []
    for path in options.shapefiles:
        file_wkts, skipped = read_geometries(path)
        wkts.extend(file_wkts)
        report.inactive_skipped += skipped
        log.info("Read %d geometries from %s (%d inactive skipped)", len(file_wkts), path, skipped)
    report.geometries_loaded = len(wkts)
    if not wkts:
        raise GisImportError("No active geometries found in the given shapefiles")

    async with AsyncSessionLocal() as session:
        report = await _run_db_steps(session, options, wkts, report, progress)
        if options.dry_run:
            await session.rollback()
            log.info("Dry run — transaction rolled back")
        else:
            await session.commit()
    return report
```

- [ ] **Step 4: Run all gis tests**

Run: `uv run pytest tests/gis/ -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add app/gis_import.py tests/gis/test_db_integration.py
git commit -m "feat: run_import orchestration with dry-run and bulk-operation audit"
```

---

### Task 6: CLI command `import-gis` with rich progress + summary table

**Files:**
- Modify: `app/cli.py`

- [ ] **Step 1: Add the command**

In `app/cli.py`, extend imports at the top:

```python
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from app.gis_import import GisImportError, ImportOptions, ImportReport, run_import
from app.logging_config import configure_logging
```

(`configure_logging()` in `app/logging_config.py` takes no arguments.)

Add after the existing commands (same error pattern as `create-admin`):

```python
@app.command("import-gis")
def import_gis(
    shapefile: list[Path] = typer.Option(
        ..., "--shapefile", help="Path to a .shp file (repeatable, lines and/or points)"
    ),
    technology: str = typer.Option(..., help="Technology variant_code, e.g. gpon"),
    distance: float = typer.Option(..., help="Max distance in meters from the network"),
    username: str = typer.Option(..., help="Existing user recorded as created_by"),
    status: str = typer.Option("available", help="Offering status"),
    download: int | None = typer.Option(None, help="Override max_download_mbps"),
    upload: int | None = typer.Option(None, help="Override max_upload_mbps"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run everything, roll back at the end"),
):
    """Import network coverage from GIS shapefiles as address offerings."""
    configure_logging()
    options = ImportOptions(
        shapefiles=shapefile,
        technology=technology,
        distance=distance,
        username=username,
        status=status,
        download=download,
        upload=upload,
        dry_run=dry_run,
    )
    try:
        asyncio.run(_import_gis(options))
    except GisImportError as e:
        rprint(f"[red]ERROR: {e}[/red]", file=sys.stderr)
        raise typer.Exit(code=1) from None
    except Exception as e:
        rprint(f"[red]ERROR: {type(e).__name__}: {e}[/red]", file=sys.stderr)
        raise typer.Exit(code=1) from None


async def _import_gis(options: ImportOptions) -> None:
    console = Console()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Starting…", total=None)
        report = await run_import(
            options, progress=lambda stage: progress.update(task, description=stage)
        )
    _print_report(console, report, options)


def _print_report(console: Console, report: ImportReport, options: ImportOptions) -> None:
    title = "GIS import — dry run (nothing saved)" if options.dry_run else "GIS import"
    table = Table(title=title)
    table.add_column("Metric")
    table.add_column("Count", justify="right")
    table.add_row("Geometries loaded", str(report.geometries_loaded))
    table.add_row("Inactive records skipped", str(report.inactive_skipped))
    table.add_row("Addresses matched", str(report.addresses_matched))
    table.add_row("Offerings created", f"[green]{report.offerings_created}[/green]")
    table.add_row("Existing skipped", str(report.existing_skipped))
    console.print(table)
```

- [ ] **Step 2: Smoke-test help and validation errors**

```bash
uv run python -m app.cli import-gis --help
uv run python -m app.cli import-gis --shapefile /nonexistent --technology gpon --distance 50 --username robert
```

Expected: help shows all options; second command prints red
`ERROR: Shapefile not found: /nonexistent.shp` and exits 1.

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest`
Expected: everything passes (no regressions in api/etl/unit).

- [ ] **Step 4: Commit**

```bash
git add app/cli.py
git commit -m "feat: import-gis CLI command with rich progress and summary"
```

---

### Task 7: Real-data dry run + docs

**Files:**
- Modify: `CLAUDE.md` (Commands section)

- [ ] **Step 1: Dry run against the real shapefiles**

```bash
uv run python -m app.cli import-gis \
  --shapefile /home/robertas/Downloads/etanetas/Rys_tinkl \
  --shapefile /home/robertas/Downloads/etanetas/Rys_t \
  --technology gpon --distance 100 --username robert --dry-run
```

Expected: spinner runs through stages, summary table shows
~3500+ geometries loaded, a plausible (non-zero, non-millions) matched count,
`dry run (nothing saved)` in the title. Sanity-check: matched count should be
in the hundreds-to-low-thousands range for the Šalčininkai area. If it is 0 or
looks like all of Lithuania, stop and investigate before a real run.

- [ ] **Step 2: Verify nothing was written**

```bash
uv run python - <<'EOF'
import asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as s:
        n = (await s.execute(text("SELECT count(*) FROM bulk_operations WHERE operation_type = 'gis_import'"))).scalar()
        print("gis_import bulk ops:", n)

asyncio.run(main())
EOF
```

Expected: `gis_import bulk ops: 0`

- [ ] **Step 3: Document the command in CLAUDE.md**

In the `## Commands` section of `CLAUDE.md`, after the `create-admin` line, add:

```bash
# Import GIS network shapefiles as address offerings (dry-run first!)
uv run python -m app.cli import-gis --shapefile X.shp [--shapefile Y.shp] \
  --technology gpon --distance 100 --username U [--dry-run]
```

- [ ] **Step 4: Final full test run + lint**

```bash
uv run pytest
uv run ruff check .
```

Expected: all tests pass, no lint errors.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document import-gis CLI command"
```

The **real import** (without `--dry-run`) is run manually by the user after
reviewing the dry-run numbers — not part of this plan.
