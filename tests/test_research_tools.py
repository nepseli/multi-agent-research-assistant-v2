import pytest

from core.config import TIER_CAPS
from core.models import Budget, ResearchPlan
from core.run_context import new_run
from tools.research_tools import build_tools


class FakeWorker:
    def __init__(self, scrape=None, parse=None):
        self._scrape = scrape or {"ok": True, "markdown": "BODY " * 50, "title": "Page", "error": None}
        self._parse = parse or {"ok": True, "markdown": "PAPER TEXT", "tables": [[["year", "n"], ["2020", "3"], ["2021", "5"]]], "error": None}
        self.scraped = []

    def scrape(self, url, timeout_s=60):
        self.scraped.append(url)
        return self._scrape

    def parse_pdf(self, url):
        return self._parse


def _plan(tier, **budget):
    b = TIER_CAPS[tier].model_copy(update=budget)
    return ResearchPlan(
        topic="t", tier=tier, budget=b, subqueries=["q"],
        use_academic=tier >= 2, use_pdf_parsing=tier >= 2,
    )


def _serper(query):
    return [
        {"title": "Result A", "link": "https://a.com/1", "snippet": "alpha snippet"},
        {"title": "Result B", "link": "https://b.com/2", "snippet": "beta snippet"},
    ]


def _paper_search(query, limit, settings):
    return [
        {"title": "GaN paper", "url": "https://doi.org/10.1/x", "doi": "10.1/x", "year": 2023,
         "authors": ["A One"], "abstract": "About GaN.", "oa_pdf_url": "https://oa/x.pdf", "source_api": "openalex"}
    ]


def _tools(tmp_path, plan, worker=None, **settings):
    ctx = new_run("topic", base=tmp_path)
    base = {"serper_search": _serper, "academic_search": _paper_search}
    base.update(settings)
    tools = build_tools(plan, ctx, worker or FakeWorker(), base)
    return ctx, {t.name: t for t in tools}


def test_web_search_registers_sources_and_prefixes_ids(tmp_path):
    ctx, t = _tools(tmp_path, _plan(1))
    out = t["web_search"].run(query="gan")
    assert "[S1] Result A" in out and "[S2] Result B" in out
    assert [s.url for s in ctx.registry.all()] == ["https://a.com/1", "https://b.com/2"]


def test_web_search_budget_exhausted(tmp_path):
    ctx, t = _tools(tmp_path, _plan(0))
    t["web_search"].run(query="one")
    t["web_search"].run(query="two")
    assert t["web_search"].run(query="three").startswith("BUDGET EXHAUSTED")


def test_read_page_registers_source_with_content(tmp_path):
    ctx, t = _tools(tmp_path, _plan(1))
    out = t["read_page"].run(url="https://a.com/1")
    assert out.startswith("[S1] Page")
    assert ctx.registry.get("S1").content_path is not None


def test_read_page_budget_exhausted_message(tmp_path):
    ctx, t = _tools(tmp_path, _plan(1, max_pages=1))
    t["read_page"].run(url="https://a.com/1")
    assert t["read_page"].run(url="https://a.com/2").startswith("BUDGET EXHAUSTED")


def test_read_page_worker_down_logs_and_returns_failure_text(tmp_path):
    worker = FakeWorker(scrape={"ok": False, "error": "worker unreachable"})
    ctx, t = _tools(tmp_path, _plan(1), worker)
    out = t["read_page"].run(url="https://a.com/1")
    assert out.startswith("FAILED to read")
    log = (ctx.run_dir / "log.jsonl").read_text(encoding="utf-8")
    assert "read_failed" in log and "worker unreachable" in log


def test_tier0_plan_has_no_read_tools(tmp_path):
    _, t = _tools(tmp_path, _plan(0))
    assert set(t) == {"web_search"}


def test_academic_tools_absent_below_tier2(tmp_path):
    _, t = _tools(tmp_path, _plan(1))
    assert "academic_search" not in t and "read_open_access_pdf" not in t
    _, t2 = _tools(tmp_path, _plan(2))
    assert {"academic_search", "read_open_access_pdf"} <= set(t2)


def test_academic_search_registers_paper_with_doi(tmp_path):
    ctx, t = _tools(tmp_path, _plan(2))
    out = t["academic_search"].run(query="gan")
    assert "[S1] GaN paper" in out and "2023" in out
    assert ctx.registry.get("S1").doi == "10.1/x"


def test_read_open_access_pdf_saves_tables_as_csv(tmp_path):
    ctx, t = _tools(tmp_path, _plan(2))
    t["academic_search"].run(query="gan")
    out = t["read_open_access_pdf"].run(doi_or_url="10.1/x")
    assert out.startswith("[S1]")
    csvs = list((ctx.run_dir / "data").glob("S1_table*.csv"))
    assert len(csvs) == 1
    assert csvs[0].read_text(encoding="utf-8").splitlines()[0] == "year,n"


def test_read_open_access_pdf_without_oa_copy(tmp_path):
    def no_oa(query, limit, settings):
        item = _paper_search(query, limit, settings)[0]
        item["oa_pdf_url"] = None
        return [item]

    ctx, t = _tools(tmp_path, _plan(2), academic_search=no_oa, unpaywall_pdf=lambda doi, email: None)
    t["academic_search"].run(query="gan")
    out = t["read_open_access_pdf"].run(doi_or_url="10.1/x")
    assert "no open-access" in out.lower()


def test_pdf_budget_exhausted(tmp_path):
    ctx, t = _tools(tmp_path, _plan(2, max_pdfs=1))
    t["academic_search"].run(query="gan")
    t["read_open_access_pdf"].run(doi_or_url="10.1/x")
    assert t["read_open_access_pdf"].run(doi_or_url="https://oa/other.pdf").startswith("BUDGET EXHAUSTED")


def test_firecrawl_fallback_only_tier3_with_key(tmp_path):
    failing = FakeWorker(scrape={"ok": False, "error": "blocked"})
    calls = []

    def fc(url, key):
        calls.append(url)
        return {"ok": True, "markdown": "FROM FIRECRAWL", "title": "FC"}

    _, t3 = _tools(tmp_path, _plan(3), failing, firecrawl_api_key="k", firecrawl_scrape=fc)
    assert t3["read_page"].run(url="https://x.com/a").startswith("[S1] FC")
    _, t3_nokey = _tools(tmp_path, _plan(3), failing, firecrawl_scrape=fc)
    assert t3_nokey["read_page"].run(url="https://x.com/b").startswith("FAILED")
    _, t2 = _tools(tmp_path, _plan(2), failing, firecrawl_api_key="k", firecrawl_scrape=fc)
    assert t2["read_page"].run(url="https://x.com/c").startswith("FAILED")
    assert calls == ["https://x.com/a"]


def test_tools_return_stopped_message_after_cancel(tmp_path):
    import threading
    from core.run_context import new_run
    from tests.fakes import FakeWorker
    from core.planning import finalize_plan
    from core.models import ResearchPlan
    from core.config import TIER_CAPS
    from tools.research_tools import build_tools

    calls = []
    ctx = new_run("t", base=tmp_path)
    ctx.cancel = threading.Event()
    plan = ResearchPlan(topic="t", tier=2, budget=TIER_CAPS[2], use_academic=True)
    tools = build_tools(plan, ctx, FakeWorker(), {"serper_search": lambda q, **k: calls.append(q) or []})
    search = next(t for t in tools if t.name == "web_search")
    ctx.cancel.set()
    out = search.run(query="anything")
    assert "STOPPED" in out and calls == []


def test_repeat_pdf_lookup_without_oa_copy_is_short_circuited(tmp_path):
    calls = []

    def no_oa(query, limit, settings):
        item = _paper_search(query, limit, settings)[0]
        item["oa_pdf_url"] = None
        return [item]

    ctx, t = _tools(tmp_path, _plan(2), academic_search=no_oa, email="me@x.org",
                    unpaywall_pdf=lambda doi, email: calls.append(doi))
    t["academic_search"].run(query="gan")
    t["read_open_access_pdf"].run(doi_or_url="10.1/x")
    out = t["read_open_access_pdf"].run(doi_or_url="10.1/X ")
    assert "already tried" in out.lower()
    assert calls == ["10.1/x"]


def test_repeat_failed_page_read_does_not_spend_budget(tmp_path):
    worker = FakeWorker(scrape={"ok": False, "error": "blocked"})
    ctx, t = _tools(tmp_path, _plan(1, max_pages=2), worker)
    t["read_page"].run(url="https://a.com/1")
    assert "already tried" in t["read_page"].run(url="https://a.com/1").lower()
    assert worker.scraped == ["https://a.com/1"]
    t["read_page"].run(url="https://a.com/2")
    assert worker.scraped == ["https://a.com/1", "https://a.com/2"]
