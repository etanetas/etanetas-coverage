"""Import network coverage from GIS shapefiles into address_offerings.

Reads ESRI shapefiles (LKS94 / EPSG:3346) with network lines and points,
matches building addresses within a distance using PostGIS ST_DWithin, and
creates AddressOffering rows for a given technology.

Design: docs/superpowers/specs/2026-06-10-gis-import-design.md
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import shapefile
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.admin import BulkOperations, User
from app.models.service import AddressOffering
from app.models.technology import Technology
from app.time import now

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
        if not has_busena:
            log.warning("No Busena field in %s — importing all records", shp)
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
        return [f"POINT({points[0][0]:.10g} {points[0][1]:.10g})"]
    if type_name.startswith("POLYLINE"):
        wkts: list[str] = []
        for start, end in pairwise([*shape.parts, len(points)]):
            segment = points[start:end]
            if len(segment) < 2:
                log.warning("Skipping degenerate polyline part (<2 points) in %s", source)
                continue
            coords = ", ".join(f"{p[0]:.10g} {p[1]:.10g}" for p in segment)
            wkts.append(f"LINESTRING({coords})")
        return wkts
    raise GisImportError(f"Unsupported shape type '{type_name}' in {source}")


async def load_temp_geometries(session: AsyncSession, wkts: list[str]) -> None:
    """Load WKT geometries into a session-local temp table with a GiST index."""
    await session.execute(text("DROP TABLE IF EXISTS gis_import_geom"))
    await session.execute(
        text(
            "CREATE TEMP TABLE gis_import_geom"
            " (geom geometry(Geometry, 3346)) ON COMMIT DROP"
        )
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


async def resolve_technology(session: AsyncSession, variant_code: str) -> Technology:
    """Resolve a Technology by variant_code; raise GisImportError if not found or deleted."""
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
    """Resolve a User by username; raise GisImportError if not found."""
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
    if not user.active:
        raise GisImportError(f"User '{options.username}' is inactive")

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
    await session.flush()
    log.info(
        "Created %d offerings (%d already existed)",
        report.offerings_created,
        report.existing_skipped,
    )
    return report


async def run_import(
    options: ImportOptions,
    progress: Callable[[str], None] | None = None,
) -> ImportReport:
    """Run the full import. Dry-run executes everything and rolls back."""
    progress = progress or (lambda stage: None)

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
        try:
            report = await _run_db_steps(session, options, wkts, report, progress)
        except Exception:
            await session.rollback()
            raise
        if options.dry_run:
            await session.rollback()
            log.info("Dry run — transaction rolled back")
        else:
            await session.commit()
    return report
