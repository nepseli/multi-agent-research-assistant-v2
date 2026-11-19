import pytest

from core.config import (
    SIZE_PRESETS,
    TIER_CAPS,
    ROLE_TIER,
    ConfigError,
    get_llm_settings,
    llm_options,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("STRONG_LLM", "LIGHT_LLM", "STRONG_LLM_PDF", "LIGHT_LLM_PDF"):
        monkeypatch.delenv(name, raising=False)
    for prefix in ("ROUTER_AGENT", "RESEARCH_AGENT", "ANALYST_AGENT", "WRITER_AGENT", "EDITOR", "FIGURE_PLANNER", "FACT_CHECKER"):
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
        "editor": "small", "figure_planner": "small", "fact_checker": "small",
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


def _env(**kw):
    return {"STRONG_LLM": "openrouter/openai/gpt-oss-120b", "LIGHT_LLM": "openrouter/openai/gpt-oss-20b", **kw}


def test_light_roles_reason_low_and_strong_roles_keep_model_default():
    assert llm_options("editor", env=_env())["reasoning_effort"] == "low"
    assert "reasoning_effort" not in llm_options("writer", env=_env())


def test_reasoning_effort_overridable_per_tier():
    env = _env(STRONG_REASONING="high", LIGHT_REASONING="default")
    assert llm_options("analyst", env=env)["reasoning_effort"] == "high"
    assert "reasoning_effort" not in llm_options("figure_planner", env=env)


def test_openrouter_tier_models_sort_by_speed_under_a_price_cap():
    strong = llm_options("research", env=_env())["extra_body"]["provider"]
    assert strong == {"sort": "throughput", "max_price": {"prompt": 0.15, "completion": 0.6}}
    light = llm_options("editor", env=_env())["extra_body"]["provider"]
    assert light["max_price"] == {"prompt": 0.075, "completion": 0.3}


def test_price_cap_skipped_for_override_models_but_speed_sort_kept():
    # A cap sized for gpt-oss would block every host of a pricier override model.
    env = _env(STRONG_LLM_PDF="openrouter/openai/gpt-5", ANALYST_AGENT_LLM="openrouter/anthropic/claude-x")
    assert llm_options("writer", pdf=True, env=env)["extra_body"]["provider"] == {"sort": "throughput"}
    assert llm_options("analyst", env=env)["extra_body"]["provider"] == {"sort": "throughput"}


def test_routing_settings_configurable_and_skipped_off_openrouter():
    env = _env(OPENROUTER_SORT="default", STRONG_MAX_PRICE="none")
    assert "extra_body" not in llm_options("writer", env=env)
    env = _env(STRONG_MAX_PRICE="0.2,0.8")
    assert llm_options("writer", env=env)["extra_body"]["provider"]["max_price"] == {"prompt": 0.2, "completion": 0.8}
    assert "extra_body" not in llm_options("writer", env=_env(STRONG_LLM="openai/gpt-4o"))


def test_bad_price_cap_raises():
    with pytest.raises(ConfigError, match="STRONG_MAX_PRICE"):
        llm_options("writer", env=_env(STRONG_MAX_PRICE="cheap"))


def test_figure_planner_reasons_at_medium_while_editor_stays_low():
    # Mermaid syntax suffers at low effort; the editor's short rewrites do not.
    assert llm_options("figure_planner", env=_env())["reasoning_effort"] == "medium"
    assert llm_options("editor", env=_env())["reasoning_effort"] == "low"


def test_role_reasoning_beats_tier_setting_which_beats_role_default():
    assert llm_options("figure_planner", env=_env(LIGHT_REASONING="high"))["reasoning_effort"] == "high"
    env = _env(LIGHT_REASONING="high", FIGURE_PLANNER_REASONING="low")
    assert llm_options("figure_planner", env=env)["reasoning_effort"] == "low"


def test_today_iso_is_an_iso_date():
    import re

    from core.config import today_iso

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", today_iso())


def test_fact_checker_is_a_light_role_that_reasons_at_medium(monkeypatch):
    from core.config import ROLE_TIER

    assert ROLE_TIER["fact_checker"] == "light"
    assert llm_options("fact_checker", env=_env())["reasoning_effort"] == "medium"
    monkeypatch.setenv("LIGHT_LLM", "small")
    assert get_llm_settings("fact_checker") == ("small", 0.0)
