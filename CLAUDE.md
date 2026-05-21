# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ISP address & service availability API for Etanetas (Šalčininkai, LT). Core question: "What internet services are available at address X?" Stack: FastAPI + SQLAlchemy 2.0 async + PostgreSQL 16/PostGIS 3.4. Package manager: `uv`.

## Commands

```bash
# Infrastructure
docker compose up -d db          # PostgreSQL + PostGIS (required before everything else)
docker compose up -d api         # FastAPI on :8000

# Dependencies & migrations
uv sync
uv run alembic upgrade head
uv run alembic revision -m "description"   # manual migration (autogenerate unreliable with GeoAlchemy2)

# API dev
uv run uvicorn app.main:app --reload

# ETL — full import (downloads RC CSV files + GeoJSON to etl/state/cache/, then loads DB)
uv run python -m etl.tasks.full_import

# ETL — nightly sync (run manually or via cron 0 2 * * *)
uv run python -m etl.tasks.nightly_sync

# ETL — monthly full resync (run manually or via cron 0 3 1 * *)
uv run python -m etl.tasks.monthly_full_resync

# CLI
uv run python -m app.cli create-admin --username X --email Y --password Z
```

```bash
# Run all tests
uv run pytest

# Run only ETL tests
uv run pytest tests/etl/ -v
```

## Cron (produkcja)

```cron
0 2 * * *   cd /app && uv run python -m etl.tasks.nightly_sync >> /var/log/etanetas/nightly.log 2>&1
0 3 1 * *   cd /app && uv run python -m etl.tasks.monthly_full_resync >> /var/log/etanetas/monthly.log 2>&1
```

## Architecture

```
app/          FastAPI application (API layer, models, migrations)
etl/          ETL pipeline (completely separate from app, shares DB)
  downloaders/  spinta_client.py (Spinta API for nightly sync)
                rc_csv_client.py (RC static CSV files — primary source for full import)
                rc_zip_fallback.py (RC GeoJSON ZIP for address points)
  transformers/ address_mapper.py (maps RC rows → DB dicts; two sets: Spinta format + CSV format)
  loaders/      upsert_load.py (batch upsert via ON CONFLICT DO UPDATE on rc_code)
  tasks/        full_import.py, nightly_sync.py, monthly_full_resync.py (stub)
  state_db.py   read/write last Spinta _cid + import checkpoint in etl_state table
  loaders/      upsert_load.py (bulk), geometry_load.py (UPDATE geometry), incremental_load.py (changes)
docs/         TZ spec (Lithuanian) — authoritative source of truth for schema & sync logic
```

## ETL Data Sources

Full import uses **RC direct files** (registrucentras.lt), not Spinta API (too slow/unreliable):
- Administrative hierarchy: `adr_apskritys.csv`, `adr_savivaldybes.csv`, `adr_gyvenamosios_vietoves.csv`, `adr_gatves.csv`
- Building/plot addresses: `adr_stat_lr.csv` — `AOB_KODAS|GYV_KODAS|GAT_KODAS|NR|PASTO_KODAS`
- Premises addresses: `adr_pat_lr.csv` — `PAT_KODAS|AOB_KODAS|PATALPOS_NR` (inherits locality/street/point from parent building)
- Address points (geometry): `adr_gra_adresai_LT.zip` → JSON with `AOB_KODAS`, `E_KOORD`/`N_KOORD` (already WGS84)

Nightly sync uses **Spinta `:changes`** endpoint (small delta, fast).

## Key Patterns

**Geometry:** Points stored as `SRID=4326;POINT(lon lat)` EWKT strings; GeoAlchemy2 + `ST_GeomFromEWKT` handles conversion. Premises inherit parent building's point.

**Upsert:** All ETL loads use `INSERT ... ON CONFLICT (rc_code) DO UPDATE`. `upsert_all()` accepts `AsyncIterator[dict]` — pass `async def` generators, not regular generators.

**ETL state cursor:** `etl_state` table, key `adresai_cid`, value = last Spinta `_cid` integer. Use `etl/state_db.py` `get_last_cid()` / `save_cid()`.

**Mapper convention:** Two sets in `address_mapper.py` — `map_*()` for Spinta JSON format (UUIDs, Lithuanian field names), `map_*_csv()` for RC CSV format (integer codes, uppercase field names). CSV mappers are used in full_import; Spinta mappers reserved for nightly_sync changes.

**RC CSV cache:** Downloaded to `etl/state/cache/`. Re-download by deleting the file. Cache is intentional — RC files update monthly.

**Migrations:** GeoAlchemy2 geometry columns require `create_geospatial_table` / `create_geospatial_index` in Alembic, not standard `create_table`. Don't use `--autogenerate` for tables with geometry columns.

## Code conventions

**Error handling:**
- Never `except: pass` or `except Exception: pass` — always log or re-raise
- External I/O (HTTP, DB, file): wrap in try/except with specific exception types
- ETL downloaders: use exponential backoff retry (see `_get_with_retry` in `etl/downloaders/spinta_client.py`)
- FastAPI endpoints: raise `HTTPException`, never return raw 500 tracebacks

**Type hints:**
- Always add type hints to function signatures and return types
- Use `dict[str, Any]`, `AsyncIterator[dict]`, etc. — not bare `dict` or `list`

**Logging:**
- Use Python `logging` module everywhere — `log = logging.getLogger(__name__)` at module level
- Never use `print()` in new code
- Log level convention: INFO for normal flow, WARNING for skipped/partial data, ERROR for failures
- Configure via `app/logging_config.py` — `configure_logging()` called at entry points

**Async:**
- All DB access via `AsyncSessionLocal` — never use sync SQLAlchemy in this codebase
- Generators passed to `upsert_all()` must be `async def` (yield), not regular generators
- Don't `await` inside list comprehensions — use `async for` loops

**FastAPI endpoints (when building):**
- Inject DB session via `Depends(get_db)` from `app/dependencies.py` — never create sessions manually
- Auth via `X-API-Key` header — check `ApiKey` model (bcrypt hash, not plaintext comparison)
- Return Pydantic response models, not raw SQLAlchemy objects

**Linting:**
- `ruff` configured in `pyproject.toml` — runs automatically via PostToolUse hook and pre-commit
- To run manually: `uv run ruff check --fix .`
- Install pre-commit hooks once after clone: `uv sync --group dev && uv run pre-commit install`

**Observability:**
- OpenTelemetry wired in `app/telemetry.py` — FastAPI + SQLAlchemy instrumented automatically
- `OTEL_EXPORTER=console` (default/dev), `OTEL_EXPORTER=otlp` (production), `OTEL_EXPORTER=none` (disable)
- Set `OTEL_EXPORTER_OTLP_ENDPOINT` when using otlp exporter

**ETL checkpoint/resume:**
- `full_import.py` saves progress after each step to `etl_state` table (key `full_import_step`)
- Re-running after failure resumes from last completed step automatically
- Force full restart: `run(force=True)` or delete `full_import_step` row from `etl_state`

## Production deployment

**Workers:** always run with `--workers 1`. The bulk preview token store (`_preview_store` in `app/api/v1/admin/bulk.py`) is in-memory per-process — multiple workers will cause preview tokens to be invisible to other workers, breaking bulk execute.

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

**Required env variables for production:**

- `DATABASE_URL` — asyncpg postgres DSN
- `SPINTA_BASE_URL` — needed for nightly ETL sync
- `OTEL_EXPORTER=none` (or `otlp`) — `console` floods logs with traces
- `LOG_FILE=/var/log/etanetas/api.log` — rotating file log (50 MB × 5)

**First deploy checklist:**

1. `cp .env.example .env` and fill in `DATABASE_URL`, `DB_PASSWORD`, `SPINTA_BASE_URL`
2. `docker compose up -d db`
3. `uv run alembic upgrade head`
4. `uv run python -m app.cli create-admin --username X --email Y` → save the key
5. `uv run python -m etl.tasks.full_import` (~10–15 min, 2.3M addresses)
6. Start API with `--workers 1`
7. Set up cron (see Cron section above)

**Key rotation:**

```bash
uv run python -m app.cli list-users          # see who exists
uv run python -m app.cli revoke-key --username X
uv run python -m app.cli create-key --username X --name "main"
```
