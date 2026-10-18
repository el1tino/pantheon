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

    # Debate engine
    seats_file: Path = REPO_ROOT / "config" / "seats.yaml"
    moderator_model: str = "openai/gpt-4o-mini"
    max_rounds: int = 3
    default_budget_usd: float = 0.25
    reply_max_tokens: int = 500
    make_max_tokens: int = 1400  # a seat writing its part of the work
    verdict_max_tokens: int = 2000  # the moderator assembling the deliverable
    build_max_tokens: int = 4000  # a seat writing files in the build phase
    call_timeout_s: float = 90.0
    # Image consultants. A provider without a key is unavailable; "practice" needs none.
    recraft_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    bfl_api_key: str = ""
    seedream_api_key: str = ""
    openai_image_model: str = "gpt-image-1"
    gemini_image_model: str = "gemini-2.5-flash-image"
    flux_model: str = "flux-pro-1.1"
    seedream_model: str = "seedream-3-0-t2i-250415"
    # Estimated USD per image, checked against the budget cap before each request.
    image_prices: dict[str, float] = {
        "recraft": 0.08, "openai": 0.07, "gemini": 0.04, "flux": 0.06, "seedream": 0.03, "practice": 0.0,
    }
    # Integrate phase: the Docker runner (backend/runner/) and its limits
    runner_image: str = "pantheon-runner:1"
    runner_timeout_s: float = 30.0
    runner_memory: str = "256m"
    runner_cpus: float = 1.0
    # Used to estimate cost when OpenRouter's price list is unavailable.
    # Deliberately high so estimates err on the safe side (USD per 1M tokens).
    fallback_price_in_per_mtok: float = 5.0
    fallback_price_out_per_mtok: float = 20.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
