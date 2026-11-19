import csv

from core.models import FigureSpec
from report.charts import render_chart
from report.diagrams import mermaid_block, plan_diagrams


def _data(tmp_path):
    with open(tmp_path / "d.csv", "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([["year", "papers"], ["2020", "3"], ["2021", "8"], ["2022", "5"]])


def _spec(kind="bar"):
    return FigureSpec(kind=kind, title="Papers per year", data_ref="d.csv", x="year", y="papers", caption="c", source_ids=[])


def test_render_chart_writes_svg_with_title(tmp_path):
    _data(tmp_path)
    out = render_chart(_spec(), tmp_path, tmp_path / "fig1.svg")
    text = out.read_text(encoding="utf-8")
    assert "<svg" in text and "Papers per year" in text


def test_render_chart_supports_line_and_pie(tmp_path):
    _data(tmp_path)
    for kind in ("line", "pie"):
        out = render_chart(_spec(kind), tmp_path, tmp_path / f"{kind}.svg")
        assert out.exists() and "<svg" in out.read_text(encoding="utf-8")


def test_mermaid_block_rejects_non_mermaid():
    assert mermaid_block("<script>alert(1)</script>", "cap") == ""
    assert mermaid_block("", "cap") == ""


def test_mermaid_block_accepts_and_escapes():
    html = mermaid_block("flowchart LR\n  A[<b>x</b>] --> B", "Flow of data")
    assert 'class="mermaid"' in html and "Flow of data" in html
    assert "<b>" not in html  # angle brackets escaped


def test_plan_diagrams_parses_json_and_filters_invalid():
    raw = '[{"code": "flowchart TD\\n A-->B", "caption": "ok"}, {"code": "nonsense", "caption": "bad"}]'
    out = [d for d in plan_diagrams(lambda p: raw, "f", "a", 2) if d.status != "dropped"]
    assert len(out) == 1 and "ok" in out[0].block()
    assert plan_diagrams(lambda p: "garbage", "f", "a", 2) == []
    assert plan_diagrams(lambda p: raw, "f", "a", 0) == []
