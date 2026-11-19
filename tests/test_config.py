import pytest

from core.config import (
    SIZE_PRESETS,
    TIER_CAPS,
    ROLE_TIER,
    ConfigError,
    get_llm_settings,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("STRONG_LLM", "LIGHT_LLM", "STRONG_LLM_PDF", "LIGHT_LLM_PDF"):
        monkeypatch.delenv(name, raising=False)
    for prefix in ("ROUTER_AGENT", "RESEARCH_AGENT", "ANALYST_AGENT", "WRITER_AGENT", "EDITOR", "FIGURE_PLANNER"):
        for suffix in ("_LLM", "_TEMP", "_LLM_PDF", "_TEMP_PDF"):
            monkeypatch.delenv(prefix + suffix, raising=False)


def test_get_llm_settings_reads_role_vars(monkeypatch):
    monkeypatch.setenv("WRITER_AGENT_LLM", "a")
    monkeypatch.setenv("WRITER_AGENT_TEMP", "0.2")
    assert get_llm_settings("writer") == ("a", 0.2)


def test_pdf_override_used_only_in_pdf_mode(monkeypatch):
    monkeypatch.setenv("WRITER_AGENT_LLM", "base")
    monkeypatch.setenv("WRITER_AGENT_TEMP", "0.3")
    monkeypatch.setenv("WRITER_AGENT_LLM_PDF", "strong")
    monkeypatch.setenv("WRITER_AGENT_TEMP_PDF", "0.5")
    assert get_llm_settings("writer", pdf=False) == ("base", 0.3)
    assert get_llm_settings("writer", pdf=True) == ("strong", 0.5)


def test_pdf_override_falls_back_to_base(monkeypatch):
    monkeypatch.setenv("ANALYST_AGENT_LLM", "base")
    monkeypatch.setenv("ANALYST_AGENT_TEMP", "0.3")
    monkeypatch.delenv("ANALYST_AGENT_LLM_PDF", raising=False)
    monkeypatch.delenv("ANALYST_AGENT_TEMP_PDF", raising=False)
    assert get_llm_settings("analyst", pdf=True) == ("base", 0.3)


def test_missing_model_raises_config_error_naming_the_tier(monkeypatch):
    with pytest.raises(ConfigError) as err:
        get_llm_settings("router")
    assert "STRONG_LLM" in str(err.value)
    with pytest.raises(ConfigError) as err:
        get_llm_settings("editor")
    assert "LIGHT_LLM" in str(err.value)


def test_roles_default_to_their_tier_model(monkeypatch):
    monkeypatch.setenv("STRONG_LLM", "big")
    monkeypatch.setenv("LIGHT_LLM", "small")
    assert {r: get_llm_settings(r)[0] for r in ROLE_TIER} == {
        "router": "big", "research": "big", "analyst": "big", "writer": "big",
        "editor": "small", "figure_planner": "small",
    }


def test_temperature_defaults_per_role(monkeypatch):
    monkeypatch.setenv("STRONG_LLM", "big")
    monkeypatch.setenv("LIGHT_LLM", "small")
    assert get_llm_settings("router")[1] == 0.0
    assert get_llm_settings("research")[1] == 0.3
    assert get_llm_settings("figure_planner")[1] == 0.0
    monkeypatch.setenv("RESEARCH_AGENT_TEMP", "0.7")
    assert get_llm_settings("research")[1] == 0.7


def test_role_model_overrides_tier(monkeypatch):
    monkeypatch.setenv("STRONG_LLM", "big")
    monkeypatch.setenv("ANALYST_AGENT_LLM", "special")
    assert get_llm_settings("analyst")[0] == "special"
    assert get_llm_settings("router")[0] == "big"


def test_tier_pdf_model_used_in_pdf_mode_unless_role_pdf_set(monkeypatch):
    monkeypatch.setenv("STRONG_LLM", "big")
    monkeypatch.setenv("STRONG_LLM_PDF", "bigger")
    monkeypatch.setenv("LIGHT_LLM", "small")
    monkeypatch.setenv("WRITER_AGENT_LLM_PDF", "writer-pdf")
    assert get_llm_settings("router", pdf=True)[0] == "bigger"
    assert get_llm_settings("writer", pdf=True)[0] == "writer-pdf"
    assert get_llm_settings("editor", pdf=True)[0] == "small"
    assert get_llm_settings("router", pdf=False)[0] == "big"


def test_bad_temperature_raises(monkeypatch):
    monkeypatch.setenv("STRONG_LLM", "big")
    monkeypatch.setenv("ROUTER_AGENT_TEMP", "warm")
    with pytest.raises(ConfigError):
        get_llm_settings("router")


def test_figure_planner_uses_figure_planner_vars(monkeypatch):
    monkeypatch.setenv("FIGURE_PLANNER_LLM", "fp")
    monkeypatch.setenv("FIGURE_PLANNER_TEMP", "0.1")
    assert get_llm_settings("figure_planner") == ("fp", 0.1)


def test_tier_caps_match_spec():
    t1 = TIER_CAPS[1]
    assert (t1.max_searches, t1.max_pages, t1.max_pdfs, t1.firecrawl_credits) == (5, 8, 0, 0)
    t3 = TIER_CAPS[3]
    assert (t3.max_searches, t3.max_pages, t3.max_pdfs, t3.firecrawl_credits) == (15, 30, 10, 100)
    assert [TIER_CAPS[t].timeout_s for t in range(4)] == [60, 180, 420, 900]


def test_size_presets_match_spec():
    m = SIZE_PRESETS["medium"]
    assert (m.words_min, m.words_max, m.tables) == (2000, 3000, 2)
    assert (m.figures_min, m.figures_max) == (3, 4)
    assert SIZE_PRESETS["small"].words_max == 1200
    assert SIZE_PRESETS["big"].words_min == 5000
