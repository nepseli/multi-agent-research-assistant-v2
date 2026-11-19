"""Figure planning and validation. Charts may only use data that exists as a CSV in the run's data folder."""
import csv
import json
import re
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from core.models import FigureSpec
from core.registry import SourceRegistry
from report.writer import LLMFn

CountsFn = Callable[[str, str | None], dict[int, int]]

PLAN_PROMPT = """FIGURE_PLAN_REQUEST
Plan between {lo} and {hi} charts for a research report. Reply with ONLY a JSON list.
Each item: {{"kind": "bar"|"line"|"pie", "title": str, "data_ref": str, "x": str, "y": str, "caption": str, "source_ids": [str]}}.
Rules: data_ref MUST be one of the data files listed below, x and y MUST be column names of that file, y must be numeric.
Never invent data. If no listed file suits a chart, return fewer charts or [].

DATA FILES:
{tables}

FINDINGS:
{findings}

ANALYSIS:
{analysis}
"""


def _read_rows(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _is_number(value: str) -> bool:
    try:
        float(value.replace(",", ""))
        return True
    except (ValueError, AttributeError):
        return False


def validate_specs(specs: list[FigureSpec], data_dir: Path, registry: SourceRegistry) -> tuple[list[FigureSpec], list[str]]:
    data_dir = Path(data_dir).resolve()
    known = {s.id for s in registry.all()}
    ok: list[FigureSpec] = []
    reasons: list[str] = []
    for spec in specs:
        path = (data_dir / spec.data_ref).resolve()
        if data_dir not in path.parents or not path.is_file():
            reasons.append(f"{spec.title}: data file {spec.data_ref} not found")
            continue
        try:
            rows = _read_rows(path)
        except (OSError, csv.Error, UnicodeDecodeError):
            reasons.append(f"{spec.title}: data file {spec.data_ref} unreadable")
            continue
        if len(rows) < 2:
            reasons.append(f"{spec.title}: {spec.data_ref} has fewer than 2 rows")
            continue
        if spec.x not in rows[0] or spec.y not in rows[0]:
            reasons.append(f"{spec.title}: columns {spec.x}/{spec.y} not in {spec.data_ref}")
            continue
        if not all(_is_number(r.get(spec.y) or "") for r in rows):
            reasons.append(f"{spec.title}: column {spec.y} is not numeric")
            continue
        unknown = [s for s in spec.source_ids if s not in known]
        if unknown:
            reasons.append(f"{spec.title}: unknown source id {', '.join(unknown)}")
            continue
        ok.append(spec)
    return ok, reasons


def describe_tables(data_dir: Path) -> list[str]:
    out = []
    for path in sorted(Path(data_dir).glob("*.csv")):
        try:
            rows = _read_rows(path)
            cols = list(rows[0].keys()) if rows else []
            if not cols:
                with open(path, newline="", encoding="utf-8") as fh:
                    cols = next(csv.reader(fh), [])
        except (OSError, csv.Error, UnicodeDecodeError):
            continue
        out.append(f"{path.name}: {', '.join(cols)} ({len(rows)} rows)")
    return out


def _json_list(raw: str) -> list:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []
    return data if isinstance(data, list) else []


def plan_figures(llm: LLMFn, findings: str, analysis: str, tables: list[str], count: tuple[int, int]) -> list[FigureSpec]:
    if not tables:
        return []
    prompt = PLAN_PROMPT.format(lo=count[0], hi=count[1], tables="\n".join(tables), findings=findings[:6000], analysis=analysis[:3000])
    specs = []
    for item in _json_list(llm(prompt)):
        try:
            specs.append(FigureSpec(**item))
        except (ValidationError, TypeError):
            continue
    return specs


def build_bibliometric_tables(topic: str, data_dir: Path, email: str | None, counts_fn: CountsFn | None = None) -> list[str]:
    if counts_fn is None:
        from tools.academic import openalex_year_counts as counts_fn
    try:
        counts = counts_fn(topic, email)
    except Exception:
        return []
    if not counts:
        return []
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / "papers_per_year.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["year", "papers"])
        for year in sorted(counts):
            w.writerow([year, counts[year]])
    return ["papers_per_year.csv"]
