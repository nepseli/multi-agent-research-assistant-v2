import pytest
from pydantic import ValidationError

from core.config import TIER_CAPS
from core.models import FigureSpec, ResearchPlan


def _plan(**kw):
    base = dict(
        topic="t", domain="general", tier=1, rationale="r", subqueries=["q"],
        use_academic=False, use_pdf_parsing=False, budget=TIER_CAPS[1],
    )
    base.update(kw)
    return ResearchPlan(**base)


def test_plan_rejects_tier_out_of_range():
    with pytest.raises(ValidationError):
        _plan(tier=4)


def test_plan_accepts_valid_tier():
    assert _plan(tier=3).tier == 3


def test_figure_spec_requires_data_ref():
    with pytest.raises(ValidationError):
        FigureSpec(kind="bar", title="t", data_ref="", x="a", y="b", caption="c", source_ids=[])
