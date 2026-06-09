# GZip Compression + Cache-Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce `/map/addresses` bandwidth 10x with GZip compression and eliminate redundant fetches with a 5-minute browser cache.

**Architecture:** GZipMiddleware added globally to `app/main.py` (compresses any response ≥ 1000 bytes when client sends `Accept-Encoding: gzip`). `Cache-Control: max-age=300` set directly in the `map_addresses` response — coverage data changes rarely so 5 minutes is safe.

**Tech Stack:** FastAPI / Starlette built-in `GZipMiddleware` (no new dependency)

---

## File Map

**Modify:**
- `app/main.py` — add `GZipMiddleware`
- `app/api/v1/admin/map.py` — add `Cache-Control` header to `map_addresses` response

**Test:**
- `tests/api/test_map_validation.py` — add header assertions

---

## Task 1: GZipMiddleware

**Files:**
- Modify: `app/main.py` (lines 65–72, middleware block)
- Test: `tests/api/test_map_validation.py`

- [ ] **Step 1: Write failing test**

Add to `tests/api/test_map_validation.py`:

```python
@pytest.mark.integration
async def test_map_addresses_accepts_gzip_encoding(client, admin):
    _, raw = admin
    resp = await client.get(
        "/api/v1/admin/map/addresses",
        params={"bbox": "25.0,54.0,26.0,55.0"},
        headers={"X-API-Key": raw, "Accept-Encoding": "gzip"},
    )
    # Middleware must not break the endpoint; empty bbox = small response = no compression
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]
```

- [ ] **Step 2: Run test to verify it passes already (baseline)**

```bash
uv run pytest tests/api/test_map_validation.py::test_map_addresses_accepts_gzip_encoding -v
```

Expected: PASS (endpoint already works; this establishes the no-regression baseline)

- [ ] **Step 3: Add GZipMiddleware to app/main.py**

In `app/main.py`, add the import after the existing starlette import on line 10:

```python
from starlette.middleware.gzip import GZipMiddleware
```

Then add the middleware after line 72 (after `CORSMiddleware` block), before `configure_telemetry`:

```python
app.add_middleware(GZipMiddleware, minimum_size=1000)
```

The full middleware block becomes:

```python
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
configure_telemetry(app, engine)
```

`minimum_size=1000` means responses under 1 KB are not compressed (no overhead for small error responses). The `/map/addresses` response at 524 KB is well above this threshold.

- [ ] **Step 4: Run all tests to verify no regression**

```bash
uv run pytest tests/api/ -v
```

Expected: all PASSED (same count as before)

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/api/test_map_validation.py
git commit -m "feat: add GZipMiddleware (minimum_size=1000) for response compression"
```

---

## Task 2: Cache-Control on /map/addresses

**Files:**
- Modify: `app/api/v1/admin/map.py` (line 85, the `return Response(...)` call)
- Test: `tests/api/test_map_validation.py`

- [ ] **Step 1: Write failing test**

Add to `tests/api/test_map_validation.py`:

```python
@pytest.mark.integration
async def test_map_addresses_has_cache_control(client, admin):
    _, raw = admin
    resp = await client.get(
        "/api/v1/admin/map/addresses",
        params={"bbox": "25.0,54.0,26.0,55.0"},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == "max-age=300"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/api/test_map_validation.py::test_map_addresses_has_cache_control -v
```

Expected: FAIL — `AssertionError: assert None == 'max-age=300'`

- [ ] **Step 3: Add Cache-Control header to map_addresses response**

In `app/api/v1/admin/map.py`, find the `return Response(...)` call at the end of `map_addresses` (currently line 85):

```python
    return Response(content=result or '{"type":"FeatureCollection","features":[]}',
                    media_type="application/json")
```

Replace with:

```python
    return Response(
        content=result or '{"type":"FeatureCollection","features":[]}',
        media_type="application/json",
        headers={"Cache-Control": "max-age=300"},
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/api/test_map_validation.py::test_map_addresses_has_cache_control -v
```

Expected: PASS

- [ ] **Step 5: Run all tests to verify no regression**

```bash
uv run pytest tests/api/ -v
```

Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add app/api/v1/admin/map.py tests/api/test_map_validation.py
git commit -m "feat: add Cache-Control max-age=300 to /map/addresses response"
```
