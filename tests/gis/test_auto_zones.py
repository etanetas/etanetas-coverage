"""Integration tests for auto-zone rebuild — require PostgreSQL+PostGIS."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auto_zones import rebuild_auto_zones
from app.models.service import AddressOffering, ServiceZone
from app.time import now
from tests.gis.test_db_integration import (
    ADDR_FAR,
    ADDR_NEAR,
    _seed_addresses,
    _seed_tech_and_user,
)


async def _add_offering(
    session: AsyncSession, address_code: int, tech_id: uuid.UUID, user_id: uuid.UUID,
    status: str = "available", download: int = 1000, upload: int = 500,
) -> AddressOffering:
    offering = AddressOffering(
        address_code=address_code,
        technology_id=tech_id,
        status=status,
        max_download_mbps=download,
        max_upload_mbps=upload,
        status_since=now().date(),
        created_by=user_id,
    )
    session.add(offering)
    await session.flush()
    return offering


async def _zone_row(session: AsyncSession, name: str):
    return (
        await session.execute(
            text(
                """
                SELECT z.id, z.source, z.deleted_at,
                       ST_SRID(z.polygon::geometry) AS srid,
                       GeometryType(z.polygon::geometry) AS gtype,
                       ST_Contains(z.polygon::geometry,
                                   (SELECT point::geometry FROM addresses WHERE rc_code = :near)) AS has_near,
                       ST_Contains(z.polygon::geometry,
                                   (SELECT point::geometry FROM addresses WHERE rc_code = :far)) AS has_far
                FROM service_zones z WHERE z.name = :name
                """
            ),
            {"near": ADDR_NEAR, "far": ADDR_FAR, "name": name},
        )
    ).one_or_none()


async def test_rebuild_creates_auto_zone_from_available_offerings(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    await _add_offering(db_session, ADDR_NEAR, tech.id, user.id, download=2000, upload=900)
    await _add_offering(db_session, ADDR_FAR, tech.id, user.id, status="planned")

    rebuilt = await rebuild_auto_zones(db_session, tech.id)

    assert rebuilt == ["Auto: Test GPON"]
    row = await _zone_row(db_session, "Auto: Test GPON")
    assert row is not None
    assert row.source == "auto"
    assert row.deleted_at is None
    assert row.srid == 4326
    assert row.gtype == "MULTIPOLYGON"
    assert row.has_near is True   # available offering → in zone
    assert row.has_far is False   # planned only → excluded
    zo = (
        await db_session.execute(
            text("SELECT status, max_download_mbps, max_upload_mbps FROM zone_offerings WHERE zone_id = :z"),
            {"z": row.id},
        )
    ).one()
    assert (zo.status, zo.max_download_mbps, zo.max_upload_mbps) == ("available", 2000, 900)


async def test_rebuild_hides_zone_when_no_available_offerings(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    offering = await _add_offering(db_session, ADDR_NEAR, tech.id, user.id)
    await rebuild_auto_zones(db_session, tech.id)

    offering.status = "unavailable"
    await db_session.flush()
    rebuilt = await rebuild_auto_zones(db_session, tech.id)

    assert rebuilt == ["Auto: Test GPON"]
    row = await _zone_row(db_session, "Auto: Test GPON")
    assert row.deleted_at is not None  # hidden from map


async def test_rebuild_revives_hidden_zone(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    offering = await _add_offering(db_session, ADDR_NEAR, tech.id, user.id)
    await rebuild_auto_zones(db_session, tech.id)
    offering.status = "unavailable"
    await db_session.flush()
    await rebuild_auto_zones(db_session, tech.id)

    offering.status = "available"
    await db_session.flush()
    await rebuild_auto_zones(db_session, tech.id)

    row = await _zone_row(db_session, "Auto: Test GPON")
    assert row.deleted_at is None
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM service_zones WHERE source = 'auto' AND name = 'Auto: Test GPON'")
        )
    ).scalar()
    assert count == 1  # revived, not duplicated


async def test_rebuild_leaves_manual_zones_untouched(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    manual = ServiceZone(name="Reczna strefa", created_by=user.id)  # source defaults to 'manual'
    db_session.add(manual)
    await db_session.flush()
    await _add_offering(db_session, ADDR_NEAR, tech.id, user.id)

    await rebuild_auto_zones(db_session, tech.id)

    row = (
        await db_session.execute(
            text("SELECT source, deleted_at, polygon FROM service_zones WHERE name = 'Reczna strefa'")
        )
    ).one()
    assert row.source == "manual"
    assert row.deleted_at is None
    assert row.polygon is None  # untouched


async def test_rebuild_all_technologies(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    await _add_offering(db_session, ADDR_NEAR, tech.id, user.id)

    rebuilt = await rebuild_auto_zones(db_session)  # technology_id=None

    assert "Auto: Test GPON" in rebuilt
