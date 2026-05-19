from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    spinta_base_url: str
    rc_geojson_url: str = "https://www.registrucentras.lt/aduomenys/?byla=adr_gra_adresai_LT.zip"

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()