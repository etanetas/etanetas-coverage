# API Best-Practices Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply all 60 findings from the API best-practices audit (Critical, Important, Minor) to bring the FastAPI admin/public surface to production-grade quality.

**Architecture:** Eleven sequential phases. Phase 0 lays shared utilities (time, error envelope, filter builder, response helpers). Phases 1-9 implement code fixes (auth, migrations, audit, validation, REST semantics, soft-delete, error envelope). Phases 10-11 polish OpenAPI metadata and final consistency. Each task is TDD when behavior-changing; pure refactors get a regression test pass instead of new tests. PUT→PATCH and soft-delete unification are breaking — frontend/LMS plugin are not yet in production, so no deprecation window.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, PostgreSQL 16/PostGIS 3.4, Alembic, Pydantic v2, bcrypt, pytest-asyncio, ruff. Package manager: `uv`. Test prerequisite: `docker compose up -d db`.

---

## Conventions

- **All file paths absolute from repo root**: `/home/robertas/workspace/robertas/etanetas-coverage`.
- **Run tests**: `unset VIRTUAL_ENV; .venv/bin/pytest <path> -v` (the project's `.venv` shadows the parent shell's `VIRTUAL_ENV`).
- **Commit message style**: `fix(area): short description` / `refactor(area): ...` / `feat(area): ...` (matches recent history).
- **Always run the affected test file after each task**; full suite at the end of every phase.

---

## Phase 0 — Foundation utilities

### Task 0.1: UTC `now()` helper

**Files:**
- Create: `app/time.py`
- Test: `tests/unit/test_time.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_time.py`:

```python
from datetime import UTC, datetime, timezone
from app.time import now


def test_now_is_timezone_aware():
    n = now()
    assert n.tzinfo is not None
    assert n.utcoffset().total_seconds() == 0


def test_now_is_utc():
    assert now().tzinfo == UTC
```

- [ ] **Step 2: Run test, expect failure**

```bash
unset VIRTUAL_ENV; .venv/bin/pytest tests/unit/test_time.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.time'`.

- [ ] **Step 3: Implement**

Create `app/time.py`:

```python
"""Project-wide timezone-aware time helpers.

Always use these instead of `datetime.now()` — the bare call returns a
naive datetime in local TZ and compares incorrectly against `timestamptz`
columns.
"""
from datetime import UTC, datetime


def now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)
```

- [ ] **Step 4: Run test, expect pass**

```bash
unset VIRTUAL_ENV; .venv/bin/pytest tests/unit/test_time.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/time.py tests/unit/test_time.py
git commit -m "feat(time): add UTC-aware now() helper"
```

---

### Task 0.2: ruff `DTZ` rule + lint gate

**Files:**
- Modify: `pyproject.toml` (the `[tool.ruff.lint]` block)

- [ ] **Step 1: Inspect current rules**

```bash
grep -A 15 "tool.ruff.lint" pyproject.toml
```

- [ ] **Step 2: Add `DTZ` to `select`**

Edit `pyproject.toml` — append `"DTZ", # flake8-datetimez (forbid naive datetime)` inside `[tool.ruff.lint].select = [...]`. The block should now include `DTZ` alongside the existing `E F I UP RUF`.

- [ ] **Step 3: Install ruff if missing**

```bash
unset VIRTUAL_ENV; .venv/bin/python -m pip install ruff
```

- [ ] **Step 4: Run ruff and capture violations**

```bash
unset VIRTUAL_ENV; .venv/bin/ruff check --select DTZ . 2>&1 | tee /tmp/dtz.txt
```

Expected: a non-empty list of `DTZ005` / `DTZ001` warnings. **Do not auto-fix yet** — these are fixed in Tasks 1.3 / 1.4.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "build(ruff): enable DTZ rule for timezone-naive datetime"
```

---

### Task 0.3: Filter builder utility

**Files:**
- Create: `app/db/filter_builder.py`
- Test: `tests/unit/test_filter_builder.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_filter_builder.py`:

```python
from app.db.filter_builder import build_where


def test_empty_returns_empty_clause():
    where, params = build_where([])
    assert where == ""
    assert params == {}


def test_single_filter():
    where, params = build_where([("a.id = :id", {"id": 7})])
    assert where == "WHERE a.id = :id"
    assert params == {"id": 7}


def test_multiple_filters_joined_with_and():
    where, params = build_where([
        ("a.id = :id", {"id": 7}),
        ("a.name ILIKE :q", {"q": "%foo%"}),
    ])
    assert where == "WHERE a.id = :id AND a.name ILIKE :q"
    assert params == {"id": 7, "q": "%foo%"}


def test_none_clauses_are_skipped():
    where, params = build_where([
        ("a.id = :id", {"id": 7}),
        None,
        ("a.x = :x", {"x": 1}),
    ])
    assert where == "WHERE a.id = :id AND a.x = :x"
    assert params == {"id": 7, "x": 1}
```

- [ ] **Step 2: Run test, expect failure**

```bash
unset VIRTUAL_ENV; .venv/bin/pytest tests/unit/test_filter_builder.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `app/db/filter_builder.py`:

```python
"""Shared helper for assembling `WHERE` clauses + parameter dicts.

Reduces duplication in endpoints that build SQL conditionally
(`hierarchy`, `audit`, `bulk._filter_addresses`, `addresses.list`,
`zones.list`).
"""
from typing import Iterable


Clause = tuple[str, dict] | None


def build_where(clauses: Iterable[Clause]) -> tuple[str, dict]:
    """Combine a list of (sql_fragment, params) into a single WHERE clause.

    `None` entries are skipped — useful for conditional filters.
    """
    fragments: list[str] = []
    params: dict = {}
    for clause in clauses:
        if clause is None:
            continue
        sql, p = clause
        fragments.append(sql)
        params.update(p)
    if not fragments:
        return "", params
    return "WHERE " + " AND ".join(fragments), params
```

- [ ] **Step 4: Run test, expect pass**

```bash
unset VIRTUAL_ENV; .venv/bin/pytest tests/unit/test_filter_builder.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/db/filter_builder.py tests/unit/test_filter_builder.py
git commit -m "feat(db): add shared WHERE-builder helper"
```

---

### Task 0.4: Error envelope + global exception handler

**Files:**
- Create: `app/errors.py`
- Modify: `app/main.py`
- Test: `tests/api/test_errors.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_errors.py`:

```python
import pytest


@pytest.mark.integration
async def test_404_returns_envelope(client, admin_user):
    _, raw = admin_user
    resp = await client.get("/api/v1/admin/addresses/99999999", headers={"X-API-Key": raw})
    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "NOT_FOUND"
    assert "message" in body["error"]


@pytest.mark.integration
async def test_401_returns_envelope(client):
    resp = await client.get("/api/v1/admin/me", headers={"X-API-Key": "bogus"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.integration
async def test_500_returns_envelope_without_traceback(client, admin_user, monkeypatch):
    _, raw = admin_user

    async def _boom(*a, **kw):
        raise RuntimeError("internal detail with secrets")

    from app.api.v1.admin import users as users_mod
    monkeypatch.setattr(users_mod, "_require_user", _boom)
    resp = await client.get(f"/api/v1/admin/users/00000000-0000-0000-0000-000000000000/api-keys",
                            headers={"X-API-Key": raw})
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "internal detail" not in body["error"]["message"]
```

- [ ] **Step 2: Run, expect failures**

```bash
unset VIRTUAL_ENV; .venv/bin/pytest tests/api/test_errors.py -v
```
Expected: all 3 fail (current shape is `{"detail": "..."}`).

- [ ] **Step 3: Implement `app/errors.py`**

```python
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
        content=_envelope("VALIDATION_ERROR", "Request validation failed",
                          errors=[{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]),
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
```

- [ ] **Step 4: Register handlers in `app/main.py`**

Open `app/main.py`. Locate `app = FastAPI(...)`. **After** the existing middleware/CORS setup, add:

```python
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)

app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
```

- [ ] **Step 5: Run, expect pass**

```bash
unset VIRTUAL_ENV; .venv/bin/pytest tests/api/test_errors.py -v
```
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add app/errors.py app/main.py tests/api/test_errors.py
git commit -m "feat(errors): unified error envelope + global handlers"
```

---

### Task 0.5: `created_response()` helper for Location header

**Files:**
- Create: `app/api/responses.py`
- Test: `tests/unit/test_responses.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_responses.py`:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.responses import created


class _Out(BaseModel):
    id: int


def test_created_sets_location_header():
    app = FastAPI()

    @app.post("/things", status_code=201, response_model=_Out)
    def make():
        return created(_Out(id=42), location="/things/42")

    with TestClient(app) as c:
        r = c.post("/things")
        assert r.status_code == 201
        assert r.headers["location"] == "/things/42"
        assert r.json() == {"id": 42}
```

- [ ] **Step 2: Run, expect failure** (ImportError).

```bash
unset VIRTUAL_ENV; .venv/bin/pytest tests/unit/test_responses.py -v
```

- [ ] **Step 3: Implement**

Create `app/api/responses.py`:

```python
"""Response helpers for FastAPI handlers."""
from typing import TypeVar

from fastapi import Response
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def created(body: T, *, location: str, response: Response | None = None) -> T:
    """Return `body` while setting the `Location` header on the response.

    Usage:
        @router.post(..., status_code=201, response_model=Out)
        async def create(..., response: Response) -> Out:
            obj = ...
            return created(Out.model_validate(obj), location=f"/api/v1/x/{obj.id}",
                           response=response)
    """
    if response is not None:
        response.headers["Location"] = location
    return body
```

Note: the simpler signature used in the test doesn't need `response` because `TestClient` evaluates the dependency injection differently. Adjust the implementation to also support being called without `response` by returning a tuple of `(body, headers)` only if needed — but the test above relies on injection. Update the test to inject `response`:

Replace the test's `make()` definition with:

```python
    @app.post("/things", status_code=201, response_model=_Out)
    def make(response: Response):
        return created(_Out(id=42), location="/things/42", response=response)
```

And import `Response` in the test from `fastapi`.

- [ ] **Step 4: Run, expect pass**

```bash
unset VIRTUAL_ENV; .venv/bin/pytest tests/unit/test_responses.py -v
```

- [ ] **Step 5: Commit**

```bash
git add app/api/responses.py tests/unit/test_responses.py
git commit -m "feat(api): add created() helper for 201 + Location header"
```

---

## Phase 1 — Critical fixes

### Task 1.1: Replace bare `except Exception` in /health

**Files:**
- Modify: `app/main.py` (around line 67 — the health endpoint)
- Test: `tests/api/test_health.py` (create if missing)

- [ ] **Step 1: Read the current handler**

```bash
sed -n '55,80p' app/main.py
```

- [ ] **Step 2: Write a regression test**

Create or extend `tests/api/test_health.py`:

```python
import pytest


@pytest.mark.integration
async def test_health_returns_ok_when_db_up(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "up"


@pytest.mark.integration
async def test_health_degraded_returns_503_envelope(client, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    from app import main as main_mod

    async def _broken_check(*a, **kw):
        raise SQLAlchemyError("connection refused")

    monkeypatch.setattr(main_mod, "_db_ping", _broken_check)
    resp = await client.get("/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"
```

- [ ] **Step 3: Refactor /health**

Replace the `/health` endpoint in `app/main.py`. The new shape:

```python
from sqlalchemy.exc import SQLAlchemyError
from app.errors import raise_error


async def _db_ping(db) -> None:
    """Tiny DB round-trip; isolated so tests can monkeypatch."""
    from sqlalchemy import text
    await db.execute(text("SELECT 1"))


@app.get("/health", tags=["health"], summary="Liveness + DB readiness probe")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    try:
        await _db_ping(db)
    except SQLAlchemyError as exc:
        log.warning("DB health check failed: %s", exc)
        raise_error(503, "SERVICE_UNAVAILABLE", "Database unavailable")
    except asyncio.TimeoutError:
        log.warning("DB health check timed out")
        raise_error(503, "SERVICE_UNAVAILABLE", "Database health check timed out")
    return {"status": "ok", "db": "up"}
```

Add `import asyncio` and `from sqlalchemy.ext.asyncio import AsyncSession` if not already imported at top of file.

- [ ] **Step 4: Run tests**

```bash
unset VIRTUAL_ENV; .venv/bin/pytest tests/api/test_health.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/api/test_health.py
git commit -m "fix(health): catch only DB errors, return 503 envelope"
```

---

### Task 1.2: Sweep `datetime.now()` → `app.time.now()`

**Files (every site flagged by `ruff --select DTZ`):**
- Modify: `app/auth.py`
- Modify: `app/api/v1/admin/bulk.py`
- Modify: `app/api/v1/admin/users.py`
- Modify: `app/api/v1/admin/zones.py`
- Modify: `app/api/v1/admin/addresses.py`
- (Any other file in the DTZ report from Task 0.2.)

- [ ] **Step 1: Re-run the DTZ scan**

```bash
unset VIRTUAL_ENV; .venv/bin/ruff check --select DTZ app/ 2>&1 | grep -E "^app/" | tee /tmp/dtz.txt
wc -l /tmp/dtz.txt
```

- [ ] **Step 2: Replace each site**

For every file in `/tmp/dtz.txt`:

1. Add `from app.time import now` to the import block (alongside existing imports).
2. Remove `from datetime import datetime` if `datetime` is no longer referenced; otherwise leave it.
3. Replace every `datetime.now()` with `now()`. **Do not** introduce a `from app import time` — module name `time` shadows stdlib.

Example for `app/auth.py` — replace `datetime.now()` calls in `_update_last_used`, `get_current_user`, and `revoke_api_key` paths.

- [ ] **Step 3: Run ruff again to confirm clean**

```bash
unset VIRTUAL_ENV; .venv/bin/ruff check --select DTZ app/
```
Expected: 0 errors.

- [ ] **Step 4: Run full test suite**

```bash
unset VIRTUAL_ENV; .venv/bin/pytest -q
```
Expected: all pass (existing TZ-naive comparisons keep working because PG silently casts; tests don't pin exact TZ).

- [ ] **Step 5: Add a regression test for the editor-window bug** (`bulk.py:171`)

Create `tests/api/test_bulk_editor_window.py`:

```python
from datetime import timedelta
import pytest
from sqlalchemy import text
from app.time import now


@pytest.mark.integration
async def test_rollback_outside_editor_window_returns_403(
    client, admin_user, db_session
):
    """A bulk_operations row from 1 day ago must be outside the editor window."""
    from app.models.admin import BulkOperations
    user, raw = admin_user
    op = BulkOperations(
        user_id=user.id,
        operation_type="add_offering",
        affected_count=1,
        created_at=now() - timedelta(days=1),
    )
    db_session.add(op)
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/admin/bulk/{op.id}/rollback",
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] in ("FORBIDDEN", "EDITOR_WINDOW_EXPIRED")
```

Run: `unset VIRTUAL_ENV; .venv/bin/pytest tests/api/test_bulk_editor_window.py -v`.

If it fails (because `bulk.py:171` previously compared naive `datetime.now()` against TZ-aware `created_at` and the boundary was always wrong), the fix in Step 2 should make it pass.

- [ ] **Step 6: Commit**

```bash
git add app/auth.py app/api/v1/admin/ tests/api/test_bulk_editor_window.py
git commit -m "fix: use UTC-aware datetimes everywhere"
```

---

### Task 1.3: BackgroundTasks for `_update_last_used`

**Files:**
- Modify: `app/auth.py`

- [ ] **Step 1: Read current `get_current_user`**

```bash
sed -n '20,70p' app/auth.py
```

- [ ] **Step 2: Refactor**

Replace the orphan `asyncio.create_task(_update_last_used(api_key.id))` call with FastAPI's `BackgroundTasks` injection:

```python
from fastapi import BackgroundTasks, Depends, Header, HTTPException
# ... existing imports ...
from app.time import now


async def _update_last_used(api_key_id: uuid.UUID) -> None:
    """Best-effort timestamp update — runs after response."""
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                update(ApiKey).where(ApiKey.id == api_key_id).values(last_used_at=now())
            )
            await session.commit()
        except SQLAlchemyError as exc:
            log.warning("Failed to update last_used_at for key %s: %s", api_key_id, exc)


async def get_current_user(
    background: BackgroundTasks,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    # ... existing key-matching logic ...
    background.add_task(_update_last_used, api_key.id)
    return user
```

`SQLAlchemyError` import: `from sqlalchemy.exc import SQLAlchemyError`.

- [ ] **Step 3: Run auth tests**

```bash
unset VIRTUAL_ENV; .venv/bin/pytest tests/api/test_auth.py -v
```
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add app/auth.py
git commit -m "refactor(auth): use BackgroundTasks for last_used_at update"
```

---

### Task 1.4: Cap `q` length on public address search

**Files:**
- Modify: `app/api/v1/public/addresses.py`

- [ ] **Step 1: Regression test**

Append to `tests/api/test_public_addresses.py`:

```python
@pytest.mark.integration
async def test_public_search_rejects_huge_q(client):
    huge = "x" * 1001
    resp = await client.get("/api/v1/public/addresses/search", params={"q": huge})
    assert resp.status_code == 422
```

Run: `unset VIRTUAL_ENV; .venv/bin/pytest tests/api/test_public_addresses.py::test_public_search_rejects_huge_q -v`.
Expected: FAIL.

- [ ] **Step 2: Implement**

In `app/api/v1/public/addresses.py`, update the `q` Query annotation on the search endpoint:

```python
from typing import Annotated
from fastapi import Query

async def search_addresses(
    ...,
    q: Annotated[str, Query(min_length=2, max_length=100, description="Address search query")],
):
    ...
```

- [ ] **Step 3: Run, expect pass**

```bash
unset VIRTUAL_ENV; .venv/bin/pytest tests/api/test_public_addresses.py -v
```

- [ ] **Step 4: Commit**

```bash
git add app/api/v1/public/addresses.py tests/api/test_public_addresses.py
git commit -m "fix(public): cap q parameter at 100 chars"
```

---

### Task 1.5: Polygon size limit on `/map/in-polygon`

**Files:**
- Modify: `app/api/v1/admin/map.py`
- Modify: `app/schemas/admin.py` (or `app/schemas/map.py` — check where the in-polygon request schema lives)

- [ ] **Step 1: Locate the request schema**

```bash
grep -n "in_polygon\|in-polygon\|InPolygon" app/schemas/*.py app/api/v1/admin/map.py
```

- [ ] **Step 2: Add a max-byte validator**

In the schema for the in-polygon request, change:

```python
class InPolygonRequest(BaseModel):
    polygon_geojson: dict
    ...
```

to:

```python
from pydantic import BaseModel, model_validator
import json

_MAX_POLYGON_BYTES = 256 * 1024  # 256 KB


class InPolygonRequest(BaseModel):
    polygon_geojson: dict
    # ... other fields ...

    @model_validator(mode="after")
    def _check_polygon_size(self):
        serialized = json.dumps(self.polygon_geojson)
        if len(serialized) > _MAX_POLYGON_BYTES:
            raise ValueError(f"polygon_geojson exceeds {_MAX_POLYGON_BYTES} bytes")
        return self
```

- [ ] **Step 3: Regression test**

Create `tests/api/test_map_in_polygon.py`:

```python
import pytest


@pytest.mark.integration
async def test_in_polygon_rejects_huge_polygon(client, admin_user):
    _, raw = admin_user
    coords = [[i * 0.0001, i * 0.0001] for i in range(60000)]
    payload = {"polygon_geojson": {"type": "Polygon", "coordinates": [coords]}}
    resp = await client.post(
        "/api/v1/admin/map/in-polygon",
        json=payload,
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 422
```

Run: `unset VIRTUAL_ENV; .venv/bin/pytest tests/api/test_map_in_polygon.py -v`.

- [ ] **Step 4: Commit**

```bash
git add app/api/v1/admin/map.py app/schemas/ tests/api/test_map_in_polygon.py
git commit -m "fix(map): cap polygon_geojson payload at 256 KB"
```

---

### Task 1.6: Rate limit on `/bulk/preview`

**Files:**
- Modify: `app/api/v1/admin/bulk.py`

- [ ] **Step 1: Find current limiter usage**

```bash
grep -n "@limiter.limit\|@router.post\|bulk_preview" app/api/v1/admin/bulk.py
```

- [ ] **Step 2: Add limit decorator**

Above the `bulk_preview` route handler, add the same decorator already used on `bulk_execute`:

```python
@router.post("/bulk/preview", response_model=BulkPreviewResponse)
@limiter.limit("30/minute")
async def bulk_preview(request: Request, ...):
    ...
```

Note: slowapi's `@limiter.limit` requires the `request: Request` parameter to be present in the handler signature. Add it if not there.

- [ ] **Step 3: Regression test**

`tests/api/test_bulk_rate_limit.py`:

```python
import pytest


@pytest.mark.integration
async def test_bulk_preview_rate_limited(client, editor_user):
    _, raw = editor_user
    payload = {
        "operation": {"type": "add_offering", "technology_id": "00000000-0000-0000-0000-000000000000",
                      "status": "available", "max_download_mbps": 100, "max_upload_mbps": 50,
                      "status_since": "2026-01-01"},
        "filter": {"locality_code": 1},
    }
    # Burst 31 calls within the same minute window
    statuses = []
    for _ in range(31):
        r = await client.post("/api/v1/admin/bulk/preview", json=payload, headers={"X-API-Key": raw})
        statuses.append(r.status_code)
    assert 429 in statuses
```

Run: `unset VIRTUAL_ENV; .venv/bin/pytest tests/api/test_bulk_rate_limit.py -v`.

- [ ] **Step 4: Commit**

```bash
git add app/api/v1/admin/bulk.py tests/api/test_bulk_rate_limit.py
git commit -m "fix(bulk): apply rate limit to /bulk/preview"
```

---

### Task 1.7: Audit query index hint + safer SQL

**Files:**
- Modify: `app/api/v1/admin/audit.py`

This task is split into 2.x because it also touches the schema. For now, just add an inline comment + a regression timing test; the actual index migration is Task 2.2.

- [ ] **Step 1: Comment the slow path**

In `app/api/v1/admin/audit.py:94` (or wherever the `(al.diff->>'address_code')::bigint` filter lives), add above the SQL:

```python
# NOTE: This predicate is a full-scan of audit_log because there is no
# functional index on (diff->>'address_code'). See migration in Task 2.2
# (`alembic ... idx_audit_log_address_code`).
```

- [ ] **Step 2: Commit**

```bash
git add app/api/v1/admin/audit.py
git commit -m "docs(audit): flag slow predicate pending index migration"
```

---

### Task 1.8: Sanitize X-Request-ID middleware input

**Files:**
- Modify: `app/middleware.py`

- [ ] **Step 1: Read current code**

```bash
sed -n '1,40p' app/middleware.py
```

- [ ] **Step 2: Implement validator**

Replace the `X-Request-ID` extraction with a validator that accepts only `[A-Za-z0-9_-]{1,64}`. If invalid, generate a fresh UUID instead.

```python
import re
import uuid

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _get_or_make_request_id(headers) -> str:
    incoming = headers.get("x-request-id")
    if incoming and _REQUEST_ID_RE.match(incoming):
        return incoming
    return str(uuid.uuid4())
```

Update the middleware to use this helper.

- [ ] **Step 3: Regression test**

Add to `tests/api/test_middleware.py` (create if missing):

```python
import pytest


@pytest.mark.integration
async def test_invalid_request_id_replaced(client):
    resp = await client.get("/health", headers={"X-Request-ID": "bogus\r\nset-cookie: evil"})
    assert "set-cookie" not in resp.headers.get("x-request-id", "")
```

- [ ] **Step 4: Commit**

```bash
git add app/middleware.py tests/api/test_middleware.py
git commit -m "fix(middleware): sanitize X-Request-ID header"
```

---

### Task 1.9: Harden `_paginated` against SQL injection

**Files:**
- Modify: `app/api/v1/admin/hierarchy.py`

- [ ] **Step 1: Assert allow-listed table names**

Replace `_paginated` to take a `_AllowedTable` literal:

```python
from typing import Literal

_TABLE_COLUMNS: dict[str, str] = {
    "counties": "rc_code, name",
    "municipalities": "rc_code, county_code, name, type",
    "localities": "rc_code, muni_code, name, type, type_abbr",
    "streets": "rc_code, locality_code, name, full_name",
}


async def _paginated(
    db: AsyncSession,
    table: Literal["counties", "municipalities", "localities", "streets"],
    where: str,
    order_by: Literal["name", "rc_code"],
    params: dict,
    page: PaginationParams,
) -> tuple[int, list[dict]]:
    if table not in _TABLE_COLUMNS:
        raise ValueError(f"unknown table: {table}")
    columns = _TABLE_COLUMNS[table]
    ...
```

Update callers to pass only the literal table name (not a free string) and remove the `columns` parameter.

- [ ] **Step 2: Run tests**

```bash
unset VIRTUAL_ENV; .venv/bin/pytest tests/api/ -q
```
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/hierarchy.py
git commit -m "fix(hierarchy): allow-list tables passed to _paginated"
```

---

### Task 1.10: Audit query length caps

**Files:**
- Modify: `app/api/v1/admin/audit.py`

- [ ] **Step 1: Tighten query types**

Update each `Query(None)` to add `max_length`:

```python
entity_type: Annotated[str | None, Query(None, max_length=64)] = None,
entity_id: Annotated[str | None, Query(None, max_length=128)] = None,
```

Also add a `since < until` validator. Since these are query params, do it inside the handler:

```python
if since and until and since >= until:
    raise_error(422, "VALIDATION_ERROR", "`since` must be before `until`")
```

- [ ] **Step 2: Regression test**

```python
@pytest.mark.integration
async def test_audit_log_rejects_since_after_until(client, admin_user):
    _, raw = admin_user
    resp = await client.get(
        "/api/v1/admin/audit-log",
        params={"since": "2026-05-22T10:00:00Z", "until": "2026-05-22T09:00:00Z"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 422
```

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/audit.py tests/api/test_audit.py
git commit -m "fix(audit): cap query lengths + validate since<until"
```

---

## Phase 2 — Database migrations

> All migrations use Alembic. `docker compose up -d db` must be running. Migration files go in `alembic/versions/`. Always test downgrade locally before merging.

### Task 2.1: ApiKey.key_prefix column + index

**Files:**
- Create: `alembic/versions/<auto>_apikey_key_prefix.py`
- Modify: `app/models/admin.py` (ApiKey model)

- [ ] **Step 1: Generate revision skeleton**

```bash
unset VIRTUAL_ENV; .venv/bin/alembic revision -m "add api_keys.key_prefix + index"
```

Open the generated file in `alembic/versions/`.

- [ ] **Step 2: Write upgrade/downgrade**

```python
def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("key_prefix", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "ix_api_keys_key_prefix",
        "api_keys",
        ["key_prefix"],
        unique=False,
    )
    op.create_index(
        "ix_api_keys_active",
        "api_keys",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_api_keys_active", table_name="api_keys")
    op.drop_index("ix_api_keys_key_prefix", table_name="api_keys")
    op.drop_column("api_keys", "key_prefix")
```

- [ ] **Step 3: Add `key_prefix` field to ORM model**

In `app/models/admin.py`, `ApiKey` class — add:

```python
key_prefix: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
```

- [ ] **Step 4: Apply migration**

```bash
unset VIRTUAL_ENV; .venv/bin/alembic upgrade head
```

- [ ] **Step 5: Verify**

```bash
docker compose exec db psql -U etanetas -d etanetas_addresses_coverage -c "\d api_keys"
```

Expected: column `key_prefix` and indexes `ix_api_keys_key_prefix`, `ix_api_keys_active`.

- [ ] **Step 6: Test downgrade then upgrade**

```bash
unset VIRTUAL_ENV; .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
```

- [ ] **Step 7: Commit**

```bash
git add alembic/versions/ app/models/admin.py
git commit -m "feat(db): add api_keys.key_prefix column + indexes"
```

---

### Task 2.2: AuditLog denormalized `address_code` + index

**Files:**
- Create: `alembic/versions/<auto>_audit_log_address_code.py`
- Modify: `app/models/admin.py` (AuditLog model)
- Modify: `app/audit.py` (`log_action` callers fill `address_code` when known)

- [ ] **Step 1: Generate revision**

```bash
unset VIRTUAL_ENV; .venv/bin/alembic revision -m "add audit_log.address_code + index"
```

- [ ] **Step 2: Write migration**

```python
def upgrade() -> None:
    op.add_column("audit_log", sa.Column("address_code", sa.BigInteger(), nullable=True))
    op.create_index(
        "ix_audit_log_address_code",
        "audit_log",
        ["address_code"],
        postgresql_where=sa.text("address_code IS NOT NULL"),
    )
    # Backfill from existing diff JSON
    op.execute("""
        UPDATE audit_log
        SET address_code = (diff->>'address_code')::bigint
        WHERE entity_type = 'address_offering'
          AND (diff->>'address_code') ~ '^[0-9]+$'
    """)


def downgrade() -> None:
    op.drop_index("ix_audit_log_address_code", table_name="audit_log")
    op.drop_column("audit_log", "address_code")
```

- [ ] **Step 3: Update ORM model**

In `app/models/admin.py`, `AuditLog`:

```python
address_code: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
```

- [ ] **Step 4: Update `log_action` to populate**

In `app/audit.py`, extend the function signature with `address_code: int | None = None` and set it on the row. Update every call site in `app/api/v1/admin/{addresses.py, bulk.py}` to pass `address_code=...` when the entity has one.

- [ ] **Step 5: Update `get_address_history` SQL**

In `app/api/v1/admin/audit.py`, change the predicate from `(al.diff->>'address_code')::bigint = :rc_code` to `al.address_code = :rc_code`.

- [ ] **Step 6: Apply migration + tests**

```bash
unset VIRTUAL_ENV; .venv/bin/alembic upgrade head
.venv/bin/pytest tests/api/test_audit.py -v
```

- [ ] **Step 7: Commit**

```bash
git add alembic/versions/ app/audit.py app/models/admin.py app/api/v1/admin/
git commit -m "feat(audit): denormalize address_code with backfill + index"
```

---

### Task 2.3: Soft-delete + FK cascade on ServiceZone

**Files:**
- Create: `alembic/versions/<auto>_zone_soft_delete.py`
- Modify: `app/models/service.py`
- Modify: `app/api/v1/admin/zones.py` (delete handler)

- [ ] **Step 1: Generate revision**

```bash
unset VIRTUAL_ENV; .venv/bin/alembic revision -m "add service_zones.deleted_at + cascade zone_offerings"
```

- [ ] **Step 2: Write migration**

```python
def upgrade() -> None:
    op.add_column("service_zones", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_service_zones_alive",
        "service_zones",
        ["id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # Ensure ON DELETE CASCADE on zone_offerings.zone_id
    op.drop_constraint("zone_offerings_zone_id_fkey", "zone_offerings", type_="foreignkey")
    op.create_foreign_key(
        "zone_offerings_zone_id_fkey",
        "zone_offerings", "service_zones",
        ["zone_id"], ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("zone_offerings_zone_id_fkey", "zone_offerings", type_="foreignkey")
    op.create_foreign_key(
        "zone_offerings_zone_id_fkey",
        "zone_offerings", "service_zones",
        ["zone_id"], ["id"],
    )
    op.drop_index("ix_service_zones_alive", table_name="service_zones")
    op.drop_column("service_zones", "deleted_at")
```

- [ ] **Step 3: Update `ServiceZone` ORM and `delete_zone` handler**

Add `deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)` in `app/models/service.py`.

In `app/api/v1/admin/zones.py`:

```python
@router.delete("/{zone_id}", status_code=204)
async def delete_zone(...):
    zone = await _require_zone(db, zone_id)
    zone.deleted_at = now()
    await log_action(db, current_user.id, "service_zone", str(zone_id), "delete", {"name": zone.name})
    await db.commit()
```

Also update `list_zones` / `_require_zone` / `get_zone_detail` queries to filter `deleted_at IS NULL`.

- [ ] **Step 4: Regression test**

```python
@pytest.mark.integration
async def test_delete_zone_soft_then_list_excludes_it(client, admin_user, seed_zone):
    _, raw = admin_user
    zone_id, _ = seed_zone
    await client.delete(f"/api/v1/admin/zones/{zone_id}", headers={"X-API-Key": raw})
    resp = await client.get("/api/v1/admin/zones", headers={"X-API-Key": raw})
    assert resp.status_code == 200
    assert not any(z["id"] == str(zone_id) for z in resp.json()["items"])
```

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/ app/models/service.py app/api/v1/admin/zones.py tests/api/test_admin_crud.py
git commit -m "feat(zones): soft-delete + FK cascade on zone_offerings"
```

---

### Task 2.4: Technologies — unify on soft-delete via `deleted_at`

**Files:**
- Create: `alembic/versions/<auto>_technologies_deleted_at.py`
- Modify: `app/models/technology.py`
- Modify: `app/api/v1/admin/technologies.py`

- [ ] **Step 1: Generate revision**

```bash
unset VIRTUAL_ENV; .venv/bin/alembic revision -m "add technologies.deleted_at; replace active"
```

- [ ] **Step 2: Migration**

```python
def upgrade() -> None:
    op.add_column("technologies", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE technologies SET deleted_at = NOW() WHERE active = false")
    op.drop_column("technologies", "active")


def downgrade() -> None:
    op.add_column("technologies", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.execute("UPDATE technologies SET active = false WHERE deleted_at IS NOT NULL")
    op.drop_column("technologies", "deleted_at")
```

- [ ] **Step 3: Update ORM + handlers**

Replace `active` with `deleted_at` everywhere in `app/models/technology.py`, `app/schemas/admin.py` (`TechnologyOut`), `app/api/v1/admin/technologies.py` (delete sets `deleted_at = now()`).

Update tests in `tests/api/test_admin_crud.py:286-289`:

```python
list_resp = await client.get("/api/v1/admin/technologies", headers={"X-API-Key": raw})
techs = [t for t in list_resp.json()["items"] if t["id"] == str(tech.id)]
assert techs == []  # excluded by deleted_at filter
```

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/ app/models/technology.py app/schemas/admin.py app/api/v1/admin/technologies.py tests/
git commit -m "refactor(tech): unify on deleted_at soft-delete"
```

---

## Phase 3 — Auth O(1) lookup

### Task 3.1: Use `key_prefix` for direct lookup

**Files:**
- Modify: `app/auth.py`
- Modify: `app/api/v1/admin/users.py` (`create_api_key` — store prefix)
- Modify: `app/cli.py` (if `create-key` / `create-admin` exist there — same change)

- [ ] **Step 1: Write the test**

`tests/api/test_auth_perf.py`:

```python
import pytest


@pytest.mark.integration
async def test_key_lookup_uses_prefix(client, admin_user, db_session):
    """If key_prefix points to a single row, validation is O(1) not O(N)."""
    from app.models.admin import ApiKey
    from sqlalchemy import select

    user, raw = admin_user
    prefix = raw[:11]  # "etn_pk_XXXX" ~ 11 chars
    rows = (await db_session.execute(
        select(ApiKey).where(ApiKey.key_prefix == prefix)
    )).scalars().all()
    # The key created for the fixture should already have the prefix populated
    assert len(rows) == 1
    assert rows[0].user_id == user.id

    # And the endpoint still authenticates
    resp = await client.get("/api/v1/admin/me", headers={"X-API-Key": raw})
    assert resp.status_code == 200
```

- [ ] **Step 2: Update `create_api_key`**

In `app/api/v1/admin/users.py:148`, after generating the raw key:

```python
raw_key = "etn_pk_" + secrets.token_urlsafe(32)
key_prefix = raw_key[:11]  # "etn_pk_" + first 4 chars
key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode()
api_key = ApiKey(user_id=user_id, key_hash=key_hash, key_prefix=key_prefix, name=body.name)
```

Same change in `app/cli.py` if a `create-admin` / `create-key` command creates ApiKey rows directly.

- [ ] **Step 3: Backfill existing rows** (one-time data migration)

Create `alembic/versions/<auto>_backfill_key_prefix.py`:

```python
def upgrade() -> None:
    # key_hash is a bcrypt string — we can't recover the raw key.
    # Mark legacy rows with a sentinel so the auth path falls back to O(N) bcrypt
    # scan ONLY for those. New rows always have the real prefix.
    op.execute("UPDATE api_keys SET key_prefix = '__legacy__' WHERE key_prefix IS NULL")
```

- [ ] **Step 4: Update `get_current_user`**

```python
async def get_current_user(...):
    if not x_api_key or not x_api_key.startswith("etn_pk_"):
        raise_error(401, "UNAUTHORIZED", "Invalid or missing API key")

    prefix = x_api_key[:11]
    # Fast path: candidate keys whose prefix matches
    candidates = (await db.execute(
        select(ApiKey, User)
        .join(User, ApiKey.user_id == User.id)
        .where(
            ApiKey.key_prefix == prefix,
            ApiKey.revoked_at.is_(None),
            User.active.is_(True),
        )
    )).all()
    if not candidates:
        # Legacy fallback (shrinking set marked `__legacy__`)
        candidates = (await db.execute(
            select(ApiKey, User)
            .join(User, ApiKey.user_id == User.id)
            .where(
                ApiKey.key_prefix == "__legacy__",
                ApiKey.revoked_at.is_(None),
                User.active.is_(True),
            )
        )).all()

    for api_key, user in candidates:
        if api_key.expires_at and api_key.expires_at < now():
            continue
        if bcrypt.checkpw(x_api_key.encode(), api_key.key_hash.encode()):
            # Opportunistic prefix migration for legacy rows
            if api_key.key_prefix == "__legacy__":
                background.add_task(_set_prefix, api_key.id, prefix)
            background.add_task(_update_last_used, api_key.id)
            return user

    raise_error(401, "UNAUTHORIZED", "Invalid or missing API key")
```

Add `_set_prefix`:

```python
async def _set_prefix(api_key_id: uuid.UUID, prefix: str) -> None:
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                update(ApiKey).where(ApiKey.id == api_key_id).values(key_prefix=prefix)
            )
            await session.commit()
        except SQLAlchemyError as exc:
            log.warning("Failed to backfill prefix for key %s: %s", api_key_id, exc)
```

- [ ] **Step 5: Run tests**

```bash
unset VIRTUAL_ENV; .venv/bin/pytest tests/api/test_auth.py tests/api/test_auth_perf.py -v
```

- [ ] **Step 6: Commit**

```bash
git add app/auth.py app/api/v1/admin/users.py app/cli.py alembic/versions/ tests/api/test_auth_perf.py
git commit -m "perf(auth): prefix-based O(1) key lookup"
```

---

## Phase 4 — Audit log gaps

### Task 4.1: Audit `create_api_key` + `revoke_api_key`

**Files:**
- Modify: `app/api/v1/admin/users.py`

- [ ] **Step 1: Regression test**

`tests/api/test_audit_keys.py`:

```python
import pytest
from sqlalchemy import text


@pytest.mark.integration
async def test_api_key_create_is_audited(client, admin, db_session):
    _, raw = admin
    from app.models.admin import User
    target = User(username="auditme", email="auditme@example.com", role="viewer", active=True)
    db_session.add(target)
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/admin/users/{target.id}/api-keys",
        json={"name": "test"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 201

    rows = (await db_session.execute(
        text("SELECT action FROM audit_log WHERE entity_type='api_key' ORDER BY at DESC LIMIT 5")
    )).all()
    assert any(r[0] == "create" for r in rows)


@pytest.mark.integration
async def test_api_key_revoke_is_audited(client, admin, db_session):
    _, raw = admin
    from app.models.admin import User
    target = User(username="rev", email="rev@example.com", role="viewer", active=True)
    db_session.add(target)
    await db_session.flush()

    create_resp = await client.post(
        f"/api/v1/admin/users/{target.id}/api-keys",
        json={"name": "tok"},
        headers={"X-API-Key": raw},
    )
    key_id = create_resp.json()["id"]
    await client.delete(f"/api/v1/admin/api-keys/{key_id}", headers={"X-API-Key": raw})

    rows = (await db_session.execute(
        text("SELECT action FROM audit_log WHERE entity_type='api_key' AND entity_id=:id"),
        {"id": str(key_id)},
    )).all()
    assert any(r[0] == "revoke" for r in rows)
```

- [ ] **Step 2: Implement**

In `create_api_key`:

```python
await log_action(db, current_user.id, "api_key", str(api_key.id), "create",
                 {"user_id": str(user_id), "name": body.name})
```

In `revoke_api_key`:

```python
await log_action(db, current_user.id, "api_key", str(key_id), "revoke",
                 {"user_id": str(key.user_id), "name": key.name})
```

Place the log call before `await db.commit()`.

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/users.py tests/api/test_audit_keys.py
git commit -m "fix(audit): log API key create + revoke"
```

---

## Phase 5 — PUT → PATCH (breaking, no deprecation)

### Task 5.1: Address offerings — PUT → PATCH

**Files:**
- Modify: `app/api/v1/admin/addresses.py:289`
- Modify: `tests/api/test_admin_crud.py` (every `.put` against `/offerings/{id}`)

- [ ] **Step 1: Replace decorator**

Change `@router.put("/offerings/{offering_id}", ...)` to `@router.patch(...)` on `update_address_offering`.

- [ ] **Step 2: Update tests**

Replace each call:

```bash
grep -n "admin/addresses/offerings.*put\|client.put.*addresses/offerings" tests/api/test_admin_crud.py
```

For each match, change `client.put(...)` to `client.patch(...)`.

- [ ] **Step 3: Run**

```bash
unset VIRTUAL_ENV; .venv/bin/pytest tests/api/test_admin_crud.py -k offering -v
```

- [ ] **Step 4: Commit**

```bash
git add app/api/v1/admin/addresses.py tests/api/test_admin_crud.py
git commit -m "refactor(addresses): PUT -> PATCH on address offering update"
```

---

### Task 5.2: Zone offerings — PUT → PATCH

**Files:**
- Modify: `app/api/v1/admin/zones.py:257` (and `update_zone` at ~151)
- Modify: tests

- [ ] **Step 1: Replace decorators**

Change `@router.put("/offerings/{offering_id}", ...)` → `@router.patch(...)` on `update_zone_offering`. Same on `update_zone`.

- [ ] **Step 2: Update tests**

Replace every `.put(f"/api/v1/admin/zones/{...}", ...)` with `.patch(...)` in `tests/api/test_admin_crud.py`.

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/zones.py tests/api/test_admin_crud.py
git commit -m "refactor(zones): PUT -> PATCH on zone + zone offering update"
```

---

### Task 5.3: Technologies + technology types — PUT → PATCH

**Files:**
- Modify: `app/api/v1/admin/technologies.py:46, 112`
- Modify: tests

- [ ] **Step 1: Replace decorators** on `update_technology` and `update_technology_type`.

- [ ] **Step 2: Update tests** (replace `.put` with `.patch`).

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/technologies.py tests/api/test_admin_crud.py
git commit -m "refactor(tech): PUT -> PATCH on technology updates"
```

---

### Task 5.4: Users — PUT → PATCH

**Files:**
- Modify: `app/api/v1/admin/users.py:79`
- Modify: tests

- [ ] **Step 1: Replace decorator** on `update_user`.

- [ ] **Step 2: Update tests in `tests/api/test_admin_users.py`** (`.put` → `.patch`).

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/users.py tests/api/test_admin_users.py
git commit -m "refactor(users): PUT -> PATCH on user update"
```

---

## Phase 6 — Status codes + RBAC

### Task 6.1: Fix 400 → 409 on self-deactivation

**Files:**
- Modify: `app/api/v1/admin/users.py:108-109`
- Modify: `tests/api/test_admin_users.py:127-130`

- [ ] **Step 1: Change status + envelope**

```python
if user_id == current_user.id:
    raise_error(409, "SELF_DEACTIVATE_FORBIDDEN", "Cannot deactivate your own account")
```

(Import `raise_error` from `app.errors`.)

- [ ] **Step 2: Update test**

```python
assert resp.status_code == 409
assert resp.json()["error"]["code"] == "SELF_DEACTIVATE_FORBIDDEN"
```

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/users.py tests/api/test_admin_users.py
git commit -m "fix(users): self-deactivate returns 409"
```

---

### Task 6.2: Restrict `/users/by-lms-username/{lms}` to admin role

**Files:**
- Modify: `app/api/v1/admin/users.py:193`

- [ ] **Step 1: Tighten dependency**

Change `get_current_user` to `require_role("admin")` on `get_user_by_lms_username`.

- [ ] **Step 2: Regression test**

`tests/api/test_admin_users.py`:

```python
@pytest.mark.integration
async def test_lms_lookup_forbidden_for_viewer(client, viewer, db_session):
    from app.models.admin import User
    target = User(username="lms-target", email="lms@example.com", role="viewer",
                  active=True, lms_username="lms-target")
    db_session.add(target)
    await db_session.flush()
    _, raw = viewer
    resp = await client.get(f"/api/v1/admin/users/by-lms-username/lms-target",
                            headers={"X-API-Key": raw})
    assert resp.status_code == 403
```

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/users.py tests/api/test_admin_users.py
git commit -m "fix(users): require admin role for LMS lookup"
```

---

### Task 6.3: Stats — 503 not 500 for unconfigured area

**Files:**
- Modify: `app/api/v1/admin/stats.py:51`

- [ ] **Step 1: Replace `HTTPException(500, ...)` with `raise_error(503, "SERVICE_UNAVAILABLE", "Operational area not configured")`.**

- [ ] **Step 2: Regression test** (mock operational_area missing → 503).

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/stats.py tests/
git commit -m "fix(stats): 503 when operational area not configured"
```

---

### Task 6.4: Editor vs admin on delete address offering

**Files:**
- Modify: `app/api/v1/admin/addresses.py:316`

This is a business decision. After confirmation with the user, either:

- **Keep editor**: no code change; document explicitly in the route summary (Task 10.x).
- **Tighten to admin**: change `require_role("editor", "admin")` → `require_role("admin")`.

Pick the option that matches the user's instruction. If unclear, keep editor and add a route `summary="Delete offering — editor+ allowed for fast UI correction"`.

- [ ] **Step 1: Apply the chosen change.**

- [ ] **Step 2: Update / add test asserting the chosen role's access.**

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/addresses.py tests/
git commit -m "docs(addresses): clarify delete offering RBAC"
```

---

## Phase 7 — Validation hardening

### Task 7.1: Map endpoint Query bounds

**Files:**
- Modify: `app/api/v1/admin/map.py:40-48`, lines around `in-polygon` `limit`

- [ ] **Step 1: Replace manual clamping with Query bounds**

```python
limit: Annotated[int, Query(ge=1, le=5000)] = 3000
```

Remove the `min(max(limit, 1), 5000)` lines.

- [ ] **Step 2: Test 422 on out-of-range**

```python
@pytest.mark.integration
async def test_map_addresses_limit_cap(client, admin_user):
    _, raw = admin_user
    resp = await client.get("/api/v1/admin/map/addresses",
                            params={"bbox": "25.0,54.0,26.0,55.0", "limit": 5001},
                            headers={"X-API-Key": raw})
    assert resp.status_code == 422
```

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/map.py tests/
git commit -m "fix(map): use Query bounds for limit"
```

---

### Task 7.2: Bulk filter — require locality or rc_codes

**Files:**
- Modify: `app/schemas/admin.py` (`BulkFilter`)
- Modify: tests

- [ ] **Step 1: Add validator**

```python
class BulkFilter(BaseModel):
    rc_codes: list[int] | None = None
    locality_code: int | None = None
    street_codes: list[int] | None = None
    house_no_pattern: str | None = None
    # ... existing fields ...

    @model_validator(mode="after")
    def _require_scope(self):
        if not self.rc_codes and self.locality_code is None:
            raise ValueError(
                "Either rc_codes or locality_code is required (prevents nation-wide updates)"
            )
        return self
```

- [ ] **Step 2: Update existing tests**

Any bulk test calling preview/execute with only `house_no_pattern` and no locality must be updated to set `locality_code` too.

- [ ] **Step 3: Regression test**

```python
@pytest.mark.integration
async def test_bulk_preview_rejects_unscoped(client, editor_user, tech):
    _, raw = editor_user
    resp = await client.post(
        "/api/v1/admin/bulk/preview",
        json={"operation": _op(tech.id), "filter": {"house_no_pattern": "%1%"}},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 422
```

- [ ] **Step 4: Commit**

```bash
git add app/schemas/admin.py tests/api/test_bulk.py
git commit -m "fix(bulk): require locality_code or rc_codes in filter"
```

---

### Task 7.3: Bulk — fail loudly when match count exceeds 10000

**Files:**
- Modify: `app/api/v1/admin/bulk.py:300` (`_filter_addresses`)

- [ ] **Step 1: Change semantics**

Currently `_filter_addresses` does `LIMIT 10000` silently. Replace with a `COUNT(*)` pre-check:

```python
_MAX_BULK_AFFECTED = 10000


async def _filter_addresses(db: AsyncSession, f: BulkFilter) -> list[int]:
    where, params = ...  # existing logic returning where_sql + params
    count = int((await db.execute(text(f"SELECT COUNT(*) FROM addresses a WHERE {where}"), params)).scalar() or 0)
    if count > _MAX_BULK_AFFECTED:
        raise_error(
            422,
            "BULK_LIMIT_EXCEEDED",
            f"Filter matches {count} addresses (max {_MAX_BULK_AFFECTED}). Narrow your filter."
        )
    rows = await db.execute(text(f"SELECT a.rc_code FROM addresses a WHERE {where}"), params)
    return [r[0] for r in rows.all()]
```

- [ ] **Step 2: Regression test**

```python
@pytest.mark.integration
async def test_bulk_preview_rejects_over_cap(client, editor_user, db_session, tech):
    """Seed >10000 addresses in one locality and confirm 422."""
    # Test infra-heavy; if seeding 10k is too slow in CI, instead monkeypatch _MAX_BULK_AFFECTED to 5.
    from app.api.v1.admin import bulk as bulk_mod
    monkeypatch_value = 5
    bulk_mod._MAX_BULK_AFFECTED = monkeypatch_value
    try:
        _, raw = editor_user
        resp = await client.post(
            "/api/v1/admin/bulk/preview",
            json={"operation": _op(tech.id), "filter": {"locality_code": 82100}},  # >5 known
            headers={"X-API-Key": raw},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "BULK_LIMIT_EXCEEDED"
    finally:
        bulk_mod._MAX_BULK_AFFECTED = 10000
```

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/bulk.py tests/api/test_bulk.py
git commit -m "fix(bulk): explicit error when filter matches >10k addresses"
```

---

### Task 7.4: Polygon Pydantic schema

**Files:**
- Modify: `app/schemas/admin.py:170, 178`

- [ ] **Step 1: Define typed polygon**

```python
from typing import Literal

class PolygonGeoJSON(BaseModel):
    type: Literal["Polygon", "MultiPolygon"]
    coordinates: list  # nested list — stays loose
```

Replace `polygon_geojson: dict | None` with `polygon_geojson: PolygonGeoJSON | None` in `ZoneCreate`, `ZoneUpdate`.

- [ ] **Step 2: Update zone handlers**

In `app/api/v1/admin/zones.py`, when serializing the polygon to SQL, use `body.polygon_geojson.model_dump()` (Pydantic) instead of treating it as `dict`.

- [ ] **Step 3: Run zone tests**

```bash
unset VIRTUAL_ENV; .venv/bin/pytest tests/api/test_admin_crud.py -k zone -v
```

- [ ] **Step 4: Commit**

```bash
git add app/schemas/admin.py app/api/v1/admin/zones.py
git commit -m "feat(zones): typed PolygonGeoJSON schema"
```

---

### Task 7.5: Zone polygon `unset` sentinel

**Files:**
- Modify: `app/api/v1/admin/zones.py` (`update_zone`)

- [ ] **Step 1: Use `model_fields_set` for tri-state**

```python
@router.patch("/{zone_id}", response_model=ZoneOut)
async def update_zone(zone_id, body: ZoneUpdate, ...):
    zone = await _require_zone(db, zone_id)
    fields = body.model_fields_set

    if "name" in fields and body.name is not None:
        zone.name = body.name
    if "description" in fields:
        zone.description = body.description
    if "priority" in fields and body.priority is not None:
        zone.priority = body.priority

    if "polygon_geojson" in fields:
        # explicitly provided — clear if None, otherwise set
        if body.polygon_geojson is None:
            await db.execute(text("UPDATE service_zones SET polygon = NULL WHERE id = :id"),
                             {"id": str(zone_id)})
        else:
            await db.execute(
                text("UPDATE service_zones SET polygon = ST_SetSRID(ST_GeomFromGeoJSON(:gj), 4326) WHERE id = :id"),
                {"gj": body.polygon_geojson.model_dump_json(), "id": str(zone_id)},
            )
    # ...
```

- [ ] **Step 2: Test all three cases**

```python
@pytest.mark.integration
async def test_update_zone_polygon_omitted_keeps_existing(client, editor_user, seed_zone_with_polygon):
    ...

@pytest.mark.integration
async def test_update_zone_polygon_null_clears(client, editor_user, seed_zone_with_polygon):
    ...

@pytest.mark.integration
async def test_update_zone_polygon_replace(client, editor_user, seed_zone):
    ...
```

(Implement seed fixture `seed_zone_with_polygon` in the test file.)

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/zones.py tests/api/test_admin_crud.py
git commit -m "fix(zones): tri-state polygon update (omitted/null/replace)"
```

---

## Phase 8 — Soft-delete consistency rollout

Already done in Phase 2 for zones and technologies. Verify across the codebase that every list query filters on `deleted_at IS NULL` and every `_require_*` helper rejects deleted rows.

### Task 8.1: Audit deleted_at usage

**Files (review):**
- `app/api/v1/admin/zones.py` — `list_zones`, `_require_zone`, `get_zone_detail`
- `app/api/v1/admin/technologies.py` — `list_technology_types`, `list_technologies`, `_require_tech`, `_require_type`
- `app/api/v1/admin/addresses.py` — already correct (`a.deleted_at IS NULL`)

- [ ] **Step 1: Audit**

```bash
grep -n "deleted_at" app/api/v1/admin/*.py
```

For each list query, verify `WHERE ... deleted_at IS NULL`. For `_require_*`, verify the same.

- [ ] **Step 2: Add missing filters.** For each gap, add the predicate.

- [ ] **Step 3: Regression test** that a soft-deleted technology/zone is excluded from list and 404 on `_require_*`.

- [ ] **Step 4: Commit**

```bash
git add app/api/v1/admin/
git commit -m "fix: consistent deleted_at filter across list and detail handlers"
```

---

## Phase 9 — Response & header polish

### Task 9.1: `Location` header on every 201

**Files:**
- Modify: `app/api/v1/admin/zones.py` (`create_zone`)
- Modify: `app/api/v1/admin/addresses.py` (`create_address_offering`)
- Modify: `app/api/v1/admin/users.py` (`create_user`, `create_api_key`)
- Modify: `app/api/v1/admin/technologies.py` (`create_technology`)
- Modify: `app/api/v1/admin/zones.py` (`create_zone_offering`)
- Modify: `app/api/v1/admin/bulk.py` (`bulk_execute` — points to a new detail endpoint, see Task 9.3)

- [ ] **Step 1: Add `response: Response` and `created()` helper**

For each create endpoint:

```python
from fastapi import Response
from app.api.responses import created

@router.post("", response_model=ZoneOut, status_code=201)
async def create_zone(body: ZoneCreate, response: Response, ...):
    zone = ServiceZone(...)
    ...
    return created(
        ZoneOut.model_validate(zone),
        location=f"/api/v1/admin/zones/{zone.id}",
        response=response,
    )
```

- [ ] **Step 2: Regression test**

```python
@pytest.mark.integration
async def test_create_zone_sets_location_header(client, editor_user):
    _, raw = editor_user
    resp = await client.post("/api/v1/admin/zones",
                             json={"name": "Loc Zone", "priority": 1},
                             headers={"X-API-Key": raw})
    assert resp.status_code == 201
    assert resp.headers["location"].startswith("/api/v1/admin/zones/")
```

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/ tests/
git commit -m "feat: Location header on all 201 responses"
```

---

### Task 9.2: Bulk preview — include TTL + `Cache-Control: no-store`

**Files:**
- Modify: `app/schemas/admin.py` (`BulkPreviewResponse`)
- Modify: `app/api/v1/admin/bulk.py` (`bulk_preview`)

- [ ] **Step 1: Schema field**

```python
class BulkPreviewResponse(BaseModel):
    preview_token: str | None
    affected_count: int
    expires_at: datetime  # NEW
    sample: list[BulkPreviewSampleItem]
```

- [ ] **Step 2: Populate**

In `bulk_preview`, when creating the token row, also compute `expires_at = now() + timedelta(minutes=10)` (or the value already used as TTL). Return it.

- [ ] **Step 3: Set `Cache-Control: no-store`**

```python
async def bulk_preview(request: Request, response: Response, ...):
    ...
    response.headers["Cache-Control"] = "no-store"
    return BulkPreviewResponse(...)
```

- [ ] **Step 4: Update test**

`tests/api/test_bulk.py` — assert `expires_at` in response and `cache-control` header.

- [ ] **Step 5: Commit**

```bash
git add app/api/v1/admin/bulk.py app/schemas/admin.py tests/api/test_bulk.py
git commit -m "feat(bulk): expose preview expires_at + no-store cache header"
```

---

### Task 9.3: `GET /admin/bulk-operations/{id}` detail endpoint

**Files:**
- Modify: `app/api/v1/admin/bulk.py`
- Modify: `app/schemas/admin.py` (`BulkOperationDetailOut`)

- [ ] **Step 1: Schema**

```python
class BulkOperationDetailOut(BulkOperationOut):
    operation_data: dict  # the stored payload
    rolled_back_count: int | None
```

- [ ] **Step 2: Handler**

```python
@router.get("/bulk-operations/{op_id}", response_model=BulkOperationDetailOut)
async def get_bulk_operation(
    op_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_role("viewer", "editor", "admin"))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = (await db.execute(text("""
        SELECT bo.id, bo.user_id, u.username, bo.operation_type, bo.operation_data,
               bo.affected_count, bo.created_at, bo.rolled_back_at, bo.rolled_back_count
        FROM bulk_operations bo
        LEFT JOIN users u ON u.id = bo.user_id
        WHERE bo.id = :id
    """), {"id": str(op_id)})).mappings().first()
    if row is None:
        raise_error(404, "NOT_FOUND", "Bulk operation not found")
    return BulkOperationDetailOut(**row)
```

(Verify `bulk_operations` table has columns `operation_data` and `rolled_back_count`; if not, that's a separate migration — add to Phase 2 task 2.5 or skip the field.)

- [ ] **Step 3: Update `bulk_execute` to return `Location: /api/v1/admin/bulk-operations/{id}`** using `created()` helper.

- [ ] **Step 4: Regression tests** for the new endpoint (200 and 404).

- [ ] **Step 5: Commit**

```bash
git add app/api/v1/admin/bulk.py app/schemas/admin.py tests/api/test_bulk.py
git commit -m "feat(bulk): add bulk-operation detail endpoint + Location on create"
```

---

### Task 9.4: Bulk rollback returns 200 + body

**Files:**
- Modify: `app/api/v1/admin/bulk.py`

- [ ] **Step 1: Change status + body**

```python
class BulkRollbackResponse(BaseModel):
    rolled_back_count: int


@router.post("/bulk/{op_id}/rollback", response_model=BulkRollbackResponse)
async def bulk_rollback(...):
    ...
    return BulkRollbackResponse(rolled_back_count=affected)
```

- [ ] **Step 2: Update test**

```python
assert rollback_resp.status_code == 200
assert rollback_resp.json()["rolled_back_count"] >= 1
```

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/bulk.py tests/api/test_bulk.py
git commit -m "refactor(bulk): rollback returns 200 with count"
```

---

### Task 9.5: Wrap public search in `{items}` object

**Files:**
- Modify: `app/api/v1/public/addresses.py`
- Modify: tests

- [ ] **Step 1: New schema**

In `app/schemas/public.py` (or wherever public schemas live):

```python
class PublicAddressSearchResponse(BaseModel):
    items: list[PublicAddressOut]
```

- [ ] **Step 2: Handler returns the wrapper**

```python
@router.get("/addresses/search", response_model=PublicAddressSearchResponse)
async def search_addresses(...):
    return PublicAddressSearchResponse(items=[...])
```

- [ ] **Step 3: Update tests** in `tests/api/test_public_addresses.py` to assert `data["items"]`.

- [ ] **Step 4: Commit**

```bash
git add app/api/v1/public/addresses.py app/schemas/ tests/api/test_public_addresses.py
git commit -m "refactor(public): wrap address search in {items}"
```

---

### Task 9.6: Paginate `/admin/addresses/{rc_code}/zone-coverage`

**Files:**
- Modify: `app/api/v1/admin/addresses.py:154`

- [ ] **Step 1: Wrap in `Page[ZoneCoverageItem]`**

```python
@router.get("/{rc_code}/zone-coverage", response_model=Page[ZoneCoverageItem])
async def get_address_zone_coverage(
    rc_code: int,
    ...,
    page: Annotated[PaginationParams, Depends(pagination_params)],
):
    # existing COUNT(...) + paginated SELECT pattern
```

- [ ] **Step 2: Update tests**

Search `tests/` for `zone-coverage` and update `.json()` reads to `.json()["items"]`.

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/addresses.py tests/
git commit -m "fix(addresses): paginate zone-coverage response"
```

---

### Task 9.7: `Cache-Control: no-store` on API key creation

**Files:**
- Modify: `app/api/v1/admin/users.py` (`create_api_key`)

- [ ] **Step 1: Add response header**

Add `response: Response` to the signature and `response.headers["Cache-Control"] = "no-store"` before returning. Same for any other endpoint that returns secrets.

- [ ] **Step 2: Test**

```python
assert resp.headers["cache-control"] == "no-store"
```

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/users.py tests/api/test_admin_users.py
git commit -m "fix(users): no-store cache header on api-key creation"
```

---

## Phase 10 — OpenAPI polish

### Task 10.1: `summary`, `description`, `operation_id`, `tags_metadata`

**Files:**
- Modify: every route decorator in `app/api/v1/admin/*.py`, `app/api/v1/public/addresses.py`
- Modify: `app/main.py` (add `openapi_tags`)

This is mechanical but bulky. Implement it as **one large file-by-file pass**, not 50 individual tasks. Each route gets:

```python
@router.get(
    "",
    response_model=Page[AddressSearchResult],
    summary="List addresses",
    description="Returns paginated addresses with optional fuzzy filter.",
    operation_id="admin.addresses.list",
    responses={
        401: {"description": "Missing or invalid API key"},
        403: {"description": "Insufficient role"},
    },
)
```

- [ ] **Step 1: Add `openapi_tags` in `app/main.py`**

```python
tags_metadata = [
    {"name": "admin-addresses", "description": "Address read + offerings management"},
    {"name": "admin-zones", "description": "Service zones (polygons) and zone offerings"},
    {"name": "admin-users", "description": "User accounts and API keys"},
    {"name": "admin-technologies", "description": "Technology catalog"},
    {"name": "admin-audit", "description": "Audit log queries"},
    {"name": "admin-bulk", "description": "Bulk operations with preview/execute/rollback"},
    {"name": "admin-hierarchy", "description": "Cascading dropdowns (county/muni/locality/street)"},
    {"name": "admin-map", "description": "GeoJSON map endpoints"},
    {"name": "admin-stats", "description": "Coverage statistics"},
    {"name": "public", "description": "Public unauthenticated endpoints"},
    {"name": "health", "description": "Service health probes"},
]
app = FastAPI(..., openapi_tags=tags_metadata)
```

- [ ] **Step 2: Add per-route metadata**

For each route in each file, add `summary=`, `operation_id=` (kebab-case under the tag, e.g. `admin.addresses.list`), and the standard `responses={...}` dict. Be patient — this is ~50 routes.

- [ ] **Step 3: Visual verification**

```bash
docker compose restart api
curl -s http://localhost:8000/openapi.json | python3 -m json.tool | grep -E '"summary"|"operationId"' | head -20
```

- [ ] **Step 4: Commit per file** (not per route — too many commits)

```bash
git add app/api/v1/admin/addresses.py
git commit -m "docs(addresses): OpenAPI summary + operation_id + responses"
```

Repeat for `audit.py`, `bulk.py`, `hierarchy.py`, `map.py`, `stats.py`, `technologies.py`, `users.py`, `zones.py`, `public/addresses.py`, `main.py`.

---

### Task 10.2: Examples on key request/response models

**Files:**
- Modify: `app/schemas/admin.py`

- [ ] **Step 1: Add `model_config = {"json_schema_extra": {"examples": [...]}}` to:**
  - `AddressSearchResult`
  - `AddressOfferingCreate` / `AddressOfferingOut`
  - `ZoneCreate` / `ZoneOut`
  - `UserCreate` / `UserOut`
  - `BulkPreviewResponse`
  - `Page[AddressSearchResult]`

Each gets a realistic example with values likely to appear in production (`rc_code: 12345`, `house_no: "5"`, etc.).

- [ ] **Step 2: Commit**

```bash
git add app/schemas/admin.py
git commit -m "docs(schemas): add OpenAPI examples"
```

---

## Phase 11 — Final cleanup

### Task 11.1: Refactor list endpoints onto `app.db.filter_builder`

**Files:**
- Modify: `app/api/v1/admin/hierarchy.py`, `app/api/v1/admin/audit.py`, `app/api/v1/admin/bulk.py` (`_filter_addresses`), `app/api/v1/admin/addresses.py` (`list_addresses`), `app/api/v1/admin/zones.py` (`list_zones`)

For each:

- [ ] **Step 1: Replace the inline `filters = []; params = {}; ... " AND ".join(filters)` blocks with `build_where([...])` from `app.db.filter_builder`.**

Run tests after each file.

- [ ] **Step 2: Commit one file at a time**

```bash
git add app/api/v1/admin/addresses.py
git commit -m "refactor(addresses): use build_where helper"
```

(Repeat for other files.)

---

### Task 11.2: Move magic numbers to `app/config.py`

**Files:**
- Modify: `app/config.py` (Settings)
- Modify: `app/api/v1/admin/bulk.py` (`_EDITOR_RATE_LIMIT`, `_MAX_BULK_AFFECTED`)
- Modify: `app/api/v1/admin/map.py` (`_LT_LON_MIN/MAX`)

- [ ] **Step 1: Add settings fields**

```python
class Settings(BaseSettings):
    ...
    bulk_editor_rate_window_hours: int = 24
    bulk_max_affected: int = 10000
    lt_bbox: tuple[float, float, float, float] = (20.9, 53.8, 26.9, 56.5)  # minlon, minlat, maxlon, maxlat
```

- [ ] **Step 2: Reference `settings.*` instead of module-level constants.**

- [ ] **Step 3: Commit**

```bash
git add app/config.py app/api/v1/admin/
git commit -m "refactor: move magic numbers to settings"
```

---

### Task 11.3: Combine count + select on `/map/in-polygon` with window function

**Files:**
- Modify: `app/api/v1/admin/map.py:155`

- [ ] **Step 1: Refactor**

Use one query:

```sql
SELECT
    a.rc_code,
    ST_AsGeoJSON(a.point)::jsonb AS geometry,
    COUNT(*) OVER () AS total
FROM addresses a
WHERE ST_Contains(ST_SetSRID(ST_GeomFromGeoJSON(:gj), 4326)::geometry, a.point::geometry)
  AND a.deleted_at IS NULL
LIMIT :limit
```

Read `total` from the first row.

- [ ] **Step 2: Run tests**

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/map.py
git commit -m "perf(map): combine count + select using COUNT(*) OVER()"
```

---

### Task 11.4: Stats consistency — soft-delete in `address_offerings` count

**Files:**
- Modify: `app/api/v1/admin/stats.py:127`

- [ ] **Step 1: Filter on parent address `deleted_at`**

```python
total = await db.scalar(text("""
    SELECT COUNT(*) FROM address_offerings ao
    JOIN addresses a ON a.rc_code = ao.address_code AND a.deleted_at IS NULL
"""))
```

- [ ] **Step 2: Regression test** — seed an offering on a soft-deleted address, confirm `scope=all` excludes it.

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/stats.py tests/api/test_stats.py
git commit -m "fix(stats): exclude offerings on soft-deleted addresses"
```

---

### Task 11.5: Operation-data type roundtrip in bulk execute

**Files:**
- Modify: `app/api/v1/admin/bulk.py:113-138`

- [ ] **Step 1: Use `TypeAdapter`**

```python
from pydantic import TypeAdapter
from app.schemas.admin import BulkOperation

_BULK_OP_ADAPTER = TypeAdapter(BulkOperation)


def parse_stored_operation(raw: dict) -> BulkOperation:
    return _BULK_OP_ADAPTER.validate_python(raw)
```

Use `parse_stored_operation(token.operation_data)` instead of if-chains on `op_type`.

- [ ] **Step 2: Run bulk tests.**

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/bulk.py
git commit -m "refactor(bulk): roundtrip BulkOperation via TypeAdapter"
```

---

### Task 11.6: Hash optimization for API keys (optional perf)

**Files:**
- Modify: `app/auth.py`, `app/api/v1/admin/users.py`, `app/cli.py`

Optional. Replace `bcrypt.hashpw(raw_key)` with `hmac.new(settings.api_key_secret, raw_key, sha256).hexdigest()`. Keep bcrypt fallback for legacy rows.

- [ ] If pursuing this, add task. Otherwise skip and document in `app/auth.py`:

```python
# NOTE: bcrypt over a 256-bit random token is overkill but acceptable.
# HMAC-SHA256 would be ~1000x faster; switch if auth latency becomes a concern.
```

- [ ] **Commit (if skipped)**

```bash
git add app/auth.py
git commit -m "docs(auth): comment hash algorithm choice"
```

---

### Task 11.7: Move top-of-file `log = ...` lines to the import block

**Files:**
- Modify: `app/main.py`, `app/api/v1/admin/bulk.py`

- [ ] **Step 1: Move `log = logging.getLogger(__name__)` to immediately after all `import` / `from` statements.**

- [ ] **Step 2: Commit**

```bash
git add app/main.py app/api/v1/admin/bulk.py
git commit -m "style: move logger init to top of import block"
```

---

### Task 11.8: Use opaque external ID for `AuditLogOut.id`

**Files:**
- Modify: `app/schemas/admin.py:334`

- [ ] **Step 1: Decide**

Either: keep `int` and document; or add a UUID column to `audit_log` (separate migration).

If keep: `id: int` stays; just add a comment:

```python
# NOTE: id is an internal serial — clients should treat it as opaque.
```

If switch: add migration in Phase 2 task 2.5 — beyond audit scope here.

- [ ] **Step 2: Commit**

```bash
git add app/schemas/admin.py
git commit -m "docs(audit): clarify id is opaque"
```

---

### Task 11.9: CORS staging origin via env

**Files:**
- Modify: `app/main.py:42`
- Modify: `app/config.py`

- [ ] **Step 1: Add setting**

```python
class Settings(BaseSettings):
    ...
    cors_origins: list[str] = ["http://localhost:3000"]
```

- [ ] **Step 2: Use it**

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 3: Document `CORS_ORIGINS=https://app.etanetas.lt,https://staging.etanetas.lt` in `.env.example`.**

- [ ] **Step 4: Commit**

```bash
git add app/main.py app/config.py .env.example
git commit -m "feat(cors): configurable origins via env"
```

---

### Task 11.10: `/zones/{id}/detail` → `/zones/{id}?expand=detail`

**Files:**
- Modify: `app/api/v1/admin/zones.py:71`
- (Note: this is a breaking URL change; if used in tests, update.)

- [ ] **Step 1: Merge detail into `GET /{zone_id}`**

```python
@router.get("/{zone_id}", response_model=ZoneOut | ZoneDetail)
async def get_zone(
    zone_id: uuid.UUID,
    ...,
    expand: Annotated[Literal["detail"] | None, Query()] = None,
) -> ZoneOut | ZoneDetail:
    ...
    if expand == "detail":
        return ZoneDetail(...)
    return ZoneOut(...)
```

If `GET /zones/{zone_id}` doesn't currently exist (the original code only had `/detail`), this is a pure addition; otherwise rename.

- [ ] **Step 2: Update tests** that hit `/{zone_id}/detail` → `/{zone_id}?expand=detail`.

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/admin/zones.py tests/
git commit -m "refactor(zones): merge /detail into /{id}?expand=detail"
```

---

### Task 11.11: Sweep ESLint-grade nits

**Files:** various

- [ ] **Step 1: Run linters once everything else is in**

```bash
unset VIRTUAL_ENV; .venv/bin/ruff check --fix .
```

Inspect remaining diagnostics and fix. Suspects: unused imports, magic numbers we missed.

- [ ] **Step 2: Run full test suite**

```bash
unset VIRTUAL_ENV; .venv/bin/pytest -q
```
Expected: all green.

- [ ] **Step 3: Commit any remaining cleanup**

```bash
git add -A
git commit -m "chore: final ruff cleanup"
```

---

## Verification (end-to-end)

After every phase:

1. **Full test suite**

   ```bash
   unset VIRTUAL_ENV; .venv/bin/pytest -q
   ```

2. **Lint**

   ```bash
   unset VIRTUAL_ENV; .venv/bin/ruff check .
   ```

3. **Smoke run**

   ```bash
   docker compose restart api
   curl -s http://localhost:8000/openapi.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['paths']),'paths')"
   ```

After the whole plan:

1. **Performance: confirm auth O(1)** — generate 1000 keys, measure `/admin/me` latency at p95 < 50 ms.

   ```bash
   for i in $(seq 1 1000); do
     docker compose exec -T api uv run python -m app.cli create-key --username robertas --name "perf-$i" >/dev/null
   done
   time for i in $(seq 1 100); do
     curl -s -H "X-API-Key: <known-key>" http://localhost:8000/api/v1/admin/me > /dev/null
   done
   ```

2. **Migration smoke**:

   ```bash
   unset VIRTUAL_ENV; .venv/bin/alembic downgrade base
   unset VIRTUAL_ENV; .venv/bin/alembic upgrade head
   ```

3. **OpenAPI**: open `http://localhost:8000/docs` and confirm every route has a summary, every tag has a description, every 401/403/404 is documented.

4. **Production checklist**:
   - All migrations reversible.
   - No naive datetimes (`ruff --select DTZ` clean).
   - All mutating endpoints write to `audit_log`.
   - All list endpoints return `{total, items}` with cap 100.
   - All errors use the envelope.
   - All 201 responses include `Location` header.
   - Rate limits cover both `/bulk/preview` and `/bulk/execute`.
   - Polygon and `q` inputs are bounded.
