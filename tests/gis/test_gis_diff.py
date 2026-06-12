"""Tryb diff importu GIS: wykrywanie ofert osieroconych (adres poza zasiegiem sieci)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.gis_import import (
    ImportOptions,
    ImportReport,
    _run_db_steps,
    find_orphans,
    load_temp_geometries,
)
from app.models.service import AddressOffering
from app.time import now
from tests.gis.test_db_integration import (
    ADDR_FAR,
    ADDR_NEAR,
    TEST_LINE,
    _seed_addresses,
    _seed_tech_and_user,
)


async def _add_offering(session: AsyncSession, address_code, tech_id, user_id) -> AddressOffering:
    offering = AddressOffering(
        address_code=address_code,
        technology_id=tech_id,
        status="available",
        max_download_mbps=1000,
        max_upload_mbps=500,
        status_since=now().date(),
        created_by=user_id,
    )
    session.add(offering)
    await session.flush()
    return offering


def _options(**overrides) -> ImportOptions:
    defaults = {
        "shapefiles": [],
        "technology": "test_gpon",
        "distance": 50.0,
        "username": "gis_tester",
        "mode": "diff",
    }
    defaults.update(overrides)
    return ImportOptions(**defaults)


async def test_find_orphans_reports_far_offering(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    await _add_offering(db_session, ADDR_FAR, tech.id, user.id)   # ~2 km od linii
    await _add_offering(db_session, ADDR_NEAR, tech.id, user.id)  # ~30 m od linii
    await load_temp_geometries(db_session, [TEST_LINE])

    orphans = await find_orphans(db_session, tech.id, distance=50.0)

    codes = [o.rc_code for o in orphans]
    assert ADDR_FAR in codes
    assert ADDR_NEAR not in codes
    far = next(o for o in orphans if o.rc_code == ADDR_FAR)
    assert "Testkaimis" in far.full_address


async def test_diff_mode_reports_orphans_without_removing(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    await _add_offering(db_session, ADDR_FAR, tech.id, user.id)

    report = await _run_db_steps(
        db_session, _options(), [TEST_LINE], ImportReport(), lambda s: None
    )

    assert [o.rc_code for o in report.orphans] == [ADDR_FAR]
    assert report.orphans_removed == 0
    # Oferta NIE zostala usunieta — diff tylko raportuje.
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM address_offerings WHERE address_code = :rc"),
            {"rc": ADDR_FAR},
        )
    ).scalar()
    assert count == 1
    # Import nadal dziala: ADDR_NEAR dostal oferte.
    count_near = (
        await db_session.execute(
            text("SELECT count(*) FROM address_offerings WHERE address_code = :rc"),
            {"rc": ADDR_NEAR},
        )
    ).scalar()
    assert count_near == 1


async def test_import_mode_skips_orphan_detection(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    await _add_offering(db_session, ADDR_FAR, tech.id, user.id)

    report = await _run_db_steps(
        db_session, _options(mode="import"), [TEST_LINE], ImportReport(), lambda s: None
    )

    assert report.orphans == []
