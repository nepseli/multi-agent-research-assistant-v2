from core.registry import SourceRegistry, normalize_citations


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


def test_references_markdown_lists_only_cited_sources(tmp_path):
    r = _reg(tmp_path)
    r.add("https://a.com", "Alpha", "web", "web_search")
    r.add("https://b.com", "Beta", "web", "web_search")
    r.add("https://c.com", "Gamma", "web", "web_search")
    md = r.references_markdown(cited=["S3", "S1"])
    assert "[S1] Alpha" in md and "[S3] Gamma" in md
    assert "Beta" not in md
    assert md.index("[S1]") < md.index("[S3]")


def test_cited_ids_reads_single_and_grouped_citations(tmp_path):
    r = _reg(tmp_path)
    assert r.cited_ids("A [S2]. B [S1, S4]; C [S2][S7]") == ["S1", "S2", "S4", "S7"]


def test_validate_citations_handles_grouped_ids(tmp_path):
    r = _reg(tmp_path)
    r.add("https://a.com", "A", "web", "web_search")
    report = r.validate_citations("Fact [S1, S99].")
    assert report.unknown == ["S99"]
    assert "S99" not in report.cleaned
    assert "[S1]" in report.cleaned


def test_empty_title_falls_back_to_doi_or_url(tmp_path):
    r = _reg(tmp_path)
    a = r.add("https://doi.org/10.1/x", "  ", "paper", "academic", doi="10.1/x")
    b = r.add("https://b.com/page", "", "web", "web_search")
    assert a.title == "10.1/x"
    assert b.title == "https://b.com/page"


def test_references_markdown_says_so_when_nothing_cited(tmp_path):
    r = _reg(tmp_path)
    r.add("https://a.com", "Alpha", "web", "web_search")
    md = r.references_markdown(cited=[])
    assert "Alpha" not in md and "No sources were cited" in md


def test_fullwidth_citations_normalised_to_ascii():
    # gpt-oss often cites as 【S8】, sometimes with a †line-range suffix or several ids.
    text = "A 【S8】. B 【S2†L10-L12】. C 【S1, S4】. Not a cite: 【note】."
    assert normalize_citations(text) == "A [S8]. B [S2]. C [S1], [S4]. Not a cite: 【note】."


def test_cited_ids_and_validation_read_fullwidth_citations(tmp_path):
    r = _reg(tmp_path)
    r.add("https://a.com", "A", "web", "web_search")
    assert SourceRegistry.cited_ids("x 【S1】 y 【S9】") == ["S1", "S9"]
    report = r.validate_citations("x 【S1】 y 【S9】.")
    assert report.unknown == ["S9"] and report.cleaned == "x [S1] y."


# -- source depth --------------------------------------------------------------

def test_reading_a_page_found_by_search_keeps_the_full_text(tmp_path):
    # The usual path: a page is first a search hit (snippet), then the agent reads it.
    r = _reg(tmp_path)
    hit = r.add("https://a.com/x", "A", "web", "web_search", content="short snippet")
    read = r.add("https://a.com/x/", "A", "web", "read_page", content="the whole article " * 50)
    assert read.id == hit.id
    assert read.depth == "full_text" and read.tool == "read_page"
    assert "whole article" in r.content(read.id)


def test_a_shallower_add_never_replaces_deeper_text(tmp_path):
    r = _reg(tmp_path)
    r.add("https://a.com/x", "A", "web", "read_page", content="the whole article")
    again = r.add("https://a.com/x", "A", "web", "web_search", content="short snippet")
    assert again.depth == "full_text" and r.content(again.id) == "the whole article"


def test_parsed_pdf_upgrades_the_paper_found_by_academic_search(tmp_path):
    r = _reg(tmp_path)
    paper = r.add("https://doi.org/10.1/x", "Paper", "paper", "academic_search", doi="10.1/x", content="abstract")
    pdf = r.add("https://host/x.pdf", "10.1/x", "pdf", "read_open_access_pdf", doi="10.1/x", content="full paper text")
    assert pdf.id == paper.id and pdf.depth == "full_text"
    assert pdf.title == "Paper"  # the readable title is kept, not the DOI
    assert r.content(pdf.id) == "full paper text"


def test_depth_from_tool_and_old_sources_json_still_loads(tmp_path):
    import json

    r = _reg(tmp_path)
    assert r.add("https://a.com", "A", "web", "web_search", content="s").depth == "snippet"
    assert r.add("https://d.org/1", "P", "paper", "academic_search", doi="10.2/y", content="abs").depth == "abstract"
    assert r.add("https://d.org/2", "P2", "paper", "academic_search").depth == "metadata"
    assert r.add("https://api.openalex.org/w", "Counts", "dataset", "openalex").depth == "dataset"
    r.save()
    data = json.loads((tmp_path / "sources.json").read_text(encoding="utf-8"))
    for item in data:
        item.pop("depth")  # a run saved before depth existed
    (tmp_path / "sources.json").write_text(json.dumps(data), encoding="utf-8")
    fresh = _reg(tmp_path)
    fresh.load()
    assert [s.depth for s in fresh.all()] == ["snippet", "abstract", "metadata", "dataset"]


def test_references_say_how_deeply_each_source_was_read(tmp_path):
    r = _reg(tmp_path)
    r.add("https://a.com", "Read page", "web", "read_page", content="text")
    r.add("https://b.com", "Search hit", "web", "web_search", content="snippet")
    r.add("https://d.org/1", "Paper", "paper", "academic_search", doi="10.2/y", content="abs")
    refs = r.references_markdown()
    assert "Read page" in refs and "(read in full)" in refs.split("\n")[2]
    assert "(search snippet only)" in refs.split("\n")[3]
    assert "(abstract only)" in refs.split("\n")[4]


def test_content_is_empty_for_a_source_without_text(tmp_path):
    r = _reg(tmp_path)
    src = r.add("https://a.com", "A", "web", "web_search")
    assert r.content(src.id) == "" and r.content("S99") == ""
