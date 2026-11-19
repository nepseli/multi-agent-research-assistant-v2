"""Pure helpers for the Streamlit app and CLI (no streamlit import, so they are unit-testable)."""
from collections.abc import Mapping
from urllib.parse import urlsplit

from core.config import _PREFIX, SIZE_PRESETS, TIER_VAR, resolve_llm

PROVIDER_KEYS = {"openrouter": "OPENROUTER_API_KEY", "openai": "OPENAI_API_KEY", "groq": "GROQ_API_KEY"}
ROLE_LABELS = {
    "router": "Router",
    "research": "Research",
    "analyst": "Analyst",
    "writer": "Writer",
    "editor": "Editor (outline, length, citations)",
    "figure_planner": "Figure planner",
    "fact_checker": "Fact checker",
}


def _get(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def missing_settings(env: Mapping[str, str]) -> list[str]:
    missing: list[str] = []
    needed_keys: set[str] = set()
    if not _get(env, "SERPER_API_KEY"):
        missing.append("SERPER_API_KEY")
    for role in _PREFIX:
        for pdf in (False, True):
            choice = resolve_llm(role, pdf, env)
            if not choice.model:
                var = TIER_VAR[choice.tier]
                if var not in missing:
                    missing.append(var)
                continue
            provider = choice.model.split("/", 1)[0].lower() if "/" in choice.model else ""
            if provider in PROVIDER_KEYS:
                needed_keys.add(PROVIDER_KEYS[provider])
    for key in sorted(needed_keys):
        if not _get(env, key):
            missing.append(key)
    return missing


def size_label(size: str) -> str:
    p = SIZE_PRESETS[size]
    pages = f"~{round(p.words_min / 350)}–{round(p.words_max / 300)} PDF pages"
    return f"{size.capitalize()} — {p.words_min:,}–{p.words_max:,} words, {pages}"


def stages_for(pdf: bool) -> list[str]:
    base = ["route", "research", "analyse", "write"]
    return ["route", "research", "analyse", "figures", "write", "render"] if pdf else base


def role_model_table(env: Mapping[str, str], pdf: bool) -> list[dict]:
    rows = []
    for role in _PREFIX:
        choice = resolve_llm(role, pdf, env)
        rows.append({
            "role": role,
            "label": ROLE_LABELS[role],
            "tier": choice.tier,
            "model": choice.model or "(not set)",
            "temperature": choice.temperature,
        })
    return rows


def _site(url: str) -> str:
    host = urlsplit(url or "").netloc.lower()
    return host.removeprefix("www.") or (url or "")[:40]


class ProgressTracker:
    """Turns the run log into one plain line for the app ("Read page 3 of 8: imda.gov.sg").
    update() returns the new line, or None for events that do not change it."""

    def __init__(self):
        self.budget: dict = {}
        self.searches = self.pages = self.pdfs = 0
        self.line = ""

    def update(self, record: dict) -> str | None:
        event = record.get("event")
        b = self.budget
        if event == "plan":
            self.budget = {k: record.get(k, 0) for k in ("max_searches", "max_pages", "max_pdfs")}
            line = (f"Planned a Tier {record.get('tier')} search: up to {self.budget['max_searches']} searches, "
                    f"{self.budget['max_pages']} pages and {self.budget['max_pdfs']} papers.")
        elif event in ("web_search", "academic_search"):
            self.searches += 1
            where = "the web" if event == "web_search" else "papers"
            line = f'Searching {where} ({self.searches} of {b.get("max_searches", "?")}): "{record.get("query", "")}"'
        elif event == "read_page":
            self.pages += 1
            line = f"Read page {self.pages} of {b.get('max_pages', '?')}: {_site(record.get('url', ''))}"
        elif event == "read_pdf":
            self.pdfs += 1
            line = f"Read paper {self.pdfs}: {_site(record.get('url', ''))}"
        elif event == "read_failed":
            line = f"Could not read {_site(record.get('url', ''))}; moving on."
        elif event == "no_open_access":
            line = f"No open-access copy of {record.get('ident', 'a paper')}; using its abstract."
        elif event == "firecrawl_fallback":
            line = f"Retrying {_site(record.get('url', ''))} through Firecrawl."
        elif event == "budget_exhausted":
            line = f"Search budget used up ({record.get('what', '')}); working with what was found."
        else:
            return None
        self.line = line
        return line



# -- past runs -----------------------------------------------------------------

def _report_files(run_dir):
    reports = sorted(run_dir.glob("*-report.md")) or sorted(run_dir.glob("report.md"))
    return reports[0] if reports else None


def _when(run_dir, short: bool = False) -> str:
    """When a run started, from its folder name: "19 Nov 2026, 13:30 UTC", or "19 Nov, 13:30" when short."""
    from datetime import datetime

    try:
        stamp = datetime.strptime(run_dir.name[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        return run_dir.name[:15] if short else ""
    return f"{stamp.day} {stamp:%b, %H:%M}" if short else f"{stamp.day} {stamp:%b %Y, %H:%M} UTC"


def list_runs(base) -> list[dict]:
    """Finished runs in the runs folder, newest first, with what the app's picker shows."""
    import json
    from pathlib import Path

    base = Path(base)
    if not base.is_dir():
        return []
    runs = []
    for run_dir in sorted((d for d in base.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True):
        report = _report_files(run_dir)
        if report is None:
            continue
        try:
            topic = json.loads((run_dir / "plan.json").read_text(encoding="utf-8")).get("topic", run_dir.name)
        except (OSError, ValueError):
            topic = run_dir.name
        pdf = any(run_dir.glob("*-report.pdf")) or (run_dir / "report.pdf").exists()
        when = _when(run_dir)
        short = _when(run_dir, short=True)
        runs.append({
            "dir": run_dir, "topic": topic, "when": when, "pdf": pdf,
            # Time first: in the narrow sidebar the same topic run twice would otherwise look identical.
            "label": f"{short} · {topic}" + (" · PDF" if pdf else ""),
        })
    return runs


def load_run(run_dir):
    """Rebuild the result of a finished run from its folder, so the app can show it again."""
    import json
    import re
    from pathlib import Path

    from core.models import ResearchPlan
    from flows.research_flow import RunResult
    from report.validators import count_words

    run_dir = Path(run_dir)
    report = _report_files(run_dir)
    markdown = report.read_text(encoding="utf-8")
    plan = ResearchPlan.model_validate_json((run_dir / "plan.json").read_text(encoding="utf-8"))
    pdfs = sorted(run_dir.glob("*-report.pdf")) or [p for p in [run_dir / "report.pdf"] if p.exists()]
    notes_block = markdown.split("\n## Coverage notes", 1)[1] if "\n## Coverage notes" in markdown else ""
    notes = [m.strip() for m in re.findall(r"(?m)^- (.+)$", notes_block)]
    usage_file = run_dir / "usage.json"
    usage = json.loads(usage_file.read_text(encoding="utf-8")) if usage_file.exists() else None
    return RunResult(run_dir=run_dir, plan=plan, markdown_path=report, pdf_path=pdfs[0] if pdfs else None,
                     words=count_words(markdown), notes=notes, usage=usage)
