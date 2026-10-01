"""Sweep sprite_latch.prg: the last raster cycle at which a write to each sprite register still
takes effect on the sprite's first display line, and the earliest at which a hardware sprite can be
rewritten without marking the previous occupant's last line.

For every sample the script pokes the probe's configuration while the machine is stopped on line 0,
lets one frame run, and records:
  - where the stable handler started (must be line 102, cycle 6);
  - where the write landed: it stops at the probe's `sta`, steps over it and reads the raster
    position, which is then one cycle after the write (the write is the last cycle of `sta abs`).
    So the write cycle is measured for every sample, including when sprite DMA holds the CPU;
  - which raster lines of VICE's frame buffer show the sprite, and how. Each display line is
    compared with two reference frames taken with no write at all: OLD (the register never
    changes) and NEW (the register has the new value from the top of the frame).
A line is N (shows the new value), O (the old one: for Y and $D015 that means no sprite), or X
(neither: a sprite drawn partly in each state, or missing). Raster lines are mapped to buffer rows
with a reference character in text row 0, whose first row is raster line 51, the first badline
(measured: tests/timing/badline), as tests/timing/sprite_wrap/sweep.py does.

Test 1, LATCH (sprite at Y = 103: first display line 104; write swept from line 103 cycle 30 to
the end of line 104), per hardware sprite 0, 2, 3, 7 and for X = 24 and X = 320:
  Y      old Y 200, write Y = 103
  D015   old disabled, write the enable bit
  PTR    old pointer solid block, write the striped block
  XLO    X = 24: old X 56, write 24.    X = 320: old X 288 ($D010 bit set), write low byte $40
  D010   X = 24: old bit set (X 280), write clear.    X = 320: old clear (X 64), write set
  COL    old colour 1, write 7
  D01C   old hires, write multicolour (the striped block is solid in multicolour)
Test 2, FREE (the old occupant is the same sprite at Y = 103, displayed on 104-124; the write is
swept from before line 124 cycle 0 to the end of line 125, i.e. over Y_old + 21 and Y_old + 22;
the probe's coarse delay carries the handler the 22 lines, and the script picks it by measuring):
XLO, PTR and COL as above. The question is whether line 124 (Y_old + 21), or any line of the old
sprite, is marked. (The stable handler can't sit just above line 124: the sprite's own DMA on its
lines would un-stabilise it. That was tried first: starts on cycles 11 and 12, and holes in the sweep.)

"Cycle" is VICE's raster cycle (CYC, 0-62), as everywhere in docs/reference/vic-ii-timing.md.
Not every cycle can hold a write: while sprite DMA has the bus the CPU is stopped, and the script
lists the cycles in the swept range that no delay reached ("no write possible").

    make GAME=sprite_latch SRC_DIR=tests/timing/sprite_latch
    uv run python tests/timing/sprite_latch/sweep.py [--quick] [--sprites 0,2,3,7] [--verbose] \
        | tee tests/timing/sprite_latch/results.txt

--quick: sprite 0 only. --verbose: every write position with its 21-line pattern. A full run takes
about a minute. Exit code 1 if the stable handler ever started anywhere but line 102 cycle 6, or
irq_late_count is not 0.

RESULTS (2026-10-01, VICE 3.10 x64sc PAL, 13,590 samples, the stable handler on line 102 cycle 6 in
every one; full output in results.txt beside this file; the table is in
docs/reference/vic-ii-timing.md#sprite-register-write-deadlines). Last write cycle (of a `sta abs`)
at which line Y + 1 still shows the new value, "Y:c" = cycle c of line Y:

  register                 sprite 0    sprite 2    sprite 3    sprite 7     then
  Y, $D015 bit             Y:53        Y:54        Y:54        Y:54         no sprite this frame (sprite 0
                                                                            at Y:54: shown, first line corrupt)
  pointer                  Y:54        Y:58        Y:60        Y+1:05       line Y + 1 shows the old data
  X low, $D010 bit,        Y+1:15 for a sprite at X = 24, the same for every sprite; in general cycle
  colour, $D01C bit        12 + X / 8 of the line being drawn (X = 320: 52; old X 288: 48; old X 64: 20)

  The pointer figures are also the last cycle a write is possible at all before the fetch: the
  sprite's own DMA holds the CPU on Y:55-59 (sprite 0), Y:59-Y+1:00 (2), Y:61-Y+1:02 (3),
  Y+1:06-10 (7), and the first write after that is too late.
  FREE: a write to X low or colour marks the old occupant's last line (Y_old + 21) up to cycle
  12 + X / 8 + 3 of that line (X = 24: 18-19; X = 320: 55); a pointer write marks it up to the
  sprite's last data fetch (sprite 0: before the end of line Y_old + 20; sprite 7: Y_old + 21 cycle
  5). No write on line Y_old + 22 or later marks anything (swept to line Y_old + 23).
"""

import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "mcp" / "vice"))

from vice_monitor import (  # noqa: E402
    CMD_CHECKPOINT_TOGGLE, CPU_OP_EXEC, load_symbols, start_vice,
)

CPL = 63
Y = 103                     # the probed sprite's Y: 103 and 104 are not badlines
HANDLER = (102, 6)          # where probe_stable must start
BG, BORDER = 0, 11
OLD_COL, NEW_COL = 1, 7
REF_CHAR, REF_COLOUR, REF_LINE = 0x0427, 7, 51
LATCH_DELAYS = range(29, 144)   # write on cycle 64 + delay from the start of line 102 (+ DMA): 103:30 on
FREE_DELAYS = range(0, 256)     # after the coarse delay, which puts delay 0 on line 122
FREE_FROM = (Y + 21) * CPL      # line 124, cycle 0
TESTS = ["Y", "D015", "PTR", "XLO", "D010", "COL", "D01C"]
FREE_TESTS = ["XLO", "PTR", "COL"]


class Probe:
    def __init__(self) -> None:
        prg = REPO / "build" / "sprite_latch" / "sprite_latch.prg"
        self.sym = load_symbols(prg)
        self.proc, self.mon = start_vice(warp=True, show_window=False)
        mon, s = self.mon, self.sym
        mon.autostart(str(prg), run=True)
        self.cp_line0 = mon.checkpoint_set(s["probe_main"], s["probe_main"], CPU_OP_EXEC)
        mon.checkpoint_condition(self.cp_line0.number, "RL == $00")
        self._go()
        self._go()                              # a whole frame with the IRQs running
        self.cp_stable = mon.checkpoint_set(s["probe_stable"], s["probe_stable"], CPU_OP_EXEC)
        self.cp_write = mon.checkpoint_set(s["probe_write"], s["probe_write"], CPU_OP_EXEC)
        self.starts: dict[tuple[int, int], int] = {}
        self.samples = 0
        self.shift = 0                          # set below
        # Row mapping: a reversed space in text row 0, column 39: its first row is raster line 51.
        mon.mem_set(REF_CHAR, b"\xa0")
        mon.mem_set(REF_CHAR + 0xD400, bytes([REF_COLOUR]))
        self.sample({"d015": 0})
        d = mon.display_get()
        col = d.offset_x + 39 * 8 + 4
        rows = [r for r in range(d.height) if d.pixels[r * d.width + col] == REF_COLOUR]
        if len(rows) != 8:
            raise SystemExit(f"reference character not found (rows {rows})")
        self.shift = REF_LINE - rows[0]         # raster line = buffer row + shift
        mon.mem_set(REF_CHAR, b"\x20")
        self.starts.clear()
        self.samples = 0

    def close(self) -> None:
        self.mon.quit()
        self.mon.close()
        self.proc.wait(timeout=5)

    def _toggle(self, cp, on: bool) -> None:
        self.mon.request(CMD_CHECKPOINT_TOGGLE, struct.pack("<IB", cp.number, int(on)))

    def _go(self) -> dict[str, int]:
        self.mon.exit()
        if not self.mon.wait_stopped(5):
            raise SystemExit("timed out waiting for a checkpoint")
        return self.mon.registers()

    def sample(self, cfg: dict, write: tuple[int, int] | None = None, delay: int = 0, coarse: int = 0):
        """One frame. cfg: d015, d010, d01c, n, x, y, col, ptr. write: (address, value) or None.
        Returns (write position in cycles from line 0 or None, {raster line: signature})."""
        mon, s = self.mon, self.sym
        n = cfg.get("n", 0)
        xy = bytearray(16)
        xy[2 * n], xy[2 * n + 1] = cfg.get("x", 24) & 0xFF, cfg.get("y", Y)
        mon.mem_set(s["cfg_d015"], bytes([cfg.get("d015", 1 << n), cfg.get("d010", 0), cfg.get("d01c", 0)]))
        mon.mem_set(s["cfg_xy"], bytes(xy))
        mon.mem_set(s["cfg_col"], bytes([cfg.get("col", OLD_COL)] * 8))
        mon.mem_set(s["cfg_ptr"], bytes([cfg.get("ptr", s["PTR_STRIPE"])] * 8))
        addr, val = write if write else (s["cfg_dummy"], 0)
        mon.mem_set(s["cfg_coarse"], bytes([coarse, delay, val]))
        mon.mem_set(s["probe_write"] + 1, struct.pack("<H", addr))
        self._toggle(self.cp_line0, False)
        r = self._go()                          # probe_stable
        start = (r["LIN"], r["CYC"])
        self.starts[start] = self.starts.get(start, 0) + 1
        self._go()                              # probe_write
        mon.advance(1)
        r = mon.registers()
        if r["PC"] != s["probe_after"]:
            raise SystemExit(f"step over the write ended at ${r['PC']:04x}")
        wpos = r["LIN"] * CPL + r["CYC"] - 1
        self._toggle(self.cp_line0, True)
        self._go()                              # line 0 of the next frame: the buffer is complete
        self.samples += 1
        d = mon.display_get()
        sigs = {}
        for line in range(Y, Y + 24):
            row = d.pixels[(line - self.shift) * d.width:(line - self.shift + 1) * d.width]
            sigs[line] = tuple((c - d.offset_x + 24, p) for c, p in enumerate(row) if p not in (BG, BORDER))
        return (wpos if write else None), sigs


def test_setup(s: dict, test: str, n: int, p: int):
    """(old configuration, new configuration, write) for one register test on sprite n at X = p."""
    hi = 1 << n if p > 255 else 0
    base = {"n": n, "x": p, "d010": hi}
    if test == "Y":
        return {**base, "y": 200}, base, (0xD001 + 2 * n, Y)
    if test == "D015":
        return {**base, "d015": 0}, base, (0xD015, 1 << n)
    if test == "PTR":
        return {**base, "ptr": s["PTR_SOLID"]}, base, (0x07F8 + n, s["PTR_STRIPE"])
    if test == "XLO":
        old_x = 56 if p == 24 else 288
        return {**base, "x": old_x}, base, (0xD000 + 2 * n, p & 0xFF)
    if test == "D010":
        return {**base, "d010": hi ^ (1 << n)}, base, (0xD010, hi)
    if test == "COL":
        return base, {**base, "col": NEW_COL}, (0xD027 + n, NEW_COL)
    if test == "D01C":
        return base, {**base, "d01c": 1 << n}, (0xD01C, 1 << n)
    raise ValueError(test)


def pos(w: int) -> str:
    return f"{w // CPL}:{w % CPL:02d}"


def describe(sig: tuple) -> str:
    if not sig:
        return "nothing drawn"
    xs = [x for x, _ in sig]
    cols = sorted({c for _, c in sig})
    return f"{len(sig)} pixels at X {min(xs)}-{max(xs)}, colour{'s' if len(cols) > 1 else ''} {cols}"


def run_test(pr: Probe, name: str, old: dict, new: dict, write, delays, lines: range, verbose: bool,
             coarse: int = 0):
    """Sweep one test. Returns {write position: pattern}, one character per line in `lines`."""
    _, ref_old = pr.sample(old)
    _, ref_new = pr.sample(new)
    out: dict[int, str] = {}
    for d in delays:
        w, sig = pr.sample(old, write, d, coarse)
        pat, note = "", ""
        for line in lines:
            o, nw, g = ref_old[line], ref_new[line], sig[line]
            c = "=" if o == nw == g else "N" if g == nw else "O" if g == o else "X"
            if c == "X" and not note:
                note = (f"   [line {line}: {describe(g)}; old: {describe(o)}; new: {describe(nw)}]")
            pat += c
        pat += note
        extra = {ln for ln in sig if ln not in lines and sig[ln] != ref_old[ln] and sig[ln] != ref_new[ln]}
        if extra:
            pat += f" (+ lines {sorted(extra)} differ from both references)"
        if w in out and out[w] != pat:
            raise SystemExit(f"{name}: two results for a write at {pos(w)}: {out[w]} / {pat}")
        out[w] = pat
    if verbose:
        for w in sorted(out):
            print(f"      {pos(w)}  {out[w]}")
    return out


def runs(out: dict[int, str]) -> list[tuple[int, int, str]]:
    """[(first write, last write, pattern)] for consecutive write positions with one pattern."""
    res: list[list] = []
    for w in sorted(out):
        if res and res[-1][2] == out[w]:
            res[-1][1] = w
        else:
            res.append([w, w, out[w]])
    return [tuple(r) for r in res]


def gaps(out: dict[int, str]) -> str:
    ws = sorted(out)
    missing = [w for w in range(ws[0], ws[-1]) if w not in out]
    if not missing:
        return "none"
    spans, a, b = [], missing[0], missing[0]
    for w in missing[1:]:
        if w == b + 1:
            b = w
        else:
            spans.append((a, b))
            a = b = w
    spans.append((a, b))
    return ", ".join(pos(a) if a == b else f"{pos(a)}-{pos(b)}" for a, b in spans)


def main() -> int:
    verbose = "--verbose" in sys.argv
    sprites = [0] if "--quick" in sys.argv else [0, 2, 3, 7]
    if "--sprites" in sys.argv:
        sprites = [int(x) for x in sys.argv[sys.argv.index("--sprites") + 1].split(",")]
    pr = Probe()
    s = pr.sym
    summary = []
    try:
        print(f"sprite_latch sweep: VICE {pr.mon.vice_info()}, sprite Y = {Y} (first display line {Y + 1}); "
              f"write positions are line:cycle (VICE CYC)")
        print("pattern: one character per display line; N = new value shown, O = old (for Y and D015: "
              "no sprite), X = neither")
        for n in sprites:
            for p in (24, 320):
                for test in TESTS:
                    old, new, write = test_setup(s, test, n, p)
                    print(f"\nLATCH {test:5s} sprite {n}, X = {p}: lines {Y + 1}-{Y + 21}")
                    out = run_test(pr, test, old, new, write, LATCH_DELAYS, range(Y + 1, Y + 22), verbose)
                    for a, b, pat in runs(out):
                        print(f"   write {pos(a)} to {pos(b)}: {pat}")
                    print(f"   no write possible at: {gaps(out)}")
                    good = [w for w in sorted(out) if out[w].startswith("N")]
                    bad = [w for w in sorted(out) if not out[w].startswith("N")]
                    last = max(w for w in good if not bad or w < min(bad)) if good and (not bad or good[0] < min(bad)) else None
                    summary.append(("LATCH", test, n, p, last, min(bad) if bad else None,
                                    out[min(bad)] if bad else "", max(out)))
                for test in FREE_TESTS:
                    old, new, write = test_setup(s, test, n, p)
                    # Coarse delay: the first that puts delay 0 on line 122 (measured; line 123 is a
                    # badline, where few cycles can be reached at all).
                    for coarse in range(170, 256):
                        w, _sig = pr.sample(old, write, 0, coarse)
                        if w >= FREE_FROM - 2 * CPL:
                            break
                    if not FREE_FROM - 2 * CPL <= w < FREE_FROM - CPL:
                        raise SystemExit(f"FREE {test}: no coarse delay found (last {coarse}: {pos(w)})")
                    print(f"\nFREE  {test:5s} sprite {n}, X = {p}: old occupant's lines {Y + 1}-{Y + 21} "
                          f"(coarse delay {coarse})")
                    out = run_test(pr, test, old, new, write, FREE_DELAYS, range(Y + 1, Y + 22), verbose, coarse)
                    for a, b, pat in runs(out):
                        print(f"   write {pos(a)} to {pos(b)}: {pat}")
                    print(f"   no write possible at: {gaps(out)}")
                    marked = [w for w in sorted(out) if set(out[w]) != {"O"}]
                    if min(out) >= FREE_FROM or max(out) < FREE_FROM + 2 * CPL - 1:
                        raise SystemExit(f"FREE sweep {pos(min(out))}-{pos(max(out))} doesn't cover lines 124-125")
                    summary.append(("FREE", test, n, p, min(out), (max(marked) if marked else None),
                                    out[max(marked)] if marked else "", max(out)))
                sys.stdout.flush()
        late = pr.mon.mem_get(s["irq_late_count"], s["irq_late_count"])[0]
    finally:
        pr.close()

    print("\nSUMMARY, LATCH: last write at which the first display line (Y + 1) shows the new value")
    print(f"  (line Y = {Y}; written as line:cycle and relative to Y)")
    print("  register sprite    X   last good write        first bad write        what line Y + 1.. shows then")
    for kind, test, n, p, last, bad, pat, end in summary:
        if kind != "LATCH":
            continue
        rel = lambda w: "-" if w is None else f"{pos(w)} (Y{'+1' if w // CPL > Y else ''} cycle {w % CPL})"  # noqa: E731
        good = rel(last) if bad is not None else f"all to {pos(end)}"
        print(f"  {test:8s} {n:6d} {p:4d}   {good:22s} {rel(bad):22s} {pat}")
    print("\nSUMMARY, FREE: last write that marks any line of the old occupant (Y_old = "
          f"{Y}, displayed {Y + 1}-{Y + 21}; swept from before {pos(FREE_FROM)} to after line {Y + 22})")
    print("  register sprite    X   last marking write     pattern then")
    for kind, test, n, p, first, bad, pat, end in summary:
        if kind != "FREE":
            continue
        txt = "none" if bad is None else f"{pos(bad)} (Y_old+{bad // CPL - Y} cycle {bad % CPL})"
        print(f"  {test:8s} {n:6d} {p:4d}   {txt:28s} {pat}")
    print(f"\n{pr.samples} samples. Stable handler start (line, cycle): "
          + ", ".join(f"{k} x{v}" for k, v in sorted(pr.starts.items())) + f". irq_late_count = {late}")
    ok = set(pr.starts) == {HANDLER} and late == 0
    print("handler stable on line 102 cycle 6 in every sample: " + ("yes" if ok else "NO"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
