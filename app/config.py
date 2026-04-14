from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Always load the .env next to the project root, regardless of current working directory.
    _ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
    model_config = SettingsConfigDict(env_file=_ENV_PATH, env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./fashion_inspiration.db"
    gemini_api_key: str | None = None
    # Gemini model for structured tagging. Override via GEMINI_MODEL.
    # Note: some older models (e.g. gemini-2.0-flash) are not available to new users.
    gemini_model: str = "gemini-2.5-flash"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    upload_dir: Path = Path(__file__).resolve().parent / "static" / "uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
