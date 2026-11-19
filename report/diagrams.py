"""Mermaid diagrams. The model proposes code; we clean it, hold it to size limits, have the worker draw
it to catch syntax errors and over-sized drawings, give the model one chance to fix a rejected
diagram, and drop it if that fails. Accepted code is escaped for HTML."""
import html
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass

from report.writer import LLMFn

_KINDS = ("flowchart", "graph", "sequenceDiagram", "timeline", "mindmap", "gantt", "stateDiagram", "classDiagram")
_PLANNED = ("flowchart", "graph", "timeline", "mindmap")  # the types we ask for and know how to size

# Limits that keep a diagram readable on an A4 page.
MAX_BOXES = 12
MAX_GROUP_BOXES = 4
MAX_LABEL_CHARS = 40
MAX_ARROWS = 4  # into or out of one box: more fan out into a column taller than a page
MAX_PERIODS = 5  # each period adds ~200 px; 5 is the most that stays above MIN_SCALE
MAX_EVENTS = 2
MAX_EVENT_CHARS = 60
MAX_MINDMAP_ITEMS = 15
# The drawing is scaled to the text width (about 660 px on A4). Narrower than 60% scale the text gets
# too small to read; taller than about 16 cm once scaled it pushes the caption onto the next page.
PAGE_WIDTH_PX = 660
MIN_SCALE = 0.6
MAX_SHOWN_HEIGHT_PX = 600

RULES = f"""- flowchart LR (left to right; a simple chain of more than 4 steps reads better as flowchart TD): at most {MAX_BOXES} boxes in total, at most {MAX_GROUP_BOXES} boxes per subgraph,
  and at most {MAX_ARROWS} arrows into or out of any one box.
  Put every label in double quotes, e.g. A["Model AI Governance Framework"] --> B["Sandbox pilots"].
  Labels are at most 5 words and spelled out: no cryptic abbreviations or numbers without units.
- timeline: at most {MAX_PERIODS} periods, distinct and from earliest to latest, each with 1 or {MAX_EVENTS} short events (at most 8 words each), e.g.
  timeline
    title Policy milestones
    2024 : Framework published
    2025 : Sandbox opens : First grants
- mindmap: at most {MAX_MINDMAP_ITEMS} items, at most 2 levels below the root; plain text, indented, e.g.
  mindmap
    root((Agentic AI in Singapore))
      Government
        National AI Strategy
      Funding
- No HTML, no styling (classDef, style, :::class), no %%{{init}}%% directives, no emojis."""

PROMPT = """DIAGRAM_REQUEST
Propose up to {n} Mermaid diagrams that clarify the research below: a flowchart LR, a timeline or a mindmap.
Reply with ONLY a JSON list of {{"code": "<mermaid source>", "caption": "<one sentence>"}}.
Use only facts present in the text. Diagrams that break these limits are rejected:
{rules}

FINDINGS:
{findings}

ANALYSIS:
{analysis}
"""

FIX_PROMPT = """DIAGRAM_FIX_REQUEST
This Mermaid diagram was rejected: {problem}
Return ONLY the corrected Mermaid source: no JSON, no code fence, no explanation.
Keep its meaning, and follow these limits:
{rules}

DIAGRAM:
{code}
"""

CheckFn = Callable[[list[str]], list[dict] | None]


@dataclass
class Diagram:
    code: str
    caption: str
    status: str = "new"  # ok | repaired | unchecked (no worker to draw it) | dropped
    problem: str | None = None

    def block(self) -> str:
        return "" if self.status == "dropped" else mermaid_block(self.code, self.caption)

    def to_dict(self) -> dict:
        return asdict(self)


def mermaid_block(code: str, caption: str) -> str:
    code = (code or "").strip()
    if not code.startswith(_KINDS):
        return ""
    return (
        f'<figure class="diagram"><pre class="mermaid">{html.escape(code, quote=False)}</pre>'
        f"<figcaption>{html.escape(caption or '')}</figcaption></figure>"
    )


# -- cleaning -------------------------------------------------------------------

_STYLE_LINE = re.compile(r"^\s*(classDef|class|style|linkStyle)\s")
_SPECIAL = set("()[]{}:;,&%#|<>\"'/?!@=")
_NODE_SQUARE = re.compile(r"(\b[A-Za-z_][\w-]*)\[(?![\[\(/\\\"])([^\]\n]+)\](?!\])")
_NODE_ROUND = re.compile(r"(\b[A-Za-z_][\w-]*)\((?![\(\[\"])([^()\n]+)\)(?!\))")
_NODE_CURLY = re.compile(r"(\b[A-Za-z_][\w-]*)\{(?![\{\"])([^{}\n]+)\}(?!\})")
_EDGE_LABEL = re.compile(r"\|(?!\")([^|\n]+)\|")


def _quoted(label: str) -> str:
    return '"' + label.strip().replace('"', "'") + '"'


def _quote_if_special(open_: str, close: str):
    def repl(m: re.Match) -> str:
        label = m.group(2)
        if not any(c in _SPECIAL for c in label):
            return m.group(0)
        return f"{m.group(1)}{open_}{_quoted(label)}{close}"

    return repl


def _quote_flow_labels(code: str) -> str:
    """Wrap labels holding characters Mermaid treats as syntax, the usual cause of 'Syntax error'."""
    out = []
    for line in code.splitlines():
        if not line.strip().startswith("subgraph"):
            line = _NODE_SQUARE.sub(_quote_if_special("[", "]"), line)
            line = _NODE_CURLY.sub(_quote_if_special("{", "}"), line)
            line = _NODE_ROUND.sub(_quote_if_special("(", ")"), line)
            line = _EDGE_LABEL.sub(
                lambda m: f"|{_quoted(m.group(1))}|" if any(c in _SPECIAL for c in m.group(1)) else m.group(0), line
            )
        out.append(line)
    return "\n".join(out)


def sanitize(code: str) -> str:
    """Strip fences, styling and init directives (the report sets the theme), and quote risky labels."""
    code = re.sub(r"^```(?:mermaid)?\s*|\s*```$", "", (code or "").strip()).strip()
    lines = [
        line.rstrip() for line in code.splitlines()
        if not line.strip().startswith("%%{") and not _STYLE_LINE.match(line) and line.strip() != "mermaid"
    ]
    while lines and not lines[0].strip():
        lines.pop(0)
    code = re.sub(r":::[\w-]+", "", "\n".join(lines))
    if _kind(code) in ("flowchart", "graph"):
        code = _quote_flow_labels(code)
    elif _kind(code) == "mindmap":
        code = _fix_mindmap(code)
    return code


def _fix_mindmap(code: str) -> str:
    """Models write 'sub "Funding"' or 'root "X"' (not mindmap syntax; Mermaid draws the keyword too),
    and parentheses in plain text start a node shape."""
    lines = code.splitlines()
    out = lines[:1]
    for i, line in enumerate(lines[1:]):
        indent, text = re.match(r"(\s*)(.*)", line).groups()
        keyword = re.fullmatch(r'[A-Za-z_]\w*\s+"([^"]+)"', text.strip())
        if keyword:
            text = keyword.group(1)
            if i == 0:
                out.append(f"{indent}root(({text.replace('(', '').replace(')', '')}))")
                continue
        if i > 0 and not re.match(r"[\w-]*[\[\(\{]", text) and ("(" in text or ")" in text):
            text = re.sub(r"\s*\(\s*", ", ", text).replace(")", "").strip()
        out.append(f"{indent}{text}")
    return "\n".join(out)


# -- size limits ----------------------------------------------------------------

def _kind(code: str) -> str:
    first = code.strip().split(None, 1)
    return first[0] if first else ""


_FLOW_SKIP = re.compile(r"^(%%|classDef\b|class\b|style\b|linkStyle\b|click\b|direction\b)")


def _flowchart_problem(code: str) -> str | None:
    seen: set[str] = set()
    group_ids: set[str] = set()
    groups: dict[str, list] = {}  # id -> [title, box count]
    stack: list[str] = []
    names: dict[str, str] = {}
    arrows_in: dict[str, set] = {}
    arrows_out: dict[str, set] = {}
    for line in code.splitlines()[1:]:
        s = line.strip()
        if not s or _FLOW_SKIP.match(s):
            continue
        m = re.match(r"subgraph\s+(.*)$", s)
        if m:
            head = m.group(1).strip()
            gm = re.match(r'([\w-]+)\s*\[\s*"?(.*?)"?\s*\]$', head)
            gid, title = (gm.group(1), gm.group(2)) if gm else ((head.split() or ["group"])[0], head.strip('"'))
            group_ids.add(gid)
            groups[gid] = [title or gid, 0]
            stack.append(gid)
            continue
        if s == "end":
            if stack:
                stack.pop()
            continue
        labels = re.findall(r'"([^"]*)"', s) + re.findall(r'[\[\(\{]+([^\[\]\(\)\{\}"]+)[\]\)\}]+', s)
        for label in labels:
            if len(label.strip()) > MAX_LABEL_CHARS:
                return f'label "{label.strip()[:50]}..." is {len(label.strip())} characters; keep labels under {MAX_LABEL_CHARS}'
        for node, name in re.findall(r'([A-Za-z_][\w-]*)\s*[\[\(\{]+"?([^\]\)\}"]+)"?', s):
            names.setdefault(node, name.strip())
        bare = re.sub(r'"[^"]*"', " ", s)
        bare = re.sub(r"\|[^|]*\|", " ", bare)
        bare = re.sub(r"--\s+[^->]+?\s+-->", " --> ", bare)  # A -- text --> B
        previous = None
        while previous != bare:
            previous = bare
            bare = re.sub(r"[\[\(\{][^\[\]\(\)\{\}]*[\]\)\}]", " ", bare)
        has_arrow = re.search(r"[-=.~]{2,}", bare) is not None
        bare = re.sub(r"<?[-=.~]{2,}[>xo]?", " ", bare)
        tokens = [t for t in re.findall(r"[A-Za-z_][\w-]*", bare) if t != "end"]
        if has_arrow:
            for src, dst in zip(tokens, tokens[1:]):
                arrows_out.setdefault(src, set()).add(dst)
                arrows_in.setdefault(dst, set()).add(src)
        for token in tokens:
            if token in group_ids or token == "end" or token in seen:
                continue
            seen.add(token)
            if stack:
                groups[stack[-1]][1] += 1
    if len(seen) > MAX_BOXES:
        return f"it has {len(seen)} boxes; use at most {MAX_BOXES} (merge or leave out the least important)"
    for title, count in groups.values():
        if count > MAX_GROUP_BOXES:
            return f'group "{title}" has {count} boxes; use at most {MAX_GROUP_BOXES} per group'
    for direction, table in (("into", arrows_in), ("out of", arrows_out)):
        for node, others in table.items():
            if len(others) > MAX_ARROWS:
                return (f'box "{names.get(node, node)}" has {len(others)} arrows {direction} it, which stacks them into '
                        f"a column taller than a page; use at most {MAX_ARROWS} (group the others into one box)")
    return None


def _timeline_problem(code: str) -> str | None:
    periods: list[list[str]] = []
    labels: list[str] = []
    for line in code.splitlines()[1:]:
        s = line.strip()
        if not s or s.startswith(("title", "section", "%%")):
            continue
        parts = [p.strip() for p in s.split(":")]
        if s.startswith(":"):
            if periods:
                periods[-1].extend(p for p in parts[1:] if p)
            continue
        periods.append([p for p in parts[1:] if p])
        labels.append(parts[0])
    for label in labels:
        if labels.count(label) > 1:
            return f'period "{label}" appears more than once; put all its events on one line'
    years = [int(m.group(0)) for m in (re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", label) for label in labels) if m]
    if any(later < earlier for earlier, later in zip(years, years[1:])):
        return f"periods are out of order ({', '.join(labels)}); list them from earliest to latest"
    if len(periods) > MAX_PERIODS:
        return f"it has {len(periods)} periods; use at most {MAX_PERIODS} (group years or drop minor ones)"
    for events in periods:
        if len(events) > MAX_EVENTS:
            return f"a period has {len(events)} events; use at most {MAX_EVENTS} per period"
        for event in events:
            if len(event) > MAX_EVENT_CHARS:
                return f'event "{event[:50]}..." is too long; keep events under {MAX_EVENT_CHARS} characters'
    return None


def _mindmap_problem(code: str) -> str | None:
    items = [line for line in code.splitlines()[1:] if line.strip()]
    count = max(len(items) - 1, 0)  # the first line is the root
    if count > MAX_MINDMAP_ITEMS:
        return f"it has {count} items; use at most {MAX_MINDMAP_ITEMS}"
    return None


def size_problem(code: str) -> str | None:
    """Why the diagram would be unreadable on a page, or None."""
    kind = _kind(code)
    if kind not in _PLANNED:
        return f"diagram type {kind or '(empty)'!r} is not allowed; use flowchart LR, timeline or mindmap"
    if kind in ("flowchart", "graph"):
        return _flowchart_problem(code)
    if kind == "timeline":
        return _timeline_problem(code)
    return _mindmap_problem(code)


def _fit_problem(result: dict, kind: str = "") -> str | None:
    """Judge the drawn size: the worker reports the drawing's width and height in px."""
    width, height = result.get("width"), result.get("height")
    if not width or not height:
        return None
    scale = min(1.0, PAGE_WIDTH_PX / width)
    if scale < MIN_SCALE:
        hint = ("lay a simple chain out top to bottom with flowchart TD, or use fewer boxes in a row"
                if kind in ("flowchart", "graph") else "use fewer items side by side")
        return f"the drawing is too wide for a page ({width:.0f} px; its text would shrink to {scale:.0%}): {hint}"
    if height * scale > MAX_SHOWN_HEIGHT_PX:
        return (f"the drawing is too tall for a page ({height * scale:.0f} px once scaled): "
                "use flowchart LR, fewer boxes per group, or fewer items")
    return None


# -- planning -------------------------------------------------------------------

def _problems(codes: list[str], check: CheckFn | None) -> tuple[list[str | None], bool]:
    """Size problems first; then the worker draws what passed. Returns (problems, whether it was drawn)."""
    problems = [size_problem(c) for c in codes]
    pending = [i for i, p in enumerate(problems) if p is None]
    results = check([codes[i] for i in pending]) if check and pending else None
    if results is None:
        return problems, False
    for i, result in zip(pending, results):
        error = result.get("error")
        problems[i] = f"Mermaid could not draw it: {error}" if error else _fit_problem(result, _kind(codes[i]))
    return problems, True


def _json_items(raw: str) -> list:
    try:
        items = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip()))
    except (json.JSONDecodeError, TypeError):
        return []
    return items if isinstance(items, list) else []


def _fixed_code(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("{"):
        try:
            text = str(json.loads(text).get("code", ""))
        except (json.JSONDecodeError, AttributeError):
            pass
    return sanitize(text)


def plan_diagrams(llm: LLMFn, findings: str, analysis: str, n: int, check: CheckFn | None = None) -> list[Diagram]:
    """Every proposal comes back with a status; dropped ones carry the reason. `check` draws diagrams
    in the worker and returns None when it cannot (then diagrams that meet the limits stay "unchecked")."""
    if n <= 0:
        return []
    raw = llm(PROMPT.format(n=n, rules=RULES, findings=findings[:5000], analysis=analysis[:3000]))
    diagrams = [
        Diagram(code=sanitize(str(item.get("code", ""))), caption=str(item.get("caption", "")).strip())
        for item in _json_items(raw) if isinstance(item, dict)
    ][:n]
    if not diagrams:
        return []
    problems, drawn = _problems([d.code for d in diagrams], check)
    for diagram, problem in zip(diagrams, problems):
        if problem is None:
            diagram.status = "ok" if drawn else "unchecked"
            continue
        fixed = _fixed_code(llm(FIX_PROMPT.format(problem=problem, rules=RULES, code=diagram.code)))
        (again,), _ = _problems([fixed], check)
        if again is None:
            diagram.code, diagram.status = fixed, "repaired"
        else:
            diagram.status, diagram.problem = "dropped", again
    return diagrams
