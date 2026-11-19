import pytest

from core.config import TIER_CAPS
from core.models import ResearchPlan
from core.run_context import new_run
from crews import factories
from flows.research_flow import FlowDeps
from tests.fakes import FakeWorker


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for prefix in ("ROUTER_AGENT", "RESEARCH_AGENT", "ANALYST_AGENT", "WRITER_AGENT", "FIGURE_PLANNER"):
        monkeypatch.setenv(f"{prefix}_LLM", "openrouter/openai/gpt-oss-20b")
        monkeypatch.setenv(f"{prefix}_TEMP", "0.3")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")


def _plan(tier):
    return ResearchPlan(
        topic="GaN defects", tier=tier, budget=TIER_CAPS[tier], subqueries=["gan defects", "gan epitaxy"],
        use_academic=tier >= 2, use_pdf_parsing=tier >= 2, domain="technical_science",
    )


def test_router_prompt_lists_tiers_and_schema():
    prompt = factories.router_prompt("GaN defects")
    for needle in ("tier", "subqueries", "domain", "GaN defects", "0", "3"):
        assert needle in prompt


def test_research_crew_has_tools_matching_tier(tmp_path):
    ctx = new_run("t", base=tmp_path)
    crew = factories.build_research_crew(_plan(2), ctx, FakeWorker(), pdf=False)
    names = {t.name for t in crew.agents[0].tools}
    assert {"web_search", "read_page", "academic_search", "read_open_access_pdf"} <= names
    crew0 = factories.build_research_crew(_plan(0), ctx, FakeWorker(), pdf=False)
    assert {t.name for t in crew0.agents[0].tools} == {"web_search"}


def test_research_task_mentions_budget_and_subqueries(tmp_path):
    ctx = new_run("t", base=tmp_path)
    crew = factories.build_research_crew(_plan(3), ctx, FakeWorker(), pdf=False)
    text = crew.tasks[0].description
    assert "gan epitaxy" in text and "15" in text and "gap" in text.lower()


def test_pdf_mode_uses_pdf_model_override(monkeypatch):
    monkeypatch.setenv("ANALYST_AGENT_LLM_PDF", "openrouter/openai/gpt-5")
    monkeypatch.setenv("ANALYST_AGENT_TEMP_PDF", "0.2")
    crew = factories.build_analyst_crew(pdf=True)
    assert "gpt-5" in crew.agents[0].llm.model
    base = factories.build_analyst_crew(pdf=False)
    assert "gpt-oss-20b" in base.agents[0].llm.model


def test_default_deps_returns_callables():
    deps = factories.default_deps(pdf=False, worker_url="http://localhost:9")
    assert isinstance(deps, FlowDeps)
    assert all(callable(f) for f in (deps.route, deps.research, deps.analyse, deps.llm))
