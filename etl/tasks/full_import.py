import asyncio
import json
from pathlib import Path

from app.database import AsyncSessionLocal
from app.models.address import Address, County, Locality, Municipality, Street
from etl.config import settings
from etl.downloaders.rc_csv_client import RCCsvClient
from etl.downloaders.rc_zip_fallback import RCZipFallback
from etl.loaders.upsert_load import upsert_all
from etl.transformers.address_mapper import (
    map_address_csv,
    map_county_csv,
    map_locality_csv,
    map_municipality_csv,
    map_street_csv,
)

STATE_FILE = Path(__file__).parent.parent / "state" / "cursors.json"


async def run() -> None:
    rc = RCCsvClient()

    async with AsyncSessionLocal() as session:

        # 1. Counties
        print("Counties...")
        path = await rc.download("counties")

        async def _counties():
            for row in rc.iter_rows(path):
                yield map_county_csv(row)

        n = await upsert_all(session, County, _counties())
        print(f"  {n} rows")

        # 2. Municipalities
        print("Municipalities...")
        path = await rc.download("municipalities")

        async def _municipalities():
            for row in rc.iter_rows(path):
                yield map_municipality_csv(row)

        n = await upsert_all(session, Municipality, _municipalities())
        print(f"  {n} rows")

        # 3. Localities
        print("Localities...")
        path = await rc.download("localities")

        async def _localities():
            for row in rc.iter_rows(path):
                yield map_locality_csv(row)

        n = await upsert_all(session, Locality, _localities())
        print(f"  {n} rows")

        # 4. Streets
        print("Streets...")
        path = await rc.download("streets")

        async def _streets():
            for row in rc.iter_rows(path):
                yield map_street_csv(row)

        n = await upsert_all(session, Street, _streets())
        print(f"  {n} rows")

        # 5. Point lookup — RC GeoJSON ZIP → aob_kodas int → EWKT WGS84 point
        print("Downloading RC address points GeoJSON...")
        rc_zip = RCZipFallback(settings.rc_geojson_url)
        zip_path = await rc_zip.download()
        print("Building point lookup...")
        point_lookup: dict[int, str] = {}
        for feat in rc_zip.iter_features(zip_path):
            props = feat["properties"]
            aob = props.get("AOB_KODAS")
            e, n_coord = props.get("E_KOORD"), props.get("N_KOORD")
            if aob is None or e is None or n_coord is None:
                continue
            point_lookup[int(aob)] = f"SRID=4326;POINT({e} {n_coord})"
            if len(point_lookup) % 200_000 == 0:
                print(f"  points: {len(point_lookup):,}")
        print(f"  point lookup done: {len(point_lookup):,} entries")

        # 6. Addresses (adr_stat_lr.csv — žemės sklypams ir pastatams)
        print("Addresses...")
        path = await rc.download("addresses")

        async def _addresses():
            for row in rc.iter_rows(path):
                if not row.get("NR", "").strip():
                    continue
                yield map_address_csv(row, point_lookup)

        n = await upsert_all(session, Address, _addresses())
        print(f"  {n} rows")

    # Zapis kursora — TODO: zastąpić rzeczywistym head _cid z :changes
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"last_cid": 0}, indent=2))
    print(f"State saved → {STATE_FILE}")
    print("Full import done.")


if __name__ == "__main__":
    asyncio.run(run())
