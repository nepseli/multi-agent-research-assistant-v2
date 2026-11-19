"""Thin wrappers over the heavy engines. Imports are lazy so the app and tests run without them."""
import asyncio
import base64
import importlib.util
import json
import os
import tempfile
import threading
from pathlib import Path

MERMAID_JS = Path(os.getenv("MERMAID_JS", "/opt/mermaid/mermaid.min.js"))


def capabilities() -> dict:
    return {
        "scrape": importlib.util.find_spec("crawl4ai") is not None,
        "parse_pdf": importlib.util.find_spec("docling") is not None,
        "render_pdf": importlib.util.find_spec("playwright") is not None,
        "check_mermaid": importlib.util.find_spec("playwright") is not None and MERMAID_JS.exists(),
    }


# Below this, the pruning filter has probably thrown away the real content (short pages, table-only pages).
_MIN_FIT_CHARS = 400


def _main_content(markdown) -> str:
    raw = getattr(markdown, "raw_markdown", None) or str(markdown or "")
    fit = getattr(markdown, "fit_markdown", None) or ""
    return fit if len(fit) >= _MIN_FIT_CHARS else raw


async def scrape_url(url: str, timeout_s: int) -> dict:
    from crawl4ai import (
        AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, DefaultMarkdownGenerator, PruningContentFilter,
    )

    # The agent sees only the first few thousand characters of a page, so spend them on the article:
    # drop page chrome by tag, prune low-value blocks, and leave out inline links (the page URL is
    # still the cited source). Measured on Wikipedia: 25k -> 14k chars, starting at the article text.
    generator = DefaultMarkdownGenerator(
        content_filter=PruningContentFilter(threshold=0.48, threshold_type="fixed"),
        options={"ignore_images": True, "ignore_links": True},
    )
    config = CrawlerRunConfig(
        page_timeout=timeout_s * 1000,
        check_robots_txt=True,
        markdown_generator=generator,
        excluded_tags=["nav", "header", "footer", "aside", "form", "noscript"],
        remove_overlay_elements=True,
    )
    async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
        result = await crawler.arun(url=url, config=config)
    if not result.success:
        return {"ok": False, "markdown": "", "title": "", "error": result.error_message or "crawl failed"}
    title = (result.metadata or {}).get("title") or ""
    return {"ok": True, "markdown": _main_content(result.markdown), "title": title, "error": None}


_CONVERTER = None
_CONVERTER_LOCK = threading.Lock()


def _converter():
    """One Docling converter for the worker's lifetime: building it loads the layout and table models (~10 s)."""
    global _CONVERTER
    if _CONVERTER is None:
        from docling.document_converter import DocumentConverter

        _CONVERTER = DocumentConverter()
    return _CONVERTER


def _parse_pdf_sync(url: str) -> dict:
    with _CONVERTER_LOCK:  # one conversion at a time; the converter is not documented as thread-safe
        document = _converter().convert(url).document
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


# Diagrams follow the report's look (navy on pale blue, Georgia) instead of Mermaid's yellow and purple.
MERMAID_CONFIG = {
    "startOnLoad": False,
    "theme": "base",
    "suppressErrorRendering": True,  # a diagram that fails is left empty (then removed), never the error bomb
    "fontFamily": "Georgia, serif",
    "themeVariables": {
        "fontFamily": "Georgia, serif",
        "fontSize": "15px",
        "primaryColor": "#eaf0f6",
        "primaryBorderColor": "#1f4e79",
        "primaryTextColor": "#222222",
        "lineColor": "#1f4e79",
        "secondaryColor": "#f4f6f9",
        "tertiaryColor": "#ffffff",
        "clusterBkg": "#f7f9fc",
        "clusterBorder": "#9fb3c8",
        "edgeLabelBackground": "#ffffff",
        # Timeline periods and mindmap branches cycle through cScale0..11: blues instead of a rainbow.
        # Only the navy first colour gets white text. Timelines draw their connector lines in the
        # cScaleLabel colours, so the rest keep Mermaid's dark default on light tints.
        "cScale0": "#1f4e79",
        "cScaleLabel0": "#ffffff",
        **{f"cScale{i}": c for i, c in enumerate(
            ["#c9daea", "#dbe6f1", "#b7cde3", "#e6eef6", "#a9c3de", "#d2e1ef"] * 2, start=1) if i < 12},
    },
    "flowchart": {"curve": "basis", "useMaxWidth": True, "wrappingWidth": 160, "padding": 12},
    # Tighter than the defaults (the left margin alone is ~250 px): 3 periods draw 650 px wide, not 995.
    "timeline": {"disableMulticolor": True, "useMaxWidth": True, "leftMargin": 10, "width": 120, "padding": 5},
    "mindmap": {"useMaxWidth": True},
}

_MERMAID_BOOT = (
    "<script src=\"mermaid.min.js\"></script><script>"
    f"mermaid.initialize({json.dumps(MERMAID_CONFIG)});"
    "const __finish=()=>{"
    # The planner already checked each diagram; this is the safety net for one that still fails to draw.
    "document.querySelectorAll('figure.diagram').forEach(f=>{if(!f.querySelector('svg'))f.remove();});"
    "const __s=document.getElementById('figures-section');"
    "if(__s&&!__s.querySelector('figure'))__s.remove();"
    "window.__mermaid_done=true;};"
    # With an options object, mermaid.run no longer defaults to ".mermaid": name the elements.
    "mermaid.run({querySelector:'.mermaid',suppressErrors:true}).then(__finish).catch(__finish);"
    "</script>"
)

_CHECK_JS = """async (codes) => {
  mermaid.initialize(%s);
  const out = [];
  for (let i = 0; i < codes.length; i++) {
    try {
      const { svg } = await mermaid.render('check' + i, codes[i]);
      const box = new DOMParser().parseFromString(svg, 'image/svg+xml').documentElement.getAttribute('viewBox') || '';
      const [, , w, h] = box.split(/\\s+/).map(Number);
      out.push({ ok: true, error: null, width: w || null, height: h || null });
    } catch (e) {
      out.push({ ok: false, error: String((e && e.message) || e).slice(0, 500), width: null, height: null });
    }
    document.querySelectorAll('[id^="dcheck"], [id^="check"]').forEach(n => n.remove());
  }
  return out;
}"""


async def check_mermaid(codes: list[str]) -> list[dict]:
    """Draw each diagram in a headless browser: syntax errors come back as messages, and the size of
    the drawing (viewBox width and height) lets the planner reject diagrams too tall for a page."""
    from playwright.async_api import async_playwright

    config = {**MERMAID_CONFIG, "suppressErrorRendering": False}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            await page.route("**/*", lambda route: route.abort())  # nothing is fetched while checking
            await page.set_content("<html><body></body></html>")
            await page.add_script_tag(content=MERMAID_JS.read_text(encoding="utf-8"))
            return await page.evaluate(_CHECK_JS % json.dumps(config), codes)
        finally:
            await browser.close()
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
