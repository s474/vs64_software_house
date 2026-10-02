"""release-check GAME: verify dist/<GAME>/ (built by `make release GAME=<GAME>`).

Run:  make test-release GAME=swarm   (builds the release first)
      uv run --package release-check release-check swarm [--text "PRESS FIRE"] [--mem zp_game_state=4]

Checks, in order (exit 1 and a message naming the file and the rule on the first failure):
  1. dist/<GAME>/<GAME>.d64 exists and `c1541 -list` shows one PRG named <GAME> (upper case),
     and the disk is named <GAME>.
  2. The crunched PRG is smaller than the raw PRG and starts with a BASIC SYS line.
  3. A fresh headless x64sc (own monitor port, warp, killed at the end) autostarts the d64
     (LOAD"*",8,1 + RUN, true drive) and the title screen appears: the expected text is in screen
     memory ($0400) in screen codes and every --mem label=value holds (labels from dist/<GAME>/main.vs).
  4. The same for the crunched PRG run directly.
Frames are PAL frames counted from VICE's start (so they include the ~100-frame KERNAL boot).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "mcp" / "vice"))

# Per-game defaults: what "reached the title" means. A game not listed must pass --text.
GAMES = {"swarm": {"text": "PRESS FIRE", "mem": {"zp_game_state": 4}}}

MAX_FRAMES = 6000  # a floppy load of ~16 KB takes ~1500 frames with the true drive


class CheckError(Exception):
    pass


def screen_codes(text: str) -> bytes:
    """Upper-case PETSCII text as screen codes (A=1 ... Z=26, digits and punctuation unchanged)."""
    return bytes((ord(c) - 64) if "A" <= c <= "Z" else ord(c) for c in text.upper())


def parse_directory(listing: str) -> tuple[str, list[tuple[int, str, str]]]:
    """Parse `c1541 -list` output into (disk name, [(blocks, file name, type)])."""
    lines = listing.splitlines()  # c1541 prints some chatter first; the header is the line starting 0 "
    start = next((i for i, ln in enumerate(lines) if re.match(r'\s*0\s+"', ln)), None)
    if start is None:
        raise CheckError(f"cannot read the disk header from c1541 -list output: {listing!r}")
    m = re.match(r'\s*0\s+"(.*?)"', lines[start])
    files = []
    for ln in lines[start + 1:]:
        fm = re.match(r'\s*(\d+)\s+"(.*?)"\s+(\w+)', ln)
        if fm:
            files.append((int(fm.group(1)), fm.group(2), fm.group(3).lower()))
    return m.group(1).strip(), files


def check_disk(d64: Path, game: str, c1541: str = "c1541") -> int:
    if not d64.exists():
        raise CheckError(f"{d64}: missing (run make release GAME={game})")
    out = subprocess.run([c1541, str(d64), "-list"], capture_output=True, text=True)
    if out.returncode:
        raise CheckError(f"{d64}: c1541 -list failed: {out.stderr.strip()}")
    name, files = parse_directory(out.stdout)
    want = game.upper()
    if name != want:
        raise CheckError(f"{d64}: disk name is {name!r}, expected {want!r}")
    if [(f, t) for _, f, t in files] != [(want, "prg")]:
        raise CheckError(f"{d64}: directory is {files}, expected one PRG named {want!r}")
    return files[0][0]


def check_prgs(raw: Path, sfx: Path) -> tuple[int, int]:
    for p in (raw, sfx):
        if not p.exists():
            raise CheckError(f"{p}: missing")
    a, b = raw.read_bytes(), sfx.read_bytes()
    if b[:2] != b"\x01\x08" or b"\x9e" not in b[6:20]:
        raise CheckError(f"{sfx}: does not start with a load address $0801 and a BASIC SYS line")
    if len(b) >= len(a):
        raise CheckError(f"{sfx}: {len(b)} bytes is not smaller than the raw PRG ({len(a)})")
    return len(a), len(b)


def boot(program: Path, symbols: dict[str, int], text: str, mem: dict[str, int]) -> int:
    """Autostart `program` in a fresh headless VICE; return the frame the title was first seen in."""
    from vice_monitor import ViceError, run_frames, start_vice

    proc, mon = start_vice(warp=True, show_window=False)
    try:
        mon.autostart(str(program), run=True)
        want = screen_codes(text)
        for frame in range(1, MAX_FRAMES + 1):
            run_frames(mon, 1)
            if frame % 2:  # every other frame is plenty; the blink is 32 frames
                continue
            screen = mon.mem_get(0x0400, 0x07E7)
            if want in screen and all(
                    mon.mem_get(symbols[k], symbols[k])[0] == v for k, v in mem.items()):
                return frame
        raise CheckError(f"{program}: title ({text!r}, {mem}) not seen within {MAX_FRAMES} frames")
    except ViceError as e:
        raise CheckError(f"{program}: VICE error: {e}") from e
    finally:
        try:
            mon.quit()
            mon.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="release-check", description=__doc__.split("\n")[0])
    ap.add_argument("game")
    ap.add_argument("--dist", type=Path, help="directory of the release files (default dist/<game>)")
    ap.add_argument("--text", help="text that must be on screen at the title (default: per game)")
    ap.add_argument("--mem", action="append", default=[], metavar="LABEL=VALUE",
                    help="byte that must hold at the title (label from main.vs); repeatable")
    ap.add_argument("--c1541", default="c1541")
    a = ap.parse_args(argv)

    dist = a.dist or REPO / "dist" / a.game
    d = GAMES.get(a.game, {})
    text = a.text or d.get("text")
    mem = dict(d.get("mem", {})) if not a.text else {}
    for m in a.mem:
        k, _, v = m.partition("=")
        mem[k] = int(v, 0)
    if not text:
        print(f"release-check: no title text known for {a.game}: pass --text", file=sys.stderr)
        return 2

    try:
        blocks = check_disk(dist / f"{a.game}.d64", a.game, a.c1541)
        raw, crunched = check_prgs(dist / f"{a.game}.prg", dist / f"{a.game}-sfx.prg")
        from vice_monitor import load_symbols
        symbols = load_symbols(dist / f"{a.game}.prg")
        missing = [k for k in mem if k not in symbols]
        if missing:
            raise CheckError(f"{dist}/main.vs: no label {missing}")
        f_disk = boot(dist / f"{a.game}.d64", symbols, text, mem)
        f_prg = boot(dist / f"{a.game}-sfx.prg", symbols, text, mem)
    except CheckError as e:
        print(f"release-check: FAIL: {e}", file=sys.stderr)
        return 1
    print(f"release-check: {a.game} OK: raw {raw} B, crunched {crunched} B, {blocks} blocks on disk; "
          f"title at frame {f_disk} from the d64, {f_prg} from the crunched PRG")
    return 0


if __name__ == "__main__":
    sys.exit(main())
