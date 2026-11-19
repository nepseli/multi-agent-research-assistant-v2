"""Agents and crews are built per run, so models, tools and budgets can differ between runs."""
import logging
import os
import textwrap

from crewai import LLM, Agent, Crew, Process, Task

from core.config import get_llm_settings, llm_options
from core.models import ResearchPlan
from core.run_context import RunContext
from flows.research_flow import FlowDeps
from report.writer import LLMFn
from tools.research_tools import build_tools
from tools.worker_client import WorkerClient

class _HideApproxTokenCount(logging.Filter):
    """CrewAI warns on every tool result that it is estimating tokens as characters / 4 because
    OpenRouter models have no native counter. The estimate is harmless and only used for a
    context-size check, so the warning is noise."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not str(record.msg).startswith("Using an approximate input token count")


_base_llm_log = logging.getLogger("crewai.llms.base_llm")
if not any(type(f).__name__ == _HideApproxTokenCount.__name__ for f in _base_llm_log.filters):  # once, even on reload
    _base_llm_log.addFilter(_HideApproxTokenCount())

_TIER_GUIDE = textwrap.dedent(
    """\
    Tier 0: a simple factual or everyday question (weather, a recipe, a quick how-to). One quick search is enough.
    Tier 1: a general topic that needs several sources and some reading of web pages.
    Tier 2: a technical or scientific topic that needs journals, preprints and open-access papers.
    Tier 3: a deep literature-review style topic that needs wide coverage, citation follow-up and gap checking."""
)


def router_prompt(topic: str) -> str:
    return textwrap.dedent(
        f"""\
        Classify the research topic and plan how deeply to search. Reply with ONLY a JSON object, no prose.

        Topic: {topic}

        Tiers:
        {_TIER_GUIDE}

        JSON fields:
        - "domain": one of general, news, technical_science, patents_standards, how_to, other
        - "tier": integer 0, 1, 2 or 3
        - "rationale": one short sentence explaining the tier
        - "subqueries": 2 to 6 focused search queries (1 to 2 for tier 0)
        Do not include budgets; they are set by the system."""
    )


def _llm(role: str, pdf: bool) -> LLM:
    model, temperature = get_llm_settings(role, pdf=pdf)
    return LLM(model=model, temperature=temperature, **llm_options(role, pdf))


def make_llm_fn(role: str, pdf: bool = False) -> LLMFn:
    llm = _llm(role, pdf)
    return lambda prompt: str(llm.call(prompt))


def build_router_agent(pdf: bool = False) -> Agent:
    return Agent(
        role="Research Router",
        goal="Decide how deeply and with which tools a topic should be researched",
        backstory="You triage research requests so simple questions stay cheap and technical ones get deep, scholarly coverage.",
        llm=_llm("router", pdf),
        verbose=False,
    )


def route_topic(topic: str, pdf: bool = False) -> str:
    agent = build_router_agent(pdf)
    task = Task(description=router_prompt(topic), expected_output="A single JSON object", agent=agent)
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
    return crew.kickoff().raw


def _research_description(plan: ResearchPlan) -> str:
    b = plan.budget
    steps = [
        f"Research the topic: {plan.topic}",
        f"Domain: {plan.domain}. Depth tier: {plan.tier}. Starting queries: {'; '.join(plan.subqueries)}.",
        f"Budget: at most {b.max_searches} searches, {b.max_pages} page reads, {b.max_pdfs} PDF reads. "
        "Tools report BUDGET EXHAUSTED when a limit is reached; then stop using that tool.",
    ]
    if plan.tier == 0:
        steps.append("This is a simple question: one or two searches are enough. Keep the answer short.")
    else:
        steps.append("Search first, then read the most relevant and most authoritative pages.")
    if plan.use_academic:
        steps.append(
            "Also use academic_search for journals, proceedings and preprints, and read_open_access_pdf "
            "for open-access papers. Never try to fetch paywalled content; use abstracts for those."
        )
    if plan.tier == 3:
        steps.append(
            "After the first pass, list the gaps in coverage and run up to two more rounds of targeted "
            "searches or citation follow-ups to fill them (gap check)."
        )
    steps.append(
        "Cite every fact with the [S#] ids shown in tool output. Never invent ids, URLs or papers. "
        "Output: key findings with [S#] after each claim, important statistics, differing views, and open gaps."
    )
    return "\n".join(steps)


def _settings() -> dict:
    return {
        "email": os.getenv("OPENALEX_EMAIL") or os.getenv("UNPAYWALL_EMAIL") or "",
        "semantic_scholar_key": os.getenv("SEMANTIC_SCHOLAR_API_KEY") or None,
        "firecrawl_api_key": os.getenv("FIRECRAWL_API_KEY") or None,
    }


def build_research_crew(plan: ResearchPlan, ctx: RunContext, worker, pdf: bool = False, settings: dict | None = None) -> Crew:
    tools = build_tools(plan, ctx, worker, settings if settings is not None else _settings())
    agent = Agent(
        role="Research Specialist",
        goal="Gather accurate, well-sourced information and cite every claim with its source id",
        backstory=(
            "You are a careful researcher. You prefer primary and scholarly sources, check claims across "
            "sources and never cite anything you did not retrieve."
        ),
        llm=_llm("research", pdf),
        tools=tools,
        verbose=False,
        max_execution_time=plan.budget.timeout_s,
    )
    task = Task(
        description=_research_description(plan),
        expected_output="Structured findings with [S#] citations, statistics, differing views and gaps",
        agent=agent,
    )
    return Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)


def build_analyst_crew(pdf: bool = False) -> Crew:
    agent = Agent(
        role="Data Analyst",
        goal="Extract patterns, trends, implications and conclusions from research findings",
        backstory="You synthesise complex findings into insight, and you keep every claim tied to its [S#] source.",
        llm=_llm("analyst", pdf),
        verbose=False,
    )
    task = Task(
        description=(
            "Analyse these research findings. Identify patterns, trends, implications and the most important "
            "conclusions. Keep the [S#] citations. Do not add sources that are not in the findings.\n\n{findings}"
        ),
        expected_output="An analysis with insights, trends, implications and actionable conclusions, with [S#] citations",
        agent=agent,
    )
    return Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)


def default_deps(pdf: bool = False, worker_url: str | None = None) -> FlowDeps:
    worker = WorkerClient(worker_url or os.getenv("WORKER_URL", "http://localhost:8000"))
    return FlowDeps(
        route=lambda topic: route_topic(topic, pdf),
        research=lambda plan, ctx: build_research_crew(plan, ctx, worker, pdf).kickoff().raw,
        analyse=lambda findings: build_analyst_crew(pdf).kickoff(inputs={"findings": findings}).raw,
        llm=make_llm_fn("writer", pdf),
        worker=worker,
        figure_llm=make_llm_fn("figure_planner", pdf),
        edit_llm=make_llm_fn("editor", pdf),
    )
