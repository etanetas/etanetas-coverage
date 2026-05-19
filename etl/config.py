from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    spinta_base_url: str
    rc_geojson_url: str = "https://www.registrucentras.lt/aduomenys/?byla=adr_gra_adresai_LT.zip"

    # Telegram alerts — optional, alerts are skipped if not set
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
