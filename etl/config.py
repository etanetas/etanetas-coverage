"""ETL configuration — reads values from .env (root) with sensible defaults.

All hardcoded values that used to live in downloaders/loaders/tasks now route through here.
Defaults match what worked in production; override via .env if you need to tune.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # === Database ===
    database_url: str

    # === Spinta API ===
    spinta_base_url: str
    spinta_timeout_seconds: float = 120.0
    spinta_connect_timeout_seconds: float = 10.0
    spinta_max_retries: int = 10
    spinta_fetch_limit: int = 5000

    # === RC direct files (CSV, GeoJSON, ZIP from registrucentras.lt) ===
    rc_geojson_url: str = "https://www.registrucentras.lt/aduomenys/?byla=adr_gra_adresai_LT.zip"
    rc_download_timeout_seconds: float = 300.0
    rc_download_connect_timeout_seconds: float = 10.0
    rc_download_max_retries: int = 5
    rc_download_chunk_size_bytes: int = 65536
    rc_progress_log_interval_mb: int = 10

    # === ETL infrastructure ===
    etl_cache_dir: str = "etl/state/cache"
    upsert_batch_size: int = 10_000
    geometry_batch_size: int = 1000
    max_pg_params: int = 32767
    point_lookup_log_interval: int = 200_000

    # === Sync schedule ===
    stale_sync_days: int = 7

    # === Notifications (optional — alerts skipped if not set) ===
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
