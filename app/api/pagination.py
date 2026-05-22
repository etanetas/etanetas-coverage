from typing import Annotated, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

MAX_LIMIT = 100
DEFAULT_LIMIT = 50


class PaginationParams(BaseModel):
    limit: int
    offset: int


def pagination_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginationParams:
    return PaginationParams(limit=limit, offset=offset)


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    total: int
    items: list[T]
