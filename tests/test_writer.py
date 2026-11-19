import re
import threading
import time

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
    llm = ScriptedLLM(outline=_outline(3), body_suffix="Claim [S1].\n## References\n- FAKE REF FROM LLM")
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


def test_references_list_only_sources_cited_in_text(tmp_path):
    r = _registry(tmp_path)
    r.add("https://b.com", "Beta Uncited", "web", "web_search")
    llm = ScriptedLLM(outline=_outline(3), body_suffix="Claim [S1].")
    out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=r, llm=llm)
    assert "[S1] Alpha Source" in out.markdown
    assert "Beta Uncited" not in out.markdown


def test_extra_cited_ids_are_listed_in_references(tmp_path):
    r = _registry(tmp_path)
    r.add("https://openalex.org/q", "OpenAlex counts", "dataset", "openalex")
    llm = ScriptedLLM(outline=_outline(3))
    out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=r, llm=llm, extra_cited=["S2"])
    assert "[S2] OpenAlex counts" in out.markdown


def test_model_added_title_and_word_count_lines_are_removed(tmp_path):
    class TitleLLM(ScriptedLLM):
        def __call__(self, prompt):
            body = super().__call__(prompt)
            return "# My Own Title\n\n**T**  \n*Short Report \u2013 1 000 words*\n\n---\n\n## Summary\n\n" + body

    out = write_report(topic="T", findings="f", analysis="a", size="small", registry=_registry(tmp_path), llm=TitleLLM())
    assert "My Own Title" not in out.markdown
    assert "1 000 words" not in out.markdown
    assert "**T**" not in out.markdown
    assert out.markdown.startswith("# T\n\n## Summary")


def test_no_removed_citation_note_when_repair_fixes_everything(tmp_path):
    class FixingLLM(ScriptedLLM):
        def __call__(self, prompt):
            if prompt.startswith("REPAIR_REQUEST"):
                self.calls.append("REPAIR_REQUEST")
                return prompt.split("TEXT:\n", 1)[1].replace("[S99]", "[S1]")
            return super().__call__(prompt)

    llm = FixingLLM(outline=_outline(3), body_suffix="Claim [S1] and bogus [S99].")
    out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path), llm=llm)
    assert llm.calls.count("REPAIR_REQUEST") == 1
    assert not any("Removed citations" in n for n in out.notes)


def test_editor_model_handles_outline_adjust_and_repair(tmp_path):
    writer = ScriptedLLM(outline=_outline(3), section_factor=0.3, body_suffix="Claim [S1] and bogus [S99].")
    editor = ScriptedLLM(outline=_outline(3), body_suffix="Still bogus [S99].")  # the length pass rewrites sections
    write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path),
                 llm=writer, edit_llm=editor)
    assert set(writer.calls) == {"SECTION_REQUEST"}
    assert editor.calls[0] == "OUTLINE_REQUEST"
    assert "ADJUST_REQUEST" in editor.calls and "REPAIR_REQUEST" in editor.calls


def test_writer_alone_still_does_everything(tmp_path):
    llm = ScriptedLLM(outline=_outline(3))
    write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path), llm=llm)
    assert llm.calls[0] == "OUTLINE_REQUEST" and "SECTION_REQUEST" in llm.calls


class _ConcurrencyLLM(ScriptedLLM):
    """Records how many section calls overlap; each one waits briefly so overlap is observable."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._lock = threading.Lock()
        self.active = self.peak = 0

    def __call__(self, prompt):
        if not prompt.startswith(("SECTION_REQUEST", "ADJUST_REQUEST")):
            return super().__call__(prompt)
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.05)
        heading = re.search(r"HEADING: (.*)", prompt).group(1)
        out = super().__call__(prompt) + f" ({heading})"
        with self._lock:
            self.active -= 1
        return out


def test_sections_are_written_in_parallel_and_kept_in_outline_order(tmp_path):
    llm = _ConcurrencyLLM(outline=_outline(5))
    out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path),
                       llm=llm, parallelism=5)
    assert llm.peak > 1
    positions = [out.markdown.index(f"## Section {i}") for i in range(5)]
    assert positions == sorted(positions)
    for i in range(5):  # each body sits under its own heading
        assert f"(Section {i})" in out.markdown.split(f"## Section {i}", 1)[1].split("## ", 1)[0]


def test_length_pass_also_runs_in_parallel(tmp_path):
    llm = _ConcurrencyLLM(outline=_outline(4), section_factor=0.3)
    write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path),
                 llm=ScriptedLLM(outline=_outline(4), section_factor=0.3), edit_llm=llm, parallelism=4)
    assert llm.calls.count("ADJUST_REQUEST") == 4 and llm.peak > 1


def test_parallelism_one_writes_sections_one_at_a_time(tmp_path):
    llm = _ConcurrencyLLM(outline=_outline(3))
    write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path),
                 llm=llm, parallelism=1)
    assert llm.peak == 1


def test_fullwidth_citations_count_and_reach_references(tmp_path):
    llm = ScriptedLLM(outline=_outline(3), body_suffix="Claim 【S1】.")
    out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path), llm=llm)
    assert "【" not in out.markdown
    assert "[S1] Alpha Source" in out.markdown
    assert "No sources were cited" not in out.markdown


# -- outline discipline --------------------------------------------------------

class PromptLLM(ScriptedLLM):
    """ScriptedLLM that also keeps every prompt, and can write some sections longer."""

    def __init__(self, long_headings=(), **kw):
        super().__init__(**kw)
        self.prompts = []
        self.long_headings = set(long_headings)

    def __call__(self, prompt):
        self.prompts.append(prompt)
        out = super().__call__(prompt)
        heading = re.search(r"^HEADING: (.*)$", prompt, re.M)
        if prompt.startswith("SECTION_REQUEST") and heading and heading.group(1) in self.long_headings:
            out = out + " " + out + " " + out
        return out

    def section_prompts(self):
        return [p for p in self.prompts if p.startswith("SECTION_REQUEST")]


def _headings(markdown):
    return re.findall(r"^## (.+)$", markdown.split("## References")[0], re.M)


def test_subsections_in_the_outline_are_folded_into_their_parent(tmp_path):
    outline = []
    for i in range(1, 9):
        outline.append({"heading": f"{i}. Topic {i}", "words": 400})
        outline += [{"heading": f"{i}.{j} Detail {i}.{j}", "words": 150} for j in range(1, 5)]
    llm = PromptLLM(outline=outline)
    out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path), llm=llm)
    heads = _headings(out.markdown)
    assert len(heads) <= 7
    assert not any(re.match(r"\d", h) for h in heads)  # no "2.1 ..." and no "3. ..." numbering
    assert "Detail 1.2" in llm.section_prompts()[0]  # a folded subsection still shapes its parent
    assert out.status == "ok"


def test_outline_word_targets_are_rescaled_to_the_size(tmp_path):
    llm = PromptLLM(outline=[{"heading": f"Part {i}", "words": 1200} for i in range(6)])  # totals 7200
    write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path), llm=llm)
    targets = [int(re.search(r"TARGET_WORDS: (\d+)", p).group(1)) for p in llm.section_prompts()]
    assert 2300 <= sum(targets) <= 2700


def test_outline_capped_but_last_section_kept(tmp_path):
    outline = [{"heading": f"Part {i}", "words": 250} for i in range(10)] + [{"heading": "Conclusion", "words": 250}]
    out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path),
                       llm=PromptLLM(outline=outline))
    heads = _headings(out.markdown)
    assert len(heads) == 7 and heads[-1] == "Conclusion"


def test_model_planned_source_sections_are_dropped(tmp_path):
    outline = _outline(4) + [{"heading": "Appendix: Source Citations", "words": 200}, {"heading": "References", "words": 100}]
    out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path),
                       llm=PromptLLM(outline=outline))
    assert "Source Citations" not in out.markdown
    assert out.markdown.count("## References") == 1


def test_each_section_sees_the_outline_and_what_others_cover(tmp_path):
    outline = [{"heading": "Funding", "words": 600, "covers": "venture rounds and grants"},
               {"heading": "Policy", "words": 600, "covers": "the governance framework"},
               {"heading": "Outlook", "words": 600, "covers": "what comes next"}]
    llm = PromptLLM(outline=outline)
    write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path), llm=llm)
    policy = next(p for p in llm.section_prompts() if "HEADING: Policy" in p)
    assert "venture rounds and grants" in policy and "do not repeat" in policy.lower()


def test_outline_prompt_asks_for_top_level_sections_with_scope(tmp_path):
    llm = PromptLLM(outline=_outline(5))
    write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path), llm=llm)
    outline_prompt = llm.prompts[0]
    assert "5 to 7" in outline_prompt and "covers" in outline_prompt and "subsection" in outline_prompt.lower()


def test_length_pass_only_rewrites_the_sections_that_are_off(tmp_path):
    llm = PromptLLM(outline=_outline(5), long_headings={"Section 0"})
    write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path), llm=llm)
    adjusted = [p for p in llm.prompts if p.startswith("ADJUST_REQUEST")]
    assert len(adjusted) == 1 and "HEADING: Section 0" in adjusted[0]


# -- cleaning model additions --------------------------------------------------

LONG_HEADING = "3. Policy & Regulatory Momentum – The Model AI Governance Framework"


def _cleaning_llm(body):
    class BodyLLM(ScriptedLLM):
        def __call__(self, prompt):
            if prompt.startswith(("SECTION_REQUEST", "ADJUST_REQUEST")):  # the length pass must not hide the body
                self.calls.append(prompt.split("\n", 1)[0])
                return body
            return super().__call__(prompt)

    return BodyLLM(outline=[{"heading": LONG_HEADING, "words": 50}])


def test_section_title_repeated_in_bold_is_removed(tmp_path):
    body = ("**3. Policy & Regulatory Momentum – The Model AI Governance Framework (MGF)**\n\n"
            "Text [S1].\n\n**Key takeaways**\n\nMore.")
    out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path),
                       llm=_cleaning_llm(body))
    assert out.markdown.count("Policy & Regulatory Momentum") == 1
    assert "**Key takeaways**" in out.markdown  # inner bold labels are fine


def test_section_title_repeated_as_a_heading_or_with_word_banner_is_removed(tmp_path):
    for first in ("### Policy & Regulatory Momentum",
                  "**Policy and regulatory momentum – 300‑Word Section**",
                  "## " + LONG_HEADING):
        out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path),
                           llm=_cleaning_llm(first + "\n\nText [S1]."))
        assert out.markdown.lower().count("regulatory momentum") == 1, first
        assert "Word Section" not in out.markdown


def test_model_written_source_list_inside_a_section_is_removed(tmp_path):
    body = "Text [S1].\n\n### Sources\n\n- [S1] Alpha, https://a.com\n- [S9] Invented"
    out = write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path),
                       llm=_cleaning_llm(body))
    assert "Invented" not in out.markdown and "### Sources" not in out.markdown


# -- prompts -------------------------------------------------------------------

def test_writer_prompts_carry_date_style_and_citation_format(tmp_path):
    llm = PromptLLM(outline=_outline(5))
    write_report(topic="T", findings="f", analysis="a", size="medium", registry=_registry(tmp_path), llm=llm,
                 today="2026-11-19")
    section = llm.section_prompts()[0]
    assert "2026-11-19" in section
    assert "plain" in section.lower() and "acronym" in section.lower()
    assert "[S3]" in section and "【" in section  # shows the right format and names the wrong one
    small = PromptLLM()
    write_report(topic="T", findings="f", analysis="a", size="small", registry=_registry(tmp_path), llm=small,
                 today="2026-11-19")
    assert "2026-11-19" in small.prompts[0] and "acronym" in small.prompts[0].lower()


def test_title_repeat_matches_across_hyphen_styles():
    from report.writer import _clean_body

    out = _clean_body("**4. Key Agentic\u2011AI Start\u2011ups in Singapore**\n\nText.", "T", "4. Key Agentic AI Start-ups in Singapore")
    assert out == "Text."
