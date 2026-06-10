# GIS import — `import-gis` CLI command

Date: 2026-06-10
Status: approved design

## Goal

Import network coverage from GIS shapefiles (QGIS/TIIIS export of the Etanetas
network) into the API as `AddressOffering` rows: every building address within
a configurable distance of the network gets an offering for a given technology.

## Input data

Directory `/home/robertas/Downloads/etanetas` (example; paths are CLI args):

| File | Geometry | Records | Meaning |
|---|---|---|---|
| `Rys_tinkl` | PolyLineZ | 1921 | network lines (cable routes, KODAS 3801) |
| `Rys_t` | PointZ | 1702 | network points (wells/cabinets, KODAS 3823) |

- CRS: LKS94 / EPSG:3346 (meters) — matching is done in this SRID.
- Attributes carry **no technology info**; technology is a CLI parameter.
- Only records with `Busena == 'v'` (operational) are used; others counted as
  skipped in the report.

## CLI

```bash
uv run python -m app.cli import-gis \
  --shapefile <path/to/Rys_tinkl> --shapefile <path/to/Rys_t> \
  --technology <variant_code> \
  --distance <meters> \
  --username <existing user> \
  [--status available] [--download N] [--upload N] [--dry-run]
```

- `--shapefile` repeatable; path without extension or with `.shp` accepted.
  Lines and points may be mixed; geometry type read from the file.
- `--technology`: must match `technologies.variant_code` (not deleted).
- `--distance`: max distance in meters from any network geometry.
- `--username`: sets `created_by` (FK NOT NULL on `address_offerings`).
- Defaults: `status=available`, download/upload from the technology's
  `theoretical_max_dl_mbps`/`theoretical_max_ul_mbps`, `status_since=today`.
- `--dry-run`: run everything inside a transaction, print the report, roll back.

## Flow

1. **Validate**: shapefiles readable (pyshp), technology exists, user exists.
   Fail fast with red error message + exit 1 (existing CLI pattern).
2. **Read** geometries with `pyshp`, skipping `Busena != 'v'`. Z coordinates
   dropped; lines → `LINESTRING`, points → `POINT` WKT in SRID 3346.
3. **Load** into a `TEMP TABLE gis_import_geom (geom geometry(Geometry,3346))`
   with a GiST index, batched inserts.
4. **Match** in one query: `addresses` where `address_type='building'`,
   `deleted_at IS NULL`, `point IS NOT NULL` and
   `EXISTS (SELECT 1 FROM gis_import_geom g WHERE ST_DWithin(ST_Transform(addresses.point, 3346), g.geom, :distance))`.
5. **Audit**: insert one `BulkOperations` row (`operation_type='gis_import'`,
   CLI params in `filter_criteria`, `affected_count` = inserted count).
6. **Insert** `AddressOffering` rows batched with
   `INSERT ... ON CONFLICT (address_code, technology_id) DO NOTHING`
   (existing manual data is never overwritten); each row carries
   `bulk_operation_id`.
7. **Report** (rich `Table`): geometries loaded / inactive skipped / addresses
   matched / offerings created / existing skipped.

Premises (`flat`) are intentionally excluded — they inherit the building
point; offerings are building-level.

## Structure

- `app/gis_import.py` — all logic: dataclass for options, shapefile reading,
  SQL steps, report data. Typed, `logging` module, async via
  `AsyncSessionLocal`.
- `app/cli.py` — thin `import-gis` typer command delegating to the module,
  same error-handling pattern as `create-admin`.
- New dependency: `pyshp` (pure Python).

## UX

`rich.progress.Progress` with spinner + per-stage tasks (read files → load
geometries → match → insert), final summary `Table`. Errors red to stderr,
exit code 1.

## Error handling

- Unreadable/missing shapefile, unknown technology, unknown user → validation
  error before touching the DB.
- DB errors propagate (transaction rolls back); no partial state besides the
  temp table, which dies with the session.

## Testing

- Unit: shapefile reading + filtering (`Busena`) against a small generated
  fixture (pyshp can write test files).
- Integration (existing tests/ DB setup): temp-table load + ST_DWithin match +
  conflict-skip behaviour on a few synthetic addresses.
