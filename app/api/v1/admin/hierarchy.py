"""Endpoints for cascading filter dropdowns (county → municipality → locality → street)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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


@router.get("/counties", response_model=list[CountyOut])
async def list_counties(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CountyOut]:
    rows = (await db.execute(
        text("SELECT rc_code, name FROM counties ORDER BY name")
    )).mappings().all()
    return [CountyOut(**r) for r in rows]


@router.get("/municipalities", response_model=list[MunicipalityOut])
async def list_municipalities(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    county_code: int | None = Query(None),
) -> list[MunicipalityOut]:
    if county_code is not None:
        rows = (await db.execute(
            text("SELECT rc_code, county_code, name, type FROM municipalities WHERE county_code = :c ORDER BY name"),
            {"c": county_code},
        )).mappings().all()
    else:
        rows = (await db.execute(
            text("SELECT rc_code, county_code, name, type FROM municipalities ORDER BY name")
        )).mappings().all()
    return [MunicipalityOut(**r) for r in rows]


@router.get("/localities", response_model=list[LocalityOut])
async def list_localities(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    muni_code: int | None = Query(None),
    q: str | None = Query(None, description="autocomplete prefix/substring"),
    limit: int = Query(100, ge=1, le=500),
) -> list[LocalityOut]:
    filters = []
    params: dict = {"limit": limit}
    if muni_code is not None:
        filters.append("muni_code = :muni_code")
        params["muni_code"] = muni_code
    if q:
        filters.append("(name ILIKE :q OR name_k ILIKE :q)")
        params["q"] = f"%{q}%"

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    sql = text(f"""
        SELECT rc_code, muni_code, name, type, type_abbr
        FROM localities
        {where}
        ORDER BY name
        LIMIT :limit
    """)
    rows = (await db.execute(sql, params)).mappings().all()
    return [LocalityOut(**r) for r in rows]


@router.get("/streets", response_model=list[StreetOut])
async def list_streets(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    locality_code: int | None = Query(None),
    q: str | None = Query(None, description="autocomplete prefix/substring"),
    limit: int = Query(100, ge=1, le=500),
) -> list[StreetOut]:
    filters = []
    params: dict = {"limit": limit}
    if locality_code is not None:
        filters.append("locality_code = :locality_code")
        params["locality_code"] = locality_code
    if q:
        filters.append("(name ILIKE :q OR full_name ILIKE :q)")
        params["q"] = f"%{q}%"

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    sql = text(f"""
        SELECT rc_code, locality_code, name, full_name
        FROM streets
        {where}
        ORDER BY name
        LIMIT :limit
    """)
    rows = (await db.execute(sql, params)).mappings().all()
    return [StreetOut(**r) for r in rows]
