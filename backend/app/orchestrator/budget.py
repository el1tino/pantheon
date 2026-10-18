"""Hard budget cap: estimate before every call, record the real cost after."""

from dataclasses import dataclass, field

from app.config import get_settings

WARN_RATIO = 0.8


def usd(value: float) -> str:
    """Dollars with enough precision that small dev budgets don't show as $0.00."""
    return f"${value:.2f}" if value >= 1 else f"${value:.4f}"


class BudgetExceeded(Exception):
    def __init__(self, spent: float, estimate: float, cap: float):
        super().__init__(f"Call estimated at {usd(estimate)} would exceed the {usd(cap)} cap")
        self.spent, self.estimate, self.cap = spent, estimate, cap


def estimate_tokens(messages: list[dict[str, str]]) -> int:
    # Rough and slightly pessimistic: ~4 characters per token plus per-message overhead.
    return sum(len(m.get("content", "")) // 4 + 8 for m in messages)


@dataclass
class Budget:
    cap_usd: float
    prices: dict[str, tuple[float, float]] = field(default_factory=dict)
    spent_usd: float = 0.0
    reserved_usd: float = 0.0  # estimates of calls still in flight

    def price(self, model: str) -> tuple[float, float]:
        if model in self.prices:
            return self.prices[model]
        s = get_settings()
        return s.fallback_price_in_per_mtok / 1e6, s.fallback_price_out_per_mtok / 1e6

    def estimate(self, model: str, messages: list[dict[str, str]], max_tokens: int) -> float:
        p_in, p_out = self.price(model)
        return estimate_tokens(messages) * p_in + max_tokens * p_out

    def check(self, estimate: float) -> None:
        """Raise BudgetExceeded if this call could take spending past the cap."""
        if self.spent_usd + self.reserved_usd + estimate > self.cap_usd:
            raise BudgetExceeded(self.spent_usd + self.reserved_usd, estimate, self.cap_usd)

    def actual_cost(
        self, model: str, prompt_tokens: int, completion_tokens: int, reported: float | None
    ) -> float:
        if reported is not None:
            return reported
        p_in, p_out = self.price(model)
        return prompt_tokens * p_in + completion_tokens * p_out

    def record(self, cost: float) -> None:
        self.spent_usd += cost

    @property
    def ratio(self) -> float:
        return self.spent_usd / self.cap_usd if self.cap_usd > 0 else 1.0

    @property
    def warning(self) -> bool:
        return self.ratio >= WARN_RATIO - 1e-9  # tolerate float rounding at exactly 80%
