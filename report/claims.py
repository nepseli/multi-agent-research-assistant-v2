"""Claim check: does each cited statement say what its sources say?

For every sentence, bullet or table row that cites [S#], the passages of the cited sources' saved text
that best match it are put in front of a model, which judges it supported, partial, unsupported or
unclear. Partial and unsupported statements are reworded to what the source supports, or removed.
Table rows change only in ways that keep the table well formed. Nothing here can invent a source:
fixes keep the original citations, and the writer validates citations again afterwards.
"""
import json
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from core.registry import _DEPTH_LABEL, SourceRegistry

LLMFn = Callable[[str], str]

_CITE = re.compile(r"\[(S\d+)\]")
# Split after ., ! or ? (and any citations that follow), before the next sentence starts.
_SENTENCE_END = re.compile(r"(?<=[.!?])((?:\s*\[S\d+\])*)\s+(?=[^\s\[a-z])")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}")
_BULLET = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+)(.*)$")
_WORD = re.compile(r"[a-z0-9$%.]+")
_STOP = set("the and for that with this from into over under about their there which have has been were was "
            "are its it's also than more most such these those other while will would could should".split())

DEFAULT_BATCH = 12
DEFAULT_MAX_CLAIMS = 80
EVIDENCE_CHARS = 1000
FULL_TEXT_EVIDENCE_CHARS = 2000  # a page read in full has more to say; give the checker more of it
_SHALLOW = ("snippet", "metadata")

# Calibrated on live runs: without the paraphrase and snippet rules, a 20b checker marked fair
# summaries of a framework page "unsupported" and treated 150-character snippets as proof of absence.
PROMPT = """CLAIM_CHECK_REQUEST
For each numbered statement from a research report, decide whether the source text shown under it supports it.
Judge meaning, not wording: a fair paraphrase or summary of the source is supported.
- supported: the source text says this, in other words or as a fair summary
- partial: the source supports the core of it, but the statement adds a detail, overstates, or changes a number,
  date or name (a year or detail the source only implies also makes it partial, not unsupported)
- unsupported: the source text says something different, or its text is long enough to cover the point and does not
- unclear: the source text is too short to judge (for example a one-line search snippet) or is about something else
For partial and unsupported, give "fix": the statement rewritten to say only what its sources support, keeping its
[S#] citations; or "" to delete it. Do not use outside knowledge: judge only against the text shown.
Reply with ONLY a JSON list: [{{"id": 1, "verdict": "supported", "fix": ""}}]

{statements}
"""


@dataclass
class Claim:
    text: str
    cites: list[str]
    section: str
    in_table: bool = False
    verdict: str | None = None  # supported | partial | unsupported | unclear | unchecked | skipped
    fix: str | None = None
    applied: str = ""  # "reworded" | "removed" | ""
    shallow: bool = False  # every cited source is only a snippet or title: never removed on its say-so

    def to_dict(self) -> dict:
        return asdict(self)


def _sentences(line: str) -> list[str]:
    parts = _SENTENCE_END.split(line)
    # split() returns text, captured citations, text, ...: glue each citation run back onto its sentence.
    out = []
    for i in range(0, len(parts), 2):
        out.append((parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")).strip())
    return [s for s in out if s]


def extract_claims(text: str) -> list[Claim]:
    """Cited statements in report order, with the section they belong to. Headings are skipped."""
    claims: list[Claim] = []
    section = ""
    for line in text.split("\n## References")[0].splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if stripped.startswith("## "):
                section = stripped[3:].strip()
            continue
        if not _CITE.search(stripped):
            continue
        if stripped.startswith("|"):
            if not _TABLE_RULE.match(stripped):
                claims.append(Claim(stripped, _CITE.findall(stripped), section, in_table=True))
            continue
        bullet = _BULLET.match(line)
        body = bullet.group(2) if bullet else stripped
        for sentence in _sentences(body):
            cites = _CITE.findall(sentence)
            if cites:
                claims.append(Claim(sentence, list(dict.fromkeys(cites)), section))
    return claims


def _tokens(text: str) -> set[str]:
    return {w.strip(".") for w in _WORD.findall(text.lower()) if len(w) > 3 and w not in _STOP}


def _units(paragraph: str, size: int) -> list[str]:
    """Sentences, with any sentence longer than `size` (tables, lists run together) cut at word breaks."""
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
        while len(sentence) > size:
            cut = sentence.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            out.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            out.append(sentence)
    return out


def _passages(content: str, size: int = 450) -> list[str]:
    """Pieces of about `size` characters that start and end at sentence boundaries, so the checker
    never reads half a word or half a figure."""
    pieces = []
    for para in re.split(r"\n\s*\n", content):
        para = " ".join(para.split())
        current = ""
        for unit in _units(para, size):
            if current and len(current) + 1 + len(unit) > size:
                pieces.append(current)
                current = unit
            else:
                current = f"{current} {unit}".strip()
        if current:
            pieces.append(current)
    return pieces


def evidence_for(claim: str, cites: list[str], registry: SourceRegistry, chars: int | None = None) -> str:
    """The passages of each cited source that share the most words (numbers count double) with the claim.
    Sources read in full get a larger budget than snippets and abstracts."""
    wanted = _tokens(_CITE.sub("", claim))
    blocks = []
    for sid in cites:
        source = registry.get(sid)
        content = registry.content(sid)
        depth = (source.depth if source else "") or ""
        label = _DEPTH_LABEL.get(depth, "")
        head = f"[{sid}] {source.title if source else ''}" + (f" ({label})" if label else "")
        if not content.strip():
            blocks.append(f"{head}: (no saved text)")
            continue
        budget = chars or (FULL_TEXT_EVIDENCE_CHARS if depth == "full_text" else EVIDENCE_CHARS)
        scored = []
        for i, passage in enumerate(_passages(content)):
            tokens = _tokens(passage)
            score = sum(2 if any(c.isdigit() for c in t) else 1 for t in wanted & tokens)
            scored.append((score, -i, passage))
        picked, used = [], 0
        for score, _, passage in sorted(scored, reverse=True):
            if used and (score == 0 or used + len(passage) > budget):
                break
            picked.append(passage)
            used += len(passage)
        blocks.append(f"{head}:\n" + "\n...\n".join(picked))
    return "\n".join(blocks)


def _shallow_only(claim: Claim, registry: SourceRegistry) -> bool:
    """Every cited source is only a search snippet or a title: too little text to prove a claim wrong."""
    return all(((registry.get(sid).depth if registry.get(sid) else "") or "metadata") in _SHALLOW
               for sid in claim.cites)


def _has_text(claim: Claim, registry: SourceRegistry) -> bool:
    return any(registry.content(sid).strip() for sid in claim.cites)


def _judge_batch(batch: list[tuple[int, Claim]], registry: SourceRegistry, llm: LLMFn) -> dict[int, dict]:
    statements = "\n\n".join(
        f"STATEMENT {n}: {claim.text}\nSOURCES FOR {n}:\n{evidence_for(claim.text, claim.cites, registry)}"
        for n, claim in batch
    )
    try:
        raw = llm(PROMPT.format(statements=statements))
        items = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip()))
    except Exception:  # a failed or garbled check must never sink the report
        return {}
    out = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("id"), int):
            out[item["id"]] = item
    return out


def _with_cites(fix: str, cites: list[str]) -> str:
    fix = " ".join(fix.split())
    if _CITE.search(fix):
        return fix
    tail = "".join(f"[{c}]" for c in cites)
    return re.sub(r"([.!?]?)$", lambda m: f" {tail}{m.group(1)}", fix, count=1)


def _cells(row: str) -> list[str]:
    row = row.strip()
    row = row[1:] if row.startswith("|") else row
    row = row[:-1] if row.endswith("|") else row
    return [c.strip() for c in row.split("|")]


def _apply_row(text: str, claim: Claim) -> str:
    """A row is replaced only by a fix with the same number of cells, and removed only if the table
    keeps at least one data row, so the table always stays well formed."""
    lines = text.split("\n")
    idx = next((i for i, line in enumerate(lines) if line.strip() == claim.text), None)
    if idx is None:
        return text
    original = _cells(claim.text)
    if claim.fix:
        fixed = _cells(claim.fix) if "|" in claim.fix else []
        if len(fixed) != len(original):
            return text
        if not _CITE.search(" ".join(fixed)):  # put the citations back in the cell that had them
            j = max((k for k, cell in enumerate(original) if _CITE.search(cell)), default=len(original) - 1)
            fixed[j] = (fixed[j] + " " + "".join(f"[{c}]" for c in claim.cites)).strip()
        lines[idx] = "| " + " | ".join(fixed) + " |"
        claim.applied = "reworded"
        return "\n".join(lines)
    if claim.verdict == "unsupported" and not claim.shallow:
        start, end = idx, idx
        while start > 0 and lines[start - 1].strip().startswith("|"):
            start -= 1
        while end + 1 < len(lines) and lines[end + 1].strip().startswith("|"):
            end += 1
        if end - (start + 2) + 1 <= 1:  # rows after the header and its rule line
            return text
        del lines[idx]
        claim.applied = "removed"
        return "\n".join(lines)
    return text


def _apply(text: str, claim: Claim) -> str:
    if claim.verdict not in ("partial", "unsupported") or claim.text not in text:
        return text
    if claim.in_table:
        return _apply_row(text, claim)
    if claim.fix:
        claim.applied = "reworded"
        return text.replace(claim.text, _with_cites(claim.fix, claim.cites), 1)
    if claim.verdict == "unsupported" and not claim.shallow:
        claim.applied = "removed"
        text = text.replace(claim.text, "", 1)
        return re.sub(r"[ \t]{2,}", " ", re.sub(r"(?m)^[ \t]*(?:[-*+]|\d+[.)])[ \t]*$\n?", "", text))
    return text


def _note(claims: list[Claim]) -> str:
    total = len(claims)
    checked = [c for c in claims if c.verdict not in (None, "skipped")]
    count = {v: sum(c.verdict == v for c in checked) for v in ("supported", "partial", "unsupported", "unclear", "unchecked")}
    reworded = sum(c.applied == "reworded" for c in claims)
    removed = sum(c.applied == "removed" for c in claims)
    scope = f"{len(checked)} of {total}" if len(checked) < total else f"all {total}"
    unchecked = count["unclear"] + count["unchecked"]
    kept = sum(c.verdict == "unsupported" and c.shallow and not c.applied for c in claims)
    return (
        f"Claim check: {scope} cited statements were compared with the text of their sources. "
        f"{count['supported']} were supported, {count['partial']} partly and {count['unsupported']} not; "
        f"{reworded} were reworded to match their sources and {removed} removed."
        + (f" {unchecked} could not be checked (the source's saved text was missing, too short or unrelated)."
           if unchecked else "")
        + ((" 1 statement rests only on search snippets too short to confirm it; it was left in, unverified."
            if kept == 1 else
            f" {kept} statements rest only on search snippets too short to confirm them; they were left in, "
            "unverified.") if kept else "")
    )


def check_claims(
    text: str,
    registry: SourceRegistry,
    llm: LLMFn,
    *,
    workers: int = 4,
    batch_size: int = DEFAULT_BATCH,
    max_claims: int = DEFAULT_MAX_CLAIMS,
) -> tuple[str, list[Claim], str]:
    """Returns the corrected text, every claim with its verdict, and a one-line summary for the notes."""
    claims = extract_claims(text)
    if not claims:
        return text, claims, "Claim check: the report has no cited statements to check."
    step = max(1, -(-len(claims) // max_claims))  # ceil: sample evenly so every section is covered
    chosen = claims[::step][:max_claims]
    chosen_ids = {id(c) for c in chosen}  # by identity: the same sentence can appear twice
    for claim in claims:
        if id(claim) not in chosen_ids:
            claim.verdict = "skipped"
    to_judge = []
    for claim in chosen:
        if _has_text(claim, registry):
            to_judge.append(claim)
        else:
            claim.verdict = "unchecked"
    numbered = list(enumerate(to_judge, 1))
    batches = [numbered[i:i + batch_size] for i in range(0, len(numbered), batch_size)]
    if batches:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(batches)))) as pool:
            results = list(pool.map(lambda b: _judge_batch(b, registry, llm), batches))
        verdicts = {k: v for r in results for k, v in r.items()}
        for n, claim in numbered:
            item = verdicts.get(n, {})
            verdict = str(item.get("verdict", "")).lower()
            claim.verdict = verdict if verdict in ("supported", "partial", "unsupported", "unclear") else "unclear"
            claim.fix = str(item.get("fix") or "").strip() or None
    for claim in to_judge:
        claim.shallow = _shallow_only(claim, registry)
        text = _apply(text, claim)
    return text, claims, _note(claims)
