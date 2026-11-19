"""worker/engines.py against fake crawl4ai and docling modules, so the heavy libraries are not needed."""
import asyncio
import sys
import types

import pytest

from worker import engines


class _Markdown(str):
    def __new__(cls, raw, fit):
        obj = super().__new__(cls, raw)
        obj.raw_markdown, obj.fit_markdown = raw, fit
        return obj


@pytest.fixture
def fake_crawl4ai(monkeypatch):
    seen = {}

    class Result:
        success, error_message, metadata = True, None, {"title": "Page"}
        markdown = None

    class AsyncWebCrawler:
        def __init__(self, config=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def arun(self, url, config):
            seen["config"] = config
            return seen["result"]

    def record(name):
        def ctor(**kw):
            seen[name] = kw
            return types.SimpleNamespace(kind=name, **kw)
        return ctor

    mod = types.ModuleType("crawl4ai")
    mod.AsyncWebCrawler = AsyncWebCrawler
    mod.BrowserConfig = record("browser")
    mod.CrawlerRunConfig = record("run")
    mod.DefaultMarkdownGenerator = record("markdown_generator")
    mod.PruningContentFilter = record("pruning")
    monkeypatch.setitem(sys.modules, "crawl4ai", mod)

    def set_markdown(raw, fit):
        result = Result()
        result.markdown = _Markdown(raw, fit)
        seen["result"] = result

    seen["set_markdown"] = set_markdown
    return seen


def test_scrape_uses_pruning_filter_and_returns_main_content(fake_crawl4ai):
    main = "Main article text. " * 40
    fake_crawl4ai["set_markdown"]("Jump to content | Main menu\n" + main, main)
    out = asyncio.run(engines.scrape_url("https://a.com", 30))
    assert out["ok"] and out["markdown"] == main
    assert "pruning" in fake_crawl4ai
    assert fake_crawl4ai["run"]["markdown_generator"].kind == "markdown_generator"
    # Page chrome is removed structurally, and inline links are dropped so the text budget goes on prose.
    assert {"nav", "header", "footer"} <= set(fake_crawl4ai["run"]["excluded_tags"])
    assert fake_crawl4ai["markdown_generator"]["options"]["ignore_links"] is True


def test_scrape_falls_back_to_raw_when_filter_keeps_too_little(fake_crawl4ai):
    raw = "Short page with a table. " * 30
    fake_crawl4ai["set_markdown"](raw, "tiny")
    out = asyncio.run(engines.scrape_url("https://a.com", 30))
    assert out["markdown"] == raw


@pytest.fixture
def fake_docling(monkeypatch):
    made = []

    class Doc:
        tables = []

        def export_to_markdown(self):
            return "# Paper"

    class DocumentConverter:
        def __init__(self):
            made.append(self)

        def convert(self, url):
            return types.SimpleNamespace(document=Doc())

    pkg = types.ModuleType("docling")
    sub = types.ModuleType("docling.document_converter")
    sub.DocumentConverter = DocumentConverter
    monkeypatch.setitem(sys.modules, "docling", pkg)
    monkeypatch.setitem(sys.modules, "docling.document_converter", sub)
    monkeypatch.setattr(engines, "_CONVERTER", None)
    return made


def test_docling_converter_is_built_once_and_reused(fake_docling):
    a = asyncio.run(engines.parse_pdf_url("https://a.com/1.pdf"))
    b = asyncio.run(engines.parse_pdf_url("https://a.com/2.pdf"))
    assert a["ok"] and b["ok"] and a["markdown"] == "# Paper"
    assert len(fake_docling) == 1
