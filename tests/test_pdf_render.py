import pytest

from core.models import FigureSpec
from report.pdf import PdfRenderError, build_html, render
from tests.fakes import FakeWorker

MD = "# Title\n\n## Summary\n\nText [S1].\n\n## Findings\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n## Analysis\n\nMore.\n\n## References\n\n[S1] Alpha\n\n## Coverage notes\n\n- md-only note\n"


def _spec(n):
    return FigureSpec(kind="bar", title=f"F{n}", data_ref="d.csv", x="x", y="y", caption=f"caption {n}", source_ids=["S1"])


def test_build_html_numbers_figures_and_includes_notes(tmp_path):
    figs = [(_spec(1), tmp_path / "fig1.svg"), (_spec(2), tmp_path / "fig2.svg")]
    html = build_html(MD, figs, ['<figure class="diagram"><pre class="mermaid">flowchart TD\nA-->B</pre></figure>'], "Title", ["Worker was down"])
    assert "Figure 1" in html and "Figure 2" in html
    assert "caption 1" in html and "fig1.svg" in html
    assert "Table 1" in html
    assert "Worker was down" in html
    assert html.count("md-only note") == 0  # md coverage section replaced by the styled appendix
    assert 'class="mermaid"' in html
    assert "<h1" in html and "Title" in html


def test_build_html_without_figures_still_valid():
    html = build_html(MD, [], [], "Title", [])
    assert "<html" in html and "Figure 1" not in html


def test_render_calls_worker_and_writes_pdf(tmp_path):
    out = render("<html></html>", {"fig1.svg": b"<svg/>"}, FakeWorker(), tmp_path / "final_report.pdf")
    assert out.read_bytes().startswith(b"%PDF")


def test_render_failure_raises_clear_error_and_writes_nothing(tmp_path):
    target = tmp_path / "final_report.pdf"
    with pytest.raises(PdfRenderError) as err:
        render("<html></html>", {}, FakeWorker(healthy=False), target)
    assert "worker" in str(err.value).lower()
    assert not target.exists()


def test_build_html_escapes_raw_html_from_report_text():
    md = "# T\n\n<script>fetch('http://169.254.169.254')</script>\n\n<img src=http://internal/x>\n\ntext [S1]\n"
    html = build_html(md, [], [], "T", [])
    assert "<script>fetch" not in html and "<img src=http://internal" not in html
    assert "&lt;script&gt;" in html


def test_figures_are_placed_before_references(tmp_path):
    html = build_html(MD, [(_spec(1), tmp_path / "fig1.svg")], [], "Title", [])
    assert html.index("Figure 1") < html.index(">References<")
