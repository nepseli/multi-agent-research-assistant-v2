from core.registry import SourceRegistry


def _reg(tmp_path):
    return SourceRegistry(tmp_path)


def test_add_assigns_sequential_ids(tmp_path):
    r = _reg(tmp_path)
    a = r.add("https://a.com/1", "A", "web", "web_search")
    b = r.add("https://b.com/2", "B", "web", "web_search")
    assert (a.id, b.id) == ("S1", "S2")


def test_duplicate_url_variants_return_same_source(tmp_path):
    r = _reg(tmp_path)
    a = r.add("https://a.com/x/", "A", "web", "web_search")
    b = r.add("https://A.com/x#top", "A again", "web", "read_page")
    assert a.id == b.id
    assert len(r.all()) == 1


def test_duplicate_doi_returns_same_source(tmp_path):
    r = _reg(tmp_path)
    a = r.add("https://x.org/p1", "P", "paper", "academic", doi="10.1/ABC")
    b = r.add("https://y.org/other", "P", "paper", "academic", doi="https://doi.org/10.1/abc")
    assert a.id == b.id


def test_content_written_to_disk(tmp_path):
    r = _reg(tmp_path)
    s = r.add("https://a.com", "A", "web", "read_page", content="hello body")
    assert (tmp_path / "sources" / "S1.md").read_text(encoding="utf-8") == "hello body"
    assert s.content_path.endswith("S1.md")


def test_validate_citations_strips_unknown_and_reports(tmp_path):
    r = _reg(tmp_path)
    r.add("https://a.com", "A", "web", "web_search")
    report = r.validate_citations("Fact one [S1]. Fact two [S99].")
    assert report.unknown == ["S99"]
    assert "[S99]" not in report.cleaned
    assert "[S1]" in report.cleaned


def test_references_markdown_numbers_by_id(tmp_path):
    r = _reg(tmp_path)
    r.add("https://a.com", "Alpha", "web", "web_search")
    r.add("https://b.com", "Beta", "paper", "academic", doi="10.2/b", year=2024, authors=["X Y"])
    md = r.references_markdown()
    assert md.startswith("## References")
    assert "[S1] Alpha" in md and "https://a.com" in md
    assert "[S2] Beta" in md and "10.2/b" in md


def test_save_load_roundtrip(tmp_path):
    r = _reg(tmp_path)
    r.add("https://a.com", "A", "web", "web_search")
    r.save()
    r2 = SourceRegistry(tmp_path)
    r2.load()
    assert [s.id for s in r2.all()] == ["S1"]
    s = r2.add("https://b.com", "B", "web", "web_search")
    assert s.id == "S2"
