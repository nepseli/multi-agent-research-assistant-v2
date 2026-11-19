"""Pure helpers for the Streamlit app and CLI (no streamlit import, so they are unit-testable)."""
from collections.abc import Mapping

from core.config import _PREFIX, SIZE_PRESETS

PROVIDER_KEYS = {"openrouter": "OPENROUTER_API_KEY", "openai": "OPENAI_API_KEY", "groq": "GROQ_API_KEY"}
ROLE_LABELS = {
    "router": "Router",
    "research": "Research",
    "analyst": "Analyst",
    "writer": "Writer",
    "figure_planner": "Figure planner",
}


def _get(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def missing_settings(env: Mapping[str, str]) -> list[str]:
    missing: list[str] = []
    needed_keys: set[str] = set()
    if not _get(env, "SERPER_API_KEY"):
        missing.append("SERPER_API_KEY")
    for prefix in _PREFIX.values():
        for suffix in ("_LLM", "_TEMP"):
            if not _get(env, prefix + suffix):
                missing.append(prefix + suffix)
        for var in (prefix + "_LLM", prefix + "_LLM_PDF"):
            model = _get(env, var)
            provider = model.split("/", 1)[0].lower() if "/" in model else ""
            if provider in PROVIDER_KEYS:
                needed_keys.add(PROVIDER_KEYS[provider])
    for key in sorted(needed_keys):
        if not _get(env, key):
            missing.append(key)
    return missing


def size_label(size: str) -> str:
    p = SIZE_PRESETS[size]
    pages = f"~{round(p.words_min / 350)}–{round(p.words_max / 300)} PDF pages"
    return f"{size.capitalize()} — {p.words_min:,}–{p.words_max:,} words, {pages}"


def stages_for(pdf: bool) -> list[str]:
    base = ["route", "research", "analyse", "write"]
    return ["route", "research", "analyse", "figures", "write", "render"] if pdf else base


def role_model_table(env: Mapping[str, str], pdf: bool) -> list[dict]:
    rows = []
    for role, prefix in _PREFIX.items():
        model = (_get(env, prefix + "_LLM_PDF") if pdf else "") or _get(env, prefix + "_LLM")
        temp = (_get(env, prefix + "_TEMP_PDF") if pdf else "") or _get(env, prefix + "_TEMP")
        rows.append({"role": role, "label": ROLE_LABELS[role], "model": model or "(not set)", "temperature": temp or "(not set)"})
    return rows
