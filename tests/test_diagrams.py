import json

from report.diagrams import plan_diagrams, sanitize, size_problem

OK = {"error": None, "width": 600, "height": 300}


class DiagramLLM:
    """Answers DIAGRAM_REQUEST with `proposals` and each DIAGRAM_FIX_REQUEST with the next of `fixes`."""

    def __init__(self, proposals, fixes=()):
        self.proposals = proposals
        self.fixes = list(fixes)
        self.calls = []
        self.prompts = []

    def __call__(self, prompt):
        kind = prompt.split("\n", 1)[0]
        self.calls.append(kind)
        self.prompts.append(prompt)
        if kind == "DIAGRAM_REQUEST":
            return json.dumps([{"code": c, "caption": f"cap {i}"} for i, c in enumerate(self.proposals)])
        return self.fixes.pop(0) if self.fixes else "nonsense"


def _checker(results):
    """A worker stand-in: maps each code to a result via `results(code)`, and records the batches."""
    seen = []

    def check(codes):
        seen.append(list(codes))
        return [results(c) for c in codes]

    check.seen = seen
    return check


# -- sanitize -------------------------------------------------------------------

def test_sanitize_quotes_labels_with_special_characters():
    code = "flowchart LR\n  A[Funding (S$1B)] -->|grants: 2024| B[Startups]\n  C{Is it safe?} --> B"
    out = sanitize(code)
    assert 'A["Funding (S$1B)"]' in out
    assert '|"grants: 2024"|' in out
    assert 'C{"Is it safe?"}' in out
    assert "B[Startups]" in out  # plain labels are left alone


def test_sanitize_strips_fences_styling_and_init_directives():
    code = "```mermaid\n%%{init: {'theme':'dark'}}%%\nflowchart LR\n A:::hot --> B\n classDef hot fill:#f00\n style B fill:#0f0\n```"
    out = sanitize(code)
    assert out.splitlines()[0] == "flowchart LR"
    for gone in ("```", "init", "classDef", "style", ":::hot"):
        assert gone not in out
    assert "A --> B" in out


def test_sanitize_replaces_inner_double_quotes():
    assert 'A["The \'Pair\' chatbot (2024)"]' in sanitize('flowchart LR\n A[The "Pair" chatbot (2024)] --> B')


# -- size limits ----------------------------------------------------------------

def test_small_flowchart_has_no_size_problem():
    assert size_problem('flowchart LR\n A["Policy"] --> B["Sandbox"]\n B --> C["Adoption"]') is None


def test_flowchart_with_too_many_boxes_is_flagged():
    code = "flowchart LR\n" + "\n".join(f" N{i} --> N{i + 1}" for i in range(13))
    assert "14 boxes" in size_problem(code)


def test_group_with_too_many_boxes_is_flagged():
    code = 'flowchart LR\n subgraph Gov["Government"]\n  A\n  B\n  C\n  D\n  E\n end\n Gov --> F'
    problem = size_problem(code)
    assert "Government" in problem or "Gov" in problem
    assert "5 boxes" in problem


def test_long_labels_are_flagged():
    code = 'flowchart LR\n A["' + "word " * 12 + '"] --> B'
    assert "label" in size_problem(code).lower()


def test_timeline_limits_periods_and_events():
    long = "timeline\n title T\n" + "\n".join(f" 20{i:02d} : event" for i in range(10))
    assert "10 periods" in size_problem(long)
    busy = "timeline\n 2024 : a : b : c\n 2025 : d"
    assert "3 events" in size_problem(busy)
    assert size_problem("timeline\n title Milestones\n section Policy\n 2024 : Framework launched\n 2025 : Sandbox : Grants") is None


def test_mindmap_limits_items():
    code = "mindmap\n  root((AI))\n" + "\n".join(f"    item{i}" for i in range(16))
    assert "16 items" in size_problem(code)


def test_unsupported_diagram_type_is_flagged():
    assert "type" in size_problem("sequenceDiagram\n A->>B: hi")


# -- plan_diagrams --------------------------------------------------------------

def test_valid_diagram_is_kept_with_status_ok():
    llm = DiagramLLM(['flowchart LR\n A["Policy"] --> B["Adoption"]'])
    check = _checker(lambda c: OK)
    out = plan_diagrams(llm, "f", "a", 2, check=check)
    assert [d.status for d in out] == ["ok"]
    assert 'class="mermaid"' in out[0].block() and "cap 0" in out[0].block()
    assert llm.calls == ["DIAGRAM_REQUEST"]
    assert len(check.seen) == 1  # all proposals checked in one worker call


def test_syntax_error_gets_one_repair_with_the_error_message():
    bad, good = "flowchart LR\n A --> ", 'flowchart LR\n A["Policy"] --> B["Adoption"]'
    llm = DiagramLLM([bad], fixes=[good])
    check = _checker(lambda c: OK if c == good else {"error": "Parse error on line 2", "width": None, "height": None})
    out = plan_diagrams(llm, "f", "a", 2, check=check)
    assert llm.calls == ["DIAGRAM_REQUEST", "DIAGRAM_FIX_REQUEST"]
    assert "Parse error on line 2" in llm.prompts[1]
    assert out[0].status == "repaired" and out[0].code == good


def test_diagram_still_broken_after_repair_is_dropped_with_reason():
    llm = DiagramLLM(["flowchart LR\n A --> "], fixes=["flowchart LR\n A --> "])
    check = _checker(lambda c: {"error": "Parse error", "width": None, "height": None})
    out = plan_diagrams(llm, "f", "a", 2, check=check)
    assert out[0].status == "dropped" and "Parse error" in out[0].problem
    assert out[0].block() == ""


def test_oversized_diagram_is_sent_back_before_drawing():
    big = "flowchart LR\n" + "\n".join(f" N{i} --> N{i + 1}" for i in range(13))
    small = 'flowchart LR\n A["Policy"] --> B["Adoption"]'
    llm = DiagramLLM([big], fixes=[small])
    check = _checker(lambda c: OK)
    out = plan_diagrams(llm, "f", "a", 2, check=check)
    assert "14 boxes" in llm.prompts[1]
    assert out[0].status == "repaired"


def test_drawing_too_tall_or_too_wide_for_a_page_is_repaired():
    tall, wide, fixed = "flowchart TD\n A --> B", "timeline\n 2024 : a", 'flowchart LR\n A["x"] --> B["y"]'
    sizes = {tall: {"error": None, "width": 400, "height": 1400}, wide: {"error": None, "width": 2600, "height": 300}}
    llm = DiagramLLM([tall, wide], fixes=[fixed, fixed])
    check = _checker(lambda c: sizes.get(c, OK))
    out = plan_diagrams(llm, "f", "a", 2, check=check)
    assert "too tall" in llm.prompts[1] and "too wide" in llm.prompts[2]
    assert [d.status for d in out] == ["repaired", "repaired"]


def test_without_a_checker_diagrams_are_kept_unchecked():
    llm = DiagramLLM(['flowchart LR\n A["Policy"] --> B["Adoption"]'])
    out = plan_diagrams(llm, "f", "a", 2, check=lambda codes: None)
    assert [d.status for d in out] == ["unchecked"]
    out = plan_diagrams(llm, "f", "a", 2)
    assert [d.status for d in out] == ["unchecked"]


def test_prompt_states_the_limits():
    llm = DiagramLLM([])
    plan_diagrams(llm, "f", "a", 2)
    prompt = llm.prompts[0]
    assert "flowchart LR" in prompt and "12" in prompt and "5 periods" in prompt


def test_garbage_and_zero_requests():
    assert plan_diagrams(lambda p: "garbage", "f", "a", 2) == []
    assert plan_diagrams(DiagramLLM(["flowchart LR\n A-->B"]), "f", "a", 0) == []


def test_at_most_n_diagrams_kept():
    llm = DiagramLLM([f'flowchart LR\n A{i}["x"] --> B["y"]' for i in range(4)])
    out = plan_diagrams(llm, "f", "a", 2, check=_checker(lambda c: OK))
    assert len([d for d in out if d.status != "dropped"]) == 2


def test_box_with_too_many_arrows_is_flagged_by_its_label():
    # Eight boxes feeding one box stack into a column taller than a page.
    code = 'flowchart LR\n' + "\n".join(f' N{i}["Actor {i}"] --> HUB["Landscape"]' for i in range(8))
    problem = size_problem(code)
    assert "Landscape" in problem and "8 arrows" in problem


def test_chains_and_small_fans_pass():
    assert size_problem("flowchart LR\n A --> B --> C\n A --> D\n A --> E\n A --> F") is None


def test_sanitize_repairs_mindmap_keyword_nodes_and_parentheses():
    code = 'mindmap\n  root "Singapore Agentic AI"\n    sub "Funding"\n      sub "ECI (150M)"\n    Companies'
    out = sanitize(code).splitlines()
    assert out[1] == "  root((Singapore Agentic AI))"
    assert out[2] == "    Funding"
    assert out[3] == "      ECI, 150M"
    assert out[4] == "    Companies"


def test_prompt_shows_correct_mindmap_syntax():
    llm = DiagramLLM([])
    plan_diagrams(llm, "f", "a", 2)
    assert "root((" in llm.prompts[0]


def test_wide_flowchart_hint_suggests_top_to_bottom():
    chain, fixed = "flowchart LR\n A --> B --> C --> D --> E --> F", 'flowchart TD\n A["x"] --> B["y"]'
    llm = DiagramLLM([chain], fixes=[fixed])
    check = _checker(lambda c: {"error": None, "width": 1300, "height": 80} if c == chain else OK)
    plan_diagrams(llm, "f", "a", 2, check=check)
    assert "flowchart TD" in llm.prompts[1]


def test_timeline_periods_must_be_in_order_and_distinct():
    shuffled = "timeline\n 2019-2026 : Strategy\n Jan 2026 : Framework\n 2024-2025 : Series A"
    assert "order" in size_problem(shuffled)
    repeated = "timeline\n 2025 : Sandbox\n 2026 : Framework\n 2026 : Funding"
    assert "2026" in size_problem(repeated) and "more than once" in size_problem(repeated)
    assert size_problem("timeline\n 2023 : Pilots\n Jan 2026 : Framework\n Jun 2026 : Update") is None


def test_timeline_months_within_a_year_must_be_in_order_too():
    assert "order" in size_problem("timeline\n 2025 : Sandbox\n Jun 2026 : MGF published\n May 2026 : MGF updated")
    assert size_problem("timeline\n 2025 : Sandbox\n Jan 2026 : MGF published\n 20 May 2026 : MGF updated") is None
