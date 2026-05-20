from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    cors_origins: list[str] = [
        "https://etanetas.lt",
        "https://www.etanetas.lt",
        "http://localhost:3000",
        "http://localhost:8001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8001",
    ]
    otel_exporter: str = "console"

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()