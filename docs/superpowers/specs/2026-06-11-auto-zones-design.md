# Auto-zones — ServiceZone polygons derived from address offerings

Date: 2026-06-11
Status: approved design
Supersedes: zone part of `2026-06-10-gis-import-zones-design.md` (`--zone-name` is removed)

## Goal

Zones become a pure visualization derived from address offerings: addresses
with an `available` offering for a technology form that technology's auto-zone
on the map. Any change to address offerings (GIS import, bulk operation,
single admin edit) refreshes the zone automatically. Address offerings are the
single source of truth.

## Data model

Alembic migration: `service_zones.source TEXT NOT NULL DEFAULT 'manual'`
with CHECK `source IN ('manual', 'auto')`. Existing rows stay `manual`
(including the GIS-imported "GPON tinklas" zone — delete it via admin API
once auto-zones land; it becomes redundant).

Auto-zone identity: exactly one active zone per technology with
`source='auto'`, found by joining `zone_offerings` on `technology_id`.
Name: `"Auto: {technology.display_name}"`.

## New module `app/auto_zones.py`

```python
async def rebuild_auto_zones(
    session: AsyncSession,
    technology_id: uuid.UUID | None = None,   # None → all technologies with any available offering
    radius_m: float = 150.0,
) -> list[str]:                                # names of zones rebuilt/hidden, for logging/CLI
```

Per technology:

1. `pg_advisory_xact_lock(hashtext('auto_zone:' || tech_id))` — concurrent
   rebuilds for the same technology serialize; no duplicate zones.
2. Polygon query (same pipeline as the former GIS zone):

   ```sql
   SELECT ST_Multi(ST_Transform(
            ST_SimplifyPreserveTopology(
              ST_Union(ST_Buffer(ST_Transform(a.point, 3346), :radius)), 1.0),
            4326)),
          MAX(ao.max_download_mbps), MAX(ao.max_upload_mbps)
   FROM addresses a
   JOIN address_offerings ao ON ao.address_code = a.rc_code
   WHERE ao.technology_id = :tech
     AND ao.status = 'available'
     AND a.deleted_at IS NULL
     AND a.point IS NOT NULL
   ```

3. Upsert: find active `source='auto'` zone for the technology.
   - polygon NULL (no available offerings) → if zone exists, set
     `deleted_at = now()` (hidden from map); done.
   - zone exists → update `polygon` (and un-delete is not needed: a hidden
     zone is matched too — lookup ignores `deleted_at` for auto zones and
     clears it on rebuild when offerings reappear).
   - missing → create (`source='auto'`, `name="Auto: {display_name}"`,
     `description="Strefa generowana automatycznie z ofert adresowych"`,
     `created_by=None`).
4. `ZoneOffering` upsert on `(zone_id, technology_id)`:
   `status='available'`, speeds = the MAX aggregates from the query,
   `status_since=today` on insert, DO UPDATE speeds/updated_at on conflict.

`created_by` is nullable on `service_zones` — auto zones are system-owned.

## Triggers

| Where | How |
|---|---|
| `import-gis` CLI | end of `_run_db_steps`, for the imported technology (dry-run rolls back zone too) |
| `POST /bulk/execute`, `POST /bulk/{id}/rollback` | FastAPI `BackgroundTasks` after response, technologies from the operation |
| `POST /{rc_code}/offerings`, `PATCH /offerings/{id}`, `DELETE` offering | `BackgroundTasks`, the offering's technology |
| CLI `rebuild-zones [--technology X] [--radius N]` | manual full/per-tech rebuild |

Background rebuilds open their own `AsyncSessionLocal` session, log errors
(`log.exception`), never fail the originating request.

`radius_m` default 150 lives as module constant `AUTO_ZONE_RADIUS_M`;
CLI `--radius` overrides per run. API-triggered rebuilds always use default.

## Removals

- `import-gis --zone-name` CLI option, `upsert_zone()` in `app/gis_import.py`,
  `ImportOptions.zone_name`, `ImportReport.zone_name/zone_action`, their
  report row and tests. The GIS network-buffer zone is replaced by the
  address-derived auto-zone (`import-gis` report instead shows the rebuilt
  auto-zone name).

## Out of scope

- No map/frontend changes — auto zones render via existing
  `/map/zones/geojson` (it filters `deleted_at IS NULL`, so hidden auto zones
  disappear correctly).
- Manual zones (`source='manual'`) are never touched by rebuilds; admin zone
  CRUD endpoints keep working on them. Editing an auto zone via admin API is
  not blocked, but the next rebuild overwrites the polygon — documented in the
  endpoint docstring (one sentence), no enforcement.

## Testing (integration, rolled-back `db_session`)

1. Rebuild creates auto zone containing the `available` address, excluding a
   `planned`-only address; MULTIPOLYGON 4326; ZoneOffering speeds = MAX.
2. Offering change (available → unavailable) + rebuild → zone polygon shrinks
   (or zone hidden when last offering gone: `deleted_at` set).
3. Offerings reappear → rebuild clears `deleted_at`.
4. Manual zone with same technology untouched by rebuild.
5. `technology_id=None` rebuilds all technologies with offerings.
6. `import-gis` end-to-end (`_run_db_steps`) produces the auto zone; report
   fields for the removed `--zone-name` are gone.
