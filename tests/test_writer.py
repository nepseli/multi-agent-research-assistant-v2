from core.config import SIZE_PRESETS
from core.registry import SourceRegistry
from report.validators import count_words, word_status
from report.writer import write_report
from tests.fakes import ScriptedLLM


def test_count_words_excludes_references_and_code():
    text = "# Title\n\none two three\n\n```python\nignored words here\n```\n\n![fig](a.png)\n\n## References\n\n[S1] many many many words"
    assert count_words(text) == 4  # "Title" + three body words


def test_word_status_boundaries():
    m = SIZE_PRESETS["medium"]
    assert word_status(1800, m) == "ok"
    assert word_status(1699, m) == "short"
    assert word_status(1700, m) == "ok"
    assert word_status(3450, m) == "ok"
    assert word_status(3451, m) == "long"


def _registry(tmp_path):
    r = SourceRegistry(tmp_path)
    r.add("https://a.com", "Alpha Source", "web", "web_search")
    return r


def _outline(n=5, total=2500):
    return [{"heading": f"Section {i}", "words": total // n} for i in range(n)]


def test_medium_report_builds_outline_then_sections(tmp_path):
    llm = ScriptedLLM(outline=_outline(5))
    out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path), llm=llm)
    assert llm.calls == ["OUTLINE_REQUEST"] + ["SECTION_REQUEST"] * 5
    assert out.status == "ok"
    assert 2000 <= out.words <= 3000
    assert out.markdown.count("\n## Section") == 5


def test_small_uses_single_call(tmp_path):
    llm = ScriptedLLM()
    out = write_report(topic="T", findings="f", analysis="a", size="small", registry=_registry(tmp_path), llm=llm)
    assert llm.calls == ["SMALL_REQUEST"]
    assert out.status == "ok"


def test_unknown_citation_triggers_one_repair_then_strips(tmp_path):
    llm = ScriptedLLM(outline=_outline(3), body_suffix="Claim [S1] and bogus [S99].")
    out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path), llm=llm)
    assert llm.calls.count("REPAIR_REQUEST") == 1
    assert out.unknown_citations == ["S99"]
    assert "[S99]" not in out.markdown
    assert "[S1]" in out.markdown


def test_short_report_gets_one_expand_pass_then_accepted(tmp_path):
    llm = ScriptedLLM(outline=_outline(4), section_factor=0.3)
    out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path), llm=llm)
    assert llm.calls.count("ADJUST_REQUEST") == 4  # one pass, one call per section
    assert out.status == "short"
    assert any("word" in n.lower() for n in out.notes)


def test_references_generated_from_registry_not_llm(tmp_path):
    llm = ScriptedLLM(outline=_outline(3), body_suffix="\n## References\n- FAKE REF FROM LLM")
    out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path), llm=llm)
    assert "FAKE REF FROM LLM" not in out.markdown
    assert "[S1] Alpha Source" in out.markdown
    assert out.markdown.count("## References") == 1


def test_outline_json_failure_falls_back_to_default_headings(tmp_path):
    llm = ScriptedLLM(outline_raw="not json at all")
    out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path), llm=llm)
    assert llm.calls[0] == "OUTLINE_REQUEST"
    assert "## Background" in out.markdown and "## Limitations" in out.markdown
    assert out.status == "ok"


def test_coverage_notes_appended(tmp_path):
    llm = ScriptedLLM(outline=_outline(3))
    out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path), llm=llm, notes=["Worker was down for 2 pages"])
    assert "## Coverage notes" in out.markdown and "Worker was down" in out.markdown
