"""Row mappers: RC source data → dicts ready for SQLAlchemy upsert.

Two sets of mappers:
 - ``map_*_csv`` for RC CSV files (used by full_import)
 - ``map_*`` for Spinta JSON format (reserved for future incremental work)
 - ``map_*_boundary`` / ``map_*_axis`` for RC GeoJSON files (geometry-only)

All mappers return ``None`` on malformed rows and log a WARNING — the caller filters out
``None`` values. This way a single bad row in a 2.3M-record file does not abort the import.
"""

import json
import logging
from typing import Any

from etl.utils.time import utcnow_naive

log = logging.getLogger(__name__)


# ============================================================================
# Spinta JSON format mappers (reserved for future incremental work)
# ============================================================================


def map_county(r: dict[str, Any]) -> dict[str, Any] | None:
    """Map Spinta ``apskritis/Apskritis`` record → County row. None on malformed."""
    try:
        return {
            "rc_code": r["adm_kodas"],
            "name": r["pavadinimas"],
            "synced_at": utcnow_naive(),
        }
    except KeyError as exc:
        log.warning("Skipping malformed county record (missing %s)", exc)
        return None


def map_municipality(r: dict[str, Any], county_lookup: dict[str, int]) -> dict[str, Any] | None:
    """Map Spinta ``savivaldybe/Savivaldybe`` record → Municipality row."""
    try:
        return {
            "rc_code": r["sav_kodas"],
            "county_code": county_lookup[r["apskritis"]["_id"]],
            "name": r["pavadinimas"],
            "type": r["tipas"],
            "synced_at": utcnow_naive(),
        }
    except KeyError as exc:
        log.warning("Skipping malformed municipality record (missing %s)", exc)
        return None


def map_locality(r: dict[str, Any], muni_lookup: dict[str, int]) -> dict[str, Any] | None:
    """Map Spinta ``gyvenamojivietove/GyvenamojiVietove`` record → Locality row."""
    try:
        return {
            "rc_code": r["gyv_kodas"],
            "muni_code": muni_lookup[r["savivaldybe"]["_id"]],
            "name": r["pavadinimas"],
            "name_k": r.get("pavadinimas_k"),
            "type": r["tipas"],
            "type_abbr": r.get("tipo_santrumpa") or None,
            "synced_at": utcnow_naive(),
        }
    except KeyError as exc:
        log.warning("Skipping malformed locality record (missing %s)", exc)
        return None


def map_street(r: dict[str, Any], locality_lookup: dict[str, int]) -> dict[str, Any] | None:
    """Map Spinta ``gatve/Gatve`` record → Street row."""
    try:
        name = r["pavadinimas"]
        type_abbr = r.get("tipo_santrumpa") or None
        return {
            "rc_code": r["gat_kodas"],
            "locality_code": locality_lookup[r["gyvenamoji_vietove"]["_id"]],
            "name": name,
            "type_abbr": type_abbr,
            "full_name": f"{name} {type_abbr}" if type_abbr else name,
            "synced_at": utcnow_naive(),
        }
    except KeyError as exc:
        log.warning("Skipping malformed street record (missing %s)", exc)
        return None


def map_address(
    r: dict[str, Any],
    adresai_lookup: dict[str, int],
    street_lookup: dict[str, int],
    locality_lookup: dict[str, int],
    point_lookup: dict[int, str],
) -> dict[str, Any] | None:
    """Map Spinta ``pastatas/Pastatas`` record → Address row (joined via adresai_lookup)."""
    try:
        rc_code = adresai_lookup[r["aob_kodas"]["_id"]]
        return {
            "rc_code": rc_code,
            "street_code": street_lookup.get(r["gatve"]["_id"]) if r.get("gatve") else None,
            "locality_code": locality_lookup[r["gyvenamoji_vietove"]["_id"]],
            "house_no": r["nr"],
            "postal_code": r.get("pasto_kodas"),
            "address_type": "building",
            "point": point_lookup.get(rc_code),
            "synced_at": utcnow_naive(),
            "deleted_at": None,
        }
    except KeyError as exc:
        log.warning("Skipping malformed address record (missing %s)", exc)
        return None


# ============================================================================
# RC CSV mappers (used by full_import via registrucentras.lt files)
# ============================================================================


def map_county_csv(row: dict[str, str]) -> dict[str, Any] | None:
    """Map RC ``adr_apskritys.csv`` row → County row. None on malformed."""
    try:
        return {
            "rc_code": int(row["ADM_KODAS"]),
            "name": row["VARDAS_K"],
            "synced_at": utcnow_naive(),
        }
    except (KeyError, ValueError) as exc:
        log.warning(
            "Skipping malformed county row ADM_KODAS=%s: %s",
            row.get("ADM_KODAS", "?"),
            exc,
        )
        return None


def map_municipality_csv(row: dict[str, str]) -> dict[str, Any] | None:
    """Map RC ``adr_savivaldybes.csv`` row → Municipality row."""
    try:
        return {
            "rc_code": int(row["SAV_KODAS"]),
            "county_code": int(row["ADM_KODAS"]),
            "name": row["VARDAS_K"],
            "type": row["TIPAS"],
            "synced_at": utcnow_naive(),
        }
    except (KeyError, ValueError) as exc:
        log.warning(
            "Skipping malformed municipality row SAV_KODAS=%s: %s",
            row.get("SAV_KODAS", "?"),
            exc,
        )
        return None


def map_locality_csv(row: dict[str, str]) -> dict[str, Any] | None:
    """Map RC ``adr_gyvenamosios_vietoves.csv`` row → Locality row."""
    try:
        return {
            "rc_code": int(row["GYV_KODAS"]),
            "muni_code": int(row["SAV_KODAS"]),
            "name": row["VARDAS"],
            "name_k": row["VARDAS_K"],
            "type": row["TIPAS"],
            "type_abbr": row.get("TIPO_SANTRUMPA") or None,
            "synced_at": utcnow_naive(),
        }
    except (KeyError, ValueError) as exc:
        log.warning(
            "Skipping malformed locality row GYV_KODAS=%s: %s",
            row.get("GYV_KODAS", "?"),
            exc,
        )
        return None


def map_street_csv(
    row: dict[str, str], locality_name_lookup: dict[int, str] | None = None
) -> dict[str, Any] | None:
    """Map RC ``adr_gatves.csv`` row → Street row."""
    try:
        rc_code = int(row["GAT_KODAS"])
        locality_code = int(row["GYV_KODAS"])
        name = row["VARDAS_K"]
        type_abbr = row.get("TIPO_SANTRUMPA") or None
        if type_abbr and locality_name_lookup:
            loc_name = locality_name_lookup.get(locality_code, "")
            full_name = f"{name} {type_abbr}, {loc_name}" if loc_name else f"{name} {type_abbr}"
        elif locality_name_lookup:
            loc_name = locality_name_lookup.get(locality_code, "")
            full_name = f"{name}, {loc_name}" if loc_name else name
        else:
            full_name = f"{name} {type_abbr}" if type_abbr else name
        return {
            "rc_code": rc_code,
            "locality_code": locality_code,
            "name": name,
            "type_abbr": type_abbr,
            "full_name": full_name,
            "synced_at": utcnow_naive(),
        }
    except (KeyError, ValueError) as exc:
        log.warning(
            "Skipping malformed street row GAT_KODAS=%s: %s",
            row.get("GAT_KODAS", "?"),
            exc,
        )
        return None


def map_address_csv(row: dict[str, str], point_lookup: dict[int, str]) -> dict[str, Any] | None:
    """Map RC ``adr_stat_lr.csv`` row → Address row (building/plot)."""
    try:
        rc_code = int(row["AOB_KODAS"])
        gat = row.get("GAT_KODAS", "").strip()
        return {
            "rc_code": rc_code,
            "street_code": int(gat) if gat else None,
            "locality_code": int(row["GYV_KODAS"]),
            "house_no": row["NR"],
            "corpus_no": row.get("KORPUSO_NR") or None,
            "flat_no": None,
            "postal_code": row.get("PASTO_KODAS") or None,
            "address_type": "building",
            "point": point_lookup.get(rc_code),
            "synced_at": utcnow_naive(),
            "deleted_at": None,
        }
    except (KeyError, ValueError) as exc:
        log.warning(
            "Skipping malformed address row AOB_KODAS=%s: %s",
            row.get("AOB_KODAS", "?"),
            exc,
        )
        return None


# stat_lookup value type: {locality_code, street_code, postal_code, house_no, corpus_no}
StatInfo = dict[str, Any]


def map_premises_csv(
    row: dict[str, str],
    stat_lookup: dict[int, StatInfo],
    point_lookup: dict[int, str],
) -> dict[str, Any] | None:
    """Map RC ``adr_pat_lr.csv`` row → Address row (premises = apartment/office in a building).

    Premises inherit locality/street/postal/point from their parent building
    (via parent AOB_KODAS lookup in stat_lookup). Returns None if no parent found.
    """
    try:
        parent_aob = int(row["AOB_KODAS"])
        parent = stat_lookup.get(parent_aob)
        if parent is None:
            return None  # premises without parent in current data — silent skip
        rc_code = int(row["PAT_KODAS"])
        return {
            "rc_code": rc_code,
            "street_code": parent["street_code"],
            "locality_code": parent["locality_code"],
            "house_no": parent["house_no"],
            "corpus_no": parent.get("corpus_no"),
            "flat_no": row["PATALPOS_NR"],
            "postal_code": parent["postal_code"],
            "address_type": "premises",
            "point": point_lookup.get(parent_aob),
            "synced_at": utcnow_naive(),
            "deleted_at": None,
        }
    except (KeyError, ValueError) as exc:
        log.warning(
            "Skipping malformed premises row PAT_KODAS=%s: %s",
            row.get("PAT_KODAS", "?"),
            exc,
        )
        return None


# ============================================================================
# Geometry mappers (GeoJSON → SQL UPDATE rows)
# ============================================================================


def map_locality_boundary(feat: dict[str, Any]) -> dict[str, Any] | None:
    """Extract ``GYV_KODAS`` + serialized geometry from an RC locality GeoJSON feature."""
    try:
        return {
            "rc_code": int(feat["properties"]["GYV_KODAS"]),
            "geom": json.dumps(feat["geometry"]),
        }
    except (KeyError, ValueError, TypeError) as exc:
        log.warning("Skipping malformed locality boundary feature: %s", exc)
        return None


def map_street_axis(feat: dict[str, Any]) -> dict[str, Any] | None:
    """Extract ``GAT_KODAS`` + serialized geometry from an RC street GeoJSON feature."""
    try:
        return {
            "rc_code": int(feat["properties"]["GAT_KODAS"]),
            "geom": json.dumps(feat["geometry"]),
        }
    except (KeyError, ValueError, TypeError) as exc:
        log.warning("Skipping malformed street axis feature: %s", exc)
        return None
