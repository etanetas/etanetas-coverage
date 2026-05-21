from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    cors_origins: list[str] = [
        "https://etanetas.lt",
        "https://www.etanetas.lt",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    otel_exporter: str = "console"
    bcrypt_rounds: int = 12
    db_pool_size: int = 20
    db_max_overflow: int = 10
    stats_municipality_codes: list[int] = [13, 41, 85]
    stats_municipality_names: list[str] = [
        "Vilniaus miesto",
        "Vilniaus rajono",
        "Šalčininkų rajono",
    ]

    @field_validator("stats_municipality_codes", mode="before")
    @classmethod
    def _parse_stats_municipality_codes(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        return value

    @field_validator("stats_municipality_names", mode="before")
    @classmethod
    def _parse_stats_municipality_names(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()
