"""Unit tests for ETL address mapper functions.

All functions are pure (modulo synced_at timestamp) — no DB or network needed.
"""

import json

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


class TestMapCountyCsv:
    def test_basic(self):
        row = {
            "ADM_KODAS": "1",
            "TIPAS": "apskritis",
            "TIPO_SANTRUMPA": "apskr.",
            "VARDAS_K": "Alytaus",
            "ADM_NUO": "1998-06-01",
        }
        result = map_county_csv(row)
        assert result["rc_code"] == 1
        assert result["name"] == "Alytaus"
        assert "synced_at" in result

    def test_rc_code_is_int(self):
        row = {
            "ADM_KODAS": "10",
            "VARDAS_K": "Vilniaus",
            "TIPAS": "apskritis",
            "TIPO_SANTRUMPA": "apskr.",
            "ADM_NUO": "1998-06-01",
        }
        assert isinstance(map_county_csv(row)["rc_code"], int)


class TestMapMunicipalityCsv:
    def test_basic(self):
        row = {
            "SAV_KODAS": "11",
            "ADM_KODAS": "2",
            "VARDAS_K": "Alytaus miesto",
            "TIPAS": "savivaldybė",
            "TIPO_SANTRUMPA": "sav.",
            "SAV_NUO": "1998-06-01",
        }
        result = map_municipality_csv(row)
        assert result["rc_code"] == 11
        assert result["county_code"] == 2
        assert result["name"] == "Alytaus miesto"
        assert result["type"] == "savivaldybė"


class TestMapLocalityCsv:
    def test_basic(self):
        row = {
            "GYV_KODAS": "10001",
            "SAV_KODAS": "56",
            "VARDAS_K": "Abakų",
            "TIPAS": "kaimas",
            "TIPO_SANTRUMPA": "k.",
            "SEN_KODAS": "5645",
            "GYV_NUO": "1998-06-01",
        }
        result = map_locality_csv(row)
        assert result["rc_code"] == 10001
        assert result["muni_code"] == 56
        assert result["type"] == "kaimas"


class TestMapStreetCsv:
    def test_basic(self):
        row = {
            "GAT_KODAS": "1122775",
            "GYV_KODAS": "27713",
            "VARDAS_K": "Pyvesos",
            "TIPAS": "gatvė",
            "TIPO_SANTRUMPA": "g.",
            "GAT_NUO": "2011-10-11",
        }
        result = map_street_csv(row)
        assert result["rc_code"] == 1122775
        assert result["locality_code"] == 27713
        assert result["name"] == "Pyvesos"
        assert result["full_name"] == "Pyvesos"


class TestMapAddressCsv:
    def _row(self, **overrides):
        base = {
            "AOB_KODAS": "155218235",
            "SAV_KODAS": "32",
            "GYV_KODAS": "21768",
            "GAT_KODAS": "1198812",
            "NR": "46",
            "KORPUSO_NR": "",
            "PASTO_KODAS": "LT-85113",
            "AOB_NUO": "2005-02-08",
        }
        base.update(overrides)
        return base

    def test_basic(self):
        result = map_address_csv(self._row(), {})
        assert result["rc_code"] == 155218235
        assert result["locality_code"] == 21768
        assert result["street_code"] == 1198812
        assert result["house_no"] == "46"
        assert result["postal_code"] == "LT-85113"
        assert result["deleted_at"] is None

    def test_no_street(self):
        result = map_address_csv(self._row(GAT_KODAS=""), {})
        assert result["street_code"] is None

    def test_empty_postal_code(self):
        result = map_address_csv(self._row(PASTO_KODAS=""), {})
        assert result["postal_code"] is None

    def test_point_from_lookup(self):
        point = "SRID=4326;POINT(25.39 54.31)"
        result = map_address_csv(self._row(), {155218235: point})
        assert result["point"] == point

    def test_missing_point(self):
        result = map_address_csv(self._row(), {})
        assert result["point"] is None


class TestMapPremisesCsv:
    def _stat_lookup(self):
        return {
            123: {"locality_code": 456, "street_code": 789, "postal_code": "LT-01234"},
        }

    def test_basic(self):
        row = {
            "PAT_KODAS": "999",
            "AOB_KODAS": "123",
            "PATALPOS_NR": "5",
            "SAV_KODAS": "11",
            "PAT_NUO": "2020-01-01",
        }
        result = map_premises_csv(row, self._stat_lookup(), {123: "SRID=4326;POINT(25.0 54.0)"})
        assert result is not None
        assert result["rc_code"] == 999
        assert result["house_no"] == "5"
        assert result["locality_code"] == 456
        assert result["street_code"] == 789
        assert result["postal_code"] == "LT-01234"
        assert result["point"] == "SRID=4326;POINT(25.0 54.0)"

    def test_no_parent_returns_none(self):
        row = {
            "PAT_KODAS": "999",
            "AOB_KODAS": "9999",
            "PATALPOS_NR": "5",
            "SAV_KODAS": "11",
            "PAT_NUO": "2020-01-01",
        }
        result = map_premises_csv(row, self._stat_lookup(), {})
        assert result is None

    def test_no_point_for_parent(self):
        row = {
            "PAT_KODAS": "999",
            "AOB_KODAS": "123",
            "PATALPOS_NR": "2",
            "SAV_KODAS": "11",
            "PAT_NUO": "2020-01-01",
        }
        result = map_premises_csv(row, self._stat_lookup(), {})
        assert result is not None
        assert result["point"] is None


class TestMapLocalityBoundary:
    def test_basic(self):
        geom = {
            "type": "Polygon",
            "coordinates": [[[25.0, 54.0], [25.1, 54.0], [25.0, 54.1], [25.0, 54.0]]],
        }
        feat = {
            "type": "Feature",
            "properties": {"GYV_KODAS": 10001, "GYV_PAV": "Test"},
            "geometry": geom,
        }
        result = map_locality_boundary(feat)
        assert result["rc_code"] == 10001
        assert json.loads(result["geom"]) == geom


class TestMapStreetAxis:
    def test_basic(self):
        geom = {"type": "LineString", "coordinates": [[25.0, 54.0], [25.1, 54.1]]}
        feat = {
            "type": "Feature",
            "properties": {"GAT_KODAS": 1122775, "GAT_PAV": "Pyvesos"},
            "geometry": geom,
        }
        result = map_street_axis(feat)
        assert result["rc_code"] == 1122775
        assert json.loads(result["geom"]) == geom
