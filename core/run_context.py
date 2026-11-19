import json
import re
import threading
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.registry import SourceRegistry


@dataclass
class RunContext:
    run_id: str
    run_dir: Path
    registry: SourceRegistry
    report_stem: str = "report"
    cancel: threading.Event | None = None
    listener: Callable[[dict], None] | None = None  # sees every log record, e.g. the app's progress line

    def cancelled(self) -> bool:
        return bool(self.cancel and self.cancel.is_set())

    def log(self, event: str, **fields) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **fields}
        with (self.run_dir / "log.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        if self.listener:
            try:
                self.listener(record)
            except Exception:  # a broken progress display must never stop a run
                pass


def _slug(topic: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", topic).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug[:40] or "topic"


def new_run(topic: str, base: Path = Path("runs")) -> RunContext:
    base = Path(base)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_id = f"{stamp}-{_slug(topic)}-{uuid.uuid4().hex[:6]}"
    run_dir = base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return RunContext(run_id=run_id, run_dir=run_dir, registry=SourceRegistry(run_dir), report_stem=f"{_slug(topic)}-report")
