import json
import math
import re
from datetime import date

from core.config import TIER_CAPS
from core.models import Budget, ResearchPlan

_FALLBACK_WARNING = "router output invalid; defaulted to tier 1"
_HARD_MULT = 1.5


def _fallback(topic: str) -> ResearchPlan:
    return ResearchPlan(
        topic=topic,
        domain="general",
        tier=1,
        rationale="Fallback plan",
        subqueries=[topic],
        budget=TIER_CAPS[1],
        warnings=[_FALLBACK_WARNING],
    )


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object found")
        text = text[start : end + 1]
    return json.loads(text)


# A year, or a range like 2023-2025, as a whole word.
_YEARS = re.compile(r"\s*\b((?:19|20)\d{2})(?:\s*[-–/]\s*((?:19|20)\d{2}))?\b")
STALE_YEARS = 6  # years before this one that a model adds from habit; older ones are deliberate history


def drop_stale_years(query: str, topic: str, year: int) -> str:
    """Remove recent-past years the topic did not ask for: models add their training-data years
    ("... 2024"), which narrows search to old results."""

    def repl(m: re.Match) -> str:
        latest = int(m.group(2) or m.group(1))
        if latest >= year or latest < year - STALE_YEARS or m.group(1) in topic:
            return m.group(0)
        return ""

    return " ".join(_YEARS.sub(repl, query).split()) or query


def parse_plan(raw: str | dict, topic: str, year: int | None = None) -> ResearchPlan:
    """Parse router output into a plan; any failure falls back to a Tier 1 plan."""
    try:
        data = dict(raw) if isinstance(raw, dict) else _extract_json(raw)
        tier = data.get("tier")
        if not isinstance(tier, int) or isinstance(tier, bool) or tier not in TIER_CAPS:
            raise ValueError(f"invalid tier {tier!r}")
        data["topic"] = topic
        data.setdefault("subqueries", [topic])
        if not data["subqueries"]:
            data["subqueries"] = [topic]
        this_year = year or date.today().year
        data["subqueries"] = [drop_stale_years(str(q), topic, this_year) for q in data["subqueries"]]
        data["budget"] = data.get("budget") or TIER_CAPS[tier].model_dump()
        data.pop("warnings", None)
        return ResearchPlan(**data)
    except Exception:
        return _fallback(topic)


def _ceil(value: float) -> int:
    return math.ceil(round(value, 6))


def finalize_plan(
    plan: ResearchPlan, *, pdf: bool, size: str, forced_tier: int | None
) -> ResearchPlan:
    """Apply user overrides, tier bump, size/PDF multipliers and hard ceilings."""
    warnings = list(plan.warnings)
    tier = plan.tier
    tier_changed = False
    if forced_tier is not None:
        tier_changed = forced_tier != plan.tier
        tier = forced_tier
    if tier == 0 and (pdf or size == "big"):
        tier = 1
        tier_changed = True
        warnings.append("Tier 0 bumped to Tier 1 because PDF mode or Big size needs source material")

    caps = TIER_CAPS[tier]
    if forced_tier is not None or tier_changed:
        base = caps
    else:
        base = Budget(
            max_searches=min(plan.budget.max_searches, caps.max_searches),
            max_pages=min(plan.budget.max_pages, caps.max_pages),
            max_pdfs=min(plan.budget.max_pdfs, caps.max_pdfs),
            firecrawl_credits=min(plan.budget.firecrawl_credits, caps.firecrawl_credits),
            timeout_s=min(plan.budget.timeout_s, caps.timeout_s),
        )

    searches, pages, pdfs = base.max_searches, base.max_pages, base.max_pdfs
    timeout = base.timeout_s
    if pdf:
        searches, pages, pdfs = (_ceil(v * 1.5) for v in (searches, pages, pdfs))
        timeout = _ceil(timeout * 1.5)
    if size == "big":
        pages, pdfs = _ceil(pages * 1.25), _ceil(pdfs * 1.25)

    ceiling = TIER_CAPS[3]
    budget = Budget(
        max_searches=min(searches, _ceil(ceiling.max_searches * _HARD_MULT)),
        max_pages=min(pages, _ceil(ceiling.max_pages * _HARD_MULT)),
        max_pdfs=min(pdfs, _ceil(ceiling.max_pdfs * _HARD_MULT)),
        firecrawl_credits=min(base.firecrawl_credits, ceiling.firecrawl_credits),
        timeout_s=min(timeout, _ceil(ceiling.timeout_s * _HARD_MULT)),
    )
    return plan.model_copy(
        update={
            "tier": tier,
            "budget": budget,
            "use_academic": tier >= 2,
            "use_pdf_parsing": tier >= 2,
            "warnings": warnings,
        }
    )
