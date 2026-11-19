"""`python main.py --check`: is this install ready to run? Each check says what is wrong and how to fix it.

By default nothing is spent: keys are validated through account endpoints and models through OpenRouter's
public model list. `--live` also sends one tiny prompt to each configured model.
"""
import time
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from app_helpers import ROLE_LABELS, missing_settings
from core.config import _PREFIX, TIER_VAR, llm_options, resolve_llm

OPENROUTER = "https://openrouter.ai/api/v1"
SERPER_ACCOUNT = "https://google.serper.dev/account"
TIMEOUT = 15


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail
    detail: str
    fix: str = ""


def _settings(env: Mapping[str, str]) -> Check:
    missing = missing_settings(env)
    if missing:
        return Check("Settings", "fail", "Missing in .env: " + ", ".join(missing),
                     "Copy .env.example to .env and fill in the values listed.")
    return Check("Settings", "ok", "All required settings are present.")


def _openrouter_key(env: Mapping[str, str]) -> Check:
    key = (env.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        return Check("OpenRouter key", "fail", "OPENROUTER_API_KEY is not set.",
                     "Create a key at https://openrouter.ai/settings/keys and put it in .env.")
    try:
        resp = httpx.get(f"{OPENROUTER}/key", headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        return Check("OpenRouter key", "fail", f"Could not reach openrouter.ai: {exc}", "Check your internet connection.")
    if resp.status_code in (401, 403):
        return Check("OpenRouter key", "fail", "The key was rejected.", "Copy the key again from https://openrouter.ai/settings/keys.")
    if resp.status_code >= 400:
        return Check("OpenRouter key", "warn", f"OpenRouter answered HTTP {resp.status_code}; try again later.")
    data = resp.json().get("data", {}) if resp.headers.get("content-type", "").startswith("application/json") else {}
    usage, remaining = data.get("usage"), data.get("limit_remaining")
    detail = "Valid."
    if usage is not None:
        detail += f" Used so far: ${usage:.2f}."
    if remaining is not None:
        detail += f" Credit left on this key: ${remaining:.2f}."
    if remaining is not None and remaining <= 0:
        return Check("OpenRouter key", "fail", detail, "Add credit at https://openrouter.ai/settings/credits.")
    return Check("OpenRouter key", "ok", detail)


def _model_uses(env: Mapping[str, str]) -> dict[str, dict]:
    """Every configured model, with the roles and variables that select it and the price cap it runs under."""
    uses: dict[str, dict] = {}
    for role in _PREFIX:
        for pdf in (False, True):
            choice = resolve_llm(role, pdf, env)
            if not choice.model:
                continue
            item = uses.setdefault(choice.model, {"modes": {}, "vars": set(), "cap": None, "cap_var": None, "role": role, "pdf": pdf})
            item["modes"].setdefault(role, set()).add(pdf)
            item["vars"].add(choice.source)
            price = llm_options(role, pdf, env).get("extra_body", {}).get("provider", {}).get("max_price")
            if price:
                item["cap"] = (price["prompt"], price["completion"])
                item["cap_var"] = f"{TIER_VAR[choice.tier].removesuffix('_LLM')}_MAX_PRICE"
    for item in uses.values():
        item["roles"] = [ROLE_LABELS[r] + (" (PDF only)" if modes == {True} else "") for r, modes in item["modes"].items()]
    return uses


def _model(model: str, use: dict) -> Check:
    name = f"Model {model}"
    roles = ", ".join(use["roles"])
    if not model.startswith("openrouter/"):
        return Check(name, "ok", f"Used by {roles}. Not an OpenRouter model, so it was not checked.")
    slug = model.removeprefix("openrouter/")
    try:
        resp = httpx.get(f"{OPENROUTER}/models/{slug}/endpoints", timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        return Check(name, "fail", f"Could not reach openrouter.ai: {exc}", "Check your internet connection.")
    if resp.status_code == 404:
        return Check(name, "fail", f"Not found on OpenRouter (set by {', '.join(sorted(use['vars']))}).",
                     "Look the ID up at https://openrouter.ai/models and prefix it with openrouter/.")
    if resp.status_code >= 400:
        return Check(name, "warn", f"OpenRouter answered HTTP {resp.status_code}; try again later.")
    endpoints = (resp.json().get("data") or {}).get("endpoints") or []
    if not endpoints:
        return Check(name, "fail", "OpenRouter lists no host serving this model right now.", "Pick another model.")
    detail = f"Used by {roles}. {len(endpoints)} hosts"
    if use["cap"]:
        cap_prompt, cap_completion = use["cap"]
        fits = [e for e in endpoints
                if float((e.get("pricing") or {}).get("prompt", 1)) * 1e6 <= cap_prompt + 1e-9
                and float((e.get("pricing") or {}).get("completion", 1)) * 1e6 <= cap_completion + 1e-9]
        if not fits:
            return Check(name, "fail",
                         f"{detail}, but none within the price cap of ${cap_prompt}/${cap_completion} per million tokens.",
                         f"Raise {use['cap_var']} in .env, or set it to none.")
        detail += f", {len(fits)} within the price cap"
    return Check(name, "ok", detail + ".")


def _serper(env: Mapping[str, str]) -> Check:
    key = (env.get("SERPER_API_KEY") or "").strip()
    if not key:
        return Check("Serper key", "fail", "SERPER_API_KEY is not set.", "Create a key at https://serper.dev and put it in .env.")
    try:
        resp = httpx.get(SERPER_ACCOUNT, headers={"X-API-KEY": key}, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        return Check("Serper key", "fail", f"Could not reach serper.dev: {exc}", "Check your internet connection.")
    if resp.status_code in (401, 403):
        return Check("Serper key", "fail", "The key was rejected.", "Copy the key again from https://serper.dev.")
    if resp.status_code >= 400:
        return Check("Serper key", "warn", f"Serper answered HTTP {resp.status_code}; try again later.")
    balance = resp.json().get("balance")
    if balance is not None and balance <= 0:
        return Check("Serper key", "warn", "Valid, but no search credits are left.", "Top up at https://serper.dev.")
    return Check("Serper key", "ok", "Valid." + (f" {balance} search credits left." if balance is not None else ""))


def _worker(worker) -> Check:
    health = worker.health()
    if not health.get("ok"):
        return Check("Worker", "warn",
                     "Not running: reports fall back to search snippets, and PDF output and diagrams are off.",
                     "Start it with: docker compose up -d --build  (lean image: set WORKER_DOCLING=0 first)")
    parts = ["Running"]
    if health.get("parse_pdf") is False:
        parts.append("lean image without PDF parsing (papers are read from abstracts)")
    else:
        parts.append("page reading, PDF parsing and PDF output available")
    if health.get("check_mermaid") is False or "check_mermaid" not in health:
        return Check("Worker", "warn", ", ".join(parts) + "; this image cannot check diagrams.",
                     "Rebuild it: docker compose up -d --build")
    return Check("Worker", "ok", ", ".join(parts) + ".")


def _live(model: str, use: dict, env: Mapping[str, str]) -> Check:
    name = f"Live call {model}"
    if not model.startswith("openrouter/"):
        return Check(name, "ok", "Skipped: not an OpenRouter model.")
    opts = llm_options(use["role"], use["pdf"], env)
    body = {
        "model": model.removeprefix("openrouter/"),
        "messages": [{"role": "user", "content": "Reply with the single word OK."}],
        "max_tokens": 64,
        **opts.get("extra_body", {}),
        **({"reasoning_effort": opts["reasoning_effort"]} if "reasoning_effort" in opts else {}),
    }
    start = time.monotonic()
    try:
        resp = httpx.post(f"{OPENROUTER}/chat/completions", json=body, timeout=60,
                          headers={"Authorization": f"Bearer {(env.get('OPENROUTER_API_KEY') or '').strip()}"})
    except httpx.HTTPError as exc:
        return Check(name, "fail", f"Request failed: {exc}")
    seconds = time.monotonic() - start
    if resp.status_code >= 400:
        message = resp.text[:200]
        return Check(name, "fail", f"HTTP {resp.status_code}: {message}",
                     "If it mentions price or providers, raise the price cap in .env.")
    data = resp.json()
    host = data.get("provider") or "unknown host"
    return Check(name, "ok", f"Answered in {seconds:.1f} s via {host}.")


def run_checks(env: Mapping[str, str], worker, live: bool = False) -> list[Check]:
    checks = [_settings(env), _openrouter_key(env)]
    uses = _model_uses(env)
    checks += [_model(model, use) for model, use in uses.items()]
    checks.append(_serper(env))
    checks.append(_worker(worker))
    if live:
        checks += [_live(model, use, env) for model, use in uses.items()]
    return checks


_MARK = {"ok": "[ ok ]", "warn": "[warn]", "fail": "[FAIL]"}


def format_checks(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        lines.append(f"{_MARK[c.status]} {c.name}: {c.detail}")
        if c.fix:
            lines.append(f"       fix: {c.fix}")
    fails = sum(c.status == "fail" for c in checks)
    warns = sum(c.status == "warn" for c in checks)
    lines.append("")
    lines.append("Ready to run." if not fails else f"{fails} problem(s) to fix before running.")
    if warns:
        lines[-1] += f" {warns} warning(s)."
    return "\n".join(line.encode("ascii", "replace").decode() for line in lines)
