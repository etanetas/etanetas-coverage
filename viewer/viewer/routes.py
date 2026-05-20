from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from viewer.db import get_db

router = APIRouter()

# Lithuania bounding box
_LT_LON_MIN, _LT_LON_MAX = 20.9, 26.9
_LT_LAT_MIN, _LT_LAT_MAX = 53.8, 56.5


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        lon1, lat1, lon2, lat2 = (float(v) for v in bbox.split(","))
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, "bbox must be lon1,lat1,lon2,lat2") from exc
    if not (_LT_LON_MIN <= lon1 <= _LT_LON_MAX and _LT_LON_MIN <= lon2 <= _LT_LON_MAX):
        raise HTTPException(400, f"longitude out of Lithuania range [{_LT_LON_MIN}, {_LT_LON_MAX}]")
    if not (_LT_LAT_MIN <= lat1 <= _LT_LAT_MAX and _LT_LAT_MIN <= lat2 <= _LT_LAT_MAX):
        raise HTTPException(400, f"latitude out of Lithuania range [{_LT_LAT_MIN}, {_LT_LAT_MAX}]")
    return lon1, lat1, lon2, lat2


@router.get("/api/addresses")
async def addresses(
    bbox: str,
    limit: int = 2000,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> Response:
    lon1, lat1, lon2, lat2 = _parse_bbox(bbox)
    sql = text("""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(json_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(point)::json,
                'properties', json_build_object(
                    'rc_code', rc_code,
                    'house_no', house_no,
                    'postal_code', postal_code,
                    'street_code', street_code,
                    'locality_code', locality_code
                )
            )), '[]'::json)
        )::text
        FROM (
            SELECT rc_code, house_no, postal_code, street_code, locality_code, point
            FROM addresses
            WHERE point IS NOT NULL
              AND deleted_at IS NULL
              AND ST_Intersects(point, ST_MakeEnvelope(:lon1, :lat1, :lon2, :lat2, 4326))
            LIMIT :limit
        ) t
    """)
    result = await db.scalar(
        sql, {"lon1": lon1, "lat1": lat1, "lon2": lon2, "lat2": lat2, "limit": limit}
    )
    return Response(content=result, media_type="application/json")


@router.get("/api/localities")
async def localities(
    bbox: str,
    limit: int = 500,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> Response:
    lon1, lat1, lon2, lat2 = _parse_bbox(bbox)
    sql = text("""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(json_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(ST_SimplifyPreserveTopology(boundary, 0.0001))::json,
                'properties', json_build_object(
                    'rc_code', rc_code,
                    'name', name,
                    'type', type
                )
            )), '[]'::json)
        )::text
        FROM (
            SELECT rc_code, name, type, boundary
            FROM localities
            WHERE boundary IS NOT NULL
              AND ST_Intersects(boundary, ST_MakeEnvelope(:lon1, :lat1, :lon2, :lat2, 4326))
            LIMIT :limit
        ) t
    """)
    result = await db.scalar(
        sql, {"lon1": lon1, "lat1": lat1, "lon2": lon2, "lat2": lat2, "limit": limit}
    )
    return Response(content=result, media_type="application/json")


@router.get("/api/streets")
async def streets(
    bbox: str,
    limit: int = 2000,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> Response:
    lon1, lat1, lon2, lat2 = _parse_bbox(bbox)
    sql = text("""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(json_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(ST_SimplifyPreserveTopology(axis, 0.00001))::json,
                'properties', json_build_object(
                    'rc_code', rc_code,
                    'name', name,
                    'locality_code', locality_code
                )
            )), '[]'::json)
        )::text
        FROM (
            SELECT rc_code, name, locality_code, axis
            FROM streets
            WHERE axis IS NOT NULL
              AND ST_Intersects(axis, ST_MakeEnvelope(:lon1, :lat1, :lon2, :lat2, 4326))
            LIMIT :limit
        ) t
    """)
    result = await db.scalar(
        sql, {"lon1": lon1, "lat1": lat1, "lon2": lon2, "lat2": lat2, "limit": limit}
    )
    return Response(content=result, media_type="application/json")


@router.get("/api/density")
async def density(
    bbox: str,
    cell: float = 0.005,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> Response:
    lon1, lat1, lon2, lat2 = _parse_bbox(bbox)
    cell = max(0.0001, min(cell, 1.0))  # clamp cell size
    sql = text("""
        SELECT json_agg(json_build_object('lon', lon, 'lat', lat, 'weight', weight))::text
        FROM (
            SELECT
                ST_X(ST_SnapToGrid(point::geometry, :cell)) AS lon,
                ST_Y(ST_SnapToGrid(point::geometry, :cell)) AS lat,
                COUNT(*) AS weight
            FROM addresses
            WHERE point IS NOT NULL
              AND deleted_at IS NULL
              AND ST_Intersects(point, ST_MakeEnvelope(:lon1, :lat1, :lon2, :lat2, 4326))
            GROUP BY ST_SnapToGrid(point::geometry, :cell)
        ) g
    """)
    result = await db.scalar(
        sql, {"lon1": lon1, "lat1": lat1, "lon2": lon2, "lat2": lat2, "cell": cell}
    )
    return Response(content=result or "[]", media_type="application/json")
