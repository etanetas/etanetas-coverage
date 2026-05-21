from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    cors_origins: list[str] = ["https://etanetas.lt", "https://www.etanetas.lt"]
    otel_exporter: str = "console"
    bcrypt_rounds: int = 12
    db_pool_size: int = 20
    db_max_overflow: int = 10

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()
