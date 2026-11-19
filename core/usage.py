"""Tokens, time and cost of a run.

CrewAI reports token counts per model call (not cost), so the cost is an upper bound: tokens times the
price cap the model was routed under (OpenRouter never picks a host above it), or, for a model without
a cap, its dearest host. OpenRouter's own usage total lags by minutes, so it cannot be read per run.
"""
import threading
from collections.abc import Callable, Mapping

import httpx

OPENROUTER = "https://openrouter.ai/api/v1"
PriceFn = Callable[[str], tuple[float, float] | None]


def _key(model: str | None) -> str:
    return (model or "").removeprefix("openrouter/")


class UsageMeter:
    """Counts calls and tokens per model from CrewAI's LLM events while attached."""

    def __init__(self):
        self._lock = threading.Lock()
        self._models: dict[str, dict] = {}
        self._handler = None

    def record(self, model: str | None, usage: Mapping | None) -> None:
        if not model or not usage:
            return
        with self._lock:
            item = self._models.setdefault(_key(model), {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
            item["calls"] += 1
            item["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
            item["completion_tokens"] += int(usage.get("completion_tokens") or 0)

    def totals(self) -> dict[str, dict]:
        with self._lock:
            return {k: dict(v) for k, v in self._models.items()}

    def attach(self) -> None:
        from crewai.events import crewai_event_bus
        from crewai.events.types.llm_events import LLMCallCompletedEvent

        def handler(source, event):
            self.record(event.model, event.usage)

        self._handler = handler
        crewai_event_bus.on(LLMCallCompletedEvent)(handler)

    def detach(self) -> None:
        if self._handler is None:
            return
        from crewai.events import crewai_event_bus
        from crewai.events.types.llm_events import LLMCallCompletedEvent

        crewai_event_bus.flush(timeout=10)  # handlers can run on the bus's own threads
        crewai_event_bus.off(LLMCallCompletedEvent, self._handler)
        self._handler = None


def _dearest_host_price(model: str) -> tuple[float, float] | None:
    """Highest (prompt, completion) price in USD per million tokens among OpenRouter's hosts."""
    try:
        resp = httpx.get(f"{OPENROUTER}/models/{model}/endpoints", timeout=10)
        endpoints = (resp.json().get("data") or {}).get("endpoints") or []
        prices = [(float(e["pricing"]["prompt"]) * 1e6, float(e["pricing"]["completion"]) * 1e6) for e in endpoints]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    return (max(p for p, _ in prices), max(c for _, c in prices)) if prices else None


def estimate_cost(totals: dict[str, dict], env: Mapping[str, str], fetch_max_price: PriceFn | None = None) -> dict:
    """Per-model and total upper-bound cost in USD; the total is None if any model's price is unknown."""
    from tools.setup_check import _model_uses  # the same model and price-cap resolution as --check

    fetch = fetch_max_price or _dearest_host_price
    caps = {_key(m): use["cap"] for m, use in _model_uses(env).items() if use.get("cap")}
    models = {}
    for model, t in totals.items():
        price = caps.get(model) or fetch(model)
        cost = (t["prompt_tokens"] * price[0] + t["completion_tokens"] * price[1]) / 1e6 if price else None
        models[model] = {**t, "max_cost_usd": cost}
    costs = [m["max_cost_usd"] for m in models.values()]
    total = round(sum(costs), 6) if costs and None not in costs else None
    return {"models": models, "max_cost_usd": total}


def _duration(seconds: float) -> str:
    seconds = round(seconds)
    return f"{seconds // 60} min {seconds % 60} s" if seconds >= 60 else f"{seconds} s"


def format_usage(seconds: float, totals: dict[str, dict], cost: dict, sep: str = " · ") -> str:
    """One line for the app and the CLI, e.g. "2 min 21 s · 52 model calls · 424k tokens · at most US$0.05"."""
    parts = [_duration(seconds)]
    calls = sum(t["calls"] for t in totals.values())
    tokens = sum(t["prompt_tokens"] + t["completion_tokens"] for t in totals.values())
    if calls:
        parts.append(f"{calls} model calls")
        parts.append(f"{round(tokens / 1000)}k tokens" if tokens >= 1000 else f"{tokens} tokens")
    usd = cost.get("max_cost_usd")
    if usd is not None and calls:
        parts.append("under US$0.01" if usd < 0.01 else f"at most US${usd:.2f}")
    return sep.join(parts)
