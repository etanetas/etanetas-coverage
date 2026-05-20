from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    cors_origins: list[str] = ["https://etanetas.lt", "https://www.etanetas.lt"]
    otel_exporter: str = "console"

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()