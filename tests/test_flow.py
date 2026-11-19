import json

import pytest

from core.config import TIER_CAPS
from flows.research_flow import FlowDeps, ResearchFlow
from tests.fakes import FakeWorker, ScriptedLLM

ROUTER_T2 = json.dumps({"domain": "technical_science", "tier": 2, "rationale": "technical", "subqueries": ["a", "b"]})


def _outline(n=4, total=2500):
    return [{"heading": f"Section {i}", "words": total // n} for i in range(n)]


class Recorder:
    def __init__(self, route_out=ROUTER_T2, research_out="FINDINGS [S1]", analyse_out="ANALYSIS"):
        self.route_out, self.research_out, self.analyse_out = route_out, research_out, analyse_out
        self.route_calls, self.plans = 0, []

    def deps(self, llm=None, worker=None):
        def route(topic):
            self.route_calls += 1
            return self.route_out

        def research(plan, ctx):
            self.plans.append(plan)
            ctx.registry.add("https://a.com", "Alpha", "web", "web_search")
            return self.research_out

        return FlowDeps(
            route=route,
            research=research,
            analyse=lambda findings: self.analyse_out,
            llm=llm or ScriptedLLM(outline=_outline()),
            worker=worker or FakeWorker(),
        )


def _flow(tmp_path, rec, **kw):
    llm = kw.pop("llm", None)
    worker = kw.pop("worker", None)
    return ResearchFlow(kw.pop("topic", "GaN defects"), deps=rec.deps(llm, worker), base_dir=tmp_path, **kw)


def test_empty_topic_raises_before_router(tmp_path):
    rec = Recorder()
    with pytest.raises(ValueError):
        _flow(tmp_path, rec, topic="   ").run()
    assert rec.route_calls == 0


def test_router_garbage_defaults_to_tier1_and_flow_completes(tmp_path):
    rec = Recorder(route_out="I refuse to output JSON")
    result = _flow(tmp_path, rec).run()
    assert result.plan.tier == 1
    assert result.plan.warnings
    assert result.markdown_path.exists()
    assert any("defaulted to tier 1" in n for n in result.notes)


def test_stage_events_order_markdown_path(tmp_path):
    events = []
    _flow(tmp_path, Recorder(), on_stage=lambda s, st: events.append((s, st))).run()
    assert events == [
        ("route", "start"), ("route", "done"),
        ("research", "start"), ("research", "done"),
        ("analyse", "start"), ("analyse", "done"),
        ("write", "start"), ("write", "done"),
    ]


def test_run_writes_files_in_run_dir_only(tmp_path):
    before = set(p.name for p in tmp_path.parent.iterdir())
    result = _flow(tmp_path, Recorder()).run()
    names = {p.name for p in result.run_dir.iterdir()}
    assert {"plan.json", "findings.md", "analysis.md", "gan-defects-report.md", "sources.json", "log.jsonl"} <= names
    assert tmp_path in result.run_dir.parents
    assert set(p.name for p in tmp_path.parent.iterdir()) == before


def test_worker_down_adds_coverage_note_and_completes(tmp_path):
    result = _flow(tmp_path, Recorder(), worker=FakeWorker(healthy=False)).run()
    assert any("worker" in n.lower() for n in result.notes)
    assert "## Coverage notes" in result.markdown_path.read_text(encoding="utf-8")


def test_forced_tier_passed_to_research(tmp_path):
    rec = Recorder()
    _flow(tmp_path, rec, forced_tier=3).run()
    assert rec.plans[0].tier == 3
    assert rec.plans[0].budget.max_pages == TIER_CAPS[3].max_pages


def test_size_passed_to_writer(tmp_path):
    llm = ScriptedLLM()
    result = _flow(tmp_path, Recorder(), size="small", llm=llm).run()
    assert llm.calls == ["SMALL_REQUEST"]
    assert result.words > 0


def test_research_crash_is_noted_not_fatal(tmp_path):
    rec = Recorder()
    deps = rec.deps()
    deps.research = lambda plan, ctx: (_ for _ in ()).throw(RuntimeError("model exploded"))
    result = ResearchFlow("topic", deps=deps, base_dir=tmp_path).run()
    assert any("model exploded" in n for n in result.notes)


class FigureLLM:
    def __init__(self):
        self.calls = []

    def __call__(self, prompt):
        kind = prompt.split("\n", 1)[0]
        self.calls.append(kind)
        if kind == "FIGURE_PLAN_REQUEST":
            return json.dumps([{"kind": "bar", "title": "Papers per year", "data_ref": "papers_per_year.csv",
                                "x": "year", "y": "papers", "caption": "Publication volume", "source_ids": []}])
        if kind == "DIAGRAM_REQUEST":
            return json.dumps([{"code": "flowchart LR\n A-->B", "caption": "Process"}])
        return "[]"


def _pdf_flow(tmp_path, worker=None, events=None):
    rec = Recorder()
    deps = rec.deps(worker=worker)
    deps.figure_llm = FigureLLM()
    deps.year_counts = lambda q, e: {2020: 5, 2021: 9, 2022: 14}
    return ResearchFlow(
        "GaN defects", pdf=True, size="medium", deps=deps, base_dir=tmp_path,
        on_stage=(lambda s, st: events.append((s, st))) if events is not None else None,
    ), deps


def test_pdf_mode_runs_figures_and_render_stages(tmp_path):
    events = []
    flow, deps = _pdf_flow(tmp_path, events=events)
    result = flow.run()
    assert [e[0] for e in events if e[1] == "start"] == ["route", "research", "analyse", "figures", "write", "render"]
    assert result.pdf_path is not None and result.pdf_path.read_bytes().startswith(b"%PDF")
    assert (result.run_dir / "figures" / "fig1.svg").exists()
    assert result.markdown_path.exists()
    assert deps.figure_llm.calls == ["FIGURE_PLAN_REQUEST", "DIAGRAM_REQUEST"]


def test_pdf_render_failure_keeps_markdown(tmp_path):
    flow, _ = _pdf_flow(tmp_path, worker=FakeWorker(healthy=False))
    result = flow.run()
    assert result.pdf_path is None
    assert result.markdown_path.exists()
    assert any("pdf" in n.lower() and "failed" in n.lower() for n in result.notes)


def test_markdown_mode_never_emits_figure_stages(tmp_path):
    events = []
    _flow(tmp_path, Recorder(), on_stage=lambda s, st: events.append(s)).run()
    assert "figures" not in events and "render" not in events


def test_report_file_named_after_topic(tmp_path):
    result = _flow(tmp_path, Recorder(), topic="Quantum Dots: A Review!").run()
    assert result.markdown_path.name == "quantum-dots-a-review-report.md"


def test_pdf_named_after_topic(tmp_path):
    flow, _ = _pdf_flow(tmp_path)
    result = flow.run()
    assert result.pdf_path.name == "gan-defects-report.pdf"


def test_non_ascii_topic_still_gets_a_usable_name(tmp_path):
    result = _flow(tmp_path, Recorder(), topic="量子コンピュータ").run()
    assert result.markdown_path.name == "topic-report.md"


def test_cancel_before_start_stops_at_first_stage(tmp_path):
    import threading
    from flows.research_flow import ResearchCancelled
    ev = threading.Event()
    ev.set()
    rec = Recorder()
    flow = ResearchFlow("GaN defects", deps=rec.deps(), base_dir=tmp_path, cancel=ev)
    with pytest.raises(ResearchCancelled):
        flow.run()
    assert rec.route_calls == 0


def test_cancel_after_research_skips_analysis_and_writing(tmp_path):
    import threading
    from flows.research_flow import ResearchCancelled
    ev = threading.Event()
    rec = Recorder()
    deps = rec.deps()
    inner = deps.research

    def research_then_cancel(plan, ctx):
        out = inner(plan, ctx)
        ev.set()
        return out

    deps.research = research_then_cancel
    analysed = []
    deps.analyse = lambda f: analysed.append(1) or "A"
    flow = ResearchFlow("GaN defects", deps=deps, base_dir=tmp_path, cancel=ev)
    with pytest.raises(ResearchCancelled) as err:
        flow.run()
    assert analysed == []
    run_dir = err.value.run_dir
    assert (run_dir / "findings.md").exists()  # partial work is kept
    assert not list(run_dir.glob("*-report.md"))
