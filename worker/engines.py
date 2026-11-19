"""Thin wrappers over the heavy engines. Imports are lazy so the app and tests run without them."""
import asyncio
import base64
import importlib.util
import os
import tempfile
from pathlib import Path

MERMAID_JS = Path(os.getenv("MERMAID_JS", "/opt/mermaid/mermaid.min.js"))


def capabilities() -> dict:
    return {
        "scrape": importlib.util.find_spec("crawl4ai") is not None,
        "parse_pdf": importlib.util.find_spec("docling") is not None,
        "render_pdf": importlib.util.find_spec("playwright") is not None,
    }


async def scrape_url(url: str, timeout_s: int) -> dict:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

    config = CrawlerRunConfig(page_timeout=timeout_s * 1000, check_robots_txt=True)
    async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
        result = await crawler.arun(url=url, config=config)
    if not result.success:
        return {"ok": False, "markdown": "", "title": "", "error": result.error_message or "crawl failed"}
    title = (result.metadata or {}).get("title") or ""
    return {"ok": True, "markdown": str(result.markdown or ""), "title": title, "error": None}


def _parse_pdf_sync(url: str) -> dict:
    from docling.document_converter import DocumentConverter

    document = DocumentConverter().convert(url).document
    tables: list[list[list[str]]] = []
    for table in document.tables:
        try:
            frame = table.export_to_dataframe(doc=document)
        except TypeError:
            frame = table.export_to_dataframe()
        rows = [list(map(str, frame.columns))] + [[str(c) for c in row] for row in frame.values.tolist()]
        tables.append(rows)
    return {"ok": True, "markdown": document.export_to_markdown(), "tables": tables, "error": None}


async def parse_pdf_url(url: str) -> dict:
    return await asyncio.to_thread(_parse_pdf_sync, url)


_MERMAID_BOOT = (
    "<script src=\"mermaid.min.js\"></script><script>"
    "mermaid.initialize({startOnLoad:false});"
    "mermaid.run().then(()=>{window.__mermaid_done=true}).catch(()=>{window.__mermaid_done=true});"
    "</script>"
)
_FOOTER = (
    "<div style=\"font-size:9px;width:100%;text-align:center;color:#666\">"
    "<span class=\"pageNumber\"></span> / <span class=\"totalPages\"></span></div>"
)


async def render_html_to_pdf(html: str, assets: dict[str, str]) -> bytes:
    from playwright.async_api import async_playwright

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for name, b64 in assets.items():
            target = (folder / Path(name).name)
            target.write_bytes(base64.b64decode(b64))
        uses_mermaid = 'class="mermaid"' in html
        if uses_mermaid and MERMAID_JS.exists():
            (folder / "mermaid.min.js").write_bytes(MERMAID_JS.read_bytes())
            html = html.replace("</body>", _MERMAID_BOOT + "</body>")
        else:
            html = html.replace("</body>", "<script>window.__mermaid_done=true</script></body>")
        page_file = folder / "report.html"
        page_file.write_text(html, encoding="utf-8")
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page()

                async def _local_only(route):
                    # Reports must never fetch remote or internal URLs while rendering.
                    if route.request.url.startswith(("file:", "data:", "about:")):
                        await route.continue_()
                    else:
                        await route.abort()

                await page.route("**/*", _local_only)
                await page.goto(page_file.as_uri())
                await page.wait_for_function("window.__mermaid_done === true", timeout=30000)
                return await page.pdf(
                    format="A4",
                    print_background=True,
                    display_header_footer=True,
                    header_template="<span></span>",
                    footer_template=_FOOTER,
                    margin={"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"},
                )
            finally:
                await browser.close()
