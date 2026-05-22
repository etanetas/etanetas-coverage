"""Response helpers for FastAPI handlers."""
from typing import TypeVar

from fastapi import Response
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def created(body: T, *, location: str, response: Response) -> T:
    """Set the `Location` header on `response` and return `body`.

    Usage:
        @router.post(..., status_code=201, response_model=Out)
        async def create(..., response: Response) -> Out:
            obj = ...
            return created(Out.model_validate(obj),
                           location=f"/api/v1/x/{obj.id}",
                           response=response)
    """
    response.headers["Location"] = location
    return body
