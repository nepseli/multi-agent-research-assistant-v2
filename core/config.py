import os
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
