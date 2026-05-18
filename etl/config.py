from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    spinta_base_url: str

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()