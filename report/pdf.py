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


def build_html(md: str, figures: list[tuple[FigureSpec, Path]], diagrams: list[str], title: str, notes: list[str]) -> str:
    # Report text comes from models and web pages: never let it inject markup into the rendered page.
    safe_md = _strip_coverage(md).replace("<", "&lt;")
    body = markdown.markdown(safe_md, extensions=["tables", "sane_lists"])
    body = _number_tables(body)
    parts = []
    for i, (spec, path) in enumerate(figures, 1):
        cite = f" Sources: {', '.join(spec.source_ids)}." if spec.source_ids else ""
        parts.append(
            f'<figure><img src="{html.escape(Path(path).name)}" alt="{html.escape(spec.title)}">'
            f"<figcaption>Figure {i}. {html.escape(spec.caption)}{html.escape(cite)}</figcaption></figure>"
        )
    start = len(figures)
    for j, block in enumerate(diagrams, start + 1):
        parts.append(block.replace("<figcaption>", f"<figcaption>Figure {j}. ", 1))
    # Figures belong with the report body, so split off the generated reference list and put it after them.
    split = re.search(r"<h2[^>]*>\s*References\s*</h2>", body)
    body, references = (body[: split.start()], body[split.start():]) if split else (body, "")
    return _ENV.get_template("report.html.j2").render(
        title=title, body=body, figures_html="\n".join(parts), references=references,
        notes=[n for n in notes if n],
    )


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
