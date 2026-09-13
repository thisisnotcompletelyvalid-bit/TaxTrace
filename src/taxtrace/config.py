from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./taxtrace.db"
    raw_data_dir: Path = Path("data/raw")
    warehouse_data_dir: Path = Path("data/warehouse")
    http_timeout_seconds: float = 60.0
    user_agent: str = "TaxTrace/0.1 (contact-not-configured)"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.raw_data_dir.mkdir(parents=True, exist_ok=True)
    settings.warehouse_data_dir.mkdir(parents=True, exist_ok=True)
    return settings
