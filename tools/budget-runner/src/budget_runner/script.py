"""The `script` check kind: run a command from the repo root, pass if it exits 0.

For behaviour checks `make test` cannot make itself (pressing joystick buttons, reading state
after a scripted play): tests/engine/input/check.py, tests/games/swarm/check.py. No VICE is
started by the runner for it; the script starts its own (on a free port, so it can run beside one).
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from .evaluate import Part, Result
from .spec import REPO, Check

TAIL_LINES = 12  # lines of output kept for a failing script
DETAIL_WIDTH = 100  # characters of the last output line shown on the result line


def command_argv(check: Check, prg: Path) -> list[str]:
    """The command as an argument list, with {prg} replaced by the program's repo-relative path."""
    cmd = check.params["command"]
    argv = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
    rel = str(prg.relative_to(REPO)) if prg.is_relative_to(REPO) else str(prg)
    return [a.replace("{prg}", rel) for a in argv]


def last_line(text: str) -> str:
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    line = lines[-1] if lines else ""
    return line if len(line) <= DETAIL_WIDTH else line[: DETAIL_WIDTH - 3] + "..."


def run_script(check: Check, prg: Path, spike: str) -> Result:
    """Run the check's command; the result is a pass if it exits 0 within its timeout."""
    argv = command_argv(check, prg)
    timeout = check.params["timeout"]
    env = dict(os.environ, BUDGET_PRG=str(prg), BUDGET_SPIKE=spike)
    try:
        proc = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return Result(check, error=f"timed out after {timeout} s: {' '.join(argv)}")
    except OSError as e:
        return Result(check, error=f"could not run {argv[0]!r}: {e}")
    text = (proc.stdout + proc.stderr).rstrip()
    shown = last_line(proc.stdout) or last_line(proc.stderr)
    tail = "\n".join(text.splitlines()[-TAIL_LINES:])
    return Result(check, [Part("exit code", proc.returncode, "==", 0)], detail=shown,
                  output="" if proc.returncode == 0 else f"$ {shlex.join(argv)}\n{tail}")
