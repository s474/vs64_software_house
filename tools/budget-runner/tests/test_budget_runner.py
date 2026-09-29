import json

import pytest

from budget_runner.evaluate import (
    FRAME, Event, Result, eval_irq_time, eval_memory, eval_profile, eval_start_cycle,
    format_result, irq_time_by_frame, irq_spans, profile_costs, union_length,
)
from budget_runner.spec import BudgetError, find_budgets, load_budget, parse_check
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def check(**kw):
    raw = {"name": "c", "basis": "measured", "source": "src"} | kw
    return parse_check(Path("b.json"), 0, raw)


# -- parsing -----------------------------------------------------------------


def test_kind_defaults_to_profile_and_samples_to_50():
    c = check(routine=["a", "b"], max_cycles=10)
    assert c.kind == "profile" and c.params["samples"] == 50


def test_start_cycle_defaults():
    c = check(kind="start_cycle", label="x", line=32, max_spread=7)
    assert c.params["frames"] == 100 and c.params["max_cycle"] is None


@pytest.mark.parametrize("raw, message", [
    ({"kind": "bogus"}, "unknown kind 'bogus'"),
    ({"kind": "profile", "routine": ["a", "b"]}, "needs 'max_cycles'"),
    ({"kind": "profile", "routine": ["a"], "max_cycles": 1}, "'routine' must be"),
    ({"kind": "profile", "routine": ["a", "b"], "max_cycles": 1, "typo": 1}, "unknown field.s. typo"),
    ({"kind": "profile", "routine": ["a", "b"], "max_cycles": -1}, "'max_cycles' must be"),
    ({"kind": "memory", "address": "x", "size": 1, "after_frames": 1}, "exactly one of"),
    ({"kind": "memory", "address": "x", "size": 3, "after_frames": 1, "equals": 0}, "'size' must be 1 or 2"),
    ({"kind": "profile", "routine": ["a", "b"], "max_cycles": 1, "basis": "guess"}, "'basis' must be"),
])
def test_bad_checks_are_rejected_with_file_and_check(raw, message):
    with pytest.raises(BudgetError, match=message) as e:
        check(**raw)
    assert "b.json: check #1 ('c')" in str(e.value)


def test_memory_comparison_recorded():
    c = check(kind="memory", address="x", size=2, after_frames=5, max=3)
    assert c.params["comparison"] == "max" and c.params["max"] == 3 and c.params["scale"] == 1


def test_load_budget_errors_name_the_file(tmp_path):
    p = tmp_path / "budget.json"
    p.write_text("{nope")
    with pytest.raises(BudgetError, match=r"budget\.json: invalid JSON"):
        load_budget(p)
    p.write_text(json.dumps({"spike": "s", "src_dir": "d", "checks": []}))
    with pytest.raises(BudgetError, match="non-empty"):
        load_budget(p)
    p.write_text(json.dumps({"spike": "s", "checks": [{}]}))
    with pytest.raises(BudgetError, match="missing 'src_dir'"):
        load_budget(p)


def test_committed_budget_files_parse():
    budgets = find_budgets(REPO, [])
    assert any(b.parent.name == "irq_chain" for b in budgets)
    for b in budgets:
        assert load_budget(b).checks


def test_find_budgets_selector(tmp_path):
    assert [p.parent.name for p in find_budgets(REPO, ["irq_chain"])] == ["irq_chain"]
    with pytest.raises(BudgetError, match="no budget.json matches 'nope'"):
        find_budgets(REPO, ["nope"])


# -- measurement arithmetic --------------------------------------------------

A, B, D, R = 0x1000, 0x1100, 0x2000, 0x2100


def ev(pc, t):
    return Event(pc, t, t // 63 % 312, t % 63)


def test_profile_costs_pair_start_with_next_end():
    events = [ev(A, 100), ev(B, 117), ev(B, 120), ev(A, 500), ev(A, 510), ev(B, 530)]
    assert profile_costs(events, A, B) == [17, 20]  # a second start restarts the pass


def test_profile_excl_irq_subtracts_nested_irq_only():
    # routine A..B runs 100..300; an IRQ inside (dispatch at 150 -> span 143..(200+6)=206) costs 63
    nested = [ev(A, 100), ev(D, 150), ev(R, 200), ev(B, 300)]
    assert profile_costs(nested, A, B) == [200]
    assert profile_costs(nested, A, B, D, R) == [200 - (206 - 143)]
    # the routine running inside an IRQ that began before it is not subtracted
    inside = [ev(D, 50), ev(A, 100), ev(B, 300), ev(R, 320)]
    assert profile_costs(inside, A, B, D, R) == [200]


def test_nested_irqs_are_counted_once():
    events = [ev(D, 100), ev(D, 120), ev(R, 140), ev(R, 160)]
    spans = irq_spans(events, D, R)
    assert spans == [(93, 166), (113, 146)]  # stack pairing: inner first
    assert union_length(spans) == (160 + 6) - (100 - 7)


def test_irq_time_per_frame_uses_whole_frames_only():
    def span(frame, start):  # dispatch at frame*FRAME+start, rti 50 later: span = 50 + 7 + 6
        return [ev(D, frame * FRAME + start), ev(R, frame * FRAME + start + 50)]
    events = span(0, 10000) + span(1, 2000) + span(1, 5000) + span(2, 2000) + span(3, 2000)
    # frame 0 is partial and dropped; frame 3 is the "next" frame proving frame 2 complete
    assert irq_time_by_frame(events, D, R, 2) == [2 * 63, 63]


# -- evaluation and report ---------------------------------------------------


def test_profile_pass_and_fail():
    c = check(routine=["a", "b"], max_cycles=17)
    assert eval_profile(c, [17, 17]).passed
    r = eval_profile(c, [17, 18])
    assert not r.passed and r.parts[0].value == 18


def test_profile_no_passes_is_an_error():
    r = eval_profile(check(routine=["a", "b"], max_cycles=17), [])
    assert not r.passed and r.error


def test_start_cycle_spread_max_and_line():
    c = check(kind="start_cycle", label="h", line=32, max_spread=7, max_cycle=41)
    ok = [Event(1, 0, 32, 34), Event(1, 0, 32, 41)]
    assert eval_start_cycle(c, ok).passed
    assert not eval_start_cycle(c, [Event(1, 0, 32, 34), Event(1, 0, 32, 42)]).passed  # max cycle
    assert not eval_start_cycle(c, [Event(1, 0, 32, 30), Event(1, 0, 32, 38)]).passed  # spread 8
    assert not eval_start_cycle(c, ok + [Event(1, 0, 33, 35)]).passed  # a hit on another line
    assert eval_start_cycle(c, []).error


def test_memory_comparisons_and_scale():
    assert eval_memory(check(kind="memory", address="n", size=1, after_frames=1, equals=0), 0).passed
    assert not eval_memory(check(kind="memory", address="n", size=1, after_frames=1, equals=0), 1).passed
    m = check(kind="memory", address="n", size=2, after_frames=1, max=100, scale=2)
    assert eval_memory(m, 50).passed and not eval_memory(m, 51).passed
    assert eval_memory(check(kind="memory", address="n", size=1, after_frames=1, min=3), 3).passed


def test_irq_time_evaluation():
    c = check(kind="irq_time_per_frame", max_cycles=508, frames=2)
    assert eval_irq_time(c, [501, 508]).passed
    assert not eval_irq_time(c, [501, 509]).passed
    assert eval_irq_time(c, [0, 0]).error


def test_report_lines():
    c = check(name="irq_dispatch overhead", routine=["a", "b"], max_cycles=17)
    line = format_result("irq_chain", eval_profile(c, [17]), 22)
    assert line == "irq_chain  irq_dispatch overhead   max 17 / budget 17  PASS  (measured)"
    bad = format_result("irq_chain", eval_profile(c, [17, 21]), 22)
    first, *rest = bad.splitlines()
    assert "max 21 / budget 17  FAIL  (measured)" in first
    assert any("over the budget of 17 by 4" in x for x in rest)
    assert any("budget source: src" in x for x in rest)


def test_report_error_and_thousands_separators():
    c = check(routine=["a", "b"], max_cycles=1500)
    assert "1,137 / budget 1,500" in format_result("m", eval_profile(c, [1137]), 1)
    out = format_result("m", Result(c, error="build failed"), 1)
    assert "FAIL" in out and "error: build failed" in out
