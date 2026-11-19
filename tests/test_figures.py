import csv
import json

from core.models import FigureSpec
from core.registry import SourceRegistry
from report.figures import build_bibliometric_tables, describe_tables, plan_figures, validate_specs


def _csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


def _spec(**kw):
    base = dict(kind="bar", title="Papers per year", data_ref="papers_per_year.csv", x="year", y="papers", caption="c", source_ids=[])
    base.update(kw)
    return FigureSpec(**base)


def _reg(tmp_path):
    r = SourceRegistry(tmp_path)
    r.add("https://a.com", "A", "web", "web_search")
    return r


def test_validate_specs_rejects_missing_data_file(tmp_path):
    ok, reasons = validate_specs([_spec()], tmp_path, _reg(tmp_path))
    assert ok == [] and "papers_per_year.csv" in reasons[0]


def test_validate_specs_rejects_non_numeric_y(tmp_path):
    _csv(tmp_path / "papers_per_year.csv", [["year", "papers"], ["2020", "many"], ["2021", "few"]])
    ok, reasons = validate_specs([_spec()], tmp_path, _reg(tmp_path))
    assert ok == [] and "numeric" in reasons[0]


def test_validate_specs_rejects_single_row_and_missing_columns(tmp_path):
    _csv(tmp_path / "papers_per_year.csv", [["year", "papers"], ["2020", "3"]])
    ok, reasons = validate_specs([_spec(), _spec(y="nope")], tmp_path, _reg(tmp_path))
    assert ok == [] and len(reasons) == 2


def test_validate_specs_drops_unknown_source_ids_but_keeps_figure(tmp_path):
    _csv(tmp_path / "papers_per_year.csv", [["year", "papers"], ["2020", "3"], ["2021", "4"]])
    ok, reasons = validate_specs([_spec(source_ids=["S1", "S99", "papers_per_year.csv"])], tmp_path, _reg(tmp_path))
    assert len(ok) == 1 and ok[0].source_ids == ["S1"]
    assert reasons == []


def test_validate_specs_attaches_data_file_sources(tmp_path):
    reg = _reg(tmp_path)
    reg.add("https://b.com", "B", "paper", "read_open_access_pdf")
    _csv(tmp_path / "papers_per_year.csv", [["year", "papers"], ["2020", "3"], ["2021", "4"]])
    _csv(tmp_path / "S2_table1.csv", [["year", "papers"], ["2020", "3"], ["2021", "4"]])
    specs = [_spec(), _spec(data_ref="S2_table1.csv")]
    ok, _ = validate_specs(specs, tmp_path, reg, data_sources={"papers_per_year.csv": "S1"})
    assert ok[0].source_ids == ["S1"]
    assert ok[1].source_ids == ["S2"]


def test_validate_specs_keeps_valid(tmp_path):
    _csv(tmp_path / "papers_per_year.csv", [["year", "papers"], ["2020", "3"], ["2021", "4"]])
    ok, reasons = validate_specs([_spec(source_ids=["S1"])], tmp_path, _reg(tmp_path))
    assert len(ok) == 1 and reasons == []


def test_validate_specs_rejects_path_traversal(tmp_path):
    ok, reasons = validate_specs([_spec(data_ref="../secret.csv")], tmp_path, _reg(tmp_path))
    assert ok == [] and reasons


def test_plan_figures_bad_json_returns_empty():
    assert plan_figures(lambda p: "not json", "f", "a", ["t.csv: x,y"], (3, 4)) == []


def test_plan_figures_parses_valid_and_skips_invalid_entries():
    raw = json.dumps([
        {"kind": "bar", "title": "T", "data_ref": "papers_per_year.csv", "x": "year", "y": "papers", "caption": "c", "source_ids": []},
        {"kind": "donut", "title": "bad kind", "data_ref": "x.csv", "x": "a", "y": "b", "caption": "c"},
    ])
    specs = plan_figures(lambda p: raw, "f", "a", ["papers_per_year.csv: year,papers"], (3, 4))
    assert [s.title for s in specs] == ["T"]


def test_bibliometric_table_written_from_year_counts(tmp_path):
    names = build_bibliometric_tables("gan", tmp_path, None, counts_fn=lambda q, e: {2021: 9, 2020: 5})
    assert names == ["papers_per_year.csv"]
    lines = (tmp_path / "papers_per_year.csv").read_text(encoding="utf-8").splitlines()
    assert lines == ["year,papers", "2020,5", "2021,9"]


def test_bibliometric_table_skipped_when_no_counts(tmp_path):
    assert build_bibliometric_tables("gan", tmp_path, None, counts_fn=lambda q, e: {}) == []


def test_describe_tables_lists_columns(tmp_path):
    _csv(tmp_path / "S1_table1.csv", [["year", "n"], ["2020", "3"]])
    assert describe_tables(tmp_path) == ["S1_table1.csv: year, n (1 rows)"]


def test_bibliometric_table_registers_openalex_source(tmp_path):
    reg = SourceRegistry(tmp_path)
    data_sources = {}
    build_bibliometric_tables("gan", tmp_path / "data", None, counts_fn=lambda q, e: {2020: 5, 2021: 9},
                              registry=reg, data_sources=data_sources)
    [src] = reg.all()
    assert "openalex" in src.url and "gan" in src.title.lower()
    assert data_sources == {"papers_per_year.csv": src.id}
