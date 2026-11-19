"""Size-controlled report writer: outline first, then one LLM call per section."""
import json
import os
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from core.config import SIZE_PRESETS
from core.registry import SourceRegistry, normalize_citations
from report.validators import count_words, strip_references, word_status

LLMFn = Callable[[str], str]

DEFAULT_HEADINGS: dict[str, list[str]] = {
    "small": ["Summary", "Key findings", "Conclusions"],
    "medium": [
        "Summary", "Background", "Coverage and method", "Key findings",
        "Analysis", "Conclusions", "Limitations",
    ],
    "big": [
        "Executive summary", "Background", "Coverage and method", "Findings: themes",
        "Findings: evidence", "Comparison", "Timeline", "Analysis", "Conclusions and recommendations",
        "Limitations", "Appendix",
    ],
}


@dataclass
class WrittenReport:
    markdown: str
    words: int
    status: str
    unknown_citations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _source_ids(registry: SourceRegistry) -> str:
    ids = ", ".join(f"[{s.id}] {s.title}" for s in registry.all())
    return ids or "(none)"


# Lines a model adds on its own: a second H1 title, or a "*Short report – 1 000 words*" banner.
_H1 = re.compile(r"^#[ \t]+\S.*$")
_WORD_BANNER = re.compile(r"^[ \t]*[*_]+[^*_\n]*\d[\d\s,.]*\s*words?\b[^*_\n]*[*_]+[ \t]*$", re.I)
_RULE = re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$")


def _clean_body(text: str, topic: str = "") -> str:
    lines = []
    for line in strip_references(normalize_citations(text)).splitlines():
        if _H1.match(line) or _WORD_BANNER.match(line):
            continue
        bold = re.fullmatch(r"[ \t]*\*\*(.+?)\*\*[ \t]*", line)
        if topic and bold and bold.group(1).strip().lower() == topic.strip().lower():
            continue  # the topic repeated as a bold title line
        lines.append(line)
    # Drop blank lines and horizontal rules left at the top once the title block is gone.
    while lines and (not lines[0].strip() or _RULE.match(lines[0])):
        lines.pop(0)
    return "\n".join(lines).strip()


def _parse_outline(raw: str, size: str, midpoint: int) -> list[dict]:
    try:
        text = raw.strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        items = json.loads(text)
        outline = [
            {"heading": str(i["heading"]).strip(), "words": max(int(i["words"]), 50)}
            for i in items
            if str(i.get("heading", "")).strip()
        ]
        if outline:
            return outline
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    headings = DEFAULT_HEADINGS[size]
    return [{"heading": h, "words": midpoint // len(headings)} for h in headings]


DEFAULT_PARALLELISM = 4


def _parallelism(value: int | None) -> int:
    if value is None:
        try:
            value = int(os.getenv("WRITER_PARALLELISM", DEFAULT_PARALLELISM))
        except ValueError:
            value = DEFAULT_PARALLELISM
    return max(1, value)


def _map(fn, items: list, workers: int) -> list:
    """Run fn over items, up to `workers` model calls at once, keeping the input order."""
    if workers == 1 or len(items) < 2:
        return [fn(i) for i in items]
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        return list(pool.map(fn, items))


def _assemble(topic: str, sections: list[tuple[str, str]]) -> str:
    parts = [f"# {topic}"]
    for heading, body in sections:
        parts.append(f"## {heading}\n\n{body}")
    return "\n\n".join(parts)


def write_report(
    *,
    topic: str,
    findings: str,
    analysis: str,
    size: str,
    registry: SourceRegistry,
    llm: LLMFn,
    pdf: bool = False,
    notes: list[str] | None = None,
    extra_cited: list[str] | None = None,
    edit_llm: LLMFn | None = None,
    parallelism: int | None = None,
) -> WrittenReport:
    """`llm` writes the prose sections; `edit_llm` (a lighter model) does the outline, length
    adjustment and citation repair. Without `edit_llm`, `llm` does everything.

    Sections are independent, so they and their length pass run `parallelism` calls at a time
    (default WRITER_PARALLELISM, else 4). Each section still sees the full material.
    """
    workers = _parallelism(parallelism)
    edit = edit_llm or llm
    preset = SIZE_PRESETS[size]
    midpoint = (preset.words_min + preset.words_max) // 2
    notes = list(notes or [])
    ids = _source_ids(registry)
    table_hint = (
        f"Include about {preset.tables} Markdown tables where the evidence supports them. "
        if pdf else ""
    )
    material = f"TOPIC: {topic}\nVALID SOURCES (cite only these, as [S#]): {ids}\n\nFINDINGS:\n{findings}\n\nANALYSIS:\n{analysis}\n"

    if size == "small":
        headings = DEFAULT_HEADINGS["small"]
        raw = llm(
            f"SMALL_REQUEST\nWrite a short report with sections {headings}. {table_hint}"
            f"Cite sources as [S#]. Do not add a title, a word count or a references list.\nTARGET_WORDS: {midpoint}\n\n{material}"
        )
        body = _clean_body(raw, topic)
        sections = [("Report", body)]
        text = f"# {topic}\n\n{body}"
    else:
        outline = _parse_outline(
            edit(
                "OUTLINE_REQUEST\nReturn ONLY a JSON list of objects {\"heading\": str, \"words\": int} "
                f"for a {size} report; the word counts must total about {midpoint}.\n\n{material}"
            ),
            size,
            midpoint,
        )

        def write_section(item: dict) -> tuple[str, str]:
            raw = llm(
                f"SECTION_REQUEST\nHEADING: {item['heading']}\nTARGET_WORDS: {item['words']}\n"
                f"{table_hint}Write only this section's body in Markdown, no heading line. "
                f"Cite sources as [S#]. Do not add a title, a word count or a references list.\n\n{material}"
            )
            return item["heading"], _clean_body(raw, topic)

        sections = _map(write_section, outline, workers)
        text = _assemble(topic, sections)

    # One expand-or-trim pass if the length is off target.
    if word_status(count_words(text), preset) != "ok":
        if size == "small":
            fixed = _clean_body(edit(f"ADJUST_REQUEST\nRewrite to about the target length.\nTARGET_WORDS: {midpoint}\n\nTEXT:\n{sections[0][1]}"), topic)
            sections = [("Report", fixed)]
            text = f"# {topic}\n\n{fixed}"
        else:

            def adjust(pair: tuple[tuple[str, str], dict]) -> tuple[str, str]:
                (heading, body), item = pair
                fixed = edit(
                    f"ADJUST_REQUEST\nHEADING: {heading}\nRewrite this section to about the target length "
                    f"(expand with evidence from the material, or trim).\nTARGET_WORDS: {item['words']}\n\n"
                    f"{material}\nTEXT:\n{body}"
                )
                return heading, _clean_body(fixed, topic)

            sections = _map(adjust, list(zip(sections, outline)), workers)
            text = _assemble(topic, sections)

    # Citations: one repair attempt, then strip anything still unknown.
    report = registry.validate_citations(text)
    unknown = list(report.unknown)
    if unknown:
        repaired = edit(
            f"REPAIR_REQUEST\nThese citation ids do not exist: {', '.join(unknown)}. "
            f"Valid sources: {ids}. Rewrite the text keeping its structure, replacing or removing "
            f"invalid citations.\n\nTEXT:\n{text}"
        )
        text = strip_references(repaired).strip() if repaired.strip() else text
        report = registry.validate_citations(text)
        text = report.cleaned
        if report.unknown:  # only note ids the repair pass did not fix
            notes.append(f"Removed citations to unknown sources: {', '.join(report.unknown)}")

    words = count_words(text)
    status = word_status(words, preset)
    if status != "ok":
        notes.append(
            f"Report length is {words} words, {status} of the {preset.words_min}-{preset.words_max} "
            f"target for a {size} report (tolerance 15%)."
        )

    # Reference only what the report actually cites (plus figure sources), not every search hit.
    cited = set(registry.cited_ids(text)) | set(extra_cited or [])
    final = text.rstrip() + "\n\n" + registry.references_markdown(cited=sorted(cited))
    if notes:
        final += "\n## Coverage notes\n\n" + "\n".join(f"- {n}" for n in notes) + "\n"
    return WrittenReport(markdown=final, words=words, status=status, unknown_citations=unknown, notes=notes)
