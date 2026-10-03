"""budget-runner: build every tests/**/budget.json spike, run it in VICE, check the budgets.

    uv run budget-runner [--no-build] [--scale N] [-v] [SPIKE_OR_PATH ...]      (or: make test / make test-long)

Exit status: 0 all checks passed (checks for a later build stage are PENDING and don't fail,
except under --strict); 1 a check failed or could not be measured; 2 a budget file is malformed
or the selection matched nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .evaluate import Result, format_result
from .spec import REPO, Budget, BudgetError, find_budgets, load_budget, scaled


def missing_source(budget: Budget) -> Path | None:
    """The spike's main.asm if it does not exist yet (its budget was written ahead of the code)."""
    main = REPO / budget.src_dir / "main.asm"
    return None if main.exists() else main


def pending_result(budget: Budget, check, strict: bool = False) -> Result:
    """A check for a later build stage: PENDING normally, a failure under --strict (sign-off)."""
    why = f"stage {check.from_stage} check, spike is at stage {budget.stage}"
    return Result(check, error=f"{why} (--strict: every stage must be done)") if strict else Result(check, pending=why)


def run_script_check(budget: Budget, check, prg: Path | None, build_error: str | None, do_build: bool) -> Result:
    """A `script` check. Its own `build` (another program, e.g. the game itself) is made first."""
    from . import session
    from .script import run_script

    spec = check.params["build"]
    try:
        if spec:
            game = spec["game"]
            if do_build:
                assets = spec.get("asset_dir")
                prg = session.build_program(game, spec.get("src_dir"), [assets] if isinstance(assets, str) else assets)
            else:
                prg = REPO / "build" / game / f"{game}.prg"
        elif prg is None:
            return Result(check, error=build_error or "the spike has no PRG")
    except Exception as e:
        return Result(check, error=str(e))
    return run_script(check, prg, budget.spike)


def run_budget(budget: Budget, do_build: bool, strict: bool = False) -> list[Result]:
    from . import session  # imports the VICE client; kept out of module load so tests need no VICE

    vice = error = prg = None
    try:
        prg = session.build(budget) if do_build else REPO / "build" / budget.spike / f"{budget.spike}.prg"
        if any(c.kind != "script" and not budget.pending(c) for c in budget.checks):  # scripts need no runner VICE
            vice = session.Vice(prg, budget.warmup_frames)
    except Exception as e:  # build failure, VICE not installed, program never started
        error = str(e)

    def one(c) -> Result:
        if budget.pending(c):  # a pending check runs no frames, so later memory checks see the same frames
            return pending_result(budget, c, strict)
        if c.kind == "script":
            return run_script_check(budget, c, prg, error, do_build)
        return Result(c, error=error) if vice is None else vice.run(c)

    try:
        return [one(c) for c in budget.checks]
    finally:
        if vice:
            vice.close()


def report(budget: Budget, results: list[Result], out=None, verbose: bool = False) -> None:
    out = out or sys.stdout  # looked up per call, not at import
    width = max(len(c.name) for c in budget.checks)
    for r in results:
        print(format_result(budget.spike, r, width, verbose), file=out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="budget-runner", description=__doc__.split("\n\n")[0])
    ap.add_argument("select", nargs="*", metavar="SPIKE",
                    help="directory name (swarm), spike name (swarm_budget) or budget.json path; default: all")
    ap.add_argument("--strict", action="store_true",
                    help="treat a spike whose main.asm does not exist yet, and a check pending a later "
                         "build stage, as a failure")
    ap.add_argument("-v", "--premise", action="store_true",
                    help="under every profile check, print where on the raster its passes started and "
                         "ended and how many IRQs fired inside them (always shown for a check with a "
                         "start_line_max / irqs_inside_max limit)")
    ap.add_argument("--no-build", action="store_true", help="use the existing build/<spike>/<spike>.prg")
    ap.add_argument("--scale", type=int, default=1, metavar="N",
                    help="long run: multiply every check's samples / frames / after_frames by N "
                         "(limits and warm-up unchanged; make test-long)")
    a = ap.parse_args(argv)
    if a.scale < 1:
        ap.error("--scale must be >= 1")
    try:
        budgets = [scaled(load_budget(p), a.scale) for p in find_budgets(REPO, a.select)]
    except BudgetError as e:
        print(f"budget-runner: error: {e}", file=sys.stderr)
        return 2
    if not budgets:
        print("budget-runner: error: no tests/**/budget.json files found", file=sys.stderr)
        return 2
    total = failed = skipped = pending = 0
    for b in budgets:
        absent = missing_source(b)
        if absent and not a.strict:
            print(f"{b.spike}  SKIP  {absent.relative_to(REPO)} does not exist yet ({len(b.checks)} checks not run)")
            skipped += 1
            continue
        results = run_budget(b, not a.no_build, a.strict)
        report(b, results, verbose=a.premise)
        waiting = sum(r.pending is not None for r in results)
        pending += waiting
        total += len(results) - waiting
        failed += sum(not r.passed and r.pending is None for r in results)
    ran = len(budgets) - skipped
    print(f"budget-runner: {total - failed}/{total} checks passed" + (f", {failed} FAILED" if failed else "")
          + (f", {pending} pending a later stage" if pending else "")
          + f" ({ran} spike{'s' if ran != 1 else ''} run" + (f", long run x{a.scale}" if a.scale > 1 else "") + (f", {skipped} skipped: no source yet" if skipped else "") + ")")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
