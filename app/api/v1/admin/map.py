import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.dependencies import get_db
from app.models.admin import User

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/map", tags=["admin-map"])

_LT_LON_MIN, _LT_LON_MAX = 20.9, 26.9
_LT_LAT_MIN, _LT_LAT_MAX = 53.8, 56.5


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        lon1, lat1, lon2, lat2 = (float(v) for v in bbox.split(","))
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, "bbox must be lon1,lat1,lon2,lat2") from exc
    if not (_LT_LON_MIN <= lon1 <= _LT_LON_MAX and _LT_LON_MIN <= lon2 <= _LT_LON_MAX):
        raise HTTPException(400, "longitude out of Lithuania range")
    if not (_LT_LAT_MIN <= lat1 <= _LT_LAT_MAX and _LT_LAT_MIN <= lat2 <= _LT_LAT_MAX):
        raise HTTPException(400, "latitude out of Lithuania range")
    return lon1, lat1, lon2, lat2


@router.get("/addresses")
async def map_addresses(
    bbox: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 3000,
) -> Response:
    """
    GeoJSON FeatureCollection of building address points within bbox.
    Returns empty collection if no points found.
    Only call at zoom >= 15 — returns at most 3000 points.
    """
    lon1, lat1, lon2, lat2 = _parse_bbox(bbox)
    limit = min(max(limit, 1), 5000)

    sql = text("""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(json_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(a.point)::json,
                'properties', json_build_object(
                    'rc_code', a.rc_code,
                    'label', COALESCE(s.name || ' ' || a.house_no, a.house_no),
                    'has_address_offering', EXISTS(
                        SELECT 1 FROM address_offerings ao WHERE ao.address_code = a.rc_code
                    )
                )
            )), '[]'::json)
        )::text
        FROM (
            SELECT a.rc_code, a.house_no, a.street_code, a.point
            FROM addresses a
            WHERE a.point IS NOT NULL
              AND a.deleted_at IS NULL
              AND a.address_type = 'building'
              AND ST_Intersects(a.point, ST_MakeEnvelope(:lon1, :lat1, :lon2, :lat2, 4326))
            LIMIT :limit
        ) a
        LEFT JOIN streets s ON s.rc_code = a.street_code
    """)

    result = await db.scalar(sql, {
        "lon1": lon1, "lat1": lat1, "lon2": lon2, "lat2": lat2, "limit": limit,
    })
    return Response(content=result or '{"type":"FeatureCollection","features":[]}',
                    media_type="application/json")


@router.get("/zones/geojson")
async def map_zones_geojson(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """
    GeoJSON FeatureCollection of all service zones with simplified polygons.
    Includes offering summary for coloring (status, technology type).
    """
    sql = text("""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(feat ORDER BY priority DESC), '[]'::json)
        )::text
        FROM (
            SELECT
                z.priority,
                json_build_object(
                    'type', 'Feature',
                    'geometry', CASE
                        WHEN z.polygon IS NOT NULL
                        THEN ST_AsGeoJSON(ST_SimplifyPreserveTopology(z.polygon::geometry, 0.0001))::json
                        ELSE NULL
                    END,
                    'properties', json_build_object(
                        'id', z.id,
                        'name', z.name,
                        'priority', z.priority,
                        'offerings', (
                            SELECT json_agg(json_build_object(
                                'status', zo.status,
                                'technology_type', tt.code,
                                'public_name', tt.public_name,
                                'max_download_mbps', zo.max_download_mbps,
                                'planned_until', zo.planned_until
                            ))
                            FROM zone_offerings zo
                            JOIN technologies t ON t.id = zo.technology_id
                            JOIN technology_types tt ON tt.id = t.type_id
                            WHERE zo.zone_id = z.id
                        )
                    )
                ) AS feat
            FROM service_zones z
            WHERE z.polygon IS NOT NULL
        ) t
    """)

    result = await db.scalar(sql)
    return Response(content=result or '{"type":"FeatureCollection","features":[]}',
                    media_type="application/json")


class InPolygonRequest(BaseModel):
    polygon_geojson: dict  # GeoJSON Polygon or MultiPolygon
    limit: int = 10000


class InPolygonResponse(BaseModel):
    total: int
    rc_codes: list[int]


@router.post("/in-polygon", response_model=InPolygonResponse)
async def addresses_in_polygon(
    body: InPolygonRequest,
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InPolygonResponse:
    """Return rc_codes of all buildings inside an ad-hoc polygon. For bulk-by-polygon flow."""
    limit = min(max(body.limit, 1), 50000)
    geojson_str = json.dumps(body.polygon_geojson)

    count = await db.scalar(text("""
        SELECT COUNT(*) FROM addresses a
        WHERE a.point IS NOT NULL
          AND a.deleted_at IS NULL
          AND a.address_type = 'building'
          AND ST_Contains(
              ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326),
              a.point::geometry
          )
    """), {"g": geojson_str})

    rows = await db.execute(text("""
        SELECT a.rc_code FROM addresses a
        WHERE a.point IS NOT NULL
          AND a.deleted_at IS NULL
          AND a.address_type = 'building'
          AND ST_Contains(
              ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326),
              a.point::geometry
          )
        ORDER BY a.rc_code
        LIMIT :limit
    """), {"g": geojson_str, "limit": limit})

    return InPolygonResponse(
        total=int(count or 0),
        rc_codes=[r[0] for r in rows.fetchall()],
    )
