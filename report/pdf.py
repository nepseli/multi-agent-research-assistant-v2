"""Assemble the styled HTML for the PDF and hand it to the worker for rendering."""
import html
import re
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

from core.models import FigureSpec
from tools.worker_client import WorkerUnavailable


class PdfRenderError(RuntimeError):
    pass


_ENV = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=select_autoescape(["j2"]))


def _strip_coverage(md: str) -> str:
    return re.sub(r"\n## Coverage notes\b.*\Z", "\n", md, flags=re.S)


def _number_tables(body: str) -> str:
    count = 0

    def repl(match: re.Match) -> str:
        nonlocal count
        count += 1
        return f"<table{match.group(1)}><caption>Table {count}</caption>"

    return re.sub(r"<table([^>]*)>", repl, body)


_STOP = set(
    "the and for that with this from into over under about their there which have has been were was are its also "
    "than more most such these those other while will would could should figure chart diagram shows showing "
    "flowchart timeline mindmap root title section subgraph".split()
)
_PLACEHOLDER = "Figure §. "


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z][a-z0-9\-]+", html.unescape(re.sub(r"<[^>]+>", " ", text)).lower())
    return {w for w in words if len(w) > 3 and w not in _STOP}


def _place_figures(body: str, blocks: list[tuple[str, str]]) -> tuple[str, list[str]]:
    """Put each figure at the end of the section whose heading and text share the most words with it;
    figures that match no section are returned for the closing Figures section."""
    starts = [m.start() for m in re.finditer(r"<h2[\s>]", body)]
    if not starts:
        return body, [b for b, _ in blocks]
    bounds = list(zip(starts, starts[1:] + [len(body)]))
    sections = []
    for a, b in bounds:
        chunk = body[a:b]
        heading = re.search(r"<h2[^>]*>(.*?)</h2>", chunk, re.S)
        sections.append((_tokens(heading.group(1) if heading else ""), _tokens(chunk)))
    placed: dict[int, list[str]] = {}
    leftover = []
    for block, text in blocks:
        wanted = _tokens(text)
        scores = [3 * len(wanted & head) + len(wanted & words) for head, words in sections]
        best = max(range(len(scores)), key=lambda i: scores[i])
        if scores[best] >= 2:
            placed.setdefault(best, []).append(block)
        else:
            leftover.append(block)
    out, last = [], 0
    for i, (a, b) in enumerate(bounds):
        out.append(body[last:b])
        out.extend(placed.get(i, []))
        last = b
    out.append(body[last:])
    return "".join(out), leftover


def _link_citations(body: str, references: str) -> tuple[str, str]:
    """[S3] in the text links to its entry in the reference list (PDF viewers follow internal links)."""
    body = re.sub(r"\[(S\d+)\]", r'<a class="cite" href="#ref-\1">[\1]</a>', body)
    references = re.sub(r"(<p>|<br />\n)\[(S\d+)\]", r'\1<a id="ref-\2"></a>[\2]', references)
    return body, references


def _number_figures(page: str) -> str:
    count = 0

    def repl(_m: re.Match) -> str:
        nonlocal count
        count += 1
        return f"Figure {count}. "

    return re.sub(re.escape(_PLACEHOLDER), repl, page)


def build_html(md: str, figures: list[tuple[FigureSpec, Path]], diagrams: list[str], title: str, notes: list[str]) -> str:
    # Report text comes from models and web pages: never let it inject markup into the rendered page.
    safe_md = _strip_coverage(md).replace("<", "&lt;")
    body = markdown.markdown(safe_md, extensions=["tables", "sane_lists"])
    body = _number_tables(body)
    # The generated reference list goes after any leftover figures, at the end.
    split = re.search(r"<h2[^>]*>\s*References\s*</h2>", body)
    body, references = (body[: split.start()], body[split.start():]) if split else (body, "")
    body, references = _link_citations(body, references)
    blocks = []
    for spec, path in figures:
        cite = f" Sources: {', '.join(spec.source_ids)}." if spec.source_ids else ""
        blocks.append((
            f'<figure><img src="{html.escape(Path(path).name)}" alt="{html.escape(spec.title)}">'
            f"<figcaption>{_PLACEHOLDER}{html.escape(spec.caption)}{html.escape(cite)}</figcaption></figure>",
            f"{spec.title} {spec.caption}",
        ))
    for block in diagrams:
        code = re.search(r'<pre class="mermaid">(.*?)</pre>', block, re.S)
        caption = re.search(r"<figcaption>(.*?)</figcaption>", block, re.S)
        text = f"{caption.group(1) if caption else ''} {caption.group(1) if caption else ''} {code.group(1) if code else ''}"
        blocks.append((block.replace("<figcaption>", f"<figcaption>{_PLACEHOLDER}", 1), text))
    body, leftover = _place_figures(body, blocks)
    page = _ENV.get_template("report.html.j2").render(
        title=title, body=body, figures_html="\n".join(leftover), references=references,
        notes=[n for n in notes if n],
    )
    return _number_figures(page)


def render(html_text: str, assets: dict[str, bytes], worker, out: Path) -> Path:
    try:
        data = worker.render_pdf(html_text, assets)
    except WorkerUnavailable as exc:
        raise PdfRenderError(f"PDF worker unavailable: {exc}") from exc
    if not data.startswith(b"%PDF"):
        raise PdfRenderError("worker returned a non-PDF response")
    out = Path(out)
    out.write_bytes(data)
    return out
