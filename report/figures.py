"""Figure planning and validation. Charts may only use data that exists as a CSV in the run's data folder."""
import csv
import json
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode

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


def validate_specs(
    specs: list[FigureSpec], data_dir: Path, registry: SourceRegistry, data_sources: dict[str, str] | None = None
) -> tuple[list[FigureSpec], list[str]]:
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
        # The data is real, so a bad citation should not cost the chart: drop unknown ids
        # and cite the source the data file actually came from.
        ids = [s for s in spec.source_ids if s in known]
        origin = _data_origin(spec.data_ref, data_sources or {})
        if origin in known and origin not in ids:
            ids.insert(0, origin)
        ok.append(spec.model_copy(update={"source_ids": ids}))
    return ok, reasons


def _data_origin(data_ref: str, data_sources: dict[str, str]) -> str | None:
    """Source id a data file came from: an explicit mapping, or the S#_tableN.csv naming used for PDF tables."""
    name = Path(data_ref).name
    if name in data_sources:
        return data_sources[name]
    match = re.match(r"(S\d+)_table\d+\.csv$", name)
    return match.group(1) if match else None


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


def build_bibliometric_tables(
    topic: str,
    data_dir: Path,
    email: str | None,
    counts_fn: CountsFn | None = None,
    registry: SourceRegistry | None = None,
    data_sources: dict[str, str] | None = None,
) -> list[str]:
    """Write papers_per_year.csv from OpenAlex. With a registry, the query is recorded as a citable source."""
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
    if registry is not None:
        url = "https://api.openalex.org/works?" + urlencode({"search": topic, "group_by": "publication_year"})
        src = registry.add(url, f'OpenAlex: publications per year matching "{topic}"', "dataset", "openalex")
        if data_sources is not None:
            data_sources["papers_per_year.csv"] = src.id
    return ["papers_per_year.csv"]
