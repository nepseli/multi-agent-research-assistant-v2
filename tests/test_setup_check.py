import httpx
import respx

from tests.fakes import FakeWorker
from tools.setup_check import format_checks, run_checks

OR = "https://openrouter.ai/api/v1"
ENV = {
    "OPENROUTER_API_KEY": "sk-or-test",
    "SERPER_API_KEY": "serper-test",
    "STRONG_LLM": "openrouter/openai/gpt-oss-120b",
    "LIGHT_LLM": "openrouter/openai/gpt-oss-20b",
}


def _endpoints(*prices):
    """OpenRouter endpoint list with (prompt, completion) prices in USD per million tokens."""
    return {"data": {"endpoints": [
        {"provider_name": f"Host{i}", "pricing": {"prompt": str(p / 1e6), "completion": str(c / 1e6)}}
        for i, (p, c) in enumerate(prices)]}}


def _mock_all(key=200, serper=200, balance=2500, strong=(0.1, 0.5), light=(0.05, 0.2)):
    respx.get(f"{OR}/key").mock(return_value=httpx.Response(key, json={"data": {"usage": 1.25, "limit_remaining": 8.75}}))
    respx.get(f"{OR}/models/openai/gpt-oss-120b/endpoints").mock(return_value=httpx.Response(200, json=_endpoints(strong)))
    respx.get(f"{OR}/models/openai/gpt-oss-20b/endpoints").mock(return_value=httpx.Response(200, json=_endpoints(light)))
    respx.get("https://google.serper.dev/account").mock(return_value=httpx.Response(serper, json={"balance": balance}))


def _by_name(checks):
    return {c.name: c for c in checks}


@respx.mock
def test_everything_configured_passes():
    _mock_all()
    checks = _by_name(run_checks(ENV, FakeWorker()))
    assert all(c.status == "ok" for c in checks.values()), [(c.name, c.detail) for c in checks.values()]
    assert "8.75" in checks["OpenRouter key"].detail
    assert "2500" in checks["Serper key"].detail
    assert "PDF parsing" in checks["Worker"].detail


@respx.mock
def test_missing_settings_fail_with_the_names_and_a_fix():
    _mock_all()
    env = {k: v for k, v in ENV.items() if k != "SERPER_API_KEY"}
    check = _by_name(run_checks(env, FakeWorker()))["Settings"]
    assert check.status == "fail" and "SERPER_API_KEY" in check.detail and ".env" in check.fix


@respx.mock
def test_rejected_keys_fail():
    _mock_all(key=401, serper=403)
    checks = _by_name(run_checks(ENV, FakeWorker()))
    assert checks["OpenRouter key"].status == "fail" and "rejected" in checks["OpenRouter key"].detail
    assert checks["Serper key"].status == "fail"


@respx.mock
def test_empty_serper_balance_warns():
    _mock_all(balance=0)
    assert _by_name(run_checks(ENV, FakeWorker()))["Serper key"].status == "warn"


@respx.mock
def test_unknown_model_id_fails_with_its_variable():
    _mock_all()
    respx.get(f"{OR}/models/openai/gpt-nope/endpoints").mock(return_value=httpx.Response(404, json={}))
    env = {**ENV, "WRITER_AGENT_LLM": "openrouter/openai/gpt-nope"}
    check = next(c for c in run_checks(env, FakeWorker()) if "gpt-nope" in c.name)
    assert check.status == "fail" and "WRITER_AGENT_LLM" in check.detail


@respx.mock
def test_price_cap_that_leaves_no_host_fails():
    _mock_all(strong=(0.35, 0.75))  # only a host dearer than the 0.15 / 0.60 default cap
    check = next(c for c in run_checks(ENV, FakeWorker()) if "gpt-oss-120b" in c.name)
    assert check.status == "fail" and "STRONG_MAX_PRICE" in check.fix


@respx.mock
def test_worker_down_warns_and_lean_worker_is_ok():
    _mock_all()
    down = _by_name(run_checks(ENV, FakeWorker(healthy=False)))["Worker"]
    assert down.status == "warn" and "docker compose up" in down.fix
    lean = _by_name(run_checks(ENV, FakeWorker(parse_pdf=False)))["Worker"]
    assert lean.status == "ok" and "lean" in lean.detail


@respx.mock
def test_unreachable_network_is_reported_not_raised():
    respx.get(f"{OR}/key").mock(side_effect=httpx.ConnectError("offline"))
    respx.get(url__startswith=f"{OR}/models/").mock(side_effect=httpx.ConnectError("offline"))
    respx.get("https://google.serper.dev/account").mock(side_effect=httpx.ConnectError("offline"))
    checks = _by_name(run_checks(ENV, FakeWorker()))
    assert checks["OpenRouter key"].status == "fail" and "reach" in checks["OpenRouter key"].detail


@respx.mock
def test_live_check_sends_one_tiny_call_per_model():
    _mock_all()
    route = respx.post(f"{OR}/chat/completions").mock(return_value=httpx.Response(200, json={
        "choices": [{"message": {"content": "OK"}}], "provider": "Groq"}))
    checks = run_checks(ENV, FakeWorker(), live=True)
    live = [c for c in checks if c.name.startswith("Live call")]
    assert len(live) == 2 and all(c.status == "ok" for c in live)
    assert route.call_count == 2
    sent = route.calls[0].request.read()
    assert b"max_tokens" in sent and b"throughput" in sent  # same routing as real runs


def test_format_is_plain_ascii_with_fixes():
    from tools.setup_check import Check

    text = format_checks([Check("Settings", "fail", "Missing: X", "Copy .env.example"), Check("Worker", "ok", "running")])
    assert text.isascii()
    assert "[FAIL] Settings" in text and "fix: Copy .env.example" in text and "[ ok ] Worker" in text


def test_cli_check_prints_results_and_exits_nonzero_on_failure(monkeypatch, capsys):
    import main as cli
    from tools import setup_check
    from tools.setup_check import Check

    seen = {}

    def fake_run(env, worker, live=False):
        seen["live"] = live
        return [Check("Settings", "fail", "Missing in .env: X", "Copy .env.example")]

    monkeypatch.setattr(setup_check, "run_checks", fake_run)
    assert cli.main(["--check", "--live"]) == 1
    out = capsys.readouterr().out
    assert "[FAIL] Settings" in out and seen["live"] is True


def test_cli_still_needs_a_topic_without_check(capsys):
    import pytest

    import main as cli

    with pytest.raises(SystemExit):
        cli.main([])


@respx.mock
def test_model_line_lists_each_role_once_and_marks_pdf_only_use():
    _mock_all()
    respx.get(f"{OR}/models/openai/gpt-5/endpoints").mock(return_value=httpx.Response(200, json=_endpoints((1.25, 10))))
    checks = run_checks({**ENV, "WRITER_AGENT_LLM_PDF": "openrouter/openai/gpt-5"}, FakeWorker())
    strong = next(c for c in checks if "gpt-oss-120b" in c.name).detail
    assert strong.count("Router") == 1 and "Router (PDF)" not in strong
    gpt5 = next(c for c in checks if "gpt-5" in c.name).detail
    assert "Writer (PDF only)" in gpt5
