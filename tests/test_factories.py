import pytest

from core.config import TIER_CAPS
from core.models import ResearchPlan
from core.run_context import new_run
from crews import factories
from flows.research_flow import FlowDeps
from tests.fakes import FakeWorker


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for prefix in ("ROUTER_AGENT", "RESEARCH_AGENT", "ANALYST_AGENT", "WRITER_AGENT", "EDITOR", "FIGURE_PLANNER", "FACT_CHECKER"):
        for suffix in ("_LLM", "_TEMP", "_LLM_PDF", "_TEMP_PDF"):
            monkeypatch.delenv(prefix + suffix, raising=False)
    for name in ("STRONG_LLM_PDF", "LIGHT_LLM_PDF", "STRONG_REASONING", "LIGHT_REASONING", "FIGURE_PLANNER_REASONING", "EDITOR_REASONING",
                 "OPENROUTER_SORT", "STRONG_MAX_PRICE", "LIGHT_MAX_PRICE", "CLAIM_CHECK"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STRONG_LLM", "openrouter/openai/gpt-oss-120b")
    monkeypatch.setenv("LIGHT_LLM", "openrouter/openai/gpt-oss-20b")
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
    assert "gpt-oss-120b" in base.agents[0].llm.model


def test_research_agent_uses_strong_tier(tmp_path):
    ctx = new_run("t", base=tmp_path)
    crew = factories.build_research_crew(_plan(1), ctx, FakeWorker(), pdf=False)
    assert "gpt-oss-120b" in crew.agents[0].llm.model


def test_default_deps_gives_writer_and_editor_separate_models(monkeypatch):
    built = []
    monkeypatch.setattr(factories, "make_llm_fn", lambda role, pdf=False: built.append(role) or (lambda p: ""))
    deps = factories.default_deps(pdf=False, worker_url="http://localhost:9")
    assert {"writer", "editor", "figure_planner"} <= set(built)
    assert callable(deps.edit_llm)


def test_default_deps_returns_callables():
    deps = factories.default_deps(pdf=False, worker_url="http://localhost:9")
    assert isinstance(deps, FlowDeps)
    assert all(callable(f) for f in (deps.route, deps.research, deps.analyse, deps.llm))


def test_llms_carry_reasoning_and_routing_options():
    editor = factories._llm("editor", pdf=False)
    assert editor.reasoning_effort == "low"
    assert editor.additional_params["extra_body"]["provider"]["sort"] == "throughput"
    assert factories._llm("writer", pdf=False).reasoning_effort is None


def test_approximate_token_count_warning_is_hidden_but_other_warnings_are_not(caplog):
    import logging

    log = logging.getLogger("crewai.llms.base_llm")
    with caplog.at_level(logging.WARNING, logger="crewai.llms.base_llm"):
        log.warning("Using an approximate input token count for model %r: assuming one token per four characters", "m")
        log.warning("something else went wrong")
    assert "approximate input token count" not in caplog.text
    assert "something else went wrong" in caplog.text


def test_research_prompt_has_date_source_ranking_and_citation_format(monkeypatch):
    monkeypatch.setattr(factories, "today_iso", lambda: "2026-11-19")
    text = factories._research_description(_plan(2))
    assert "2026-11-19" in text
    assert "official" in text.lower() and "social media" in text.lower()
    assert "publication date" in text.lower()
    assert "[S3]" in text and "【" in text


def test_analyst_prompt_has_date_and_keeps_only_the_findings_placeholder(monkeypatch):
    import re

    monkeypatch.setattr(factories, "today_iso", lambda: "2026-11-19")
    description = factories.build_analyst_crew().tasks[0].description
    assert "2026-11-19" in description and "[S3]" in description
    assert re.findall(r"\{(\w+)\}", description) == ["findings"]  # CrewAI fills {placeholders} from inputs


def test_router_prompt_knows_the_date_so_queries_are_not_stale(monkeypatch):
    monkeypatch.setattr(factories, "today_iso", lambda: "2026-11-19")
    prompt = factories.router_prompt("agentic AI in Singapore")
    assert "2026-11-19" in prompt and "year" in prompt.lower()


def test_default_deps_include_a_fact_checker_unless_switched_off(monkeypatch):
    assert factories.default_deps().check_llm is not None
    monkeypatch.setenv("CLAIM_CHECK", "off")
    assert factories.default_deps().check_llm is None


def test_research_prompt_asks_to_read_pages_not_rely_on_snippets():
    text = factories._research_description(_plan(1))
    assert "Read at least" in text and "snippet" in text.lower()
