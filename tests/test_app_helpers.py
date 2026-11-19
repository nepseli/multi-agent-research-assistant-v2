from app_helpers import missing_settings, role_model_table, size_label, stages_for

FULL = {
    "SERPER_API_KEY": "k", "OPENROUTER_API_KEY": "k",
    "STRONG_LLM": "openrouter/openai/gpt-oss-120b",
    "LIGHT_LLM": "openrouter/openai/gpt-oss-20b",
}


def test_missing_settings_empty_when_complete():
    assert missing_settings(FULL) == []


def test_missing_settings_names_the_tier_variable():
    env = {k: v for k, v in FULL.items() if k != "LIGHT_LLM"}
    assert missing_settings(env) == ["LIGHT_LLM"]
    env = {k: v for k, v in FULL.items() if k != "STRONG_LLM"}
    assert missing_settings(env) == ["STRONG_LLM"]


def test_role_models_can_replace_a_tier():
    env = {k: v for k, v in FULL.items() if k != "LIGHT_LLM"}
    env.update({"EDITOR_LLM": "openrouter/x", "FIGURE_PLANNER_LLM": "openrouter/y", "FACT_CHECKER_LLM": "openrouter/z"})
    assert missing_settings(env) == []


def test_missing_settings_requires_provider_key_for_openrouter_model():
    env = {k: v for k, v in FULL.items() if k != "OPENROUTER_API_KEY"}
    assert missing_settings(env) == ["OPENROUTER_API_KEY"]
    env["WRITER_AGENT_LLM_PDF"] = "openai/gpt-5"
    assert "OPENAI_API_KEY" in missing_settings(env)


def test_missing_settings_flags_serper():
    env = {k: v for k, v in FULL.items() if k != "SERPER_API_KEY"}
    assert missing_settings(env) == ["SERPER_API_KEY"]


def test_size_label_medium_default_text():
    assert size_label("medium") == "Medium — 2,000–3,000 words, ~6–10 PDF pages"


def test_stages_for_pdf_includes_figures_and_render():
    assert stages_for(False) == ["route", "research", "analyse", "write"]
    assert stages_for(True) == ["route", "research", "analyse", "figures", "write", "render"]


def test_role_model_table_shows_tiers_and_pdf_override():
    env = {**FULL, "WRITER_AGENT_LLM_PDF": "openrouter/openai/gpt-5", "WRITER_AGENT_TEMP_PDF": "0.2"}
    base = {r["role"]: r for r in role_model_table(env, pdf=False)}
    pdf = {r["role"]: r for r in role_model_table(env, pdf=True)}
    assert base["router"]["model"] == "openrouter/openai/gpt-oss-120b" and base["router"]["tier"] == "strong"
    assert base["editor"]["model"] == "openrouter/openai/gpt-oss-20b" and base["editor"]["tier"] == "light"
    assert base["writer"]["temperature"] == "0.3"
    assert pdf["writer"]["model"] == "openrouter/openai/gpt-5" and pdf["writer"]["temperature"] == "0.2"
    assert pdf["router"]["model"] == "openrouter/openai/gpt-oss-120b"


def test_role_model_table_marks_unset():
    rows = {r["role"]: r for r in role_model_table({}, pdf=False)}
    assert rows["router"]["model"] == "(not set)"


def test_progress_tracker_turns_log_events_into_plain_lines():
    from app_helpers import ProgressTracker

    p = ProgressTracker()
    assert "Tier 1" in p.update({"event": "plan", "tier": 1, "max_searches": 5, "max_pages": 8, "max_pdfs": 0})
    assert p.update({"event": "web_search", "query": "agentic AI Singapore", "results": 8}) == \
        'Searching the web (1 of 5): "agentic AI Singapore"'
    assert p.update({"event": "academic_search", "query": "agents", "results": 3}) == 'Searching papers (2 of 5): "agents"'
    assert p.update({"event": "read_page", "url": "https://www.imda.gov.sg/x/y", "source": "S3"}) == \
        "Read page 1 of 8: imda.gov.sg"
    assert "could not read" in p.update({"event": "read_failed", "url": "https://bad.example.com/a"}).lower()
    assert p.update({"event": "read_pdf", "url": "https://arxiv.org/pdf/1", "source": "S9"}) == "Read paper 1: arxiv.org"
    assert "used up" in p.update({"event": "budget_exhausted", "what": "searches"})
    assert p.update({"event": "stage", "stage": "research", "status": "done"}) is None  # stages have their own label
    assert p.line == "Search budget used up (searches); working with what was found."


# -- past runs -----------------------------------------------------------------

def _fake_run(base, stamp, topic, words=40, pdf=True, usage=True):
    import json

    from core.config import TIER_CAPS
    from core.models import ResearchPlan

    run = base / f"{stamp}-{topic.lower().replace(' ', '-')}-abc123"
    run.mkdir(parents=True)
    plan = ResearchPlan(topic=topic, tier=1, budget=TIER_CAPS[1])
    (run / "plan.json").write_text(plan.model_dump_json(), encoding="utf-8")
    body = " ".join(["word"] * words)
    (run / "t-report.md").write_text(
        f"# {topic}\n\n{body} [S1].\n\n## References\n\n[S1] A.\n\n## Coverage notes\n\n- Note one\n- Note two\n",
        encoding="utf-8")
    if pdf:
        (run / "t-report.pdf").write_bytes(b"%PDF-1.7")
    if usage:
        (run / "usage.json").write_text(json.dumps({"summary": "1 min 5 s · 3 model calls"}), encoding="utf-8")
    return run


def test_list_runs_newest_first_with_what_the_picker_shows(tmp_path):
    from app_helpers import list_runs

    _fake_run(tmp_path, "20261119-101500", "Old topic", pdf=False, usage=False)
    _fake_run(tmp_path, "20261119-133041", "New topic")
    (tmp_path / "20261119-140000-unfinished-abc").mkdir()  # no report yet: not listed
    runs = list_runs(tmp_path)
    assert [r["topic"] for r in runs] == ["New topic", "Old topic"]
    assert runs[0]["when"] == "19 Nov 2026, 13:30 UTC"
    assert runs[0]["pdf"] is True and runs[1]["pdf"] is False
    # Time first: in the narrow sidebar the same topic run twice would otherwise look identical.
    assert runs[0]["label"] == "19 Nov, 13:30 · New topic · PDF"
    assert runs[1]["label"] == "19 Nov, 10:15 · Old topic"
    assert list_runs(tmp_path / "missing") == []


def test_load_run_rebuilds_the_result_the_app_displays(tmp_path):
    from app_helpers import load_run

    run = _fake_run(tmp_path, "20261119-133041", "New topic", words=40)
    result = load_run(run)
    from report.validators import count_words

    assert result.plan.topic == "New topic"
    assert result.words == count_words((run / "t-report.md").read_text(encoding="utf-8"))
    assert result.pdf_path.name == "t-report.pdf"
    assert result.notes == ["Note one", "Note two"]
    assert result.usage["summary"].startswith("1 min 5 s")
