import json
from datetime import UTC, datetime
from typing import Any


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def map_county(r: dict) -> dict:
    return {
        "rc_code": r["adm_kodas"],
        "name": r["pavadinimas"],
        "synced_at": _now(),
    }


def map_municipality(r: dict, county_lookup: dict[str, int]) -> dict:
    return {
        "rc_code": r["sav_kodas"],
        "county_code": county_lookup[r["apskritis"]["_id"]],
        "name": r["pavadinimas"],
        "type": r["tipas"],
        "synced_at": _now(),
    }


def map_locality(r: dict, muni_lookup: dict[str, int]) -> dict:
    return {
        "rc_code": r["gyv_kodas"],
        "muni_code": muni_lookup[r["savivaldybe"]["_id"]],
        "name": r["pavadinimas"],
        "type": r["tipas"],
        "synced_at": _now(),
    }


def map_street(r: dict, locality_lookup: dict[str, int]) -> dict:
    return {
        "rc_code": r["gat_kodas"],
        "locality_code": locality_lookup[r["gyvenamoji_vietove"]["_id"]],
        "name": r["pavadinimas"],
        "full_name": r["pavadinimas"],
        "synced_at": _now(),
    }


def map_address(
    r: dict,
    adresai_lookup: dict[str, int],
    street_lookup: dict[str, int],
    locality_lookup: dict[str, int],
    point_lookup: dict[int, str],
) -> dict:
    rc_code = adresai_lookup[r["aob_kodas"]["_id"]]
    return {
        "rc_code": rc_code,
        "street_code": street_lookup.get(r["gatve"]["_id"]) if r.get("gatve") else None,
        "locality_code": locality_lookup[r["gyvenamoji_vietove"]["_id"]],
        "house_no": r["nr"],
        "postal_code": r.get("pasto_kodas"),
        "point": point_lookup.get(rc_code),
        "synced_at": _now(),
        "deleted_at": None,
    }


# --- RC CSV mappers (full_import via registrucentras.lt files) ---


def map_county_csv(row: dict) -> dict:
    return {
        "rc_code": int(row["ADM_KODAS"]),
        "name": row["VARDAS_K"],
        "synced_at": _now(),
    }


def map_municipality_csv(row: dict) -> dict:
    return {
        "rc_code": int(row["SAV_KODAS"]),
        "county_code": int(row["ADM_KODAS"]),
        "name": row["VARDAS_K"],
        "type": row["TIPAS"],
        "synced_at": _now(),
    }


def map_locality_csv(row: dict) -> dict:
    return {
        "rc_code": int(row["GYV_KODAS"]),
        "muni_code": int(row["SAV_KODAS"]),
        "name": row["VARDAS_K"],
        "type": row["TIPAS"],
        "synced_at": _now(),
    }


def map_street_csv(row: dict) -> dict:
    return {
        "rc_code": int(row["GAT_KODAS"]),
        "locality_code": int(row["GYV_KODAS"]),
        "name": row["VARDAS_K"],
        "full_name": row["VARDAS_K"],
        "synced_at": _now(),
    }


def map_address_csv(row: dict, point_lookup: dict[int, str]) -> dict:
    rc_code = int(row["AOB_KODAS"])
    gat = row.get("GAT_KODAS", "").strip()
    return {
        "rc_code": rc_code,
        "street_code": int(gat) if gat else None,
        "locality_code": int(row["GYV_KODAS"]),
        "house_no": row["NR"],
        "postal_code": row.get("PASTO_KODAS") or None,
        "point": point_lookup.get(rc_code),
        "synced_at": _now(),
        "deleted_at": None,
    }


# stat_lookup value type
StatInfo = dict  # {"locality_code": int, "street_code": int|None, "postal_code": str|None, "point": str|None}


def map_premises_csv(
    row: dict,
    stat_lookup: dict[int, StatInfo],
    point_lookup: dict[int, str],
) -> dict | None:
    parent_aob = int(row["AOB_KODAS"])
    parent = stat_lookup.get(parent_aob)
    if parent is None:
        return None  # lokal bez budynku-rodzica w danych — pomijamy
    rc_code = int(row["PAT_KODAS"])
    return {
        "rc_code": rc_code,
        "street_code": parent["street_code"],
        "locality_code": parent["locality_code"],
        "house_no": row["PATALPOS_NR"],
        "postal_code": parent["postal_code"],
        "point": point_lookup.get(parent_aob),
        "synced_at": _now(),
        "deleted_at": None,
    }


# --- Geometry mappers (GeoJSON LKS-94 → geometry update rows) ---


def map_locality_boundary(feat: dict) -> dict[str, Any]:
    return {
        "rc_code": int(feat["properties"]["GYV_KODAS"]),
        "geom": json.dumps(feat["geometry"]),
    }


def map_street_axis(feat: dict) -> dict[str, Any]:
    return {
        "rc_code": int(feat["properties"]["GAT_KODAS"]),
        "geom": json.dumps(feat["geometry"]),
    }
