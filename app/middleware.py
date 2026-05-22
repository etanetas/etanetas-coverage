import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger(__name__)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _get_or_make_request_id(headers) -> str:
    incoming = headers.get("X-Request-ID") or headers.get("x-request-id")
    if incoming and _REQUEST_ID_RE.match(incoming):
        return incoming
    return str(uuid.uuid4())


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = _get_or_make_request_id(request.headers)
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        log.info(
            "%s %s %d %.1fms request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response
