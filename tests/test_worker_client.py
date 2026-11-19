import httpx
import pytest
import respx

from tools.worker_client import WorkerClient, WorkerUnavailable

BASE = "http://worker.test:8000"


@respx.mock
def test_scrape_returns_json():
    respx.post(f"{BASE}/scrape").mock(return_value=httpx.Response(200, json={"ok": True, "markdown": "x", "title": "t", "error": None}))
    assert WorkerClient(BASE).scrape("https://a.com")["markdown"] == "x"


@respx.mock
def test_scrape_400_returns_error_dict():
    respx.post(f"{BASE}/scrape").mock(return_value=httpx.Response(400, json={"ok": False, "error": "private host"}))
    out = WorkerClient(BASE).scrape("http://10.0.0.1")
    assert out["ok"] is False and out["error"] == "private host"


@respx.mock
def test_client_returns_error_dict_when_worker_down():
    respx.post(f"{BASE}/scrape").mock(side_effect=httpx.ConnectError("refused"))
    respx.post(f"{BASE}/parse-pdf").mock(side_effect=httpx.ConnectError("refused"))
    respx.get(f"{BASE}/health").mock(side_effect=httpx.ConnectError("refused"))
    c = WorkerClient(BASE)
    assert c.scrape("https://a.com")["ok"] is False
    assert c.parse_pdf("https://a.com/p.pdf")["ok"] is False
    assert c.health()["ok"] is False


@respx.mock
def test_client_render_pdf_raises_worker_unavailable():
    respx.post(f"{BASE}/render-pdf").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(WorkerUnavailable):
        WorkerClient(BASE).render_pdf("<html></html>")


@respx.mock
def test_render_pdf_sends_assets_base64_and_returns_bytes():
    route = respx.post(f"{BASE}/render-pdf").mock(return_value=httpx.Response(200, content=b"%PDF-1.7 x", headers={"content-type": "application/pdf"}))
    out = WorkerClient(BASE).render_pdf("<html></html>", {"fig1.svg": b"<svg/>"})
    assert out.startswith(b"%PDF")
    sent = route.calls.last.request.read()
    assert b"ZmlnMS5zdmc" not in sent  # asset names are keys, not encoded
    assert b"PHN2Zy8+" in sent  # base64 of <svg/>


def test_parse_pdf_allows_long_documents(monkeypatch):
    seen = {}

    def fake_post(url, json, timeout):
        seen["timeout"] = timeout
        return httpx.Response(200, json={"ok": True, "markdown": "", "tables": []})

    monkeypatch.setattr(httpx, "post", fake_post)
    WorkerClient(BASE).parse_pdf("https://a.com/p.pdf")
    assert seen["timeout"] >= 300


@respx.mock
def test_check_mermaid_returns_error_or_none_per_code():
    respx.post(f"{BASE}/check-mermaid").mock(return_value=httpx.Response(200, json={
        "ok": True, "results": [{"ok": True, "error": None, "width": 600, "height": 300},
                                {"ok": False, "error": "Parse error", "width": None, "height": None}]}))
    assert WorkerClient(BASE).check_mermaid(["a", "b"]) == [
        {"error": None, "width": 600, "height": 300}, {"error": "Parse error", "width": None, "height": None}]


@respx.mock
def test_check_mermaid_is_none_when_worker_cannot_check():
    respx.post(f"{BASE}/check-mermaid").mock(side_effect=httpx.ConnectError("refused"))
    assert WorkerClient(BASE).check_mermaid(["a"]) is None
    respx.post(f"{BASE}/check-mermaid").mock(return_value=httpx.Response(404, json={"detail": "Not Found"}))
    assert WorkerClient(BASE).check_mermaid(["a"]) is None
