"""ResearchFlow: router -> tiered research -> analysis -> report (Markdown, optionally PDF)."""
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

import os

from core.config import SIZE_PRESETS
from core.models import FigureSpec, ResearchPlan
from core.planning import finalize_plan, parse_plan
from core.run_context import RunContext, new_run
from report.charts import render_chart
from report.diagrams import plan_diagrams
from report.figures import build_bibliometric_tables, describe_tables, plan_figures, validate_specs
from report.pdf import PdfRenderError, build_html, render
from report.writer import LLMFn, write_report

StageCallback = Callable[[str, str], None]


class ResearchCancelled(Exception):
    """Raised when the user stops a run. Partial work stays in run_dir (None if stopped before it existed)."""

    def __init__(self, run_dir: Path | None = None):
        super().__init__("Research stopped by user.")
        self.run_dir = run_dir


@dataclass
class FlowDeps:
    """Injectable collaborators. Tests replace them; real ones come from crews.factories."""

    route: Callable[[str], str]
    research: Callable[[ResearchPlan, RunContext], str]
    analyse: Callable[[str], str]
    llm: LLMFn
    worker: object
    figure_llm: LLMFn | None = None
    edit_llm: LLMFn | None = None  # outline, length adjustment and citation repair; defaults to llm
    year_counts: Callable[[str, str | None], dict[int, int]] | None = None


@dataclass
class RunResult:
    run_dir: Path
    plan: ResearchPlan
    markdown_path: Path
    pdf_path: Path | None
    words: int
    notes: list[str] = field(default_factory=list)


class _State(BaseModel):
    done: bool = False


class ResearchFlow(Flow[_State]):
    def __init__(
        self,
        topic: str,
        *,
        pdf: bool = False,
        size: str = "medium",
        forced_tier: int | None = None,
        on_stage: StageCallback | None = None,
        deps: FlowDeps | None = None,
        base_dir: Path = Path("runs"),
        cancel: threading.Event | None = None,
    ):
        super().__init__(suppress_flow_events=True)
        self.topic = topic.strip()
        self.pdf = pdf
        self.size = size
        self.forced_tier = forced_tier
        self.on_stage = on_stage
        self.base_dir = Path(base_dir)
        self._deps = deps
        self.cancel = cancel
        self.notes: list[str] = []
        self.plan: ResearchPlan | None = None
        self.ctx: RunContext | None = None
        self.findings = ""
        self.analysis = ""
        self.result: RunResult | None = None
        self.figures: list[tuple[FigureSpec, Path]] = []
        self.diagrams: list[str] = []

    @property
    def deps(self) -> FlowDeps:
        if self._deps is None:
            from crews.factories import default_deps

            self._deps = default_deps(pdf=self.pdf)
        return self._deps

    # -- helpers -------------------------------------------------------------
    def _check(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            if self.ctx:
                self.ctx.log("cancelled")
            raise ResearchCancelled(self.ctx.run_dir if self.ctx else None)

    def _emit(self, stage: str, status: str) -> None:
        if self.on_stage:
            self.on_stage(stage, status)
        if self.ctx:
            self.ctx.log("stage", stage=stage, status=status)

    def _note(self, text: str) -> None:
        self.notes.append(text)
        if self.ctx:
            self.ctx.log("note", text=text)

    # -- stages --------------------------------------------------------------
    @start()
    def step_route(self):
        self._check()
        self._emit("route", "start")
        try:
            raw = self.deps.route(self.topic)
        except Exception as exc:
            raw = ""
            self.notes.append(f"Router failed ({exc}); defaulted to tier 1.")
        plan = parse_plan(raw, self.topic)
        self.plan = finalize_plan(plan, pdf=self.pdf, size=self.size, forced_tier=self.forced_tier)
        self.ctx = new_run(self.topic, base=self.base_dir)
        self.ctx.cancel = self.cancel
        (self.ctx.run_dir / "plan.json").write_text(self.plan.model_dump_json(indent=2), encoding="utf-8")
        self.notes.extend(self.plan.warnings)
        self.ctx.log("plan", tier=self.plan.tier, domain=self.plan.domain, size=self.size, pdf=self.pdf)
        self._emit("route", "done")
        return "routed"

    @staticmethod
    def _without_worker_reads(plan: ResearchPlan) -> ResearchPlan:
        """Take page and PDF reading away from the agent so it does not spend time and budget on a dead worker.
        Tier 3 keeps page reads when Firecrawl can stand in for the worker."""
        firecrawl = plan.tier == 3 and plan.budget.firecrawl_credits > 0 and bool(os.getenv("FIRECRAWL_API_KEY"))
        budget = plan.budget.model_copy(update={"max_pdfs": 0, **({} if firecrawl else {"max_pages": 0})})
        return plan.model_copy(update={"budget": budget, "use_pdf_parsing": False})

    @listen(step_route)
    def step_research(self):
        self._check()
        self._emit("research", "start")
        plan, ctx = self.plan, self.ctx
        if plan.budget.max_pages > 0:
            health = self.deps.worker.health()
            if not health.get("ok"):
                plan = self._without_worker_reads(plan)
                self.plan = plan
                (ctx.run_dir / "plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
                self._note(
                    "Worker unavailable: pages and PDFs could not be read; this report relies on "
                    "search snippets and abstracts."
                )
        try:
            self.findings = self.deps.research(plan, ctx)
        except Exception as exc:
            self.findings = ""
            self._note(f"Research stage failed: {exc}")
        failures = self._count_events("read_failed")
        if failures:
            self._note(f"{failures} page or PDF reads failed; see log.jsonl in the run folder.")
        (ctx.run_dir / "findings.md").write_text(self.findings or "", encoding="utf-8")
        self._emit("research", "done")
        return "researched"

    @listen(step_research)
    def step_analyse(self):
        self._check()
        self._emit("analyse", "start")
        try:
            self.analysis = self.deps.analyse(self.findings)
        except Exception as exc:
            self.analysis = ""
            self._note(f"Analysis stage failed: {exc}")
        (self.ctx.run_dir / "analysis.md").write_text(self.analysis or "", encoding="utf-8")
        self._emit("analyse", "done")
        return "analysed"

    @listen(step_analyse)
    def step_figures(self):
        self._check()
        if not self.pdf:
            return "skipped"
        self._emit("figures", "start")
        try:
            self._build_figures()
        except Exception as exc:  # figures are optional; never sink the report
            self._note(f"Figure stage failed: {exc}")
        self._emit("figures", "done")
        return "figures"

    def _build_figures(self) -> None:
        deps, ctx = self.deps, self.ctx
        if deps.figure_llm is None:
            self._note("No figure planner configured; report has no figures.")
            return
        data_dir = ctx.run_dir / "data"
        email = os.getenv("OPENALEX_EMAIL") or os.getenv("UNPAYWALL_EMAIL")
        data_sources: dict[str, str] = {}
        if self.plan.use_academic:
            build_bibliometric_tables(
                self.topic, data_dir, email, counts_fn=deps.year_counts,
                registry=ctx.registry, data_sources=data_sources,
            )
        preset = SIZE_PRESETS[self.size]
        specs = plan_figures(
            deps.figure_llm, self.findings, self.analysis, describe_tables(data_dir) if data_dir.exists() else [],
            (preset.figures_min, preset.figures_max),
        )
        ok, reasons = validate_specs(specs, data_dir, ctx.registry, data_sources) if specs else ([], [])
        for reason in reasons:
            self._note(f"Figure skipped: {reason}")
        fig_dir = ctx.run_dir / "figures"
        for i, spec in enumerate(ok[: preset.figures_max], 1):
            try:
                self.figures.append((spec, render_chart(spec, data_dir, fig_dir / f"fig{i}.svg")))
            except Exception as exc:
                self._note(f"Figure skipped: {spec.title}: {exc}")
        room = max(preset.figures_max - len(self.figures), 0)
        self.diagrams = plan_diagrams(deps.figure_llm, self.findings, self.analysis, min(room, 2))

    @listen(step_figures)
    def step_write(self):
        self._check()
        self._emit("write", "start")
        written = write_report(
            topic=self.topic,
            findings=self.findings,
            analysis=self.analysis,
            size=self.size,
            registry=self.ctx.registry,
            llm=self.deps.llm,
            edit_llm=self.deps.edit_llm,
            pdf=self.pdf,
            notes=self.notes,
            extra_cited=[sid for spec, _ in self.figures for sid in spec.source_ids],
        )
        md_path = self.ctx.run_dir / f"{self.ctx.report_stem}.md"
        md_path.write_text(written.markdown, encoding="utf-8")
        self.ctx.registry.save()
        self.result = RunResult(
            run_dir=self.ctx.run_dir,
            plan=self.plan,
            markdown_path=md_path,
            pdf_path=None,
            words=written.words,
            notes=list(written.notes),
        )
        self._emit("write", "done")
        if self.pdf:
            self._render_pdf(written.markdown)
        return "written"

    def _render_pdf(self, markdown_text: str) -> None:
        self._emit("render", "start")
        try:
            html_text = build_html(markdown_text, self.figures, self.diagrams, self.topic, self.notes)
            assets = {p.name: p.read_bytes() for _, p in self.figures}
            pdf_path = render(html_text, assets, self.deps.worker, self.ctx.run_dir / f"{self.ctx.report_stem}.pdf")
            self.result.pdf_path = pdf_path
        except (PdfRenderError, OSError) as exc:
            self._note(f"PDF render failed: {exc}. The Markdown report is complete.")
            self.result.notes.append(self.notes[-1])
        self._emit("render", "done")

    # -- public --------------------------------------------------------------
    def run(self) -> RunResult:
        if not self.topic:
            raise ValueError("A research topic is required.")
        self.kickoff()
        return self.result

    def _count_events(self, name: str) -> int:
        path = self.ctx.run_dir / "log.jsonl"
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if json.loads(line).get("event") == name)
