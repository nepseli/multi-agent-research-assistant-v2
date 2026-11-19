# Multi-Agent Research Assistant v2 — Design

Date: 2026-11-19
Status: Draft for approval
Repo: github.com/nepseli/multi-agent-research-assistant (CrewAI, Streamlit, uv, Python 3.12, Windows dev machine)

Legend: **[Decided]** = you said it or picked it. **[My call]** = I chose it; change anything you disagree with.

## 1. Intent

The v1 assistant runs three agents in sequence: researcher, analyst, writer. The researcher only sees Serper search snippets and never opens a page. The output is three Markdown files in the project root.

v2 should:

1. Decide up front how hard a topic is, and search accordingly. A recipe gets one quick search. A semiconductor-materials question gets journals, preprints, open-access papers and patents.
2. Read sources properly: scrape pages, parse PDFs, query scholarly databases.
3. Optionally produce a professional PDF with tables, charts and diagrams, through a separate, richer flow chosen by a checkbox in Streamlit.

The report must stand up to scrutiny. Every citation is a real source the system actually retrieved, and every chart number comes from data, not from an LLM's imagination.

## 2. Goals, non-goals, anti-goals

**Goals**
- Pre-research router that classifies the query and picks tools and a depth tier. **[Decided]**
- Deeper search: scraping, PDF parsing, academic APIs. **[Decided]**
- Free and open-source tools by default; paid services are optional fallbacks only. **[Decided]**
- PDF report option with tables, charts and diagrams, via a separate flow. **[Decided]**
- Stay on CrewAI, using CrewAI Flows. **[Decided]**
- Keep the existing Markdown path working and fast.
- Per-role model choice, so a stronger model such as OpenAI GPT-5 can be used only where it matters. **[Decided]**
- Report size selector: Small, Medium (default) or Big, applying to both Markdown and PDF output. **[Decided]**

**Non-goals**
- Multi-user accounts, auth or hosting.
- Vector database or RAG over past runs.
- Integrating third-party academic MCP servers (possible later; see section 14).
- Paid publisher APIs (IEEE Xplore, Scopus). The tool interface should allow adding them, but nothing ships for them.
- Scraping Google Scholar or bypassing paywalls.

**Anti-goals (would make v2 a failure even if it runs)**
- A reference that points to something the system never retrieved.
- A chart or table figure that no source or computation supports.
- A trivial query that burns 50 page fetches.
- A run that silently degrades: if a tool fails or a tier is under-covered, the report says so.

## 3. Constraints

- Developer machine is Windows (PowerShell, uv). Streamlit runs natively. **[Decided: Docker is acceptable for heavy parts.]**
- Models come through OpenRouter. v1 uses `gpt-oss-20b` for every role. **[Decided: keep OpenRouter, and use stronger models like GPT-5 for demanding jobs.]**
- Cost target: free tools by default. Budget caps per run enforce this. **[My call: your answer on budget was not given, so defaults assume $0–20/month.]**

## 4. Approaches considered

| | Approach | Trade-off |
|---|---|---|
| A | Keep one sequential Crew; add tools and a router task | Smallest change. Branching and a second PDF crew get awkward. |
| **B** | **CrewAI Flow: router → tier-specific research crew → report stage (Markdown or PDF)** | **Chosen [Decided].** Moderate rewrite of `crews/` and `app.py`, but branching is native to CrewAI. |
| C | Rewrite in LangGraph | Most control, but leaves CrewAI and was not requested. |

Scraping options (see section 7) were compared on licence, footprint and fit. Crawl4AI is the default. Firecrawl cloud is a capped fallback. Firecrawl self-hosted, ScrapeGraphAI, Scrapy and bare Playwright were rejected as too heavy, too token-hungry, or too low-level. **[Decided: Crawl4AI default, in Docker.]**

## 5. Architecture

```
Streamlit app.py ──► ResearchFlow (CrewAI Flow)
   topic, depth override, PDF checkbox
                │
        1. route()          Router agent → ResearchPlan (structured)
                │
        2. research()       Tier-specific crew; tools write every source to SourceRegistry
                │
        3. analyse()        Analyst crew
                │
        ┌───────┴────────┐
   4a. write_markdown()   4b. write_pdf()     (only if PDF selected)
     Writer agent           Figure planner → deterministic chart/diagram render
                            → Writer (long form) → Jinja2 HTML → worker /render-pdf

Docker "worker" service (FastAPI, one container)
   /scrape       Crawl4AI (Chromium)
   /parse-pdf    Docling
   /render-pdf   Playwright Chromium: HTML → PDF
```

**Why one worker container [My call]:** Crawl4AI already requires Chromium, so the same image can render the report PDF. That avoids WeasyPrint, which as far as I know needs GTK/Pango libraries on Windows. It also lets Mermaid and Plotly render natively in the browser engine.

## 6. Pre-research router

Input: topic text plus optional user override of depth.
Output (Pydantic `ResearchPlan`):

```
domain: general | news | technical_science | patents_standards | how_to | other
tier: 0 | 1 | 2 | 3
rationale: short string (shown in the UI)
subqueries: list[str]   (2–6 focused queries)
use_academic: bool
use_pdf_parsing: bool
budget: {max_searches, max_pages, max_pdfs, firecrawl_credits, timeout_s}
```

Rules:
- The router can only choose from a whitelist of tools and may not raise budgets above the tier's hard caps.
- If the LLM output fails to parse after one retry, fall back to Tier 1 with a visible warning.
- The user can force a tier in the UI. The router's choice is shown in an expander before research starts and is stored in the run folder.

## 7. Tiers and tools

| Tier | Typical topic | Search | Reading | Default caps **[My call]** |
|---|---|---|---|---|
| 0 | Weather, recipe | Serper (or Brave) snippets, 1–2 queries | None | 2 searches |
| 1 | General research | Serper, 3–5 queries | Crawl4AI on top pages | 5 searches, 8 pages |
| 2 | Technical / scientific | Tier 1 + OpenAlex, arXiv, Crossref, Semantic Scholar, Unpaywall | Crawl4AI for pages, Docling for open-access PDFs | 8 searches, 15 pages, 5 PDFs |
| 3 | Literature-review depth | Tier 2 + citation expansion + gap-check loop (max 2 rounds) | Plus Firecrawl cloud fallback for pages Crawl4AI cannot open | 15 searches, 30 pages, 10 PDFs, 100 Firecrawl credits |

Tool decisions:
- **Academic APIs are called directly from Python (httpx), not through third-party MCP servers [My call].** This gives full control over what goes into the source registry and avoids depending on small community MCP servers of uneven quality. All are free; Semantic Scholar and OpenAlex work better with a free key or contact email, which go in `.env`.
- **Serper stays as the default web search** since the key already exists; Brave is an optional alternative behind the same interface.
- **Firecrawl cloud** is enabled only if `FIRECRAWL_API_KEY` is set, only at Tier 3, and only as a fallback after the worker fails on a URL.
- **Respect robots.txt and do not bypass paywalls.** For papers, use open-access copies via Unpaywall; otherwise use abstracts and metadata and say so in the report.
- Third-party MCP servers (e.g. a multi-database academic one) can be added later as an alternate tool provider.

## 8. Source registry (the citation guarantee)

Every search or scrape tool writes to a per-run `SourceRegistry`:

```
Source: id ("S1"…), url, doi?, title, authors?, year?, kind (web|paper|patent|pdf),
        retrieved_at, content_path (cleaned text/markdown on disk), tier_tool (which tool found it)
```

- Agents see source IDs plus content, and cite as `[S12]`.
- After writing, a validator checks every `[Sx]` against the registry. Unknown IDs fail the stage once (the writer is asked to fix), then are stripped and logged.
- The references list is generated from the registry by code, not by the LLM.

## 9. Report flows

**Markdown flow (default):** router → research → analyse → writer produces `final_report.md`. Intermediate files go in the run folder.

**PDF flow (checkbox):** same research and analysis, then:

1. **Figure planner** (LLM) proposes charts and diagrams as structured specs. A chart spec must reference a data table in the run's `data/` folder. Specs without a data reference are rejected.
2. **Data tables come from real sources:** (a) bibliometric counts computed in code from OpenAlex (papers per year, top venues, top institutions) at Tier 2+; (b) tables extracted by Docling from retrieved PDFs; (c) figures the analyst quotes from a source, tagged with source ID.
3. **Deterministic rendering:** Plotly or matplotlib renders charts to SVG. Mermaid renders diagrams (flows, taxonomies, timelines).
4. **Long-form writer** gets a richer prompt: executive summary, background, methods/coverage, findings with tables, figure captions citing `[Sx]`, limitations, references.
5. **Jinja2 HTML template** (cover, headers/footers, page numbers, numbered figures and tables) → worker `/render-pdf` → `final_report.pdf`. The Markdown version is also saved.
6. **Appendix:** coverage notes (tier used, tools that failed, sources skipped for paywalls).

The PDF flow is allowed to use more LLM calls and a stronger model than the Markdown flow.

**[My call] PDF mode also raises research budgets:** page, PDF and search caps are multiplied by 1.5 (rounded up), and a Tier 0 topic is bumped to Tier 1 so there is something to build tables and figures from. The router's chosen tier is still shown; the bump is logged in the coverage notes.

## 9a. Report size **[Decided: Small/Medium/Big, Medium default. Word counts are my call.]**

| Size | Body word count (excluding references) | Typical PDF length | PDF tables / figures | Sections |
|---|---|---|---|---|
| Small | 800–1,200 | 2–3 pages | 1 table, 1–2 figures | Summary, key findings, conclusions, references |
| **Medium (default)** | 2,000–3,000 | 6–10 pages | 2 tables, 3–4 figures | Adds background, methodology/coverage, analysis, limitations |
| Big | 5,000–7,000 | 15–25 pages | 4 tables, 6–8 figures | Adds detailed per-theme sections, comparison tables, timeline, appendix |

How it works:
- Size applies to both Markdown and PDF output. In Markdown mode only the word count and section list apply; the table/figure counts apply to PDF mode only.
- The writer builds an outline first, with a word budget per section, then writes section by section. This is how Medium and Big hit their length, because one long generation tends to come out short or drift.
- A validator counts words. Outside the target range by more than 15%, the writer gets one targeted expand-or-trim pass; after that the result is accepted and the actual count is shown in the coverage notes.
- Size is independent of depth tier, but Big on a Tier 0 topic is bumped to Tier 1 (same rule as PDF mode), because there is not enough material otherwise. Big at Tier 1 shows a warning that coverage may be thin.
- Size also sets the research caps' floor: Small never exceeds the tier's base caps, Medium uses them as listed, Big multiplies page and PDF caps by 1.25 (stacking with the PDF 1.5x, capped at the tier's hard maximum).

## 10. Streamlit changes

- Depth selector: Auto (default), 0, 1, 2, 3.
- Checkbox: "Generate PDF report (slower, more detailed)".
- Report size selector (Small / Medium / Big), Medium preselected, with the word range and rough page count shown beside each option.
- Show the router's plan (domain, tier, queries, budgets) in an expander as soon as it exists.
- Progress shown per stage; the stage list adapts to the flow chosen. Progress comes from a callback passed into the Flow, replacing today's patching of global task callbacks.
- Results tabs as today, plus Sources and Coverage notes; download buttons for `.md` and `.pdf`.
- Sidebar status checks the worker (`/health`) and reports which optional keys are present.

## 11. Configuration

Every role has `*_LLM` and `*_TEMP` variables in `.env`.

### Models per role **[My call on the assignments]**

Each role reads its own `*_LLM` and `*_TEMP` variable, so any role can be moved to a different model without code changes. Suggested assignment:

| Role | Why | Suggested model |
|---|---|---|
| Router | Must return valid structured JSON; one short call per run | Strong (GPT-5 class) |
| Research agents | Many tool calls; mostly reading and summarising | Cheap (keep `gpt-oss-20b`) |
| Analyst | Reasoning over findings | Cheap for Markdown mode, strong for PDF mode |
| Figure planner | Structured specs that must reference real data | Strong |
| Report writer | Long-form quality and instruction-following | Medium/Big and PDF: strong. Small: cheap. |

Implementation: the variables are `ROUTER_AGENT_LLM`, `RESEARCH_AGENT_LLM`, `ANALYST_AGENT_LLM`, `WRITER_AGENT_LLM`, `FIGURE_PLANNER_LLM`, plus optional `*_PDF` overrides (for example `ANALYST_AGENT_LLM_PDF`, `WRITER_AGENT_LLM_PDF`) that are used only in PDF mode and fall back to the base variable when unset. The OpenRouter model ID for GPT-5 (for example `openrouter/openai/gpt-5`) must be checked against OpenRouter's current model list before use; I have not verified the exact ID or its price. The sidebar shows the model each role will use and a rough warning if a strong model is assigned to a role that makes many calls (the research agents).

Other `.env` additions: `WORKER_URL` (default `http://localhost:8000`), optional `FIRECRAWL_API_KEY`, `OPENALEX_EMAIL`, `SEMANTIC_SCHOLAR_API_KEY`, `UNPAYWALL_EMAIL`, `BRAVE_API_KEY`.

## 12. Code layout **[My call]**

```
app.py, main.py
core/        config.py, models.py (ResearchPlan, Source, FigureSpec), registry.py, run_context.py
crews/       agent/task factories (build per run, no import-time env reads)
flows/       research_flow.py
tools/       web_search.py, academic.py, worker_client.py, firecrawl_fallback.py
report/      figure_planner.py, charts.py, diagrams.py, templates/report.html.j2, validators.py
worker/      Dockerfile, app.py (FastAPI), requirements
runs/<run_id>/   plan.json, sources.json, data/, figures/, final_report.md, final_report.pdf, log.jsonl
docker-compose.yml
tests/
```

Existing `crews/*.py` become factories; `research_crew` as a module-level global goes away. Output files move from the project root to `runs/<run_id>/` so runs do not overwrite each other.

## 13. Testing and verification

- Unit tests: plan parsing and fallback, registry validation and citation stripping, chart-spec validator (rejects specs without data), tier budget enforcement, template render with fixture data.
- Tool tests with recorded HTTP fixtures for OpenAlex, arXiv, Crossref, Unpaywall.
- Worker tests: `/scrape` on a local static page, `/parse-pdf` on a small sample PDF, `/render-pdf` producing a valid multi-page PDF with an SVG chart and a Mermaid diagram.
- Manual smoke test, one topic per tier (for example: "weather in Singapore this week", "pros and cons of heat pumps", "GaN-on-silicon wafer defect mechanisms", a broad literature topic), checking that Tier 0 stays tiny and Tier 3 stays inside its caps.
- Acceptance check: open a generated PDF, confirm figures have data provenance and every reference resolves to a retrieved source.

## 14. Risks and open items

- **Model quality** is the biggest risk, as above. Mitigations: structured-output fallback, validators, stronger-model option.
- **Docling is heavy** (model downloads, slow on CPU). Limited to Tier 2+ with a PDF cap. Marker or MinerU are drop-in alternatives for math-heavy papers; check their licences before any commercial use.
- **Some sites block crawlers.** Handled by retries, optional Firecrawl cloud at Tier 3, and honest coverage notes.
- **Crawl4AI licence** is Apache-2.0 with an attribution clause in recent versions; fine for this repo, worth keeping in mind if you productise it.
- **Windows asyncio issue** with Playwright is avoided by keeping Crawl4AI inside Docker.
- **Pricing and repo facts drift.** Firecrawl pricing and tool popularity were checked on 2026-11-19; recheck before relying on them.

## 15. Suggested build order (for the plan)

1. Foundations: config, models, registry, run folders, crew factories, Flow skeleton with router, Tier 0/1 and the Markdown path. Streamlit updated for the new flow.
2. Worker: Docker image, `/scrape`, `/health`, client tool, Tier 1 reading.
3. Academic tools and `/parse-pdf`; Tier 2.
4. Tier 3: citation expansion, gap-check loop, Firecrawl fallback.
5. Report size: outline-then-sections writer, word-count validator and size presets. Build it early, right after step 1, on the Markdown path, then reuse it for PDF.
6. PDF flow: figure planner, data tables, charts, diagrams, template, `/render-pdf`, UI checkbox and downloads.
7. Tests, README rewrite, `.env.example`.

## 16. Left to the builder

Exact prompts, chart styling and the report template's look, the Docling configuration, retry and backoff values, the logging format, and whether the router uses CrewAI's structured-output parameter or a plain JSON parse. All of these must still respect the anti-goals above.
