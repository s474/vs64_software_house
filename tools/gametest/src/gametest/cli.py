"""The command line of a game's behaviour script: --prg, --only, --list, --results."""

from __future__ import annotations

import argparse
import datetime
import sys
from collections.abc import Callable
from pathlib import Path

from .cases import Suite


def run_cli(suite: Suite, *, make_rig: Callable[[Path], object], default_prg: Path | str, guard: Callable | None = None,
            results_header: str = "", argv: list[str] | None = None) -> int:
    """Parse the arguments and run the suite; returns the exit code (the script does sys.exit(...)).

    make_rig(prg) -> a Rig (opened on the first case that needs it).
    --results FILE writes a comment line saying how the file was made (the command line and the date, or
    `results_header` if given) and every line printed, so a results file is what the script printed, not
    hand-copied.
    """
    ap = argparse.ArgumentParser(description=f"{suite.name}: behaviour checks in headless VICE")
    ap.add_argument("--prg", default=str(default_prg), help="the build to run (default: %(default)s)")
    ap.add_argument("--only", nargs="+", metavar="CASE", help="run only these cases (see --list)")
    ap.add_argument("--list", action="store_true", help="print the case names and exit")
    ap.add_argument("--results", metavar="FILE", help="also write the output to FILE")
    a = ap.parse_args(argv)
    if a.list:
        for c in suite.cases:
            print(c.name + (f"  (needs {c.needs})" if c.needs else ""))
        return 0
    lines: list[str] = []

    def out(s: str) -> None:
        lines.append(s)
        print(s, flush=True)

    code, _ = suite.run(lambda: make_rig(Path(a.prg)), guard=guard, only=a.only, out=out)
    if a.results:
        used = argv if argv is not None else sys.argv[1:]
        header = results_header or f"# python {Path(sys.argv[0]).as_posix()} {' '.join(used)}  ({datetime.date.today()})"
        Path(a.results).write_text(header.rstrip() + "\n" + "\n".join(lines) + "\n")
    return code
