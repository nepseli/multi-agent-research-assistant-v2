import pytest
from fastapi.testclient import TestClient

from worker import app as worker_app
from worker.app import app

client = TestClient(app)


async def _scrape_ok(url, timeout_s):
    return {"ok": True, "markdown": "# Hello", "title": "Hello", "error": None}


async def _parse_ok(url):
    return {"ok": True, "markdown": "# Paper", "tables": [[["a", "b"], ["1", "2"]]], "error": None}


async def _render_ok(html, assets):
    return b"%PDF-1.7 fake"


def test_health_reports_capabilities(monkeypatch):
    monkeypatch.setattr(worker_app.engines, "capabilities", lambda: {"scrape": True, "parse_pdf": False, "render_pdf": True})
    body = client.get("/health").json()
    assert body == {"ok": True, "scrape": True, "parse_pdf": False, "render_pdf": True}


def test_scrape_rejects_file_scheme():
    r = client.post("/scrape", json={"url": "file:///etc/passwd"})
    assert r.status_code == 400
    assert r.json()["ok"] is False


@pytest.mark.parametrize("url", ["http://127.0.0.1/x", "http://10.0.0.5/a", "http://localhost:8000/", "http://169.254.169.254/latest"])
def test_scrape_rejects_private_hosts(url):
    r = client.post("/scrape", json={"url": url})
    assert r.status_code == 400
    assert "private" in r.json()["error"].lower() or "not allowed" in r.json()["error"].lower()


def test_scrape_returns_markdown_from_engine(monkeypatch):
    monkeypatch.setattr(worker_app.engines, "scrape_url", _scrape_ok)
    monkeypatch.setattr(worker_app, "validate_url", lambda u: None)
    r = client.post("/scrape", json={"url": "https://example.com/a", "timeout_s": 10})
    assert r.status_code == 200
    assert r.json()["markdown"] == "# Hello"


def test_parse_pdf_returns_tables(monkeypatch):
    monkeypatch.setattr(worker_app.engines, "parse_pdf_url", _parse_ok)
    monkeypatch.setattr(worker_app, "validate_url", lambda u: None)
    r = client.post("/parse-pdf", json={"url": "https://example.com/p.pdf"})
    assert r.json()["tables"] == [[["a", "b"], ["1", "2"]]]


def test_render_pdf_returns_pdf_bytes_header(monkeypatch):
    monkeypatch.setattr(worker_app.engines, "render_html_to_pdf", _render_ok)
    r = client.post("/render-pdf", json={"html": "<html><body>hi</body></html>", "assets": {}})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_render_pdf_rejects_oversized_body():
    r = client.post("/render-pdf", json={"html": "x" * (5 * 1024 * 1024 + 1), "assets": {}})
    assert r.status_code == 413


def test_engine_failure_is_reported_not_raised(monkeypatch):
    async def boom(url, timeout_s):
        raise RuntimeError("browser crashed")

    monkeypatch.setattr(worker_app.engines, "scrape_url", boom)
    monkeypatch.setattr(worker_app, "validate_url", lambda u: None)
    r = client.post("/scrape", json={"url": "https://example.com"})
    assert r.status_code == 200
    assert r.json()["ok"] is False and "browser crashed" in r.json()["error"]
