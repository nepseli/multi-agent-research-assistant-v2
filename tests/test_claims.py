import json
import re
import threading

from core.registry import SourceRegistry
from report.claims import check_claims, evidence_for, extract_claims

ARTICLE = (
    "Singapore published its Model AI Governance Framework for agentic AI on 22 January 2026.\n\n"
    "The framework sets out four dimensions of mitigation. Unrelated paragraph about weather and tides.\n\n"
    "Manus raised US$75 million in a Series B round led by Benchmark in 2025."
)

REPORT = """# T

## Policy

Singapore published the framework in January 2026 [S1]. It has six dimensions [S1].

| Item | Detail | Source |
|---|---|---|
| MGF | four dimensions | [S1] |

## Funding

Manus raised US$500 million [S1]. A sentence with no citation.
- Bullet claim about Manus funding [S2].
"""


def _registry(tmp_path):
    r = SourceRegistry(tmp_path)
    r.add("https://imda.gov.sg/mgf", "MGF", "web", "read_page", content=ARTICLE)
    r.add("https://x.com/post", "Post", "web", "web_search")  # no saved text
    return r


class CheckLLM:
    """Answers each CLAIM_CHECK_REQUEST from a function of the statement text."""

    def __init__(self, judge):
        self.judge = judge
        self.prompts = []
        self._lock = threading.Lock()

    def __call__(self, prompt):
        with self._lock:
            self.prompts.append(prompt)
        statements = re.findall(r"^STATEMENT (\d+): (.*)$", prompt, re.M)
        return json.dumps([{"id": int(i), **self.judge(text)} for i, text in statements])


def _judge(text):
    if "six dimensions" in text:
        return {"verdict": "partial", "fix": "It has four dimensions [S1]."}
    if "US$500 million" in text:
        return {"verdict": "unsupported", "fix": ""}
    return {"verdict": "supported", "fix": ""}


# -- extraction ----------------------------------------------------------------

def test_extracts_cited_sentences_rows_and_bullets_with_their_section():
    claims = extract_claims(REPORT)
    texts = [c.text for c in claims]
    assert "Singapore published the framework in January 2026 [S1]." in texts
    assert "It has six dimensions [S1]." in texts
    assert any(c.in_table and "four dimensions" in c.text for c in claims)
    assert "Bullet claim about Manus funding [S2]." in texts
    assert not any("no citation" in t for t in texts)
    assert {c.section for c in claims} == {"Policy", "Funding"}
    assert claims[0].cites == ["S1"]


def test_evidence_picks_the_passages_that_match_the_claim(tmp_path):
    r = _registry(tmp_path)
    ev = evidence_for("Manus raised US$500 million [S1].", ["S1"], r, chars=200)
    assert "Series B" in ev and "weather" not in ev
    assert "(read in full)" in ev
    assert "no saved text" in evidence_for("x [S2].", ["S2"], r)


# -- checking and fixing -------------------------------------------------------

def test_partial_claims_are_reworded_and_unsupported_ones_removed(tmp_path):
    text, claims, note = check_claims(REPORT, _registry(tmp_path), CheckLLM(_judge))
    assert "It has four dimensions [S1]." in text and "six dimensions" not in text
    assert "US$500 million" not in text
    assert "Singapore published the framework in January 2026 [S1]." in text
    assert "A sentence with no citation." in text  # uncited text is left alone
    verdicts = {c.text: c.verdict for c in claims}
    assert verdicts["It has six dimensions [S1]."] == "partial"
    assert "reworded" in note and "removed" in note


def test_the_last_data_row_of_a_table_is_never_removed(tmp_path):
    def judge(text):
        return {"verdict": "unsupported", "fix": ""}

    text, claims, _ = check_claims(REPORT, _registry(tmp_path), CheckLLM(judge))
    assert "| MGF | four dimensions | [S1] |" in text  # removing it would leave a header-only table
    assert any(c.in_table and c.verdict == "unsupported" for c in claims)


TABLE = """# T

## Players

| Name | Funding | Source |
|---|---|---|
| **Manus** | US$500M Series C | [S1] |
| Dyna.Ai | Series A | [S1] |
| GovTech | Sandbox owner | [S1] |
"""


def test_table_row_fix_with_the_same_columns_replaces_the_row(tmp_path):
    def judge(text):
        if "US$500M" in text:
            return {"verdict": "partial", "fix": "Manus | US$75M Series B"}  # pipes lost, citation cell dropped
        return {"verdict": "supported", "fix": ""}

    def judge3(text):
        if "US$500M" in text:
            return {"verdict": "partial", "fix": "| **Manus** | US$75M Series B | [S1] |"}
        return {"verdict": "supported", "fix": ""}

    text, _, _ = check_claims(TABLE, _registry(tmp_path), CheckLLM(judge))
    assert "| **Manus** | US$500M Series C | [S1] |" in text  # 2 cells for a 3-column row: left alone
    text, claims, _ = check_claims(TABLE, _registry(tmp_path), CheckLLM(judge3))
    assert "| **Manus** | US$75M Series B | [S1] |" in text and "US$500M" not in text
    assert next(c for c in claims if "Manus" in c.text).applied == "reworded"


def test_unsupported_table_row_without_fix_is_removed(tmp_path):
    def judge(text):
        return {"verdict": "unsupported", "fix": ""} if "Dyna.Ai" in text else {"verdict": "supported", "fix": ""}

    text, claims, _ = check_claims(TABLE, _registry(tmp_path), CheckLLM(judge))
    assert "Dyna.Ai" not in text
    assert "| GovTech | Sandbox owner | [S1] |" in text and "|---|---|---|" in text
    assert next(c for c in claims if "Dyna.Ai" in c.text).applied == "removed"


def test_row_fix_without_citations_keeps_them_in_the_last_cell(tmp_path):
    def judge(text):
        if "US$500M" in text:
            return {"verdict": "partial", "fix": "| **Manus** | US$75M Series B | |"}
        return {"verdict": "supported", "fix": ""}

    text, _, _ = check_claims(TABLE, _registry(tmp_path), CheckLLM(judge))
    assert "| **Manus** | US$75M Series B | [S1] |" in text


def test_claims_citing_sources_without_text_are_not_sent_to_the_model(tmp_path):
    llm = CheckLLM(_judge)
    _, claims, _ = check_claims(REPORT, _registry(tmp_path), llm)
    bullet = next(c for c in claims if "Bullet claim" in c.text)
    assert bullet.verdict == "unchecked"
    assert not any("Bullet claim" in p for p in llm.prompts)


def test_a_fix_without_citations_keeps_the_original_ones(tmp_path):
    def judge(text):
        if "six dimensions" in text:
            return {"verdict": "partial", "fix": "It has four dimensions."}
        return {"verdict": "supported", "fix": ""}

    text, _, _ = check_claims(REPORT, _registry(tmp_path), CheckLLM(judge))
    assert "It has four dimensions [S1]." in text


def test_garbage_from_the_model_changes_nothing(tmp_path):
    text, claims, note = check_claims(REPORT, _registry(tmp_path), lambda p: "I cannot help with that")
    assert text == REPORT
    assert all(c.verdict in ("unclear", "unchecked") for c in claims)
    assert "could not be checked" in note


def test_sections_are_checked_in_parallel_batches(tmp_path):
    llm = CheckLLM(_judge)
    check_claims(REPORT, _registry(tmp_path), llm, batch_size=2)
    assert len(llm.prompts) >= 2
    assert all(len(re.findall(r"^STATEMENT \d+:", p, re.M)) <= 2 for p in llm.prompts)


def test_claim_count_is_capped_by_even_sampling(tmp_path):
    body = "\n".join(f"Fact number {i} about the framework [S1]." for i in range(30))
    llm = CheckLLM(_judge)
    _, claims, note = check_claims(f"# T\n\n## A\n\n{body}\n", _registry(tmp_path), llm, max_claims=10)
    checked = [c for c in claims if c.verdict not in (None, "skipped")]
    assert len(checked) == 10
    assert "10 of 30" in note


def test_prompt_explains_the_verdicts_and_shows_source_depth(tmp_path):
    llm = CheckLLM(_judge)
    check_claims(REPORT, _registry(tmp_path), llm)
    prompt = llm.prompts[0]
    for word in ("supported", "partial", "unsupported", "unclear", "fix"):
        assert word in prompt
    assert "(read in full)" in prompt


def test_identical_sentences_are_sampled_as_separate_claims(tmp_path):
    body = "\n".join("The framework exists [S1]." for _ in range(4))
    _, claims, note = check_claims(f"# T\n\n## A\n\n{body}\n", _registry(tmp_path), CheckLLM(_judge), max_claims=2)
    assert [c.verdict for c in claims].count("skipped") == 2
    assert "2 of 4" in note


# -- calibration ---------------------------------------------------------------

def test_claims_resting_only_on_snippets_are_kept_but_counted_as_unverified(tmp_path):
    r = _registry(tmp_path)
    r.add("https://y.com/a", "Snippet source", "web", "web_search", content="Manus is a Singapore AI firm.")
    text = "# T\n\n## A\n\nManus has 300 staff and raised US$1 billion [S3].\n"

    def judge(statement):
        return {"verdict": "unsupported", "fix": ""}

    out, claims, note = check_claims(text, r, CheckLLM(judge))
    assert "Manus has 300 staff" in out  # a snippet cannot prove a claim wrong
    assert claims[0].applied == "" and claims[0].verdict == "unsupported"
    assert "snippet" in note and "1 " in note


def test_evidence_passages_start_at_sentence_boundaries(tmp_path):
    r = SourceRegistry(tmp_path)
    sentences = [f"Sentence number {i} talks about topic{i} in some detail here." for i in range(60)]
    r.add("https://a.com", "A", "web", "read_page", content=" ".join(sentences))
    ev = evidence_for("topic37 detail [S1].", ["S1"], r)
    body = ev.split(":\n", 1)[1]
    for passage in body.split("\n...\n"):
        assert passage.startswith("Sentence number"), passage[:40]
    assert "topic37" in body


def test_full_text_sources_get_more_evidence_than_snippets(tmp_path):
    r = SourceRegistry(tmp_path)
    page = "\n\n".join(f"Paragraph {i} mentions the framework and its dimensions at length." * 3 for i in range(40))
    r.add("https://a.com", "A", "web", "read_page", content=page)
    assert len(evidence_for("the framework dimensions [S1].", ["S1"], r)) > 1500


def test_prompt_treats_paraphrase_as_supported_and_short_snippets_as_unclear(tmp_path):
    llm = CheckLLM(_judge)
    check_claims(REPORT, _registry(tmp_path), llm)
    prompt = llm.prompts[0].lower()
    assert "paraphrase" in prompt and "summary" in prompt
    assert "snippet" in prompt and "unclear" in prompt
