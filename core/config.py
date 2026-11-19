import os
from datetime import date
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from core.models import Budget

Role = Literal["router", "research", "analyst", "writer", "editor", "figure_planner"]
Tier = Literal["strong", "light"]


class ConfigError(RuntimeError):
    """Raised when a required environment setting is missing or invalid."""


_PREFIX = {
    "router": "ROUTER_AGENT",
    "research": "RESEARCH_AGENT",
    "analyst": "ANALYST_AGENT",
    "writer": "WRITER_AGENT",
    "editor": "EDITOR",
    "figure_planner": "FIGURE_PLANNER",
}

# Judgement-heavy steps get the strong model; short, constrained ones (JSON outlines, length
# rewrites, citation repair, chart and diagram specs) get the light one.
ROLE_TIER: dict[str, Tier] = {
    "router": "strong",
    "research": "strong",
    "analyst": "strong",
    "writer": "strong",
    "editor": "light",
    "figure_planner": "light",
}
TIER_VAR: dict[str, str] = {"strong": "STRONG_LLM", "light": "LIGHT_LLM"}
DEFAULT_TEMP: dict[str, float] = {
    "router": 0.0, "research": 0.3, "analyst": 0.3, "writer": 0.3, "editor": 0.2, "figure_planner": 0.0,
}


@dataclass(frozen=True)
class LLMChoice:
    model: str | None
    temperature: str  # as configured (or the default), for display; parsed by get_llm_settings
    tier: Tier
    source: str  # the variable the model came from, or "" when unset


def _get(env: Mapping[str, str], name: str) -> str | None:
    value = (env.get(name) or "").strip()
    return value or None


def resolve_llm(role: str, pdf: bool = False, env: Mapping[str, str] | None = None) -> LLMChoice:
    """Model lookup order: ROLE_LLM_PDF, TIER_LLM_PDF (PDF mode only), ROLE_LLM, then the tier's model."""
    env = os.environ if env is None else env
    prefix, tier = _PREFIX[role], ROLE_TIER[role]
    names = [f"{prefix}_LLM", TIER_VAR[tier]]
    if pdf:
        names = [f"{prefix}_LLM_PDF", f"{TIER_VAR[tier]}_PDF", *names]
    source = next((n for n in names if _get(env, n)), "")
    temp_names = [f"{prefix}_TEMP_PDF", f"{prefix}_TEMP"] if pdf else [f"{prefix}_TEMP"]
    temp = next((_get(env, n) for n in temp_names if _get(env, n)), None) or str(DEFAULT_TEMP[role])
    return LLMChoice(model=_get(env, source) if source else None, temperature=temp, tier=tier, source=source)


def get_llm_settings(role: Role, pdf: bool = False) -> tuple[str, float]:
    """Return (model, temperature) for a role."""
    choice = resolve_llm(role, pdf)
    prefix = _PREFIX[role]
    if not choice.model:
        raise ConfigError(f"Set {TIER_VAR[choice.tier]} (or {prefix}_LLM) in .env")
    try:
        return choice.model, float(choice.temperature)
    except ValueError as exc:
        raise ConfigError(f"{prefix}_TEMP must be a number, got {choice.temperature!r}") from exc


# Light steps are short and tightly constrained, so long hidden reasoning only adds latency.
# None leaves the model's own default (medium for gpt-oss). Override with STRONG_REASONING /
# LIGHT_REASONING; "default" sends nothing.
TIER_REASONING: dict[str, str | None] = {"strong": None, "light": "low"}
# Per-role exceptions to the tier default: Mermaid syntax comes out broken more often at low effort.
ROLE_REASONING: dict[str, str] = {"figure_planner": "medium"}
# OpenRouter serves gpt-oss from many hosts. We ask for the fastest host, capped at Groq's price in
# USD per million tokens (prompt, completion), so the fastest and dearest hosts are skipped.
TIER_MAX_PRICE: dict[str, tuple[float, float]] = {"strong": (0.15, 0.60), "light": (0.075, 0.30)}
_NO_VALUE = {"default", "none", "off"}


def _max_price(tier: str, env: Mapping[str, str]) -> tuple[float, float] | None:
    name = f"{TIER_VAR[tier].removesuffix('_LLM')}_MAX_PRICE"
    raw = _get(env, name)
    if raw is None:
        return TIER_MAX_PRICE[tier]
    if raw.lower() in _NO_VALUE:
        return None
    try:
        prompt, completion = (float(x) for x in raw.split(","))
    except ValueError as exc:
        raise ConfigError(f'{name} must be "prompt,completion" in USD per million tokens, got {raw!r}') from exc
    return prompt, completion


def llm_options(role: str, pdf: bool = False, env: Mapping[str, str] | None = None) -> dict:
    """Extra LLM kwargs for a role: reasoning effort, and OpenRouter host routing.

    The price cap only applies to the tier's own model (STRONG_LLM / LIGHT_LLM). A role or PDF
    override is usually a pricier model, and a cap sized for gpt-oss would leave it no host.
    """
    env = os.environ if env is None else env
    choice = resolve_llm(role, pdf, env)
    tier = choice.tier
    opts: dict = {}
    # ROLE_REASONING env, then the tier's env, then the role's default, then the tier's default.
    effort = (
        _get(env, f"{_PREFIX[role]}_REASONING")
        or _get(env, f"{tier.upper()}_REASONING")
        or ROLE_REASONING.get(role)
        or TIER_REASONING[tier]
    )
    if effort and effort.lower() != "default":
        opts["reasoning_effort"] = effort
    sort = _get(env, "OPENROUTER_SORT") or "throughput"
    if (choice.model or "").startswith("openrouter/") and sort.lower() not in _NO_VALUE:
        provider: dict = {"sort": sort}
        price = _max_price(tier, env) if choice.source == TIER_VAR[tier] else None
        if price:
            provider["max_price"] = {"prompt": price[0], "completion": price[1]}
        opts["extra_body"] = {"provider": provider}
    return opts


TIER_CAPS: dict[int, Budget] = {
    0: Budget(max_searches=2, max_pages=0, max_pdfs=0, firecrawl_credits=0, timeout_s=60),
    1: Budget(max_searches=5, max_pages=8, max_pdfs=0, firecrawl_credits=0, timeout_s=180),
    2: Budget(max_searches=8, max_pages=15, max_pdfs=5, firecrawl_credits=0, timeout_s=420),
    3: Budget(max_searches=15, max_pages=30, max_pdfs=10, firecrawl_credits=100, timeout_s=900),
}


@dataclass(frozen=True)
class SizePreset:
    words_min: int
    words_max: int
    tables: int
    figures_min: int
    figures_max: int


SIZE_PRESETS: dict[str, SizePreset] = {
    "small": SizePreset(800, 1200, 1, 1, 2),
    "medium": SizePreset(2000, 3000, 2, 3, 4),
    "big": SizePreset(5000, 7000, 4, 6, 8),
}


def today_iso() -> str:
    """Today's date for prompts: models otherwise assume their training cutoff and search for stale years."""
    return date.today().isoformat()
