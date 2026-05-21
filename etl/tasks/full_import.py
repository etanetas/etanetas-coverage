"""Full ETL import — loads all RC data into the database from scratch (or resumes).

Each step is independently checkpointed in ``etl_state.full_import_step``. Re-running
the task after a failure resumes from the last completed step; no data is lost.

Steps (in order):
    1. counties              ← adr_apskritys.csv
    2. municipalities        ← adr_savivaldybes.csv
    3. localities            ← adr_gyvenamosios_vietoves.csv
    4. streets               ← adr_gatves.csv
    5. points                ← adr_gra_adresai_LT.zip (GeoJSON → point_lookup)
    6. addresses             ← adr_stat_lr.csv (buildings/plots, uses point_lookup)
    7. [SKIPPED] premises    ← ISP operates at building level; per-apartment records not needed
    8. boundaries            ← adr_gra_gyvenamosios_vietoves.json (UPDATE localities.boundary)
    9. axes                  ← adr_gra_gatves.json (UPDATE streets.axis)
   10. cid                   ← Spinta head _cid → etl_state (sync cursor)
"""

import asyncio
import logging
import socket
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.logging_config import configure_logging
from etl.notifications import send_alert
from app.models.address import Address, County, Locality, Municipality, Street
from etl.config import settings
from etl.downloaders.rc_address_points_client import RCAddressPointsClient
from etl.downloaders.rc_csv_client import RCCsvClient
from etl.downloaders.rc_geojson_client import RCGeoJsonClient
from etl.downloaders.spinta_client import SpintaClient
from etl.loaders.geometry_load import update_geometries
from etl.loaders.upsert_load import upsert_all
from etl.state_db import (
    clear_import_progress,
    get_completed_step,
    save_cid,
    save_completed_step,
    steps_to_run,
)
from etl.transformers.address_mapper import (
    map_address_csv,
    map_county_csv,
    map_locality_boundary,
    map_locality_csv,
    map_municipality_csv,
    map_premises_csv,
    map_street_axis,
    map_street_csv,
)

log = logging.getLogger(__name__)


# ============================================================================
# Helpers
# ============================================================================


async def _async_iter_mapped(
    rows: AsyncIterator[dict[str, str]] | list[dict[str, str]],
    mapper,
) -> AsyncIterator[dict[str, Any]]:
    """Apply :mapper: to each row; yield only non-None results."""
    for row in rows:
        mapped = mapper(row)
        if mapped is not None:
            yield mapped


# ============================================================================
# Step implementations (one async fn per step)
# ============================================================================


async def _import_counties(session: AsyncSession, rc: RCCsvClient) -> None:
    log.info("Counties...")
    path = await rc.download("counties")

    async def _rows():
        for row in rc.iter_rows(path):
            mapped = map_county_csv(row)
            if mapped is not None:
                yield mapped

    n = await upsert_all(session, County, _rows())
    log.info("  %d rows", n)


async def _import_municipalities(session: AsyncSession, rc: RCCsvClient) -> None:
    log.info("Municipalities...")
    path = await rc.download("municipalities")

    async def _rows():
        for row in rc.iter_rows(path):
            mapped = map_municipality_csv(row)
            if mapped is not None:
                yield mapped

    n = await upsert_all(session, Municipality, _rows())
    log.info("  %d rows", n)


async def _import_localities(session: AsyncSession, rc: RCCsvClient) -> None:
    log.info("Localities...")
    path = await rc.download("localities")

    async def _rows():
        for row in rc.iter_rows(path):
            mapped = map_locality_csv(row)
            if mapped is not None:
                yield mapped

    n = await upsert_all(session, Locality, _rows())
    log.info("  %d rows", n)


async def _import_streets(session: AsyncSession, rc: RCCsvClient) -> None:
    log.info("Streets...")
    path = await rc.download("streets")

    async def _rows():
        for row in rc.iter_rows(path):
            mapped = map_street_csv(row)
            if mapped is not None:
                yield mapped

    n = await upsert_all(session, Street, _rows())
    log.info("  %d rows", n)


async def _build_point_lookup(rc_zip: RCAddressPointsClient) -> dict[int, str]:
    """Stream RC address-points GeoJSON; build ``{aob_kodas → EWKT POINT}`` map."""
    log.info("Downloading RC address points GeoJSON...")
    zip_path = await rc_zip.download()
    log.info("Building point lookup...")
    point_lookup: dict[int, str] = {}
    log_every = settings.point_lookup_log_interval

    for feat in rc_zip.iter_features(zip_path):
        try:
            props = feat["properties"]
            aob = props.get("AOB_KODAS")
            e, n = props.get("E_KOORD"), props.get("N_KOORD")
            if aob is None or e is None or n is None:
                continue
            point_lookup[int(aob)] = f"SRID=4326;POINT({e} {n})"
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("Skipping malformed point feature: %s", exc)
            continue
        if len(point_lookup) % log_every == 0:
            log.info("  points: %d", len(point_lookup))

    log.info("  point lookup done: %d entries", len(point_lookup))
    return point_lookup


async def _import_addresses(
    session: AsyncSession, rc: RCCsvClient, point_lookup: dict[int, str]
) -> None:
    """Import stat addresses (buildings/plots)."""
    log.info("Addresses (stat)...")
    stat_path = await rc.download("addresses")

    async def _rows():
        for row in rc.iter_rows(stat_path):
            if not row.get("NR", "").strip():
                continue
            mapped = map_address_csv(row, point_lookup)
            if mapped is None:
                continue
            yield mapped

    n = await upsert_all(session, Address, _rows())
    log.info("  %d rows", n)


def _rebuild_stat_lookup(
    rc: RCCsvClient, stat_path, point_lookup: dict[int, str]
) -> dict[int, dict[str, Any]]:
    """Rebuild stat_lookup from cached CSV without inserting (used when addresses step is skipped)."""
    log.info("Rebuilding stat_lookup from cache for premises step...")
    stat_lookup: dict[int, dict[str, Any]] = {}
    for row in rc.iter_rows(stat_path):
        if not row.get("NR", "").strip():
            continue
        mapped = map_address_csv(row, point_lookup)
        if mapped is None:
            continue
        stat_lookup[mapped["rc_code"]] = {
            "locality_code": mapped["locality_code"],
            "street_code": mapped["street_code"],
            "postal_code": mapped["postal_code"],
        }
    return stat_lookup


async def _import_premises(
    session: AsyncSession,
    rc: RCCsvClient,
    stat_lookup: dict[int, dict[str, Any]],
    point_lookup: dict[int, str],
) -> None:
    log.info("Addresses (premises)...")
    pat_path = await rc.download("premises")

    async def _rows():
        skipped = 0
        for row in rc.iter_rows(pat_path):
            if not row.get("PATALPOS_NR", "").strip():
                continue
            mapped = map_premises_csv(row, stat_lookup, point_lookup)
            if mapped is None:
                skipped += 1
                continue
            yield mapped
        if skipped:
            log.warning("skipped %d premises without parent building", skipped)

    n = await upsert_all(session, Address, _rows())
    log.info("  %d rows", n)


async def _import_boundaries(session: AsyncSession, rc_geo: RCGeoJsonClient) -> None:
    log.info("Locality boundaries...")
    path = await rc_geo.download("localities_boundary")
    n = await update_geometries(
        session,
        "localities",
        (map_locality_boundary(feat) for feat in rc_geo.iter_features(path)),
    )
    log.info("  %d rows updated", n)


async def _import_axes(session: AsyncSession, rc_geo: RCGeoJsonClient) -> None:
    log.info("Street axes...")
    path = await rc_geo.download("streets_axis")
    n = await update_geometries(
        session,
        "streets",
        (map_street_axis(feat) for feat in rc_geo.iter_features(path)),
    )
    log.info("  %d rows updated", n)


async def _save_head_cid(session: AsyncSession) -> None:
    """Fetch the latest Spinta ``_cid`` and save it as the nightly sync cursor."""
    log.info("Fetching head _cid from Spinta...")
    spinta = SpintaClient()
    head_cid = 0
    try:
        async for record in spinta.fetch_changes("adresai/Adresas", since_cid=-1, limit=1):
            head_cid = record["_cid"]
    except Exception as exc:
        log.error("Failed to fetch head _cid from Spinta: %s", exc)
        raise
    log.info("  head _cid = %d", head_cid)
    await save_cid(session, head_cid)
    log.info("State saved to DB (key=adresai_cid, value=%d)", head_cid)


# ============================================================================
# Entry point
# ============================================================================


async def run(force: bool = False) -> None:
    """Run the full import. Resumes from last checkpoint unless :force: is True.

    Idempotent: re-running after success is a no-op (all steps already done).
    """
    try:
        await _run(force=force)
    except Exception:
        log.exception("Full import failed")
        await send_alert(
            f"❌ Full import FAILED on {socket.gethostname()}\n"
            f"Check logs. Re-run: uv run python -m etl.tasks.full_import"
        )
        raise


async def _run(force: bool = False) -> None:
    rc = RCCsvClient()
    rc_zip = RCAddressPointsClient(settings.rc_geojson_url)
    rc_geo = RCGeoJsonClient()

    async with AsyncSessionLocal() as session:
        if force:
            await clear_import_progress(session)
            log.info("Forced restart — cleared import checkpoint.")

        last_completed = await get_completed_step(session)
        todo = steps_to_run(last_completed)

        if last_completed:
            log.info("Resuming from checkpoint: last completed step = '%s'", last_completed)
        else:
            log.info("Starting full import from scratch.")

        # --- Steps 1-4: admin hierarchy (counties, municipalities, localities, streets) ---
        for step_name, fn in [
            ("counties", _import_counties),
            ("municipalities", _import_municipalities),
            ("localities", _import_localities),
            ("streets", _import_streets),
        ]:
            if step_name in todo:
                await fn(session, rc)
                await save_completed_step(session, step_name)
            else:
                log.info("%s... skipped (already done)", step_name.capitalize())

        # --- Step 5: point lookup (built in memory; needed by addresses) ---
        # If "points" step is skipped but addresses still need to run,
        # we MUST rebuild the lookup from cache (it's not persisted).
        point_lookup: dict[int, str] = {}
        needs_point_lookup = bool({"points", "addresses"} & todo)
        if needs_point_lookup:
            point_lookup = await _build_point_lookup(rc_zip)
            if "points" in todo:
                await save_completed_step(session, "points")
        else:
            log.info("Points... skipped (already done)")

        # --- Step 6: stat addresses (buildings/plots only) ---
        if "addresses" in todo:
            await _import_addresses(session, rc, point_lookup)
            await save_completed_step(session, "addresses")
        else:
            log.info("Addresses (stat)... skipped (already done)")

        # --- Step 7: premises --- SKIPPED (ISP operates at building level) ---

    # New session for geometry updates (separates concerns + lets the addresses txn close)
    async with AsyncSessionLocal() as session:
        if "boundaries" in todo:
            await _import_boundaries(session, rc_geo)
            await save_completed_step(session, "boundaries")
        else:
            log.info("Locality boundaries... skipped (already done)")

        if "axes" in todo:
            await _import_axes(session, rc_geo)
            await save_completed_step(session, "axes")
        else:
            log.info("Street axes... skipped (already done)")

    # --- Step 10: save head _cid as nightly_sync cursor ---
    if "cid" in todo:
        async with AsyncSessionLocal() as session:
            await _save_head_cid(session)
            await save_completed_step(session, "cid")

    log.info("Full import done.")


if __name__ == "__main__":
    configure_logging()
    asyncio.run(run())
