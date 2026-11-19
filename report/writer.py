"""Size-controlled report writer: outline first, then one LLM call per section."""
import json
import os
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from core.config import SIZE_PRESETS, today_iso
from core.registry import SourceRegistry, normalize_citations
from report.claims import check_claims
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
    claims: list[dict] = field(default_factory=list)


def _source_ids(registry: SourceRegistry) -> str:
    ids = ", ".join(f"[{s.id}] {s.title}" for s in registry.all())
    return ids or "(none)"


# Shared by every writing prompt. gpt-oss defaults to dense consultant prose with bold labels and
# 【S#】 citations; it also has no idea of today's date unless told.
STYLE = """Today is {today}. Use only facts that are in the findings and analysis below: never add
names, dates, numbers or other details from memory, even ones you believe are true.
Write for an informed reader who is not a specialist:
- plain language, short sentences, active voice; explain each acronym the first time it appears
- give numbers with units, currency and the year they refer to; say when evidence is old, thin or disputed
- no filler, hype or wrap-up lines such as "In summary"; no bold "Key takeaway" labels in every section
- cite each factual claim right after it as [S3] or [S3][S7]: square brackets, never 【S3】 or (S3);
  cite only the listed sources"""

# Lines a model adds on its own: a second H1 title, or a "*Short report – 1 000 words*" banner.
_H1 = re.compile(r"^#[ \t]+\S.*$")
_RULE = re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$")
# A heading line, or a line that is only bold/italic text: what models use as a section title.
_TITLE_LINE = re.compile(r"^[ \t]*(?:#{1,6}[ \t]+(?P<h>.+?)|(?P<m>\*\*|__|\*|_)(?P<b>[^*_\n].*?)(?P=m))[ \t:]*$")
_WORD_COUNT = re.compile(r"\d[\d,.\s]*[\s\-‐‑–]*words?\b", re.I)
# Source lists the model writes itself; the real one is built from the registry.
_SOURCE_HEADING = re.compile(
    r"^(?:appendix\b[^a-z]*)?(?:references?|sources?|source citations?|citations?|bibliography|works cited|reference list)\b",
    re.I,
)
_NUMBERING = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.)\s+")


def _title_text(line: str) -> str | None:
    m = _TITLE_LINE.match(line)
    return (m.group("h") or m.group("b")).strip() if m else None


def _norm(text: str) -> str:
    text = _NUMBERING.sub("", text).lower().replace("&", " and ")
    text = re.sub(r"[\-‐-―−/]", " ", text)  # every dash style, and slashes, separate words
    return " ".join(re.sub(r"[^a-z0-9 ]+", "", text).split())


def _repeats(title: str, heading: str) -> bool:
    """A title line restating the section heading: same opening, ignoring numbering and punctuation."""
    a, b = _norm(title), _norm(heading)
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 6 and long_.startswith(short[:30])


def _clean_body(text: str, topic: str = "", heading: str = "") -> str:
    lines: list[str] = []
    for line in strip_references(normalize_citations(text)).splitlines():
        title = _title_text(line)
        if _H1.match(line):
            continue
        if title is not None:
            if _SOURCE_HEADING.match(_NUMBERING.sub("", title)):
                break  # a model-written source list: drop it and everything after it
            if _WORD_COUNT.search(title):
                continue  # "*Short report – 1 000 words*", "**Market – 300-Word Section**"
            if topic and _norm(title) == _norm(topic):
                continue  # the topic repeated as a title line
            if heading and not any(l.strip() for l in lines) and _repeats(title, heading):
                continue  # the section's own heading restated as its first line
        lines.append(line)
    # Drop blank lines and horizontal rules left at the top once the title block is gone.
    while lines and (not lines[0].strip() or _RULE.match(lines[0])):
        lines.pop(0)
    return "\n".join(lines).strip()


# Top-level sections per size. Each section is a separate model call that sees all the material, so
# more sections mean more repetition and more words: the 6 790-word "medium" report had 41.
SECTION_RANGE: dict[str, tuple[int, int]] = {"medium": (5, 7), "big": (8, 12)}
MIN_SECTION_WORDS = 120
_SUBSECTION = re.compile(r"^\s*\d+\.\d+")


def _normalize_outline(items: list[dict], size: str, midpoint: int) -> list[dict]:
    """Fold numbered subsections into their parent, drop source-list sections, strip numbering,
    cap the count (keeping the last section, usually the conclusion) and rescale the word targets."""
    outline: list[dict] = []
    for item in items:
        heading = item["heading"]
        if _SUBSECTION.match(heading) and outline:
            outline[-1]["parts"].append(_NUMBERING.sub("", heading).strip())
            continue
        heading = _NUMBERING.sub("", heading).strip()
        if not heading or _SOURCE_HEADING.match(heading):
            continue
        outline.append({"heading": heading, "words": item["words"], "covers": item.get("covers", ""), "parts": []})
    cap = SECTION_RANGE[size][1]
    if len(outline) > cap:
        extra = outline[cap - 1:-1]
        outline = outline[: cap - 1] + outline[-1:]
        outline[-2]["parts"] += [e["heading"] for e in extra]
    total = sum(i["words"] for i in outline) or 1
    for item in outline:
        item["words"] = max(MIN_SECTION_WORDS, round(item["words"] * midpoint / total))
    return outline


def _parse_outline(raw: str, size: str, midpoint: int) -> list[dict]:
    try:
        text = raw.strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        items = [
            {"heading": str(i["heading"]).strip(), "words": max(int(i["words"]), 50),
             "covers": str(i.get("covers") or "").strip()}
            for i in json.loads(text)
            if str(i.get("heading", "")).strip()
        ]
        outline = _normalize_outline(items, size, midpoint)
        if outline:
            return outline
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    headings = DEFAULT_HEADINGS[size]
    return [{"heading": h, "words": midpoint // len(headings), "covers": "", "parts": []} for h in headings]


def _outline_brief(outline: list[dict], current: dict) -> str:
    lines = []
    for item in outline:
        scope = f": {item['covers']}" if item.get("covers") else ""
        mark = "  <- this section" if item is current else ""
        lines.append(f"- {item['heading']}{scope}{mark}")
    brief = ("REPORT OUTLINE (each section is written separately; do not repeat what other sections cover):\n"
             + "\n".join(lines))
    if current.get("parts"):
        brief += "\nThis section also covers: " + "; ".join(current["parts"]) + "."
    return brief


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
    today: str | None = None,
    check_llm: LLMFn | None = None,
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
    style = STYLE.format(today=today or today_iso())
    rules = "Do not add a title, a word count or a references list."

    if size == "small":
        headings = DEFAULT_HEADINGS["small"]
        raw = llm(
            f"SMALL_REQUEST\nWrite a short report with sections {headings}. {table_hint}{rules}\n"
            f"TARGET_WORDS: {midpoint}\n{style}\n\n{material}"
        )
        body = _clean_body(raw, topic)
        sections = [("Report", body)]
        text = f"# {topic}\n\n{body}"
    else:
        lo, hi = SECTION_RANGE[size]
        outline = _parse_outline(
            edit(
                f"OUTLINE_REQUEST\nReturn ONLY a JSON list of {lo} to {hi} top-level sections for a {size} report, "
                'each {"heading": str, "words": int, "covers": "<one sentence: what this section, and only '
                'this section, covers>"}. No subsections and no numbering. No references or sources section '
                f"(the system adds one). Give sections distinct scopes so no fact needs to appear twice. "
                f"The word counts must total about {midpoint}.\n\n{material}"
            ),
            size,
            midpoint,
        )

        def write_section(item: dict) -> tuple[str, str]:
            raw = llm(
                f"SECTION_REQUEST\nHEADING: {item['heading']}\nTARGET_WORDS: {item['words']}\n"
                f"{_outline_brief(outline, item)}\n"
                f"{table_hint}Write only this section's body in Markdown: no heading or title line. "
                f"Stay within 10% of TARGET_WORDS. {rules}\n{style}\n\n{material}"
            )
            return item["heading"], _clean_body(raw, topic, item["heading"])

        sections = _map(write_section, outline, workers)
        text = _assemble(topic, sections)

    # One expand-or-trim pass if the length is off target, on the sections that cause it.
    status = word_status(count_words(text), preset)
    if status != "ok":
        if size == "small":
            fixed = _clean_body(edit(f"ADJUST_REQUEST\nRewrite to about the target length.\nTARGET_WORDS: {midpoint}\n{style}\n\nTEXT:\n{sections[0][1]}"), topic)
            sections = [("Report", fixed)]
            text = f"# {topic}\n\n{fixed}"
        else:

            def off_target(body: str, item: dict) -> bool:
                words = count_words(body)
                return words > item["words"] * 1.15 if status == "long" else words < item["words"] * 0.85

            def adjust(pair: tuple[tuple[str, str], dict]) -> tuple[str, str]:
                (heading, body), item = pair
                if not off_target(body, item):
                    return heading, body
                fixed = edit(
                    f"ADJUST_REQUEST\nHEADING: {heading}\nRewrite this section to about the target length "
                    f"(expand with evidence from the material, or trim).\nTARGET_WORDS: {item['words']}\n"
                    f"{style}\n\n{material}\nTEXT:\n{body}"
                )
                return heading, _clean_body(fixed, topic, heading)

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

    # Claim check: compare each cited statement with its sources' saved text; reword or drop the
    # ones they do not support. Fixes are validated like any other text, so no source can be invented.
    claims: list[dict] = []
    if check_llm is not None:
        try:
            text, checked, note = check_claims(text, registry, check_llm, workers=workers)
            text = registry.validate_citations(text).cleaned
            claims = [c.to_dict() for c in checked]
            notes.append(note)
        except Exception as exc:  # the check is a safeguard; it must never cost the report
            notes.append(f"Claim check failed and was skipped: {exc}")

    words = count_words(text)
    status = word_status(words, preset)
    if status != "ok":
        note = (f"Report length is {words} words, {status} of the {preset.words_min}-{preset.words_max} "
                f"target for a {size} report (tolerance 15%).")
        removed = sum(c.get("applied") == "removed" for c in claims)
        if status == "short" and check_llm is not None:
            # Say why: the sources backed too little, so the claim check took statements out.
            found, used = len(registry.all()), len(registry.cited_ids(text))
            share = (f"none of the {found} sources found" if used == 0
                     else f"only {used} of the {found} sources found")
            note += (f" The sources supported too little to say more: {share} back its statements, and the "
                     f"claim check removed {removed} statements their sources did not support.")
        notes.append(note)

    # Reference only what the report actually cites (plus figure sources), not every search hit.
    cited = set(registry.cited_ids(text)) | set(extra_cited or [])
    final = text.rstrip() + "\n\n" + registry.references_markdown(cited=sorted(cited))
    if notes:
        final += "\n## Coverage notes\n\n" + "\n".join(f"- {n}" for n in notes) + "\n"
    return WrittenReport(markdown=final, words=words, status=status, unknown_citations=unknown, notes=notes,
                         claims=claims)
