"""App-wide configuration. APP_NAME is the single place the product name lives."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "Pantheon"

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    default_model: str = "openai/gpt-4o-mini"
    database_url: str = f"sqlite:///{REPO_ROOT / 'pantheon.db'}"
    projects_dir: Path = REPO_ROOT / "projects"
    frontend_origin: str = "http://localhost:3000"
    # Hard cap on output tokens for the test call, to keep dev runs cheap.
    test_call_max_tokens: int = 400


@lru_cache
def get_settings() -> Settings:
    return Settings()
