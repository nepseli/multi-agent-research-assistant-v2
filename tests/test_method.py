from core.config import TIER_CAPS
from core.models import ResearchPlan
from core.registry import SourceRegistry
from report.method import add_method_box, method_box

ENV = {"STRONG_LLM": "openrouter/openai/gpt-oss-120b", "LIGHT_LLM": "openrouter/openai/gpt-oss-20b"}


def _registry(tmp_path):
    r = SourceRegistry(tmp_path)
    r.add("https://a.com", "A", "web", "read_page", content="page")
    r.add("https://b.com", "B", "web", "web_search", content="snippet")
    r.add("https://d.org/1", "P", "pdf", "read_open_access_pdf", doi="10.1/x", content="paper")
    return r


def test_box_states_how_the_report_was_made_in_plain_words(tmp_path):
    plan = ResearchPlan(topic="T", tier=1, budget=TIER_CAPS[1])
    claims = [{"verdict": "supported", "applied": ""}, {"verdict": "partial", "applied": "reworded"},
              {"verdict": "unsupported", "applied": "removed"}, {"verdict": "skipped", "applied": ""}]
    box = method_box(plan, _registry(tmp_path), "Text [S1] and [S3].", searches=6, claims=claims, env=ENV,
                     today="2026-11-19")
    assert box.startswith("> **How this report was made.**")
    for part in ("19 November 2026", "Tier 1", "6 searches", "1 web page", "1 paper", "3 sources were found",
                 "2 are cited", "3 cited statements", "2 were reworded or removed", "gpt-oss-120b", "gpt-oss-20b"):
        assert part in box, part


def test_box_without_claim_check_or_reads_stays_short(tmp_path):
    plan = ResearchPlan(topic="T", tier=0, budget=TIER_CAPS[0])
    box = method_box(plan, SourceRegistry(tmp_path), "Text.", searches=1, claims=[], env=ENV, today="2026-11-19")
    assert "claim check" not in box.lower() and "1 search." in box and "read in full" not in box


def test_box_goes_right_under_the_title():
    md = add_method_box("# Topic\n\n## Summary\n\nText.\n", "> **How this report was made.** X.")
    assert md.startswith("# Topic\n\n> **How this report was made.** X.\n\n## Summary")


def test_box_says_why_a_short_report_is_short(tmp_path):
    plan = ResearchPlan(topic="T", tier=1, budget=TIER_CAPS[1])
    box = method_box(plan, _registry(tmp_path), "Text [S1].", searches=5, claims=[], env=ENV, today="2026-11-19",
                     short=(676, 800, 1200))
    assert "676 words" in box and "800-1,200" in box and "only 1 of 3 sources" in box
    normal = method_box(plan, _registry(tmp_path), "Text [S1].", searches=5, claims=[], env=ENV, today="2026-11-19")
    assert "shorter" not in normal
