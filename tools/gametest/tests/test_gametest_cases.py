"""Suite / guard / cli tests with a fake rig (no VICE)."""

import pytest

from budget_runner.session import MeasureError
from gametest import GuardError, Handoff, Suite, run_cli


class FakeRig:
    def __init__(self):
        self.closed, self.state, self.rep, self.ns = False, "clean", None, Handoff()

    def close(self):
        self.closed = True


def run(suite, **kw):
    lines, rigs = [], []

    def open_rig():
        rigs.append(FakeRig())
        return rigs[-1]
    code, results = suite.run(open_rig, out=lines.append, **kw)
    return code, results, lines, rigs


def test_cases_run_in_order_and_report():
    s = Suite("g")

    @s.case("a")
    def a(t): t.rep("a", True, "fine")

    @s.case()
    def second_case(t):
        t.rep("b1", True, "x")
        t.rep("b2", False, "bad")
    code, results, lines, rigs = run(s)
    assert code == 1 and [r.name for r in results] == ["a", "b1", "b2"]
    assert [r.case for r in results] == ["a", "second-case", "second-case"]
    assert lines[0] == "[PASS] a: fine" and lines[2] == "[FAIL] b2: bad"
    assert lines[-1] == "\nFAILED: b2" and rigs[0].closed


def test_all_pass_is_exit_0():
    s = Suite("g")
    s.case("a")(lambda t: t.rep("a", True, ""))
    code, _, lines, _ = run(s)
    assert code == 0 and lines[-1] == "\nALL PASS"


def test_duplicate_case_name_rejected():
    s = Suite("g")
    s.case("a")(lambda t: None)
    with pytest.raises(ValueError, match="twice"):
        s.case("a")(lambda t: None)


def test_rig_is_opened_lazily_and_rigless_cases_do_not_open_it():
    s = Suite("g")
    s.case("solo", rig=False)(lambda t: t.rep("solo", True, "own emulator"))
    code, _, _, rigs = run(s)
    assert code == 0 and rigs == []


def test_guard_failure_is_reported_and_the_case_still_runs():
    s = Suite("g")
    ran = []
    s.case("dirty-start", needs="quiet")(lambda t: ran.append("dirty"))
    s.case("fine", needs="quiet")(lambda t: (ran.append("fine"), t.rep("fine", True, "")))

    def guard(t, case):
        if case.name == "dirty-start":
            return ["explosion 2 still running", "divers active 1"]
    code, results, lines, _ = run(s, guard=guard)
    assert code == 1 and ran == ["dirty", "fine"]
    assert lines[0].startswith("[FAIL] guard:dirty-start: clean-state guard (needs 'quiet'): explosion 2 still running; divers")
    code, _, lines, _ = run(s, guard=guard, skip_on_guard_failure=True)
    assert code == 1 and ran[2:] == ["fine"]


def test_guard_can_restore_and_raise():
    s = Suite("g")
    s.case("a")(lambda t: t.rep("a", t.state == "clean", ""))

    def guard(t, case):
        t.state = "clean"              # restoring is allowed: nothing reported
    assert run(s, guard=guard)[0] == 0

    def guard2(t, case):
        raise GuardError("not at the title")
    code, _, lines, _ = run(s, guard=guard2)
    assert code == 1 and "not at the title" in lines[0]


def test_an_exception_aborts_with_exit_2_and_closes_the_rig():
    s = Suite("g")
    s.case("boom")(lambda t: (_ for _ in ()).throw(MeasureError("frame not reached")))
    s.case("never")(lambda t: t.rep("never", True, ""))
    code, results, lines, rigs = run(s)
    assert code == 2 and results == [] and rigs[0].closed
    assert "FAIL (jam/hang) in case 'boom': frame not reached" in lines[0] and lines[-1] == "\nABORTED"

    s2 = Suite("g")
    s2.case("bug")(lambda t: 1 / 0)
    code, _, lines, _ = run(s2)
    assert code == 2 and "ZeroDivisionError" in lines[0]


def test_only_runs_the_named_cases_and_rejects_unknown_ones():
    s = Suite("g")
    s.case("a")(lambda t: t.rep("a", True, ""))
    s.case("b")(lambda t: t.rep("b", True, ""))
    _, results, _, _ = run(s, only=["b"])
    assert [r.name for r in results] == ["b"]
    with pytest.raises(ValueError, match="unknown case"):
        run(s, only=["c"])


def test_cli_writes_results_and_lists(tmp_path, capsys):
    s = Suite("g")
    s.case("a", needs="play")(lambda t: t.rep("a", True, "ok"))
    out = tmp_path / "r.txt"
    code = run_cli(s, make_rig=lambda prg: FakeRig(), default_prg="x.prg", results_header="# header",
                   argv=["--results", str(out)])
    assert code == 0
    assert out.read_text() == "# header\n[PASS] a: ok\n\nALL PASS\n"
    out2 = tmp_path / "r2.txt"
    run_cli(s, make_rig=lambda prg: FakeRig(), default_prg="x.prg", argv=["--results", str(out2)])
    first = out2.read_text().splitlines()[0]
    assert first.startswith("# python ") and "--results" in first and first.endswith(")")
    assert run_cli(s, make_rig=None, default_prg="x.prg", argv=["--list"]) == 0
    assert "a  (needs play)" in capsys.readouterr().out


def test_handoff_carries_values_and_explains_a_missing_one():
    ns = Handoff()
    ns.first = 3
    assert ns.first == 3
    with pytest.raises(GuardError, match="'second' was never handed over"):
        ns.second

    s = Suite("g")
    s.case("needs-earlier")(lambda t: t.ns.first)
    code, _, lines, _ = run(s)
    assert code == 2 and "FAIL (state) in case 'needs-earlier'" in lines[0]
