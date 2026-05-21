"""Unit tests for ETL state_db helper functions (pure logic, no DB)."""

from etl.state_db import IMPORT_STEPS, steps_to_run


class TestStepsToRun:
    def test_fresh_start_returns_all_steps(self):
        assert steps_to_run(None) == set(IMPORT_STEPS)

    def test_empty_string_returns_all_steps(self):
        assert steps_to_run("") == set(IMPORT_STEPS)

    def test_unknown_checkpoint_returns_all_steps(self):
        assert steps_to_run("nonexistent_step") == set(IMPORT_STEPS)

    def test_after_counties_skips_counties(self):
        result = steps_to_run("counties")
        assert "counties" not in result
        assert "municipalities" in result
        assert "addresses" in result
        assert "cid" in result

    def test_after_addresses_only_geo_and_cid_remain(self):
        result = steps_to_run("addresses")
        assert result == {"boundaries", "axes", "cid"}

    def test_after_axes_only_cid_remains(self):
        result = steps_to_run("axes")
        assert result == {"cid"}

    def test_after_cid_nothing_remains(self):
        assert steps_to_run("cid") == set()

    def test_steps_are_ordered_subset(self):
        result = steps_to_run("streets")
        expected_done = {"counties", "municipalities", "localities", "streets"}
        assert not result.intersection(expected_done)
