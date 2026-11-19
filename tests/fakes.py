import json
import re


class ScriptedLLM:
    """Fake LLM keyed on markers in the prompt. `section_words` scales how much it writes."""

    def __init__(self, outline=None, section_factor=1.0, body_suffix="", outline_raw=None):
        self.calls = []
        self.outline = outline
        self.factor = section_factor
        self.suffix = body_suffix
        self.outline_raw = outline_raw

    def __call__(self, prompt: str) -> str:
        kind = re.search(r"^(OUTLINE_REQUEST|SECTION_REQUEST|REPAIR_REQUEST|ADJUST_REQUEST|SMALL_REQUEST)", prompt, re.M).group(1)
        self.calls.append(kind)
        target = int(re.search(r"TARGET_WORDS: (\d+)", prompt).group(1)) if "TARGET_WORDS" in prompt else 0
        if kind == "OUTLINE_REQUEST":
            if self.outline_raw is not None:
                return self.outline_raw
            return json.dumps(self.outline)
        if kind == "REPAIR_REQUEST":
            return re.search(r"TEXT:\n(.*)", prompt, re.S).group(1)  # returns text unchanged, still invalid
        words = max(int(target * self.factor), 1)
        return ("word " * words).strip() + " " + self.suffix


class FakeWorker:
    """Stands in for WorkerClient in flow tests."""

    def __init__(self, healthy=True):
        self.healthy = healthy

    def health(self):
        return {"ok": True, "scrape": True, "parse_pdf": True, "render_pdf": True} if self.healthy else {"ok": False, "error": "down"}

    def scrape(self, url, timeout_s=60):
        return {"ok": self.healthy, "markdown": "body", "title": "t", "error": None if self.healthy else "down"}

    def parse_pdf(self, url):
        return {"ok": self.healthy, "markdown": "pdf", "tables": [], "error": None if self.healthy else "down"}

    def render_pdf(self, html, assets=None):
        if not self.healthy:
            from tools.worker_client import WorkerUnavailable
            raise WorkerUnavailable("down")
        return b"%PDF-1.7 fake"
