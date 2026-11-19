"""Free scholarly search APIs. Every function swallows network errors and returns an empty value."""
import re
import time
import xml.etree.ElementTree as ET

import httpx

_TIMEOUT = 20.0
_RETRY_DELAY = 1.0
_ATOM = {"a": "http://www.w3.org/2005/Atom"}


def _request(url: str, params: dict | None = None, headers: dict | None = None) -> httpx.Response | None:
    """GET with one retry on 429/5xx. Returns None on any failure."""
    for attempt in range(2):
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=_TIMEOUT, follow_redirects=True)
        except httpx.HTTPError:
            resp = None
        if resp is not None and resp.status_code < 400:
            return resp
        retryable = resp is None or resp.status_code == 429 or resp.status_code >= 500
        if attempt == 0 and retryable:
            time.sleep(_RETRY_DELAY)
            continue
        return None
    return None


def _json(resp: httpx.Response | None) -> dict:
    if resp is None:
        return {}
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _clean_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip().lower()) or None


def _item(**kw) -> dict:
    base = dict(title="", url="", doi=None, year=None, authors=[], abstract="", oa_pdf_url=None, source_api="")
    base.update(kw)
    return base


def _rebuild_abstract(index: dict | None) -> str:
    if not index:
        return ""
    words: dict[int, str] = {}
    for word, positions in index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words[i] for i in sorted(words))


def search_openalex(query: str, limit: int = 10, email: str | None = None) -> list[dict]:
    params = {"search": query, "per-page": limit}
    if email:
        params["mailto"] = email
    out = []
    for w in _json(_request("https://api.openalex.org/works", params)).get("results", []):
        loc = w.get("best_oa_location") or {}
        doi = _clean_doi(w.get("doi"))
        out.append(
            _item(
                title=w.get("display_name") or "",
                url=w.get("doi") or w.get("id") or "",
                doi=doi,
                year=w.get("publication_year"),
                authors=[a["author"]["display_name"] for a in w.get("authorships", []) if a.get("author")],
                abstract=_rebuild_abstract(w.get("abstract_inverted_index")),
                oa_pdf_url=loc.get("pdf_url"),
                source_api="openalex",
            )
        )
    return out


def _arxiv_query(query: str) -> str:
    # "all:a b c" lets arXiv match any one word, which pulled in off-topic papers; require every term.
    terms = re.findall(r"[\w\-]+", query)
    return " AND ".join(f"all:{t}" for t in terms) or f"all:{query}"


def search_arxiv(query: str, limit: int = 10) -> list[dict]:
    resp = _request(
        "https://export.arxiv.org/api/query",
        {"search_query": _arxiv_query(query), "start": 0, "max_results": limit},
    )
    if resp is None:
        return []
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        return []
    out = []
    for e in root.findall("a:entry", _ATOM):
        published = (e.findtext("a:published", default="", namespaces=_ATOM) or "")[:4]
        pdf = next(
            (l.get("href") for l in e.findall("a:link", _ATOM) if l.get("title") == "pdf"), None
        )
        out.append(
            _item(
                title=" ".join((e.findtext("a:title", default="", namespaces=_ATOM)).split()),
                url=(e.findtext("a:id", default="", namespaces=_ATOM)).strip(),
                year=int(published) if published.isdigit() else None,
                authors=[n.text for n in e.findall("a:author/a:name", _ATOM) if n.text],
                abstract=" ".join((e.findtext("a:summary", default="", namespaces=_ATOM)).split()),
                oa_pdf_url=pdf,
                source_api="arxiv",
            )
        )
    return out


def search_crossref(query: str, limit: int = 10, email: str | None = None) -> list[dict]:
    params = {"query": query, "rows": limit}
    if email:
        params["mailto"] = email
    out = []
    for it in _json(_request("https://api.crossref.org/works", params)).get("message", {}).get("items", []):
        parts = (it.get("issued") or {}).get("date-parts") or [[None]]
        abstract = re.sub(r"<[^>]+>", "", it.get("abstract") or "").strip()
        out.append(
            _item(
                title=(it.get("title") or [""])[0],
                url=it.get("URL") or "",
                doi=_clean_doi(it.get("DOI")),
                year=parts[0][0] if parts and parts[0] else None,
                authors=[f"{a.get('given', '')} {a.get('family', '')}".strip() for a in it.get("author", [])],
                abstract=abstract,
                source_api="crossref",
            )
        )
    return out


def search_semantic_scholar(query: str, limit: int = 10, api_key: str | None = None) -> list[dict]:
    headers = {"x-api-key": api_key} if api_key else None
    params = {
        "query": query,
        "limit": limit,
        "fields": "title,year,authors,abstract,externalIds,openAccessPdf,url",
    }
    out = []
    for p in _json(_request("https://api.semanticscholar.org/graph/v1/paper/search", params, headers)).get("data", []):
        out.append(
            _item(
                title=p.get("title") or "",
                url=p.get("url") or "",
                doi=_clean_doi((p.get("externalIds") or {}).get("DOI")),
                year=p.get("year"),
                authors=[a.get("name", "") for a in p.get("authors", [])],
                abstract=p.get("abstract") or "",
                oa_pdf_url=(p.get("openAccessPdf") or {}).get("url"),
                source_api="semantic_scholar",
            )
        )
    return out


def unpaywall_pdf_url(doi: str, email: str) -> str | None:
    data = _json(_request(f"https://api.unpaywall.org/v2/{doi}", {"email": email}))
    return (data.get("best_oa_location") or {}).get("url_for_pdf")


def openalex_year_counts(query: str, email: str | None = None) -> dict[int, int]:
    params = {"search": query, "group_by": "publication_year"}
    if email:
        params["mailto"] = email
    counts: dict[int, int] = {}
    for g in _json(_request("https://api.openalex.org/works", params)).get("group_by", []):
        try:
            counts[int(g["key"])] = int(g["count"])
        except (KeyError, ValueError, TypeError):
            continue
    return dict(sorted(counts.items()))


def search_all(query: str, limit: int, settings: dict) -> list[dict]:
    """Query every free scholarly API and merge, deduping by DOI then by lowercase title."""
    email = settings.get("email")
    batches = [
        search_openalex(query, limit, email),
        search_semantic_scholar(query, limit, settings.get("semantic_scholar_key")),
        search_crossref(query, limit, email),
        search_arxiv(query, limit),
    ]
    seen: set[str] = set()
    merged: list[dict] = []
    for batch in batches:
        for item in batch:
            key = item["doi"] or item["title"].strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged
