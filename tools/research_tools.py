"""CrewAI tools bound to one run: they enforce the plan's budget and record every source."""
import csv
import functools
import os
from dataclasses import dataclass, field

import httpx
from crewai.tools import tool

from core.models import ResearchPlan
from core.run_context import RunContext
from tools import academic

_SNIPPET_CHARS = 700
_PAGE_CHARS = 8000


@dataclass
class _Counters:
    searches: int = 0
    pages: int = 0
    pdfs: int = 0
    credits: int = 0
    oa_urls: dict[str, str] = field(default_factory=dict)  # doi -> open-access PDF URL


def serper_search(query: str) -> list[dict]:
    """Default web search via the Serper API. Returns [{title, link, snippet}]."""
    key = os.getenv("SERPER_API_KEY", "")
    try:
        resp = httpx.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": query, "num": 8},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get("organic", [])
    except (httpx.HTTPError, ValueError):
        return []


def firecrawl_scrape(url: str, api_key: str) -> dict:
    """Fallback scrape through the Firecrawl cloud API (1 credit per page)."""
    try:
        resp = httpx.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"url": url, "formats": ["markdown"]},
            timeout=90,
        )
        data = resp.json().get("data", {})
        markdown = data.get("markdown", "")
        if resp.status_code >= 400 or not markdown:
            return {"ok": False, "error": f"firecrawl HTTP {resp.status_code}"}
        return {"ok": True, "markdown": markdown, "title": (data.get("metadata") or {}).get("title", "")}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


def build_tools(plan: ResearchPlan, ctx: RunContext, worker, settings: dict) -> list:
    budget = plan.budget
    counters = _Counters()
    search_fn = settings.get("serper_search", serper_search)
    academic_fn = settings.get("academic_search", academic.search_all)
    unpaywall_fn = settings.get("unpaywall_pdf", academic.unpaywall_pdf_url)
    fc_key = settings.get("firecrawl_api_key") or None
    fc_fn = settings.get("firecrawl_scrape", firecrawl_scrape)
    email = settings.get("email") or ""

    def exhausted(what: str) -> str:
        ctx.log("budget_exhausted", what=what)
        return f"BUDGET EXHAUSTED: {what}. Work with the sources already collected."

    def stoppable(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if ctx.cancelled():
                return "STOPPED: the user cancelled this run. Finish now with what you have."
            return fn(*args, **kwargs)

        return wrapper

    @tool("web_search")
    @stoppable
    def web_search(query: str) -> str:
        """Search the web. Returns numbered sources like [S3] with title, URL and snippet. Cite sources by their [S#] id."""
        if counters.searches >= budget.max_searches:
            return exhausted("searches")
        counters.searches += 1
        lines = []
        for item in search_fn(query):
            link = item.get("link") or item.get("url")
            if not link:
                continue
            title = item.get("title") or link
            snippet = (item.get("snippet") or "")[:_SNIPPET_CHARS]
            src = ctx.registry.add(link, title, "web", "web_search", content=snippet or None)
            lines.append(f"[{src.id}] {title} — {link}\n    {snippet}")
        ctx.log("web_search", query=query, results=len(lines))
        return "\n".join(lines) or "No results."

    tools = [web_search]

    if budget.max_pages > 0:

        @tool("read_page")
        @stoppable
        def read_page(url: str) -> str:
            """Open a web page and return its main text as Markdown, tagged with its [S#] source id."""
            if counters.pages >= budget.max_pages:
                return exhausted("pages")
            counters.pages += 1
            result = worker.scrape(url)
            if not result.get("ok") and plan.tier == 3 and fc_key and counters.credits < budget.firecrawl_credits:
                counters.credits += 1
                ctx.log("firecrawl_fallback", url=url)
                result = fc_fn(url, fc_key)
            if not result.get("ok"):
                ctx.log("read_failed", url=url, error=result.get("error"))
                return f"FAILED to read {url}: {result.get('error')}. Use search snippets instead."
            title = result.get("title") or url
            src = ctx.registry.add(url, title, "web", "read_page", content=result["markdown"])
            ctx.log("read_page", url=url, source=src.id, chars=len(result["markdown"]))
            return f"[{src.id}] {title}\n{result['markdown'][:_PAGE_CHARS]}"

        tools.append(read_page)

    if plan.use_academic:

        @tool("academic_search")
        @stoppable
        def academic_search(query: str) -> str:
            """Search scholarly databases (OpenAlex, Semantic Scholar, Crossref, arXiv). Returns numbered papers with abstracts."""
            if counters.searches >= budget.max_searches:
                return exhausted("searches")
            counters.searches += 1
            lines = []
            for p in academic_fn(query, 8, settings):
                src = ctx.registry.add(
                    p["url"] or (f"https://doi.org/{p['doi']}" if p.get("doi") else p["title"]),
                    p["title"], "paper", "academic_search",
                    doi=p.get("doi"), year=p.get("year"), authors=p.get("authors"),
                    content=p.get("abstract") or None,
                )
                if p.get("doi") and p.get("oa_pdf_url"):
                    counters.oa_urls[src.doi or p["doi"]] = p["oa_pdf_url"]
                who = ", ".join(p.get("authors", [])[:3])
                lines.append(f"[{src.id}] {p['title']} ({p.get('year')}) {who}\n    {(p.get('abstract') or '')[:_SNIPPET_CHARS]}")
            ctx.log("academic_search", query=query, results=len(lines))
            return "\n".join(lines) or "No papers found."

        tools.append(academic_search)

    if plan.use_pdf_parsing:

        @tool("read_open_access_pdf")
        @stoppable
        def read_open_access_pdf(doi_or_url: str) -> str:
            """Parse an open-access paper PDF (by DOI or direct PDF URL) into Markdown. Paywalled papers are not fetched."""
            if counters.pdfs >= budget.max_pdfs:
                return exhausted("pdfs")
            ident = doi_or_url.strip()
            doi = None if ident.startswith("http") else ident.lower()
            url = ident if ident.startswith("http") else counters.oa_urls.get(doi or "")
            if not url and doi and email:
                url = unpaywall_fn(doi, email)
            if not url:
                ctx.log("no_open_access", ident=ident)
                return f"No open-access copy found for {ident}; rely on the abstract only."
            counters.pdfs += 1
            result = worker.parse_pdf(url)
            if not result.get("ok"):
                ctx.log("read_failed", url=url, error=result.get("error"))
                return f"FAILED to parse {url}: {result.get('error')}. Rely on the abstract."
            src = ctx.registry.add(url, doi or url, "pdf", "read_open_access_pdf", doi=doi, content=result["markdown"])
            data_dir = ctx.run_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            for i, rows in enumerate(result.get("tables", []), start=1):
                with (data_dir / f"{src.id}_table{i}.csv").open("w", newline="", encoding="utf-8") as fh:
                    csv.writer(fh).writerows(rows)
            ctx.log("read_pdf", url=url, source=src.id, tables=len(result.get("tables", [])))
            return f"[{src.id}] {src.title}\n{result['markdown'][:_PAGE_CHARS]}"

        tools.append(read_open_access_pdf)

    return tools
