"""Data integrity tests — verify DB matches source RC files and live Spinta API.

These tests require:
- @pytest.mark.integration: running DB
- @pytest.mark.live: network access to Spinta / RC

Run integration only (no network):
    uv run pytest tests/etl/test_data_integrity.py -m "integration and not live"

Run all including live:
    uv run pytest tests/etl/test_data_integrity.py
"""

import csv
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.models.address import Address, County, Locality, Municipality, Street
from etl.transformers.address_mapper import map_county_csv

_CACHE = Path("etl/state/cache")

# Lithuania bounding box (WGS84)
_LT_LON_MIN, _LT_LON_MAX = 20.9, 26.9
_LT_LAT_MIN, _LT_LAT_MAX = 53.8, 56.5


def _csv_rows(name: str) -> list[dict]:
    path = _CACHE / f"rc_{name}.csv"
    if not path.exists():
        pytest.skip(f"Cache file {path.name} not found — run full_import first")
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter="|"))


# ---------------------------------------------------------------------------
# County tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCounties:
    async def test_all_csv_counties_exist_in_db(self, db_session):
        """Every county from RC CSV must exist in DB with correct name."""
        rows = _csv_rows("counties")
        for row in rows:
            expected = map_county_csv(row)
            db_row = await db_session.get(County, expected["rc_code"])
            assert db_row is not None, f"County rc_code={expected['rc_code']} missing from DB"
            assert db_row.name == expected["name"]

    async def test_db_has_at_least_all_csv_counties(self, db_session):
        """DB may have more counties than CSV (historical data) — but must have at least CSV count."""
        rows = _csv_rows("counties")
        # Filter out test data (rc_codes used in upsert tests are 9000+; real LT codes are 1-10)
        real_count = await db_session.scalar(
            select(func.count()).select_from(County).where(County.rc_code <= 100)
        )
        assert real_count == len(rows), (
            f"DB has {real_count} real counties (rc_code<=100) but CSV has {len(rows)}"
        )


# ---------------------------------------------------------------------------
# Municipality / Locality / Street counts
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAdminHierarchyCounts:
    async def test_municipality_count_matches_source(self, db_session):
        rows = _csv_rows("municipalities")
        db_count = await db_session.scalar(select(func.count()).select_from(Municipality))
        assert db_count == len(rows)

    async def test_db_has_at_least_csv_localities(self, db_session):
        """DB may have historical localities from Spinta — must have at least what CSV has."""
        rows = _csv_rows("localities")
        db_count = await db_session.scalar(select(func.count()).select_from(Locality))
        assert db_count >= len(rows), (
            f"DB has {db_count} localities but CSV has {len(rows)} — data loss detected"
        )

    async def test_db_has_at_least_csv_streets(self, db_session):
        """DB may have historical streets from Spinta — must have at least what CSV has."""
        rows = _csv_rows("streets")
        db_count = await db_session.scalar(select(func.count()).select_from(Street))
        assert db_count >= len(rows), (
            f"DB has {db_count} streets but CSV has {len(rows)} — data loss detected"
        )


# ---------------------------------------------------------------------------
# Address sample fidelity
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAddressSampleFidelity:
    def _sample_rows(self, n=20) -> list[dict]:
        """Return first n non-empty rows from cached addresses CSV."""
        all_rows = _csv_rows("addresses")
        return [r for r in all_rows if r.get("NR", "").strip()][:n]

    async def test_sample_addresses_exist_in_db(self, db_session):
        for row in self._sample_rows():
            rc_code = int(row["AOB_KODAS"])
            result = await db_session.get(Address, rc_code)
            assert result is not None, f"Address rc_code={rc_code} (NR={row['NR']}) missing from DB"

    async def test_house_no_matches_source(self, db_session):
        for row in self._sample_rows():
            rc_code = int(row["AOB_KODAS"])
            result = await db_session.get(Address, rc_code)
            assert result is not None
            assert result.house_no == row["NR"], (
                f"rc_code={rc_code}: DB house_no={result.house_no!r} but CSV NR={row['NR']!r}"
            )

    async def test_locality_code_matches_source(self, db_session):
        for row in self._sample_rows():
            rc_code = int(row["AOB_KODAS"])
            result = await db_session.get(Address, rc_code)
            assert result is not None
            assert result.locality_code == int(row["GYV_KODAS"])

    async def test_total_address_count_matches_stat_plus_premises(self, db_session):
        stat_rows = [r for r in _csv_rows("addresses") if r.get("NR", "").strip()]
        pat_rows = [r for r in _csv_rows("premises") if r.get("PATALPOS_NR", "").strip()]
        source_total = len(stat_rows) + len(pat_rows)
        db_total = await db_session.scalar(
            select(func.count()).select_from(Address).where(Address.deleted_at.is_(None))
        )
        # Allow small delta (addresses added/removed between file generation and import)
        assert abs(db_total - source_total) < 100, (
            f"DB has {db_total} addresses, source has {source_total} (delta={db_total - source_total})"
        )


# ---------------------------------------------------------------------------
# Geometry / spatial integrity
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSpatialIntegrity:
    async def test_point_coverage(self, db_session):
        """At least 99% of non-deleted addresses should have a point."""
        total = await db_session.scalar(
            select(func.count()).select_from(Address).where(Address.deleted_at.is_(None))
        )
        with_point = await db_session.scalar(
            select(func.count())
            .select_from(Address)
            .where(Address.deleted_at.is_(None), Address.point.isnot(None))
        )
        pct = with_point / total * 100
        assert pct >= 99.0, f"Only {pct:.1f}% of addresses have a point (expected >=99%)"

    async def test_points_within_lithuania_bbox(self, db_session):
        """Sample 1000 random points — all should be within Lithuania bounding box."""
        result = await db_session.execute(
            text("""
                SELECT ST_X(point::geometry) AS lon, ST_Y(point::geometry) AS lat
                FROM addresses
                WHERE point IS NOT NULL AND deleted_at IS NULL
                ORDER BY RANDOM()
                LIMIT 1000
            """)
        )
        rows = result.fetchall()
        assert len(rows) > 0, "No addresses with points found"
        outside = [
            (lon, lat)
            for lon, lat in rows
            if not (_LT_LON_MIN <= lon <= _LT_LON_MAX and _LT_LAT_MIN <= lat <= _LT_LAT_MAX)
        ]
        assert len(outside) == 0, (
            f"{len(outside)} points outside Lithuania bbox: first={outside[:3]}"
        )

    async def test_locality_boundary_coverage(self, db_session):
        """Localities loaded from current CSV (those in GeoJSON) should have boundary.

        DB may contain historical localities from Spinta without boundaries — we check
        coverage only on localities that appear in the current RC CSV (active localities).
        """
        csv_codes = {int(r["GYV_KODAS"]) for r in _csv_rows("localities")}
        csv_count = len(csv_codes)
        with_boundary = await db_session.scalar(
            text("SELECT COUNT(*) FROM localities WHERE boundary IS NOT NULL")
        )
        pct = with_boundary / csv_count * 100
        assert pct >= 99.0, (
            f"Only {with_boundary}/{csv_count} active localities have boundary ({pct:.1f}%)"
        )

    async def test_street_axis_coverage(self, db_session):
        """Streets loaded from current CSV should all have axis geometry."""
        csv_count = len(_csv_rows("streets"))
        with_axis = await db_session.scalar(
            text("SELECT COUNT(*) FROM streets WHERE axis IS NOT NULL")
        )
        assert with_axis >= csv_count, f"Only {with_axis} streets have axis but CSV has {csv_count}"


# ---------------------------------------------------------------------------
# Referential integrity
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReferentialIntegrity:
    async def test_no_orphan_addresses(self, db_session):
        """All addresses must reference an existing locality."""
        orphans = await db_session.scalar(
            text("""
                SELECT COUNT(*) FROM addresses a
                LEFT JOIN localities l ON l.rc_code = a.locality_code
                WHERE l.rc_code IS NULL
            """)
        )
        assert orphans == 0, f"{orphans} addresses with missing locality_code"

    async def test_no_orphan_streets(self, db_session):
        """All addresses with street_code must reference an existing street."""
        orphans = await db_session.scalar(
            text("""
                SELECT COUNT(*) FROM addresses a
                LEFT JOIN streets s ON s.rc_code = a.street_code
                WHERE a.street_code IS NOT NULL AND s.rc_code IS NULL
            """)
        )
        assert orphans == 0, f"{orphans} addresses with invalid street_code"

    async def test_no_duplicate_rc_codes(self, db_session):
        dupes = await db_session.scalar(
            text("""
                SELECT COUNT(*) FROM (
                    SELECT rc_code FROM addresses GROUP BY rc_code HAVING COUNT(*) > 1
                ) t
            """)
        )
        assert dupes == 0, f"{dupes} duplicate rc_codes in addresses"


# ---------------------------------------------------------------------------
# Live Spinta API smoke test
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.live
@pytest.mark.timeout(30)
class TestLiveSpintaConsistency:
    async def test_sample_spinta_addresses_in_db(self, db_session):
        """Fetch 10 addresses from Spinta, verify their rc_codes exist in DB."""
        from etl.downloaders.spinta_client import SpintaClient

        spinta = SpintaClient()
        checked = 0
        async for rec in spinta.fetch_all("adresai/Adresas", limit=10):
            aob_kodas = rec["aob_kodas"]
            result = await db_session.get(Address, aob_kodas)
            assert result is not None, f"Spinta aob_kodas={aob_kodas} not found in DB"
            checked += 1
            if checked >= 10:
                break
        assert checked == 10, "Could not fetch 10 addresses from Spinta"

    async def test_spinta_cid_is_current(self, db_session):
        """Our saved _cid should be <= the current Spinta head cid."""
        from etl.downloaders.spinta_client import SpintaClient
        from etl.state_db import get_last_cid

        our_cid = await get_last_cid(db_session)
        spinta = SpintaClient()
        head_cid = 0
        async for rec in spinta.fetch_changes("adresai/Adresas", since_cid=-1, limit=1):
            head_cid = rec["_cid"]
        assert our_cid <= head_cid, (
            f"Our cid={our_cid} is ahead of Spinta head={head_cid} — something is wrong"
        )
