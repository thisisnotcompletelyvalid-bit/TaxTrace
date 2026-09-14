from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve()}"


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = _sqlite_url(PROJECT_ROOT / "taxtrace.db")
    raw_data_dir: Path = PROJECT_ROOT / "data" / "raw"
    warehouse_data_dir: Path = PROJECT_ROOT / "data" / "warehouse"
    http_timeout_seconds: float = 60.0
    user_agent: str = "TaxTrace/0.1 (contact-not-configured)"

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    @field_validator("database_url", mode="after")
    @classmethod
    def normalize_relative_sqlite_url(cls, value: str) -> str:
        """Anchor relative SQLite URLs at the repository root instead of the shell cwd."""
        prefix = "sqlite:///"
        if not value.startswith(prefix):
            return value
        path_text = value[len(prefix) :]
        if not path_text or path_text == ":memory:" or path_text.startswith("/"):
            return value
        while path_text.startswith("./"):
            path_text = path_text[2:]
        return _sqlite_url(PROJECT_ROOT / path_text)

    @field_validator("raw_data_dir", "warehouse_data_dir", mode="after")
    @classmethod
    def normalize_relative_data_dir(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return PROJECT_ROOT / value


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.raw_data_dir.mkdir(parents=True, exist_ok=True)
    settings.warehouse_data_dir.mkdir(parents=True, exist_ok=True)
    return settings
