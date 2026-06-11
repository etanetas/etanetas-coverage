"""Integration tests for GIS import DB steps — require PostgreSQL+PostGIS."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.gis_import import (
    GisImportError,
    ImportOptions,
    ImportReport,
    _run_db_steps,
    insert_offerings,
    load_temp_geometries,
    match_addresses,
    resolve_technology,
    resolve_user,
)
from app.models.address import Address, County, Locality, Municipality
from app.models.admin import BulkOperations, User
from app.models.technology import Technology, TechnologyType

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


def _options(**overrides) -> ImportOptions:
    defaults = {
        "shapefiles": [],
        "technology": "test_gpon",
        "distance": 50.0,
        "username": "gis_tester",
        "status": "available",
    }
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
            text(
                """
                SELECT bo.operation_type, bo.affected_count
                FROM bulk_operations bo JOIN users u ON u.id = bo.user_id
                WHERE bo.operation_type = 'gis_import' AND u.username = 'gis_tester'
                """
            )
        )
    ).one()
    assert bulk_op.operation_type == "gis_import"
    assert bulk_op.affected_count == 1


async def test_run_db_steps_rejects_inactive_user(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    _, user = await _seed_tech_and_user(db_session)
    user.active = False
    await db_session.flush()

    with pytest.raises(GisImportError, match="inactive"):
        await _run_db_steps(
            db_session, _options(), [TEST_LINE], ImportReport(), progress=lambda stage: None
        )


async def test_load_temp_geometries_rerun_same_transaction(db_session: AsyncSession) -> None:
    await load_temp_geometries(db_session, [TEST_LINE])
    # second call in the same transaction must not collide with the first table
    await load_temp_geometries(db_session, ["POINT(580050 6050000)"])

    count = (await db_session.execute(text("SELECT count(*) FROM gis_import_geom"))).scalar()
    assert count == 1  # table was replaced, not appended to


async def test_run_db_steps_rebuilds_auto_zone(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    await _seed_tech_and_user(db_session)

    report = await _run_db_steps(
        db_session, _options(), [TEST_LINE], ImportReport(), progress=lambda stage: None
    )

    assert report.zones_rebuilt == ["Auto: Test GPON"]
    row = (
        await db_session.execute(
            text("SELECT source, deleted_at FROM service_zones WHERE name = 'Auto: Test GPON'")
        )
    ).one()
    assert row.source == "auto"
    assert row.deleted_at is None
