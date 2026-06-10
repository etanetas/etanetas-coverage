"""Integration tests for GIS import DB steps — require PostgreSQL+PostGIS."""

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
    await session.flush()
    session.add(Municipality(rc_code=MUNI, county_code=COUNTY, name="Test sav.", type="r. sav."))
    await session.flush()
    session.add(
        Locality(rc_code=LOCALITY, muni_code=MUNI, name="Testkaimis", type="k.")
    )
    await session.flush()
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


async def test_load_temp_geometries_empty_input(db_session: AsyncSession) -> None:
    await load_temp_geometries(db_session, [])
    assert await match_addresses(db_session, distance=50) == []
