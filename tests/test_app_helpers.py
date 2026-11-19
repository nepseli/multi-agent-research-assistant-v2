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
