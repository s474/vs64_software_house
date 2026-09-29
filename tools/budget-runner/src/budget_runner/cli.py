"""budget-runner: build every tests/**/budget.json spike, run it in VICE, check the budgets.

    uv run budget-runner [--no-build] [SPIKE_OR_PATH ...]      (or: make test)

Exit status: 0 all checks passed; 1 a check failed or could not be measured;
2 a budget file is malformed or the selection matched nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .evaluate import Result, format_result
from .spec import REPO, Budget, BudgetError, find_budgets, load_budget


def missing_source(budget: Budget) -> Path | None:
    """The spike's main.asm if it does not exist yet (its budget was written ahead of the code)."""
    main = REPO / budget.src_dir / "main.asm"
    return None if main.exists() else main


def run_budget(budget: Budget, do_build: bool) -> list[Result]:
    from . import session  # imports the VICE client; kept out of module load so tests need no VICE

    try:
        prg = session.build(budget) if do_build else REPO / "build" / budget.spike / f"{budget.spike}.prg"
        vice = session.Vice(prg, budget.warmup_frames)
    except Exception as e:  # build failure, VICE not installed, program never started
        return [Result(c, error=str(e)) for c in budget.checks]
    try:
        return [vice.run(c) for c in budget.checks]
    finally:
        vice.close()


def report(budget: Budget, results: list[Result], out=sys.stdout) -> None:
    width = max(len(c.name) for c in budget.checks)
    for r in results:
        print(format_result(budget.spike, r, width), file=out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="budget-runner", description=__doc__.split("\n\n")[0])
    ap.add_argument("select", nargs="*", help="spike name or budget.json path (default: all)")
    ap.add_argument("--strict", action="store_true",
                    help="treat a spike whose main.asm does not exist yet as a failure, not a skip")
    ap.add_argument("--no-build", action="store_true", help="use the existing build/<spike>/<spike>.prg")
    a = ap.parse_args(argv)
    try:
        budgets = [load_budget(p) for p in find_budgets(REPO, a.select)]
    except BudgetError as e:
        print(f"budget-runner: error: {e}", file=sys.stderr)
        return 2
    if not budgets:
        print("budget-runner: error: no tests/**/budget.json files found", file=sys.stderr)
        return 2
    total = failed = skipped = 0
    for b in budgets:
        absent = missing_source(b)
        if absent and not a.strict:
            print(f"{b.spike}  SKIP  {absent.relative_to(REPO)} does not exist yet ({len(b.checks)} checks not run)")
            skipped += 1
            continue
        results = run_budget(b, not a.no_build)
        report(b, results)
        total += len(results)
        failed += sum(not r.passed for r in results)
    ran = len(budgets) - skipped
    print(f"budget-runner: {total - failed}/{total} checks passed" + (f", {failed} FAILED" if failed else "")
          + f" ({ran} spike{'s' if ran != 1 else ''} run" + (f", {skipped} skipped: no source yet" if skipped else "") + ")")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
