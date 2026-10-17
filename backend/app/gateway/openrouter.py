"""OpenRouter client built on the OpenAI Python SDK. The API key never leaves the server."""

from dataclasses import dataclass

import httpx
from openai import AsyncOpenAI

from app.config import APP_NAME, get_settings


class GatewayError(RuntimeError):
    """Raised when the provider call fails or the gateway is not configured."""


@dataclass
class ChatResult:
    model: str
    content: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None


_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise GatewayError("OPENROUTER_API_KEY is not set in .env")
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            default_headers={"X-Title": APP_NAME},
            max_retries=1,
        )
    return _client


async def chat(
    messages: list[dict[str, str]],
    model: str | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> ChatResult:
    settings = get_settings()
    model = model or settings.default_model
    try:
        resp = await _get_client().chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            timeout=timeout,
            # Ask OpenRouter to report the real cost of the call in `usage`.
            extra_body={"usage": {"include": True}},
        )
    except GatewayError:
        raise
    except Exception as exc:  # provider/network errors
        raise GatewayError(f"{type(exc).__name__}: {exc}") from exc

    if not resp.choices:
        raise GatewayError("Provider returned no choices")

    usage = resp.usage
    cost = None
    if usage is not None:
        cost = (usage.model_extra or {}).get("cost")
    return ChatResult(
        model=resp.model or model,
        content=resp.choices[0].message.content or "",
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        cost_usd=float(cost) if cost is not None else None,
    )


async def fetch_prices() -> dict[str, tuple[float, float]]:
    """USD per token (input, output) for every model OpenRouter lists.

    The model list is public, so no key is sent with this request.
    """
    url = get_settings().openrouter_base_url.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()["data"]
    except Exception as exc:
        raise GatewayError(f"Could not fetch model prices: {exc}") from exc

    prices: dict[str, tuple[float, float]] = {}
    for m in data:
        pricing = m.get("pricing") or {}
        try:
            prices[m["id"]] = (float(pricing["prompt"]), float(pricing["completion"]))
        except (KeyError, TypeError, ValueError):
            continue
    return prices
