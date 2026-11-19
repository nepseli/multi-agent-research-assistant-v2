import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from core.models import Source

_CITE = re.compile(r"\[(S\d+)\]")
# "[S1, S4]" or "[S1; S4]": models often group ids; split them so each id is validated.
_GROUP = re.compile(r"\[\s*(S\d+(?:\s*[,;]\s*S\d+)+)\s*\]")


# gpt-oss tends to cite as 【S8】 or 【S8†L10-L12】 (its browsing-tool format), sometimes 【S1, S4】.
_FULLWIDTH = re.compile(r"【([^】]*)】")


def normalize_citations(text: str) -> str:
    """Rewrite full-width citations as [S#]; brackets without an S# id are left alone."""

    def repl(m: re.Match) -> str:
        ids = re.findall(r"S\d+", m.group(1).split("†", 1)[0])
        return ", ".join(f"[{i}]" for i in ids) if ids else m.group(0)

    return _FULLWIDTH.sub(repl, text)


def _split_groups(text: str) -> str:
    text = normalize_citations(text)
    return _GROUP.sub(lambda m: ", ".join(f"[{i}]" for i in re.split(r"\s*[,;]\s*", m.group(1))), text)


def _id_key(sid: str) -> int:
    return int(sid[1:])


@dataclass
class CitationReport:
    unknown: list[str]
    cleaned: str


def _norm_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    return d or None


class SourceRegistry:
    """Per-run record of every source a tool retrieved. Citations resolve against it."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self._sources: list[Source] = []
        self._by_key: dict[str, str] = {}

    def _next_id(self) -> str:
        return f"S{len(self._sources) + 1}"

    def add(
        self,
        url: str,
        title: str,
        kind: str,
        tool: str,
        *,
        doi: str | None = None,
        year: int | None = None,
        authors: list[str] | None = None,
        content: str | None = None,
    ) -> Source:
        doi_key = _norm_doi(doi)
        url_key = _norm_url(url)
        existing_id = self._by_key.get(f"doi:{doi_key}") if doi_key else None
        existing_id = existing_id or self._by_key.get(f"url:{url_key}")
        if existing_id:
            source = self.get(existing_id)
            if content and not source.content_path:
                source.content_path = self._write_content(source.id, content)
            return source

        sid = self._next_id()
        source = Source(
            id=sid,
            url=url,
            title=(title or "").strip() or doi_key or url,
            kind=kind,
            tool=tool,
            doi=doi_key,
            year=year,
            authors=authors or [],
            retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            content_path=self._write_content(sid, content) if content else None,
        )
        self._sources.append(source)
        self._by_key[f"url:{url_key}"] = sid
        if doi_key:
            self._by_key[f"doi:{doi_key}"] = sid
        return source

    def _write_content(self, sid: str, content: str) -> str:
        folder = self.run_dir / "sources"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{sid}.md"
        path.write_text(content, encoding="utf-8")
        return str(path)

    def get(self, sid: str) -> Source | None:
        return next((s for s in self._sources if s.id == sid), None)

    def all(self) -> list[Source]:
        return list(self._sources)

    def save(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        data = [s.model_dump() for s in self._sources]
        (self.run_dir / "sources.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self) -> None:
        path = self.run_dir / "sources.json"
        if not path.exists():
            return
        self._sources = [Source(**item) for item in json.loads(path.read_text(encoding="utf-8"))]
        self._by_key = {}
        for s in self._sources:
            self._by_key[f"url:{_norm_url(s.url)}"] = s.id
            if s.doi:
                self._by_key[f"doi:{s.doi}"] = s.id

    @staticmethod
    def cited_ids(text: str) -> list[str]:
        """Every [S#] id cited in the text, grouped citations included, sorted by number."""
        return sorted(set(_CITE.findall(_split_groups(text))), key=_id_key)

    def validate_citations(self, text: str) -> CitationReport:
        text = _split_groups(text)
        known = {s.id for s in self._sources}
        unknown: list[str] = []
        for cid in _CITE.findall(text):
            if cid not in known and cid not in unknown:
                unknown.append(cid)
        # An unknown id takes its leading ", " with it, so "[S1], [S99]" becomes "[S1]".
        cleaned = re.sub(
            r"(?:[ \t]*,[ \t]*)?\[(S\d+)\]",
            lambda m: m.group(0) if m.group(1) in known else "",
            text,
        )
        cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
        return CitationReport(unknown=unknown, cleaned=cleaned)

    def references_markdown(self, cited: list[str] | None = None) -> str:
        """Reference list. With `cited`, only those sources are listed, so retrieved-but-unused hits stay out."""
        wanted = set(cited) if cited is not None else None
        lines = ["## References", ""]
        for s in self._sources:
            if wanted is not None and s.id not in wanted:
                continue
            parts = [f"[{s.id}] {s.title}"]
            if s.authors:
                parts.append(", ".join(s.authors))
            if s.year:
                parts.append(str(s.year))
            if s.doi:
                parts.append(f"doi:{s.doi}")
            parts.append(s.url)
            lines.append(". ".join(parts) + "  ")
        if len(lines) == 2:
            lines.append("No sources were cited in this report.")
        return "\n".join(lines) + "\n"
