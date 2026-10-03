"""The case registry and runner: cases as top-level functions, run in registration order.

    suite = Suite("swarm")

    @suite.case("title", needs="title")
    def title(t):                       # t is the rig (or a Bare for a case registered with rig=False)
        ...
        t.rep("title", ok, "what was seen")      # PASS/FAIL line; a case may report several

A case's `needs` is a word the game's CLEAN-STATE GUARD understands ("play", "title", ... or None for
"no requirement"). Before each case the runner calls guard(t, case); the guard asserts (or restores)
the known state and reports what is wrong by raising GuardError or returning a list of problems. A
case whose state came from the case before it then FAILS LOUDLY ("[FAIL] guard:name: needs 'play': ...")
instead of passing on leftovers; the fix belongs in the case (put its own start state in place). The case
still runs after a guard failure (so one dirty start doesn't hide the rest of the chain), unless
Suite.run(skip_on_guard_failure=True).

A case that raises (a jam, a missing label, a bug in the script) stops the run: the machine's state is
unknown. Exit codes of Suite.run: 0 all pass, 1 any FAIL, 2 aborted by an error.
"""

from __future__ import annotations

import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field

from budget_runner.session import MeasureError


class GuardError(Exception):
    """The clean-state guard found the game in a state the case does not accept."""


@dataclass
class Result:
    name: str
    ok: bool
    text: str
    case: str = ""

    def line(self) -> str:
        return f"[{'PASS' if self.ok else 'FAIL'}] {self.name}: {self.text}"


@dataclass
class Case:
    name: str
    fn: Callable
    needs: str | None = None
    rig: bool = True          # False: runs without the rig (it starts its own emulator); t is a Bare


class Handoff:
    """Values one case hands to a later one (rig.ns): plain attributes, with a clear error when the case that
    makes a value didn't run (--only) instead of an AttributeError from deep in a case."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise GuardError(f"{name!r} was never handed over: the earlier case that makes it did not run "
                         f"(a case that builds on another can't be run alone with --only)")


class Bare:
    """What a rig-less case gets as `t`: just rep()."""

    def __init__(self, rep):
        self.rep = rep


@dataclass
class Suite:
    name: str
    cases: list[Case] = field(default_factory=list)

    def case(self, name: str | None = None, *, needs: str | None = None, rig: bool = True):
        """Register a function as a case (decorator). Names must be unique."""
        def deco(fn):
            n = name or fn.__name__.replace("_", "-")
            if any(c.name == n for c in self.cases):
                raise ValueError(f"case {n!r} registered twice")
            self.cases.append(Case(n, fn, needs, rig))
            return fn
        return deco

    def names(self) -> list[str]:
        return [c.name for c in self.cases]

    def run(self, open_rig: Callable[[], object], *, guard: Callable | None = None, only: list[str] | None = None,
            skip_on_guard_failure: bool = False, out: Callable[[str], None] | None = None) -> tuple[int, list[Result]]:
        """Run the cases in order. open_rig() makes the rig on the first case that needs it (it is closed
        at the end); guard(t, case) runs before every rig case. Returns (exit code, results).
        `only`: names of the cases to run (the rest are skipped; a later case may then fail its guard)."""
        say = out or (lambda s: print(s, flush=True))
        results: list[Result] = []
        unknown = [n for n in (only or []) if n not in self.names()]
        if unknown:
            raise ValueError(f"unknown case(s) {unknown}; known: {self.names()}")
        current = ""

        def rep(name, ok, text):
            r = Result(name, bool(ok), text, current)
            results.append(r)
            say(r.line())

        rig = None
        code = 0
        try:
            for case in self.cases:
                if only and case.name not in only:
                    continue
                current = case.name
                if case.rig:
                    if rig is None:
                        rig = open_rig()
                        rig.rep = rep
                    t = rig
                    if guard is not None:
                        try:
                            problems = guard(t, case)
                        except GuardError as e:
                            problems = [str(e)]
                        if problems:
                            rep("guard:" + case.name, False, f"clean-state guard (needs {case.needs!r}): "
                                + "; ".join(problems))
                            if skip_on_guard_failure:
                                continue
                else:
                    t = Bare(rep)
                case.fn(t)
        except GuardError as e:
            say(f"FAIL (state) in case {current!r}: {e}")
            code = 2
        except MeasureError as e:
            say(f"FAIL (jam/hang) in case {current!r}: {e}")
            code = 2
        except Exception:
            say(f"FAIL (error in case {current!r}):\n{traceback.format_exc().rstrip()}")
            code = 2
        finally:
            if rig is not None:
                rig.close()
        failed = [r.name for r in results if not r.ok]
        if code == 0 and failed:
            code = 1
        say("\nFAILED: " + ", ".join(failed) if failed else ("\nALL PASS" if code == 0 else "\nABORTED"))
        return code, results
