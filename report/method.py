"""The "How this report was made" box under the title: what was searched, read and checked, and by
which models. Built from the run's own records, so a reader can judge how far to trust the report."""
from collections.abc import Mapping
from datetime import date

from core.config import resolve_llm
from core.models import ResearchPlan
from core.registry import SourceRegistry

TIER_NAMES = {0: "a quick lookup", 1: "a general topic", 2: "a technical topic", 3: "a literature review"}


def _plural(n: int, word: str) -> str:
    if n == 1:
        return f"{n} {word}"
    return f"{n} {word}" + ("es" if word.endswith(("ch", "sh", "s")) else "s")


def _model_name(role: str, env: Mapping[str, str]) -> str:
    model = resolve_llm(role, False, env).model or "(not set)"
    return model.rsplit("/", 1)[-1]


def method_box(
    plan: ResearchPlan,
    registry: SourceRegistry,
    markdown: str,
    *,
    searches: int,
    claims: list[dict],
    env: Mapping[str, str],
    today: str | None = None,
    short: tuple[int, int, int] | None = None,
) -> str:
    """`short` is (words, target minimum, target maximum) when the report came out under its size."""
    day = date.fromisoformat(today) if today else date.today()
    sources = registry.all()
    pages = sum(s.depth == "full_text" and s.kind == "web" for s in sources)
    papers = sum(s.depth == "full_text" and s.kind != "web" for s in sources)
    cited = len(registry.cited_ids(markdown.split("\n## References")[0]))
    reads = [p for p in (_plural(pages, "web page") if pages else "", _plural(papers, "paper") if papers else "") if p]
    read_text = f", and read {' and '.join(reads)} in full" if reads else ""
    parts = [
        f"Researched on {day.day} {day:%B %Y} as {TIER_NAMES.get(plan.tier, 'a topic')} (Tier {plan.tier}): "
        f"{_plural(searches, 'search')}{read_text}.",
        f"{_plural(len(sources), 'source')} {'was' if len(sources) == 1 else 'were'} found and {cited} "
        f"{'is' if cited == 1 else 'are'} cited; each reference says how deeply it was read.",
    ]
    checked = [c for c in claims if c.get("verdict") not in (None, "skipped")]
    if checked:
        changed = sum(bool(c.get("applied")) for c in checked)
        parts.append(
            f"A claim check compared {_plural(len(checked), 'cited statement')} with the text of their sources; "
            f"{changed} were reworded or removed to match them."
        )
    if short:
        words, lo, hi = short
        parts.append(
            f"At {words} words it is shorter than the {lo:,}-{hi:,} word target because the sources supported "
            f"too little: only {cited} of {_plural(len(sources), 'source')} found back its statements."
        )
    strong, light = _model_name("writer", env), _model_name("fact_checker", env)
    models = f"{strong} (research and writing)" + (f" and {light} (editing and checks)" if light != strong else "")
    parts.append(f"Models: {models}.")
    return "> **How this report was made.** " + " ".join(parts)


def add_method_box(markdown: str, box: str) -> str:
    """Insert the box right after the report's title line."""
    title, _, rest = markdown.partition("\n")
    return f"{title}\n\n{box}\n\n{rest.lstrip()}"
