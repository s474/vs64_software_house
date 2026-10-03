"""Build a game for a test: the DEBUG build (budget_runner's build_program) or the release build."""

from __future__ import annotations

import subprocess
from pathlib import Path

from budget_runner.session import MeasureError, build_program
from budget_runner.spec import REPO

__all__ = ["build_game", "prg_path"]


def prg_path(game: str, release: bool = False) -> Path:
    """Where the Makefile puts the PRG: build/<game>/<game>.prg, or build/<game>-release/ for a release."""
    return REPO / "build" / (f"{game}-release" if release else game) / f"{game}.prg"


def build_game(game: str, release: bool = False, src_dir: str | None = None) -> Path:
    """make GAME=<game> [BUILD=release] [SRC_DIR=...]; returns the PRG. Raises MeasureError if make fails."""
    if not release:
        return build_program(game, src_dir)
    args = ["BUILD=release", f"GAME={game}"] + ([f"SRC_DIR={src_dir}"] if src_dir else [])
    proc = subprocess.run(["make", "-s", *args], cwd=REPO, capture_output=True, text=True)
    if proc.returncode:
        raise MeasureError(f"build failed (make {' '.join(args)}):\n" + (proc.stdout + proc.stderr).strip())
    prg = prg_path(game, True)
    if not prg.exists():
        raise MeasureError(f"build produced no {prg}")
    return prg
