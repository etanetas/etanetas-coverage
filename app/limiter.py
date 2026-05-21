from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _key_func(request: Request) -> str:
    """Rate-limit by X-API-Key for admin endpoints, by IP for public."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"key:{api_key[:32]}"
    return get_remote_address(request)


limiter = Limiter(key_func=_key_func)
