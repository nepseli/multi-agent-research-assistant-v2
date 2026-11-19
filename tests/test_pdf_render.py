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


def test_diagrams_are_capped_to_one_page():
    html = build_html(MD, [], ['<figure class="diagram"><pre class="mermaid">flowchart LR\nA-->B</pre></figure>'], "Title", [])
    assert "figure.diagram svg" in html and "max-height" in html


def test_figures_heading_has_an_id_for_the_renderer():
    html = build_html(MD, [], ['<figure class="diagram"><pre class="mermaid">flowchart LR\nA-->B</pre></figure>'], "Title", [])
    assert 'id="figures-heading"' in html


def test_figures_heading_stays_with_the_first_figure():
    html = build_html(MD, [], ['<figure class="diagram"><pre class="mermaid">flowchart LR\nA-->B</pre></figure>'], "Title", [])
    assert "#figures-heading" in html and "break-after: avoid" in html


# -- layout: figures by section, linked citations ------------------------------

LAYOUT_MD = (
    "# Title\n\n"
    "## Funding and investment\n\nVenture funding for agent startups grew [S1].\n\n"
    "## Policy\n\nThe governance framework sets rules [S2].\n\n"
    "## References\n\n[S1] Alpha  \n[S2] Beta\n"
)


def _chart(title, caption):
    return FigureSpec(kind="bar", title=title, data_ref="d.csv", x="x", y="y", caption=caption, source_ids=[])


def _diagram(caption, code="flowchart LR\nA-->B"):
    return f'<figure class="diagram"><pre class="mermaid">{code}</pre><figcaption>{caption}</figcaption></figure>'


def test_figures_go_after_the_section_they_illustrate_and_are_numbered_in_reading_order(tmp_path):
    figs = [(_chart("Governance framework rules", "Rules in the governance framework"), tmp_path / "fig1.svg")]
    diagrams = [_diagram("Venture funding of agent startups")]
    page = build_html(LAYOUT_MD, figs, diagrams, "Title", [])
    funding, policy = page.index("Funding and investment"), page.index("<h2>Policy")
    funding_fig = page.index("Venture funding of agent startups")
    policy_fig = page.index("Rules in the governance framework")
    assert funding < funding_fig < policy < policy_fig < page.index("References")
    assert page.index("Figure 1.") < page.index("Figure 2.")  # numbered by position, not by list order
    assert "Figure 1. Venture funding" in page
    assert 'id="figures-section"' not in page  # nothing left over for an end section


def test_a_figure_that_matches_no_section_goes_to_the_figures_section(tmp_path):
    page = build_html(LAYOUT_MD, [], [_diagram("Weather patterns over oceans")], "Title", [])
    assert page.index('id="figures-section"') < page.index("Weather patterns") < page.index("References")


def test_citations_link_to_their_reference_entries():
    page = build_html(LAYOUT_MD, [], [], "Title", [])
    assert '<a class="cite" href="#ref-S1">[S1]</a>' in page
    assert 'id="ref-S1"' in page and 'id="ref-S2"' in page
    refs = page[page.index("References"):]
    assert 'href="#ref-' not in refs  # the reference list itself is not linked to itself


def test_method_box_is_styled_as_a_box():
    page = build_html("# T\n\n> **How this report was made.** Searched.\n\n## A\n\nx\n", [], [], "T", [])
    assert "<blockquote>" in page and "blockquote" in page.split("</style>")[0]
