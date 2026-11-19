import json

from core.config import TIER_CAPS
from core.models import ResearchPlan
from core.planning import finalize_plan, parse_plan


def _plan(tier=1, **kw):
    base = dict(
        topic="t", domain="general", tier=tier, rationale="r", subqueries=["q"],
        use_academic=False, use_pdf_parsing=False, budget=TIER_CAPS[tier],
    )
    base.update(kw)
    return ResearchPlan(**base)


def test_parse_plan_accepts_fenced_json():
    raw = "```json\n" + json.dumps({"domain": "technical_science", "tier": 2, "rationale": "x", "subqueries": ["a", "b"]}) + "\n```"
    plan = parse_plan(raw, "GaN defects")
    assert plan.tier == 2 and plan.topic == "GaN defects"
    assert plan.budget == TIER_CAPS[2]
    assert plan.subqueries == ["a", "b"]


def test_parse_plan_falls_back_on_garbage():
    plan = parse_plan("sorry I cannot do that", "recipe")
    assert plan.tier == 1
    assert plan.warnings == ["router output invalid; defaulted to tier 1"]
    assert plan.subqueries == ["recipe"]


def test_parse_plan_falls_back_on_tier_9():
    plan = parse_plan({"tier": 9, "domain": "x"}, "topic")
    assert plan.tier == 1 and plan.warnings


def test_finalize_bumps_tier0_for_pdf():
    out = finalize_plan(_plan(0), pdf=True, size="medium", forced_tier=None)
    assert out.tier == 1
    assert any("tier 0" in w.lower() for w in out.warnings)


def test_finalize_bumps_tier0_for_big():
    out = finalize_plan(_plan(0), pdf=False, size="big", forced_tier=None)
    assert out.tier == 1


def test_finalize_applies_pdf_multiplier():
    out = finalize_plan(_plan(1), pdf=True, size="medium", forced_tier=None)
    assert out.budget.max_pages == 12
    assert out.budget.max_searches == 8  # ceil(5 * 1.5)


def test_finalize_big_multiplies_pages_not_searches():
    out = finalize_plan(_plan(1), pdf=False, size="big", forced_tier=None)
    assert out.budget.max_pages == 10
    assert out.budget.max_searches == 5


def test_finalize_pdf_and_big_stack():
    out = finalize_plan(_plan(1), pdf=True, size="big", forced_tier=None)
    assert out.budget.max_pages == 15


def test_finalize_clamps_router_inflated_budget():
    inflated = TIER_CAPS[1].model_copy(update={"max_pages": 500, "max_searches": 400})
    out = finalize_plan(_plan(1, budget=inflated), pdf=False, size="medium", forced_tier=None)
    assert out.budget.max_pages == TIER_CAPS[1].max_pages
    assert out.budget.max_searches == TIER_CAPS[1].max_searches


def test_never_exceeds_hard_ceiling():
    out = finalize_plan(_plan(3), pdf=True, size="big", forced_tier=None)
    assert out.budget.max_pages <= 45
    assert out.budget.max_pdfs <= 15
    assert out.budget.max_searches <= 23


def test_forced_tier_overrides_router():
    out = finalize_plan(_plan(1), pdf=False, size="medium", forced_tier=3)
    assert out.tier == 3
    assert out.budget.max_pages == TIER_CAPS[3].max_pages


def test_tier2_enables_academic_and_pdf_parsing():
    out = finalize_plan(_plan(2), pdf=False, size="medium", forced_tier=None)
    assert out.use_academic and out.use_pdf_parsing
    low = finalize_plan(_plan(1, use_academic=True), pdf=False, size="medium", forced_tier=None)
    assert not low.use_academic and not low.use_pdf_parsing
