# Project notes for Claude Code

Multi-agent research assistant (CrewAI Flow). See README.md for the architecture.

## Commands
- Install: `uv sync` (on Windows inside OneDrive set `UV_LINK_MODE=copy`)
- Tests: `uv run pytest -q` (fakes for LLMs and the worker; no keys or Docker needed)
- App: `uv run streamlit run app.py` · CLI: `uv run python main.py --topic "..." --size medium --pdf`
- Worker: `docker compose up -d --build` (Crawl4AI, Docling, Playwright PDF rendering on 127.0.0.1:8000)

## Conventions
- Write the failing test first. Keep the suite green.
- Flow stages live in `flows/research_flow.py`; collaborators are injected through `FlowDeps` so tests need no models.
- Every claim is cited as `[S#]` from `core/registry.py`; never let the writer invent sources.
- Charts only from real CSV data in `runs/<id>/data/`; report text is HTML-escaped before PDF rendering.

## Known unverified areas (never run in the original sandbox)
- (Verified 2026-11-19: the worker image builds and /scrape, /parse-pdf, /render-pdf pass a live smoke test. Docling takes ~1.5 s per page on CPU.)
- Live router/research/analyst crews against a real model.
- Streamlit Stop button and run loop in a real browser.
- (Verified 2026-11-19: `openrouter/openai/gpt-5` exists on OpenRouter; models are set per tier with STRONG_LLM / LIGHT_LLM.)
