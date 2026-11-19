from core.usage import UsageMeter, estimate_cost, format_usage

ENV = {"STRONG_LLM": "openrouter/openai/gpt-oss-120b", "LIGHT_LLM": "openrouter/openai/gpt-oss-20b"}


def test_meter_sums_tokens_per_model_and_ignores_the_provider_prefix():
    m = UsageMeter()
    m.record("openai/gpt-oss-120b", {"prompt_tokens": 1000, "completion_tokens": 200})
    m.record("openrouter/openai/gpt-oss-120b", {"prompt_tokens": 500, "completion_tokens": 100})
    m.record("openai/gpt-oss-20b", {"prompt_tokens": 10})
    m.record(None, None)  # events without data are skipped
    totals = m.totals()
    assert totals["openai/gpt-oss-120b"] == {"calls": 2, "prompt_tokens": 1500, "completion_tokens": 300}
    assert totals["openai/gpt-oss-20b"]["calls"] == 1


def test_cost_uses_the_price_cap_as_an_upper_bound():
    totals = {"openai/gpt-oss-120b": {"calls": 2, "prompt_tokens": 1_000_000, "completion_tokens": 100_000}}
    cost = estimate_cost(totals, ENV, fetch_max_price=lambda m: None)
    assert round(cost["max_cost_usd"], 4) == round(0.15 + 0.06, 4)  # 0.15/M in, 0.60/M out


def test_cost_for_an_uncapped_model_uses_its_dearest_host():
    totals = {"openai/gpt-5": {"calls": 1, "prompt_tokens": 1_000_000, "completion_tokens": 0}}
    env = {**ENV, "WRITER_AGENT_LLM": "openrouter/openai/gpt-5"}
    assert estimate_cost(totals, env, fetch_max_price=lambda m: (1.25, 10.0))["max_cost_usd"] == 1.25


def test_unknown_price_leaves_the_cost_out():
    totals = {"some/model": {"calls": 1, "prompt_tokens": 10, "completion_tokens": 10}}
    assert estimate_cost(totals, ENV, fetch_max_price=lambda m: None)["max_cost_usd"] is None


def test_format_usage_reads_like_a_sentence():
    totals = {"a": {"calls": 30, "prompt_tokens": 400_000, "completion_tokens": 12_000},
              "b": {"calls": 22, "prompt_tokens": 9_000, "completion_tokens": 3_000}}
    text = format_usage(141.2, totals, {"max_cost_usd": 0.0461})
    assert text == "2 min 21 s · 52 model calls · 424k tokens · at most US$0.05"
    assert format_usage(42, {}, {"max_cost_usd": None}) == "42 s"


def test_meter_listens_to_crewai_llm_events_while_attached():
    from crewai.events import crewai_event_bus
    from crewai.events.types.llm_events import LLMCallCompletedEvent, LLMCallType

    m = UsageMeter()
    m.attach()
    try:
        crewai_event_bus.emit(None, LLMCallCompletedEvent(
            model="openai/gpt-oss-20b", call_id="x", response="hi", call_type=LLMCallType.LLM_CALL,
            usage={"prompt_tokens": 7, "completion_tokens": 3}))
    finally:
        m.detach()
    crewai_event_bus.emit(None, LLMCallCompletedEvent(
        model="openai/gpt-oss-20b", call_id="y", response="hi", call_type=LLMCallType.LLM_CALL,
        usage={"prompt_tokens": 100, "completion_tokens": 100}))
    crewai_event_bus.flush(timeout=5)
    assert m.totals()["openai/gpt-oss-20b"] == {"calls": 1, "prompt_tokens": 7, "completion_tokens": 3}


def test_plain_separator_for_consoles():
    totals = {"a": {"calls": 2, "prompt_tokens": 100, "completion_tokens": 10}}
    assert format_usage(5, totals, {"max_cost_usd": 0.001}, sep=" | ") == "5 s | 2 model calls | 110 tokens | under US$0.01"
