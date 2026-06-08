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
    bulk_editor_rate_limit: int = 5000  # addresses per minute per editor
    bulk_max_affected: int = 10000  # max addresses affected by a single bulk operation
    stats_municipality_codes: list[int] = [13, 41, 85]
    stats_municipality_names: list[str] = [
        "Vilniaus miesto",
        "Vilniaus rajono",
        "Šalčininkų rajono",
    ]
    stats_locality_codes: list[int] = []
    stats_locality_names: list[str] = [
        "Šalčininkai",
        "Vilnius",
        "Skaidiškės",
        "Jašiūnai",
        "Pagiriai",
        "Eišiškės",
        "Salininkai",
        "Dieveniškės",
        "Butrimonys",
        "Kalesnikai",
        "Murlinė",
        "Gudeliai",
        "Gojus",
        "Didieji Baušiai",
        "Šalčininkų Tartokas",
        "Turgeliai",
        "Zavišonys",
        "Didžiasalis",
        "Talkotiškės",
        "Stankutiškės",
        "Daržininkai",
        "Rudamina",
        "Parapijoniškės",
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

    @field_validator("stats_locality_codes", mode="before")
    @classmethod
    def _parse_stats_locality_codes(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        return value

    @field_validator("stats_locality_names", mode="before")
    @classmethod
    def _parse_stats_locality_names(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()
