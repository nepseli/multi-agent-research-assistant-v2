import ipaddress
import socket
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from worker import engines

MAX_BODY = 5 * 1024 * 1024

app = FastAPI(title="research-assistant worker")


class UrlRejected(ValueError):
    pass


def validate_url(url: str) -> None:
    """Allow only http(s) URLs that do not resolve to private, loopback or link-local addresses."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise UrlRejected("only http and https URLs are allowed")
    try:
        infos = socket.getaddrinfo(parts.hostname, None)
    except socket.gaierror as exc:
        raise UrlRejected(f"cannot resolve host: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise UrlRejected("private or internal addresses are not allowed")


class ScrapeRequest(BaseModel):
    url: str
    timeout_s: int = 60


class ParseRequest(BaseModel):
    url: str


class RenderRequest(BaseModel):
    html: str
    assets: dict[str, str] = {}


def _reject(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "error": message})


@app.get("/health")
async def health() -> dict:
    return {"ok": True, **engines.capabilities()}


@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    try:
        validate_url(req.url)
    except UrlRejected as exc:
        return _reject(str(exc))
    try:
        return await engines.scrape_url(req.url, min(max(req.timeout_s, 5), 120))
    except Exception as exc:  # engine crashes must not take the worker down
        return {"ok": False, "markdown": "", "title": "", "error": str(exc)}


@app.post("/parse-pdf")
async def parse_pdf(req: ParseRequest):
    try:
        validate_url(req.url)
    except UrlRejected as exc:
        return _reject(str(exc))
    try:
        return await engines.parse_pdf_url(req.url)
    except Exception as exc:
        return {"ok": False, "markdown": "", "tables": [], "error": str(exc)}


@app.post("/render-pdf")
async def render_pdf(req: RenderRequest):
    if len(req.html.encode("utf-8")) > MAX_BODY:
        return _reject("html body exceeds 5 MB", status=413)
    try:
        pdf = await engines.render_html_to_pdf(req.html, req.assets)
    except Exception as exc:
        return _reject(f"render failed: {exc}", status=500)
    return Response(content=pdf, media_type="application/pdf")
