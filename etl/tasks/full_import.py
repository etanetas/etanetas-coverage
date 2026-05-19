import asyncio
import logging

from app.database import AsyncSessionLocal
from app.logging_config import configure_logging
from app.models.address import Address, County, Locality, Municipality, Street
from etl.config import settings
from etl.downloaders.rc_csv_client import RCCsvClient
from etl.downloaders.rc_geojson_client import RCGeoJsonClient
from etl.downloaders.rc_zip_fallback import RCZipFallback
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


async def run(force: bool = False) -> None:
    rc = RCCsvClient()

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

        # 1. Counties
        if "counties" in todo:
            log.info("Counties...")
            path = await rc.download("counties")

            async def _counties():
                for row in rc.iter_rows(path):
                    yield map_county_csv(row)

            n = await upsert_all(session, County, _counties())
            log.info("  %d rows", n)
            await save_completed_step(session, "counties")
        else:
            log.info("Counties... skipped (already done)")

        # 2. Municipalities
        if "municipalities" in todo:
            log.info("Municipalities...")
            path = await rc.download("municipalities")

            async def _municipalities():
                for row in rc.iter_rows(path):
                    yield map_municipality_csv(row)

            n = await upsert_all(session, Municipality, _municipalities())
            log.info("  %d rows", n)
            await save_completed_step(session, "municipalities")
        else:
            log.info("Municipalities... skipped (already done)")

        # 3. Localities
        if "localities" in todo:
            log.info("Localities...")
            path = await rc.download("localities")

            async def _localities():
                for row in rc.iter_rows(path):
                    yield map_locality_csv(row)

            n = await upsert_all(session, Locality, _localities())
            log.info("  %d rows", n)
            await save_completed_step(session, "localities")
        else:
            log.info("Localities... skipped (already done)")

        # 4. Streets
        if "streets" in todo:
            log.info("Streets...")
            path = await rc.download("streets")

            async def _streets():
                for row in rc.iter_rows(path):
                    yield map_street_csv(row)

            n = await upsert_all(session, Street, _streets())
            log.info("  %d rows", n)
            await save_completed_step(session, "streets")
        else:
            log.info("Streets... skipped (already done)")

        # 5. Point lookup — RC GeoJSON ZIP → aob_kodas int → EWKT WGS84 point
        point_lookup: dict[int, str] = {}
        if "points" in todo:
            log.info("Downloading RC address points GeoJSON...")
            rc_zip = RCZipFallback(settings.rc_geojson_url)
            zip_path = await rc_zip.download()
            log.info("Building point lookup...")
            for feat in rc_zip.iter_features(zip_path):
                props = feat["properties"]
                aob = props.get("AOB_KODAS")
                e, n_coord = props.get("E_KOORD"), props.get("N_KOORD")
                if aob is None or e is None or n_coord is None:
                    continue
                point_lookup[int(aob)] = f"SRID=4326;POINT({e} {n_coord})"
                if len(point_lookup) % 200_000 == 0:
                    log.info("  points: %d", len(point_lookup))
            log.info("  point lookup done: %d entries", len(point_lookup))
            await save_completed_step(session, "points")
        else:
            log.info(
                "Points... skipped (already done) — rebuilding lookup from cache for addresses step"
            )
            rc_zip = RCZipFallback(settings.rc_geojson_url)
            zip_path = await rc_zip.download()
            for feat in rc_zip.iter_features(zip_path):
                props = feat["properties"]
                aob = props.get("AOB_KODAS")
                e, n_coord = props.get("E_KOORD"), props.get("N_KOORD")
                if aob is None or e is None or n_coord is None:
                    continue
                point_lookup[int(aob)] = f"SRID=4326;POINT({e} {n_coord})"

        # 6. Addresses — budynki/działki (adr_stat_lr.csv)
        stat_lookup: dict[int, dict] = {}
        if "addresses" in todo:
            log.info("Addresses (stat)...")
            stat_path = await rc.download("addresses")

            async def _addresses():
                for row in rc.iter_rows(stat_path):
                    if not row.get("NR", "").strip():
                        continue
                    mapped = map_address_csv(row, point_lookup)
                    stat_lookup[mapped["rc_code"]] = {
                        "locality_code": mapped["locality_code"],
                        "street_code": mapped["street_code"],
                        "postal_code": mapped["postal_code"],
                    }
                    yield mapped

            n = await upsert_all(session, Address, _addresses())
            log.info("  %d rows", n)
            await save_completed_step(session, "addresses")
        else:
            log.info(
                "Addresses (stat)... skipped (already done) — rebuilding stat_lookup for premises step"
            )
            stat_path = await rc.download("addresses")
            for row in rc.iter_rows(stat_path):
                if not row.get("NR", "").strip():
                    continue
                mapped = map_address_csv(row, point_lookup)
                stat_lookup[mapped["rc_code"]] = {
                    "locality_code": mapped["locality_code"],
                    "street_code": mapped["street_code"],
                    "postal_code": mapped["postal_code"],
                }

        # 7. Premises — lokale (adr_pat_lr.csv)
        if "premises" in todo:
            log.info("Addresses (premises)...")
            pat_path = await rc.download("premises")

            async def _premises():
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

            n = await upsert_all(session, Address, _premises())
            log.info("  %d rows", n)
            await save_completed_step(session, "premises")
        else:
            log.info("Premises... skipped (already done)")

    rc_geo = RCGeoJsonClient()

    async with AsyncSessionLocal() as session:
        # 8. Locality boundaries (adr_gra_gyvenamosios_vietoves.json)
        if "boundaries" in todo:
            log.info("Locality boundaries...")
            path = await rc_geo.download("localities_boundary")
            n = await update_geometries(
                session,
                "localities",
                (map_locality_boundary(feat) for feat in rc_geo.iter_features(path)),
            )
            log.info("  %d rows updated", n)
            await save_completed_step(session, "boundaries")
        else:
            log.info("Locality boundaries... skipped (already done)")

        # 9. Street axes (adr_gra_gatves.json)
        if "axes" in todo:
            log.info("Street axes...")
            path = await rc_geo.download("streets_axis")
            n = await update_geometries(
                session,
                "streets",
                (map_street_axis(feat) for feat in rc_geo.iter_features(path)),
            )
            log.info("  %d rows updated", n)
            await save_completed_step(session, "axes")
        else:
            log.info("Street axes... skipped (already done)")

    # Zapis head _cid ze Spinty do DB
    if "cid" in todo:
        log.info("Fetching head _cid from Spinta...")
        spinta = SpintaClient()
        head_cid = 0
        async for record in spinta.fetch_changes("adresai/Adresas", since_cid=-1, limit=1):
            head_cid = record["_cid"]
        log.info("  head _cid = %d", head_cid)
        async with AsyncSessionLocal() as session:
            await save_cid(session, head_cid)
            await save_completed_step(session, "cid")
        log.info("State saved to DB (key=adresai_cid, value=%d)", head_cid)

    log.info("Full import done.")


if __name__ == "__main__":
    configure_logging()
    asyncio.run(run())
