import httpx
import pytest
import respx

from tools import academic
from tools.academic import (
    openalex_year_counts,
    search_all,
    search_arxiv,
    search_crossref,
    search_openalex,
    search_semantic_scholar,
    unpaywall_pdf_url,
)

OPENALEX = {
    "results": [
        {
            "display_name": "GaN on Si defects",
            "doi": "https://doi.org/10.1000/gan1",
            "id": "https://openalex.org/W1",
            "publication_year": 2023,
            "authorships": [{"author": {"display_name": "A One"}}, {"author": {"display_name": "B Two"}}],
            "abstract_inverted_index": {"Defects": [0], "in": [1], "GaN": [2]},
            "best_oa_location": {"pdf_url": "https://oa.example/gan1.pdf"},
        }
    ]
}

ARXIV = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <id>http://arxiv.org/abs/2301.00001v1</id>
  <title> Wide bandgap   review </title>
  <summary> A survey. </summary>
  <published>2023-01-02T00:00:00Z</published>
  <author><name>C Three</name></author>
  <link title="pdf" href="http://arxiv.org/pdf/2301.00001v1" rel="related" type="application/pdf"/>
 </entry>
</feed>"""

CROSSREF = {
    "message": {
        "items": [
            {
                "title": ["Strain in epitaxy"],
                "DOI": "10.1000/Epi2",
                "URL": "https://doi.org/10.1000/epi2",
                "issued": {"date-parts": [[2021, 5]]},
                "author": [{"given": "D", "family": "Four"}],
                "abstract": "<jats:p>Strain matters.</jats:p>",
            }
        ]
    }
}

S2 = {
    "data": [
        {
            "title": "GaN on Si defects",
            "year": 2023,
            "authors": [{"name": "A One"}],
            "abstract": "Defects in GaN",
            "externalIds": {"DOI": "10.1000/GAN1"},
            "openAccessPdf": {"url": "https://s2.example/gan1.pdf"},
            "url": "https://www.semanticscholar.org/paper/x",
        }
    ]
}


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    monkeypatch.setattr(academic, "_RETRY_DELAY", 0)


@respx.mock
def test_openalex_normalises_fields():
    respx.get("https://api.openalex.org/works").mock(return_value=httpx.Response(200, json=OPENALEX))
    [r] = search_openalex("gan", limit=5, email="me@x.org")
    assert r["title"] == "GaN on Si defects"
    assert r["doi"] == "10.1000/gan1"
    assert r["year"] == 2023
    assert r["authors"] == ["A One", "B Two"]
    assert r["abstract"] == "Defects in GaN"
    assert r["oa_pdf_url"] == "https://oa.example/gan1.pdf"
    assert r["source_api"] == "openalex"


@respx.mock
def test_arxiv_parses_atom():
    respx.get("https://export.arxiv.org/api/query").mock(return_value=httpx.Response(200, text=ARXIV))
    [r] = search_arxiv("wide bandgap")
    assert r["title"] == "Wide bandgap review"
    assert r["year"] == 2023
    assert r["authors"] == ["C Three"]
    assert r["oa_pdf_url"].endswith("2301.00001v1")
    assert r["url"] == "http://arxiv.org/abs/2301.00001v1"


@respx.mock
def test_crossref_normalises_fields():
    respx.get("https://api.crossref.org/works").mock(return_value=httpx.Response(200, json=CROSSREF))
    [r] = search_crossref("strain")
    assert r["doi"] == "10.1000/epi2"
    assert r["year"] == 2021
    assert r["authors"] == ["D Four"]
    assert r["abstract"] == "Strain matters."


@respx.mock
def test_semantic_scholar_sends_api_key_header_when_given():
    route = respx.get("https://api.semanticscholar.org/graph/v1/paper/search").mock(
        return_value=httpx.Response(200, json=S2)
    )
    [r] = search_semantic_scholar("gan", api_key="KEY")
    assert route.calls.last.request.headers["x-api-key"] == "KEY"
    assert r["doi"] == "10.1000/gan1"
    assert r["oa_pdf_url"] == "https://s2.example/gan1.pdf"


@respx.mock
def test_semantic_scholar_no_header_without_key():
    route = respx.get("https://api.semanticscholar.org/graph/v1/paper/search").mock(
        return_value=httpx.Response(200, json=S2)
    )
    search_semantic_scholar("gan")
    assert "x-api-key" not in route.calls.last.request.headers


@respx.mock
def test_unpaywall_returns_best_oa_pdf_or_none():
    respx.get("https://api.unpaywall.org/v2/10.1/a").mock(
        return_value=httpx.Response(200, json={"best_oa_location": {"url_for_pdf": "https://oa/a.pdf"}})
    )
    respx.get("https://api.unpaywall.org/v2/10.1/b").mock(
        return_value=httpx.Response(200, json={"best_oa_location": None})
    )
    assert unpaywall_pdf_url("10.1/a", "me@x.org") == "https://oa/a.pdf"
    assert unpaywall_pdf_url("10.1/b", "me@x.org") is None


@respx.mock
def test_year_counts_returns_int_keys():
    payload = {"group_by": [{"key": "2022", "count": 10}, {"key": "2023", "count": 14}]}
    respx.get("https://api.openalex.org/works").mock(return_value=httpx.Response(200, json=payload))
    assert openalex_year_counts("gan") == {2022: 10, 2023: 14}


@respx.mock
def test_failure_returns_empty_not_exception():
    respx.get("https://api.openalex.org/works").mock(return_value=httpx.Response(500))
    respx.get("https://api.crossref.org/works").mock(side_effect=httpx.ConnectError("down"))
    respx.get("https://api.unpaywall.org/v2/10.1/zz").mock(return_value=httpx.Response(503))
    assert search_openalex("x") == []
    assert search_crossref("x") == []
    assert openalex_year_counts("x") == {}
    assert unpaywall_pdf_url("10.1/zz", "a@b.c") is None


@respx.mock
def test_retries_once_on_429():
    route = respx.get("https://api.openalex.org/works").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json=OPENALEX)]
    )
    assert len(search_openalex("gan")) == 1
    assert route.call_count == 2


@respx.mock
def test_search_all_dedupes_by_doi():
    respx.get("https://api.openalex.org/works").mock(return_value=httpx.Response(200, json=OPENALEX))
    respx.get("https://export.arxiv.org/api/query").mock(return_value=httpx.Response(200, text=ARXIV))
    respx.get("https://api.crossref.org/works").mock(return_value=httpx.Response(200, json=CROSSREF))
    respx.get("https://api.semanticscholar.org/graph/v1/paper/search").mock(
        return_value=httpx.Response(200, json=S2)
    )
    results = search_all("gan", limit=5, settings={})
    dois = [r["doi"] for r in results if r["doi"]]
    assert dois.count("10.1000/gan1") == 1
    assert len(results) == 3  # gan1 (deduped), arxiv paper, crossref paper
