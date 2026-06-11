"""Integration tests for auto-zone rebuild — require PostgreSQL+PostGIS."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auto_zones import rebuild_auto_zones
from app.models.address import Address
from app.models.service import AddressOffering, ServiceZone
from app.time import now
from tests.gis.test_db_integration import (
    ADDR_FAR,
    ADDR_NEAR,
    LOCALITY,
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


async def _add_building(session: AsyncSession, rc_code: int, x: float, y: float) -> None:
    """Building address at LKS94 (x, y) in the test locality."""
    session.add(Address(rc_code=rc_code, locality_code=LOCALITY, house_no=str(rc_code)[-3:], address_type="building"))
    await session.flush()
    await session.execute(
        text(
            "UPDATE addresses SET point = ST_Transform(ST_SetSRID(ST_MakePoint(:x, :y), 3346), 4326) "
            "WHERE rc_code = :code"
        ),
        {"code": rc_code, "x": x, "y": y},
    )


# Bridge connecting ADDR_NEAR (y=6050030) to ADDR_FAR (y=6052000): points every 250m
# (150m buffer -> adjacent circles overlap), last point is 220m from ADDR_FAR.
BRIDGE_YS = [6050280, 6050530, 6050780, 6051030, 6051280, 6051530, 6051780]
BRIDGE_RC = [99000000020 + i for i in range(len(BRIDGE_YS))]


async def _add_bridge(session: AsyncSession, tech_id: uuid.UUID, user_id: uuid.UUID) -> None:
    for rc, y in zip(BRIDGE_RC, BRIDGE_YS):
        await _add_building(session, rc, 580050, y)
        await _add_offering(session, rc, tech_id, user_id)


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

    assert rebuilt == ["Auto: Test GPON — Testkaimis"]
    row = await _zone_row(db_session, "Auto: Test GPON — Testkaimis")
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

    assert rebuilt == ["Auto: Test GPON — Testkaimis"]
    row = await _zone_row(db_session, "Auto: Test GPON — Testkaimis")
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

    row = await _zone_row(db_session, "Auto: Test GPON — Testkaimis")
    assert row.deleted_at is None
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM service_zones WHERE source = 'auto' AND name = 'Auto: Test GPON — Testkaimis'")
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

    assert "Auto: Test GPON — Testkaimis" in rebuilt


async def test_two_disconnected_areas_get_two_zones(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    # Cluster NEAR: 2 buildings 100m apart -> larger area, no suffix.
    await _add_offering(db_session, ADDR_NEAR, tech.id, user.id, download=2000, upload=900)
    await _add_building(db_session, 99000000010, 580050, 6050130)
    await _add_offering(db_session, 99000000010, tech.id, user.id, download=1000, upload=500)
    # Cluster FAR: 1 building 2km away -> separate area, suffix (2).
    await _add_offering(db_session, ADDR_FAR, tech.id, user.id, download=300, upload=100)

    rebuilt = await rebuild_auto_zones(db_session, tech.id)

    assert sorted(rebuilt) == [
        "Auto: Test GPON — Testkaimis",
        "Auto: Test GPON — Testkaimis (2)",
    ]
    rows = (
        await db_session.execute(
            text(
                """
                SELECT z.name, zo.max_download_mbps AS dl, zo.max_upload_mbps AS ul
                FROM service_zones z JOIN zone_offerings zo ON zo.zone_id = z.id
                WHERE z.source = 'auto' AND z.deleted_at IS NULL
                  AND zo.technology_id = :tid
                ORDER BY z.name
                """
            ),
            {"tid": str(tech.id)},
        )
    ).all()
    # Speeds aggregated per area, not globally.
    assert [(r.name, r.dl, r.ul) for r in rows] == [
        ("Auto: Test GPON — Testkaimis", 2000, 900),
        ("Auto: Test GPON — Testkaimis (2)", 300, 100),
    ]


async def test_merge_preserves_custom_name_of_larger_area(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    await _add_offering(db_session, ADDR_NEAR, tech.id, user.id)
    await _add_building(db_session, 99000000010, 580050, 6050130)
    await _add_offering(db_session, 99000000010, tech.id, user.id)
    await _add_offering(db_session, ADDR_FAR, tech.id, user.id)
    await rebuild_auto_zones(db_session, tech.id)

    near_zone_id = (
        await db_session.execute(
            text(
                "SELECT id FROM service_zones "
                "WHERE source = 'auto' AND name = 'Auto: Test GPON — Testkaimis'"
            )
        )
    ).scalar_one()
    await db_session.execute(
        text("UPDATE service_zones SET custom_name = 'Centrum' WHERE id = :id"),
        {"id": near_zone_id},
    )

    await _add_bridge(db_session, tech.id, user.id)  # connects both areas
    await rebuild_auto_zones(db_session, tech.id)

    rows = (
        await db_session.execute(
            text(
                "SELECT z.id, z.custom_name, z.deleted_at FROM service_zones z "
                "JOIN zone_offerings zo ON zo.zone_id = z.id "
                "WHERE z.source = 'auto' AND zo.technology_id = :tid ORDER BY z.created_at"
            ),
            {"tid": str(tech.id)},
        )
    ).all()
    active = [r for r in rows if r.deleted_at is None]
    hidden = [r for r in rows if r.deleted_at is not None]
    assert len(active) == 1
    assert active[0].id == near_zone_id        # larger intersection wins
    assert active[0].custom_name == "Centrum"  # custom_name survived merge
    assert len(hidden) == 1                    # FAR zone hidden


async def test_split_keeps_id_on_largest_component(db_session: AsyncSession) -> None:
    await _seed_addresses(db_session)
    tech, user = await _seed_tech_and_user(db_session)
    await _add_offering(db_session, ADDR_NEAR, tech.id, user.id)
    await _add_bridge(db_session, tech.id, user.id)
    await _add_offering(db_session, ADDR_FAR, tech.id, user.id)
    await rebuild_auto_zones(db_session, tech.id)

    orig_id = (
        await db_session.execute(
            text(
                "SELECT z.id FROM service_zones z "
                "JOIN zone_offerings zo ON zo.zone_id = z.id "
                "WHERE z.source = 'auto' AND z.deleted_at IS NULL AND zo.technology_id = :tid"
            ),
            {"tid": str(tech.id)},
        )
    ).scalar_one()
    await db_session.execute(
        text("UPDATE service_zones SET custom_name = 'Magistrala' WHERE id = :id"),
        {"id": orig_id},
    )

    # Break bridge: NEAR side keeps 4 points (ADDR_NEAR + 3 bridge), FAR side keeps 3.
    # BRIDGE_RC = [99000000020, ...026]; indices 3 and 4 are rc 99000000023 and 99000000024.
    await db_session.execute(
        text("DELETE FROM address_offerings WHERE address_code IN (99000000023, 99000000024)")
    )
    await rebuild_auto_zones(db_session, tech.id)

    rows = (
        await db_session.execute(
            text(
                "SELECT z.id, z.custom_name FROM service_zones z "
                "JOIN zone_offerings zo ON zo.zone_id = z.id "
                "WHERE z.source = 'auto' AND z.deleted_at IS NULL AND zo.technology_id = :tid "
                "ORDER BY z.created_at"
            ),
            {"tid": str(tech.id)},
        )
    ).all()
    assert len(rows) == 2
    survivor = next(r for r in rows if r.id == orig_id)
    assert survivor.custom_name == "Magistrala"  # largest piece inherits ID and custom_name
    newcomer = next(r for r in rows if r.id != orig_id)
    assert newcomer.custom_name is None
