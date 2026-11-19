import base64

import httpx


class WorkerUnavailable(RuntimeError):
    """The worker container could not be reached or failed to render."""


class WorkerClient:
    """HTTP client for the Docker worker (scrape, parse-pdf, render-pdf)."""

    def __init__(self, base_url: str = "http://localhost:8000", timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post_json(self, path: str, payload: dict) -> dict:
        try:
            resp = httpx.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
        except httpx.HTTPError as exc:
            return {"ok": False, "error": f"worker unreachable: {exc}"}
        try:
            data = resp.json()
        except ValueError:
            return {"ok": False, "error": f"worker returned HTTP {resp.status_code} with no JSON"}
        if resp.status_code >= 400 and "ok" not in data:
            data = {"ok": False, "error": str(data.get("detail", data))}
        return data

    def health(self) -> dict:
        try:
            return httpx.get(f"{self.base_url}/health", timeout=5).json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def scrape(self, url: str, timeout_s: int = 60) -> dict:
        return self._post_json("/scrape", {"url": url, "timeout_s": timeout_s})

    def parse_pdf(self, url: str) -> dict:
        return self._post_json("/parse-pdf", {"url": url})

    def render_pdf(self, html: str, assets: dict[str, bytes] | None = None) -> bytes:
        encoded = {name: base64.b64encode(data).decode() for name, data in (assets or {}).items()}
        try:
            resp = httpx.post(
                f"{self.base_url}/render-pdf",
                json={"html": html, "assets": encoded},
                timeout=max(self.timeout, 180),
            )
        except httpx.HTTPError as exc:
            raise WorkerUnavailable(f"worker unreachable: {exc}") from exc
        if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
            raise WorkerUnavailable(f"worker render failed (HTTP {resp.status_code}): {resp.text[:200]}")
        return resp.content
