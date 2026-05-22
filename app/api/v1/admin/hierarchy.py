"""Endpoints for cascading filter dropdowns (county → municipality → locality → street)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import Page, PaginationParams, pagination_params
from app.auth import get_current_user
from app.dependencies import get_db
from app.models.admin import User

router = APIRouter(prefix="/api/v1/admin", tags=["admin-hierarchy"])


class CountyOut(BaseModel):
    rc_code: int
    name: str


class MunicipalityOut(BaseModel):
    rc_code: int
    county_code: int
    name: str
    type: str


class LocalityOut(BaseModel):
    rc_code: int
    muni_code: int
    name: str
    type: str
    type_abbr: str | None


class StreetOut(BaseModel):
    rc_code: int
    locality_code: int
    name: str
    full_name: str


_ALLOWED_TABLES: dict[str, str] = {
    "counties": "rc_code, name",
    "municipalities": "rc_code, county_code, name, type",
    "localities": "rc_code, muni_code, name, type, type_abbr",
    "streets": "rc_code, locality_code, name, full_name",
}


async def _paginated(
    db: AsyncSession,
    table: str,
    where: str,
    order_by: str,
    params: dict,
    page: PaginationParams,
) -> tuple[int, list[dict]]:
    """Internal pagination helper. `table` must be a key of `_ALLOWED_TABLES`."""
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"unknown table: {table}")
    columns = _ALLOWED_TABLES[table]
    total = int(
        (await db.execute(text(f"SELECT COUNT(*) FROM {table} {where}"), params)).scalar() or 0
    )
    params = {**params, "limit": page.limit, "offset": page.offset}
    rows = (await db.execute(
        text(f"SELECT {columns} FROM {table} {where} ORDER BY {order_by} LIMIT :limit OFFSET :offset"),
        params,
    )).mappings().all()
    return total, list(rows)


@router.get("/counties", response_model=Page[CountyOut])
async def list_counties(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
) -> Page[CountyOut]:
    total, rows = await _paginated(db, "counties", "", "name", {}, page)
    return Page[CountyOut](total=total, items=[CountyOut(**r) for r in rows])


@router.get("/municipalities", response_model=Page[MunicipalityOut])
async def list_municipalities(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
    county_code: int | None = Query(None),
) -> Page[MunicipalityOut]:
    where = "WHERE county_code = :c" if county_code is not None else ""
    params = {"c": county_code} if county_code is not None else {}
    total, rows = await _paginated(db, "municipalities", where, "name", params, page)
    return Page[MunicipalityOut](total=total, items=[MunicipalityOut(**r) for r in rows])


@router.get("/localities", response_model=Page[LocalityOut])
async def list_localities(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
    muni_code: int | None = Query(None),
    q: str | None = Query(None, description="autocomplete prefix/substring"),
) -> Page[LocalityOut]:
    filters = []
    params: dict = {}
    if muni_code is not None:
        filters.append("muni_code = :muni_code")
        params["muni_code"] = muni_code
    if q:
        filters.append("(name ILIKE :q OR name_k ILIKE :q)")
        params["q"] = f"%{q}%"
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    total, rows = await _paginated(db, "localities", where, "name", params, page)
    return Page[LocalityOut](total=total, items=[LocalityOut(**r) for r in rows])


@router.get("/streets", response_model=Page[StreetOut])
async def list_streets(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[PaginationParams, Depends(pagination_params)],
    locality_code: int | None = Query(None),
    q: str | None = Query(None, description="autocomplete prefix/substring"),
) -> Page[StreetOut]:
    filters = []
    params: dict = {}
    if locality_code is not None:
        filters.append("locality_code = :locality_code")
        params["locality_code"] = locality_code
    if q:
        filters.append("(name ILIKE :q OR full_name ILIKE :q)")
        params["q"] = f"%{q}%"
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    total, rows = await _paginated(db, "streets", where, "name", params, page)
    return Page[StreetOut](total=total, items=[StreetOut(**r) for r in rows])
