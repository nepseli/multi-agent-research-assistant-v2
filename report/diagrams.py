"""Mermaid diagrams: the LLM proposes code, we only accept known diagram types and escape it for HTML."""
import html
import json
import re

from report.writer import LLMFn

_KINDS = ("flowchart", "graph", "sequenceDiagram", "timeline", "mindmap", "gantt", "stateDiagram", "classDiagram")

PROMPT = """DIAGRAM_REQUEST
Propose up to {n} Mermaid diagrams (flowchart, timeline or mindmap) that clarify the research below.
Reply with ONLY a JSON list of {{"code": "<mermaid source>", "caption": "<one sentence>"}}.
Use only concepts present in the text. Keep labels short and plain (no HTML).

FINDINGS:
{findings}

ANALYSIS:
{analysis}
"""


def mermaid_block(code: str, caption: str) -> str:
    code = (code or "").strip()
    if not code.startswith(_KINDS):
        return ""
    return (
        f'<figure class="diagram"><pre class="mermaid">{html.escape(code, quote=False)}</pre>'
        f"<figcaption>{html.escape(caption or '')}</figcaption></figure>"
    )


def plan_diagrams(llm: LLMFn, findings: str, analysis: str, n: int) -> list[str]:
    if n <= 0:
        return []
    raw = llm(PROMPT.format(n=n, findings=findings[:5000], analysis=analysis[:3000]))
    try:
        items = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip()))
    except (json.JSONDecodeError, TypeError):
        return []
    blocks = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            block = mermaid_block(str(item.get("code", "")), str(item.get("caption", "")))
            if block:
                blocks.append(block)
    return blocks[:n]
