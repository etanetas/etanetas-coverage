# GIS import — coverage zone creation (`--zone-name`)

Date: 2026-06-10
Status: approved design
Extends: `2026-06-10-gis-import-design.md` (implemented, merged)

## Goal

Optionally create/refresh a `ServiceZone` polygon during `import-gis` so the
map (`/map/zones/geojson`) visually shows the coverage area of the imported
network, colored by technology.

## CLI

```bash
uv run python -m app.cli import-gis ... --zone-name "GPON Šalčininkai"
```

- `--zone-name` optional `str`; omitted → current behavior (address offerings
  only), no zone work at all.
- Dry-run covers the zone too (same transaction, rolled back).

## Behavior

In `_run_db_steps`, after `insert_offerings` (temp table `gis_import_geom`
still alive in the same transaction):

1. **Polygon** — one PostGIS query over the temp table:

   ```sql
   SELECT ST_Multi(ST_Transform(
            ST_SimplifyPreserveTopology(
              ST_Union(ST_Buffer(geom, :distance)), 1.0),
            4326))
   FROM gis_import_geom
   ```

   Buffer and simplify run in EPSG:3346 (meters); 1 m simplification keeps
   the MULTIPOLYGON compact. Result is WGS84 MULTIPOLYGON.

2. **ServiceZone upsert by name** (`name = zone_name`, `deleted_at IS NULL`):
   - exists → update `polygon` (and `updated_at` via ORM onupdate)
   - missing → create with `created_by = user.id`, `priority` default,
     `description = "Imported from GIS shapefiles (distance {X} m)"`
   - If multiple active zones share the name → `GisImportError` (ambiguous;
     user must clean up manually).

3. **ZoneOffering upsert** on `(zone_id, technology_id)`:
   - status / max_download / max_upload / status_since identical to the
     address offerings of this run
   - conflict → `DO UPDATE` of status, speeds, status_since, updated_at
     (zone reflects the latest import, unlike address offerings which are
     never overwritten).

## Reporting

- `ImportReport` gains `zone_name: str | None` and
  `zone_action: str | None` (`"created"` / `"updated"`).
- CLI summary table gains a row `Zone` → `"<name>" (created|updated)`,
  only when `--zone-name` was given.
- `BulkOperations.filter_criteria` gains `"zone_name"` key (None when absent).

## Out of scope

- No changes to map endpoints or frontend — the zone appears via the
  existing `/map/zones/geojson` (simplification on read already in place).
- No zone deletion/cleanup; reruns update in place.

## Testing (integration, rolled-back `db_session`)

1. Zone created: valid MULTIPOLYGON SRID 4326; `ST_Contains` true for the
   near address point, false for the far one.
2. Rerun with same zone name: still exactly one active zone with that name,
   polygon updated.
3. ZoneOffering upserted: second run with different status updates the row
   (still one row per zone+technology).
4. No `--zone-name` → no zone, no zone offering rows.
