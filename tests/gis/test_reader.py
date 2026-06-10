"""Unit tests for shapefile reading — no DB required."""

from pathlib import Path

import pytest
import shapefile

from app.gis_import import GisImportError, read_geometries


def _write_points(path: Path, records: list[tuple[float, float, str]]) -> None:
    """Write a POINTZ shapefile with a Busena field."""
    with shapefile.Writer(str(path), shapeType=shapefile.POINTZ) as w:
        w.field("Busena", "C", size=10)
        for x, y, busena in records:
            w.pointz(x, y, 0)
            w.record(busena)


def _write_lines(path: Path, lines: list[tuple[list[list[list[float]]], str]]) -> None:
    """Write a POLYLINEZ shapefile. Each entry: (parts, busena)."""
    with shapefile.Writer(str(path), shapeType=shapefile.POLYLINEZ) as w:
        w.field("Busena", "C", size=10)
        for parts, busena in lines:
            w.linez(parts)
            w.record(busena)


def test_reads_points_and_skips_inactive(tmp_path: Path) -> None:
    _write_points(
        tmp_path / "pts",
        [(580000.0, 6050000.0, "v"), (580010.0, 6050010.0, "b"), (580020.0, 6050020.0, "v")],
    )
    wkts, skipped = read_geometries(tmp_path / "pts")
    assert wkts == ["POINT(580000.0 6050000.0)", "POINT(580020.0 6050020.0)"]
    assert skipped == 1


def test_reads_multipart_polyline_as_separate_linestrings(tmp_path: Path) -> None:
    _write_lines(
        tmp_path / "lines",
        [([[[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]], [[20.0, 0.0, 0.0], [30.0, 5.0, 0.0]]], "v")],
    )
    wkts, skipped = read_geometries(tmp_path / "lines")
    assert wkts == ["LINESTRING(0.0 0.0, 10.0 0.0)", "LINESTRING(20.0 0.0, 30.0 5.0)"]
    assert skipped == 0


def test_accepts_path_with_shp_extension(tmp_path: Path) -> None:
    _write_points(tmp_path / "pts", [(1.0, 2.0, "v")])
    wkts, _ = read_geometries(tmp_path / "pts.shp")
    assert wkts == ["POINT(1.0 2.0)"]


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(GisImportError, match="not found"):
        read_geometries(tmp_path / "nope")
