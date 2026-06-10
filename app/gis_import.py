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
