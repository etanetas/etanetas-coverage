# Etanetas Address Service

ISP address & service availability API for Etanetas (Šalčininkai, LT). Answers the question: "What internet services are available at address X?"

## Implementation status

| Stage | Description | Status |
|---|---|---|
| 1 | Foundation — DB schema, PostGIS, models, migrations | ✅ Done |
| 2 | RC import ETL — full import, nightly sync, monthly resync | ✅ Done |
| 3 | Public API — `/public/addresses/search` + `/availability` | ✅ Done |
| 4 | Internal API — auth, admin CRUD, bulk ops, audit log | ✅ Done |
| 5 | GIS import + auto-zones — shapefiles → offerings, zones derived from offerings | ✅ Done |
| 6 | LMS Plus PHP plugin | ✅ Done (separate repo: `lms-etanetas`) |
| 7 | etanetas.lt frontend integration | 🔜 Planned |

## Requirements

- [Docker](https://docs.docker.com/get-docker/) with Compose
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (Python package manager)
- Python 3.12+

## Quick start

```bash
# 1. Copy environment file and set password
cp .env.example .env
# Edit .env — set DB_PASSWORD

# 2. Start the database
docker compose up -d db

# 3. Run migrations
uv run alembic upgrade head

# 4. Create the first admin user
uv run python -m app.cli create-admin --username jonas --email jonas@etanetas.lt
# API key is shown ONCE — save it

# 5. Start the API
docker compose up -d api

# 6. Verify
curl http://localhost:8000/health
```

## Environment

Copy `.env.example` to `.env` and fill in values:

| Variable | Description |
|---|---|
| `DB_PASSWORD` | PostgreSQL password |
| `DATABASE_URL` | Full async DSN — auto-set in Docker, override for local dev |

For local development (outside Docker) `DATABASE_URL` points to `localhost:5432`.  
Inside Docker the `api` service overrides it to point to the `db` service hostname.

## Docker

`compose.yml` defines two services:

| Service | Image | Port | Description |
|---|---|---|---|
| `db` | `postgis/postgis:16-3.4` | `5432` | PostgreSQL 16 + PostGIS 3.4 |
| `api` | local build | `8000` | FastAPI application |

The `db` service has a healthcheck (`pg_isready`). The `api` service waits for `db` to be healthy before starting.

Data is persisted in the `pgdata` Docker volume — it survives `docker compose down`.  
To wipe the database: `docker compose down -v`.

```bash
# Start everything
docker compose up -d

# Start only the database (useful when running API locally with uv)
docker compose up -d db

# View logs
docker compose logs -f api

# Stop
docker compose down
```

## Database & migrations

Migrations are managed with [Alembic](https://alembic.sqlalchemy.org/) using an async engine (`asyncpg`).

`alembic/env.py` reads `DATABASE_URL` from `.env` automatically. GeoAlchemy2 PostGIS types are registered via `alembic_helpers`.

```bash
# Apply all pending migrations
uv run alembic upgrade head

# Roll back one migration
uv run alembic downgrade -1

# Show migration history
uv run alembic history

# Create a new (empty) migration — fill it in manually
uv run alembic revision -m "add something"
```

> **Note:** Write migrations manually — `--autogenerate` is unreliable with GeoAlchemy2 geometry columns and partial indexes. Geometry tables need `create_geospatial_table` / `create_geospatial_index` helpers.

### Schema overview

| Table group | Tables |
|---|---|
| Address registry | `counties`, `municipalities`, `localities`, `streets`, `addresses` |
| Service coverage | `service_zones` (incl. `source` manual/auto, `custom_name`), `zone_offerings`, `address_offerings` |
| Technology catalog | `technology_types`, `technologies` |
| Administration | `users`, `api_keys`, `bulk_operations`, `bulk_preview_tokens`, `audit_log` |
| ETL bookkeeping | `etl_state` |

## CLI

```bash
uv run python -m app.cli --help
```

| Command | Description |
|---|---|
| `create-admin --username X --email Y` | Creates an admin user and generates an initial API key |
| `create-key --username X --name label` | Generates a new API key for an existing user |
| `revoke-key --username X` | Revokes all active API keys for a user |
| `list-users` | Lists all users and their active key count |
| `import-gis` | Imports network shapefiles as address offerings (see below) |
| `rebuild-zones` | Rebuilds auto-zones from address offerings (see below) |
| `version` | Prints the package version |

### create-admin

```bash
uv run python -m app.cli create-admin --username jonas --email jonas@etanetas.lt
```

- Creates a `users` row with `role = admin`
- Generates an API key with prefix `etn_pk_` using `secrets.token_urlsafe(32)`
- Stores only the bcrypt hash in `api_keys` — the raw key is shown **once** in the terminal
- Use the key in the `X-API-Key` header to authenticate against internal API endpoints

### import-gis — GIS network import

Imports ESRI shapefiles of the physical network (lines = cable routes, points = wells/cabinets, CRS LKS94/EPSG:3346) and creates an `available` address offering for every building within `--distance` meters of the network. Existing offerings are **never overwritten**. Each run is recorded in `bulk_operations`.

```bash
# Always dry-run first — full run, rolled back at the end, prints the summary table
uv run python -m app.cli import-gis \
  --shapefile Rys_tinkl.shp --shapefile Rys_t.shp \
  --technology gpon --distance 100 --username admin --dry-run

# Real import: same command without --dry-run
```

| Option | Description |
|---|---|
| `--shapefile` | Path to `.shp` (repeatable — lines and/or points) |
| `--technology` | `variant_code` from the technology catalog (e.g. `gpon`) — shapefiles carry no technology info |
| `--distance` | Max distance in meters from any network geometry |
| `--username` | Existing user recorded as `created_by` |
| `--status` / `--download` / `--upload` | Override status (default `available`) and speeds (default: technology maxima) |
| `--mode diff` | Additionally reports *orphaned* offerings — GIS-imported offerings now outside network reach |
| `--remove-orphans` | With `--mode diff`: removes orphaned offerings as a rollbackable bulk operation |
| `--dry-run` | Runs everything inside a transaction and rolls back |

After a (non-dry-run) import the auto-zones for the technology are rebuilt automatically.

### rebuild-zones — auto-zones

Auto-zones are `service_zones` rows (`source = 'auto'`) **derived from address offerings** — address offerings are the single source of truth, zones are visualization. A zone is the union of buffers (default 150 m) around addresses holding an `available` offering; contiguous areas become separate zones named after their dominant locality (`custom_name` allows a manual display-name override). Zones rebuild automatically after `import-gis`, offering create/update/delete and bulk operations; the CLI exists for manual/initial rebuilds:

```bash
uv run python -m app.cli rebuild-zones [--technology gpon] [--radius 150]
```

Zones whose offerings disappear are soft-hidden (`deleted_at`) and revived automatically when offerings return. Manual zones (`source = 'manual'`) are never touched by rebuilds.

## API

The API runs at `http://localhost:8000`.

| Endpoint group | Auth | Description |
|---|---|---|
| `GET /health` | none | Liveness check — returns `{"status": "ok"}` |
| `GET /docs`, `GET /redoc` | none | Swagger UI / ReDoc (full endpoint reference) |
| `/api/v1/public/addresses/*` | none (rate-limited) | Address search + service availability for the public site |
| `/api/v1/admin/*` | `X-API-Key` | Addresses, offerings, zones, technologies, users, bulk ops, audit log, coverage stats |
| `/api/v1/admin/map/*` | `X-API-Key` | GeoJSON for the coverage map: address points, zone polygons, in-polygon selection |

## Project structure

```
app/
├── main.py          # FastAPI app, health endpoint
├── cli.py           # CLI commands (Typer)
├── config.py        # Settings (pydantic-settings, reads .env)
├── database.py      # Async SQLAlchemy engine + session factory
└── models/
    ├── base.py      # DeclarativeBase
    ├── address.py   # County, Municipality, Locality, Street, Address
    ├── technology.py# TechnologyType, Technology
    ├── service.py   # ServiceZone, ZoneOffering, AddressOffering
    └── admin.py     # User, ApiKey, BulkOperations, AuditLog
```

## ETL — Address data import

Address data comes from [Registrų centras](https://www.registrucentras.lt) (CC BY 4.0). Add attribution to the public site: *„Adresų duomenys: VĮ Registrų centras (CC BY 4.0)"*

### Initial import (run once at deploy)

Downloads ~300 MB of RC files to `etl/state/cache/`, loads ~2.3M addresses into DB.

```bash
uv run python -m etl.tasks.full_import
```

Duration: ~10–15 min. Resumes automatically if interrupted (checkpoint saved in `etl_state` table).

### Nightly sync (cron `0 2 * * *`)

Fetches only changes from Spinta API since last run. Takes seconds to minutes.

```bash
uv run python -m etl.tasks.nightly_sync
```

### Monthly full resync (cron `0 3 1 * *`)

Safety net — re-downloads fresh RC files, re-upserts everything, marks removed addresses as `deleted_at`.

```bash
uv run python -m etl.tasks.monthly_full_resync
```

### Cron setup (production)

Nightly sync has 3 scheduled attempts (+4h, +8h) for resilience. Each run checks if sync already succeeded today — later attempts exit immediately if the earlier one succeeded.

```cron
# Nightly sync — primary attempt
0 2 * * *   cd /app && uv run python -m etl.tasks.nightly_sync >> /var/log/etanetas/nightly.log 2>&1
# Nightly sync — retry +4h (runs only if 02:00 failed)
0 6 * * *   cd /app && uv run python -m etl.tasks.nightly_sync >> /var/log/etanetas/nightly.log 2>&1
# Nightly sync — retry +8h (runs only if 06:00 failed)
0 10 * * *  cd /app && uv run python -m etl.tasks.nightly_sync >> /var/log/etanetas/nightly.log 2>&1
# Monthly full resync — 1st of each month at 03:00
0 3 1 * *   cd /app && uv run python -m etl.tasks.monthly_full_resync >> /var/log/etanetas/monthly.log 2>&1
```

### Environment variables (ETL)

| Variable | Default | Description |
|---|---|---|
| `SPINTA_BASE_URL` | `https://get.data.gov.lt/datasets/gov/rc/ar` | Spinta API base |
| `RC_GEOJSON_URL` | `https://www.registrucentras.lt/aduomenys/?byla=adr_gra_adresai_LT.zip` | Address points ZIP |
| `TELEGRAM_BOT_TOKEN` | *(empty)* | Telegram bot token for failure alerts (optional) |
| `TELEGRAM_CHAT_ID` | *(empty)* | Telegram chat/group ID for alerts (optional) |

### ETL state

| Key in `etl_state` | Value | Description |
|---|---|---|
| `adresai_cid` | integer | Last processed Spinta `_cid` — used by nightly sync |
| `full_import_step` | step name | Checkpoint for resume after interrupted import |

## Production deployment

Multiple workers are supported — bulk preview tokens live in the `bulk_preview_tokens` DB table, no in-process state.

```bash
# 1. Apply migrations
uv run alembic upgrade head

# 2. Create first admin
uv run python -m app.cli create-admin --username admin --email admin@etanetas.lt
# → save the printed API key (shown ONCE)

# 3. Run initial ETL import (~10-15 min, 2.3M addresses)
uv run python -m etl.tasks.full_import

# 4. (optional) Import network shapefiles + build auto-zones
uv run python -m app.cli import-gis --shapefile ... --technology gpon \
  --distance 100 --username admin --dry-run   # then without --dry-run

# 5. Start API (log to file)
LOG_FILE=/var/log/etanetas/api.log \
OTEL_EXPORTER=none \
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1

# 6. Set up cron (see Cron setup section above)
```

**Required env for production:**

- `DATABASE_URL` — postgres connection
- `SPINTA_BASE_URL` — for ETL nightly sync
- `OTEL_EXPORTER=none` (or `otlp` with endpoint) — disables noisy console traces
- `LOG_FILE` — writes rotating logs instead of stdout-only

## Development

```bash
# Install dependencies
uv sync

# Run API locally (with hot reload)
docker compose up -d db
uv run uvicorn app.main:app --reload

# Run tests
uv run pytest

# Lint
uv run ruff check --fix .

# Run CLI
uv run python -m app.cli --help
```
