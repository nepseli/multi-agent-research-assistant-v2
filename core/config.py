import os
from dataclasses import dataclass
from typing import Literal

from core.models import Budget

Role = Literal["router", "research", "analyst", "writer", "figure_planner"]


class ConfigError(RuntimeError):
    """Raised when a required environment setting is missing or invalid."""


_PREFIX = {
    "router": "ROUTER_AGENT",
    "research": "RESEARCH_AGENT",
    "analyst": "ANALYST_AGENT",
    "writer": "WRITER_AGENT",
    "figure_planner": "FIGURE_PLANNER",
}


def _read(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def get_llm_settings(role: Role, pdf: bool = False) -> tuple[str, float]:
    """Return (model, temperature) for a role. PDF overrides use the _PDF suffix."""
    prefix = _PREFIX[role]
    model = temp = None
    if pdf:
        model = _read(f"{prefix}_LLM_PDF")
        temp = _read(f"{prefix}_TEMP_PDF")
    model = model or _read(f"{prefix}_LLM")
    temp = temp or _read(f"{prefix}_TEMP")
    if not model or temp is None:
        raise ConfigError(f"Set {prefix}_LLM and {prefix}_TEMP in .env")
    try:
        return model, float(temp)
    except ValueError as exc:
        raise ConfigError(f"{prefix}_TEMP must be a number, got {temp!r}") from exc


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
