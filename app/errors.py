"""Project-wide error envelope.

All HTTP errors return:
    {"error": {"code": "MACHINE_CODE", "message": "human text", "field": "optional"}}
"""
import logging
from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

_STATUS_TO_CODE = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def _envelope(code: str, message: str, field: str | None = None, **extra: Any) -> dict:
    err: dict = {"code": code, "message": message}
    if field is not None:
        err["field"] = field
    if extra:
        err.update(extra)
    return {"error": err}


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _STATUS_TO_CODE.get(exc.status_code, "ERROR")
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        body = {"error": detail}
    else:
        body = _envelope(code, str(detail))
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_envelope(
            "VALIDATION_ERROR",
            "Request validation failed",
            errors=[{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()],
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled exception in %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=_envelope("INTERNAL_ERROR", "An internal error occurred"),
    )


def raise_error(status_code: int, code: str, message: str, field: str | None = None) -> None:
    """Raise an HTTPException whose detail is an envelope payload."""
    detail: dict = {"code": code, "message": message}
    if field is not None:
        detail["field"] = field
    raise HTTPException(status_code=status_code, detail=detail)
