"""multiplexer_edge: check from OUTSIDE the engine that every zone slot's register writes land before
the deadlines tests/timing/sprite_latch measured, and that the picture is right, in layouts built
to sit at the scheduler's limit with slot Y lines on badlines (engine/README.md#slot-write-deadline,
probe 2). Nothing in the engine or the probe program is instrumented: the script only sets
execution / store checkpoints and reads registers, memory and VICE's frame buffer.

Deadlines (measured, docs/reference/vic-ii-timing.md#sprite-register-write-deadlines; a "write
cycle" is the raster cycle, VICE CYC, in which the store happens = the position after the `sta`
minus one):
  uniform   every write of a slot at or before cycle 53 of line Y: the earliest deadline of all
            (the Y register on hardware sprite 0). A slot that meets it meets every deadline.
  per register (used when a slot's last write is later than the uniform deadline, and in --detail):
            Y: Y:53.   pointer: Y:54 (sprites 0-2), Y:60 (3-6), Y+1:05 (7).
            X low, $D010, colour, $D01C: Y+1:12 (the measured 12 + X / 8, taken at X = 0).

Three tiers:
  fast      a checkpoint on the `inx` that follows each zone block's last store (found from the
            block layout, checked to be an $E8), one stop per zone slot: X = the slot, the raster
            position minus one = the last write. Slack = cycles from it to the uniform deadline.
  detail    store checkpoints on $D000-$D010, $D01C, $D027-$D02E and the 8 sprite pointers, one
            stop per register write: every write of every zone slot against its own deadline, and
            how close the Y write gets to the end of line Y - 1.
  picture   the whole 320 x 200 window of VICE's frame buffer compared, pixel for pixel, with the
            picture the virtual sprites should make (static layouts: from mux_y / mux_x_* / mux_ptr
            / mux_col / mux_flags; random layouts, which flicker: from the front buffer's slots).
            A pointer, colour, X or multicolour bit written late shows as a wrong first line.

Layouts:
  phases    the probe's 18 built-in phases (main.asm): rows / reuse / stairs, yB = 98, 99 (a
            badline), 100, uniform and mixed multicolour. --frames each (default 1,000).
  sweep     the same three types written by this script in the probe's manual mode, with yB =
            88-103 (every line offset against the badlines, twice), uniform and mixed; and
            "reuse h": the reuse layout on each hardware sprite h = 0-7 in turn (h earlier sprites
            first, so the limit slot is slot 8 + h and the 7 displayed across its Y line are the
            other 7 hardware sprites), yB = 96-103, uniform and mixed. A fresh zone IRQ for one
            slot at the 25-line limit with 7 sprites' DMA is the latest a slot's writes get.
  stairs    random staircases: three rows of 8 with random steps of 2-4 lines between
            neighbours (2 is the least the selection allows), each row as close under the one
            above as the 25-line gap allows, random base line, mixed multicolour. Step-2 runs
            are where the zone IRQ falls behind (see the README): this varies where the runs
            start and end against the badlines.
  random    dense random layouts (12-24 sprites inside 30-120 lines, random multicolour and pinned
            flags), most of them overloaded, so the selection's slow path picks the slots.
            The five with the least slack are run again for longer.

Run from the repo root (build first: make GAME=multiplexer_edge SRC_DIR=tests/engine/multiplexer_edge;
for the release build add BUILD=release, run this, then rebuild without it so make test's build is back):

    uv run --package budget-runner python tests/engine/multiplexer_edge/edge.py \
        [--frames 1000] [--sweep-frames 200] [--random 300] [--stairs 300] [--detail-frames 100] [--seed 1] \
        [--quick] [--prg build/multiplexer_edge/multiplexer_edge.prg]

--hunt N: instead of all that, search for the closest call on a badline: N random staircases (20
frames each, fast tier), then a hill climb from the ten closest; the closest layout is then run for
1,000 frames with the detail tier. --hunt 1500 takes about 20 minutes.
--quick: 100 frames a phase, 50 a sweep layout, 40 random layouts and staircases. Exit code 0 = no
write past a deadline, every picture right, counters 0; 1 otherwise. A full run takes about 15 minutes.

RESULTS (2026-10-01, VICE 3.10 x64sc PAL, stage 4 engine; full output in results-debug.txt,
results-release.txt, results-hunt-debug.txt and results-hunt-release.txt beside this file; summary
and the reasoning in engine/README.md#slot-write-deadline):
                                             DEBUG                  release
  frames / zone slots (fast tier)            90,800 / 843,538       90,800 / 842,738
  zone slots with Y on a badline             127,616                128,194
  register writes (detail tier)              375,492                374,892
  writes past a deadline                     0                      0
  pictures compared / wrong                  1,868 / 0              1,868 / 0
  least slack of a last write to Y:53        4 (Y:49, mixed)        28
  closest call with Y on a badline           last write Y-1:46      Y-1:33
    in the hunt (1,855 / 1,857 layouts)      Y-1:50                 Y-1:35
  mux_late_count, irq_late_count             0, 0                   (not in a release build)
No miss could be provoked. On a badline the DEBUG mixed build's last store lands as late as cycle
50 of line Y - 1 (counted for the path that produces it, and the latest the hunt found; not proven
to be the worst of every layout); cycle 54 is the last a store can be made on: 4 to spare.
"""

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

from budget_runner.session import Vice

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "mcp" / "vice"))

from vice_monitor import CPU_OP_EXEC, CPU_OP_STORE, run_frames  # noqa: E402

CPL = 63
UNIFORM = 53                        # cycle of line Y: the earliest measured deadline
MUX_Y_MIN, MUX_Y_MAX, MUX_OFF = 30, 0xF9, 0xFF
BG, MC1, MC2 = 0, 5, 2
REF_CHAR, REF_COLOUR, REF_LINE = 0x0427, 7, 51
MANUAL = 0x80
TYPES = ["rows", "reuse", "stairs"]


def badline(y: int) -> bool:
    return 51 <= y <= 247 and y % 8 == 3


def layout(kind: int, yb: int) -> list[int]:
    """The probe's three layout types (main.asm edge_yv), for any yB."""
    ys = []
    for v in range(24):
        row, i = divmod(v, 8)
        if kind == 0:
            ys.append(yb - 39 + 39 * row)
        elif kind == 2:
            ys.append(yb - 25 + 25 * row + 2 * i)
        elif row == 0:
            ys.append(yb - 25 if i == 0 else yb - 18 + 2 * i)
        else:
            ys.append(yb if (row, i) == (1, 0) else MUX_OFF)
    return ys


def reuse_h(h: int, yb: int) -> tuple[list[int], list[int]]:
    """(Y, flags) of the reuse layout on hardware sprite h: slots 0..h-1 early sprites (row 2),
    slot h the first occupant at yb - 25, 7 sprites at yb - 17 .. yb - 5 displayed across line yb
    (slots h+1..7, then 8..8+h-1 on the early sprites' hardware sprites), slot 8 + h at yb."""
    ys, flags = [MUX_OFF] * 24, [0] * 24
    for i in range(h):
        ys[16 + i] = yb - 60                        # row 2, columns 0..h-1: gone long before
    ys[7] = yb - 25                                 # row 0, column 7: the first occupant
    ys[15] = yb                                     # row 1, column 7: the limit slot
    flags[15] = 1                                   # (multicolour when the layout is run mixed)
    for m in range(7):                              # row 0, columns 0-6: displayed across line yb
        ys[m] = yb - 17 + 2 * m
    return ys, flags


def staircase(base: int, steps: list[int]) -> list[int]:
    """Three rows of 8 from 21 steps (7 a row, each >= 2 lines): every sprite as high as the step
    from its neighbour and the 25-line gap to the sprite above it allow, and each row below the
    whole row above, so the Y order is row by row and every sprite fits."""
    rows: list[list[int]] = []
    for r in range(3):
        st = steps[7 * r:7 * r + 7]
        ys: list[int] = []
        for j in range(8):
            lo = base if not rows else rows[-1][j] + 25
            if j == 0 and rows:
                lo = max(lo, rows[-1][7] + 2)
            ys.append(lo if j == 0 else max(lo, ys[-1] + st[j - 1]))
        rows.append(ys)
    return [y for row in rows for y in row]


def deadline(reg: str, hw: int, y: int) -> int:
    if reg == "Y":
        return y * CPL + 53
    if reg == "PTR":
        return y * CPL + 54 if hw <= 2 else y * CPL + 60 if hw <= 6 else (y + 1) * CPL + 5
    return (y + 1) * CPL + 12


class Edge:
    def __init__(self, prg: Path) -> None:
        self.v = Vice(prg, 20)
        self.mon, s = self.v.mon, self.v.symbols
        self.s = s
        self.debug = "mux_late_count" in s
        off_u, off_m = (45, 51) if self.debug else (30, 36)
        self.inx = {}
        for j in range(8):
            for name, off in ((f"mux_zone_{j}", off_u), (f"mux_zone_m{j}", off_m)):
                a = s[name] + off
                if self.mon.mem_get(a, a)[0] != 0xE8:
                    raise SystemExit(f"{name} + {off} is not the block's inx: the zone block layout changed")
                self.inx[a] = j
        self.shapes = {}
        self.fixed = None
        self.shift = 0
        self.bad_pictures = 0
        self.pictures = 0
        # Row mapping: reversed space in text row 0, column 39 (first row = raster line 51), with
        # every sprite hidden so nothing covers it.
        self.manual([MUX_OFF] * 24, [0] * 24)
        self.mon.mem_set(REF_CHAR, b"\xa0")
        self.mon.mem_set(REF_CHAR + 0xD400, bytes([REF_COLOUR]))
        run_frames(self.mon, 2)
        d = self.mon.display_get()
        col = d.offset_x + 39 * 8 + 4
        rows = [r for r in range(d.height) if d.pixels[r * d.width + col] == REF_COLOUR]
        if len(rows) != 8:
            raise SystemExit(f"reference character not found (rows {rows})")
        self.shift = REF_LINE - rows[0]
        self.mon.mem_set(REF_CHAR, b"\x20")

    def close(self) -> None:
        self.v.close()

    # -- driving the probe ----------------------------------------------------------------

    def _until(self, addr: int, times: int = 1) -> None:
        cp = self.mon.checkpoint_set(addr, addr, CPU_OP_EXEC)
        try:
            for _ in range(times):
                self.mon.exit()
                if not self.mon.wait_stopped(5):
                    raise SystemExit(f"${addr:04x} not reached")
        finally:
            self.mon.checkpoint_delete(cp.number)

    def phase(self, p: int) -> None:
        """Hold built-in phase p, and let it reach the screen."""
        self._until(self.s["edge_main"])
        self.mon.mem_set(self.s["edge_lock"], bytes([p]))
        self._until(self.s["edge_main"], 4)

    def manual(self, ys: list[int], flags: list[int], settle: int = 4) -> None:
        """Manual mode: write Y and flags of the 24 virtual sprites (X, pointer, colour stay)."""
        self._until(self.s["edge_main"])            # the main loop is about to start a frame: no race
        self.mon.mem_set(self.s["edge_lock"], bytes([MANUAL]))
        self.mon.mem_set(self.s["mux_y"], bytes(ys))
        self.mon.mem_set(self.s["mux_flags"], bytes(flags))
        self._until(self.s["edge_main"], settle)

    def counters(self) -> dict[str, int]:
        out = {}
        for n, size in (("mux_late_count", 1), ("irq_late_count", 1), ("edge_overrun_count", 1),
                        ("edge_drop_total", 2)):
            if n in self.s and (self.debug or n == "edge_overrun_count"):
                out[n] = int.from_bytes(self.mon.mem_get(self.s[n], self.s[n] + size - 1), "little")
        return out

    # -- fast tier ------------------------------------------------------------------------

    def fast(self, frames: int) -> list[tuple[int, int, int]]:
        """[(slot, Y, last write position in cycles from line 0)] for every zone slot of `frames` frames."""
        mon, s = self.mon, self.s
        main = s["edge_main"]
        cps = [mon.checkpoint_set(a, a, CPU_OP_EXEC) for a in list(self.inx) + [main]]
        out, n = [], 0
        try:
            while n < frames:
                mon.exit()
                if not mon.wait_stopped(5):
                    raise SystemExit("timed out in the fast trace")
                r = mon.registers()
                if r["PC"] == main:
                    n += 1
                    continue
                x = r["X"]
                y = mon.mem_get(s["mux_s_y"] + x, s["mux_s_y"] + x)[0]
                out.append((x, y, r["LIN"] * CPL + r["CYC"] - 1))
        finally:
            for c in cps:
                mon.checkpoint_delete(c.number)
        return out

    # -- detail tier ----------------------------------------------------------------------

    def detail(self, frames: int) -> list[tuple[int, int, str, int]]:
        """[(slot, Y, register class, write position)] for every store a zone block makes."""
        mon, s = self.mon, self.s
        lo, hi = s["mux_zone_blocks"], s["mux_zone_blocks_end"]
        ptrs = 0x0400 + 0x3F8
        ranges = [(0xD000, 0xD010), (0xD01C, 0xD01C), (0xD027, 0xD02E), (ptrs, ptrs + 7)]
        cps = [mon.checkpoint_set(a, b, CPU_OP_STORE) for a, b in ranges]
        cps.append(mon.checkpoint_set(s["edge_main"], s["edge_main"], CPU_OP_EXEC))
        out, n = [], 0
        try:
            while n < frames:
                mon.exit()
                if not mon.wait_stopped(5):
                    raise SystemExit("timed out in the detail trace")
                r = mon.registers()
                pc = r["PC"]
                if pc == s["edge_main"]:
                    n += 1
                    continue
                if not lo <= pc - 3 < hi:
                    continue                        # mux_irq_top's stores, on lines 16-22
                op = mon.mem_get(pc - 3, pc - 1)
                if op[0] != 0x8D:
                    raise SystemExit(f"store before ${pc:04x} is not a sta abs")
                addr = op[1] | op[2] << 8
                x = r["X"]
                y = mon.mem_get(s["mux_s_y"] + x, s["mux_s_y"] + x)[0]
                reg = ("PTR" if addr >= ptrs and addr < ptrs + 8 else "D010" if addr == 0xD010 else
                       "D01C" if addr == 0xD01C else "COL" if addr >= 0xD027 else "Y" if addr & 1 else "XLO")
                out.append((x, y, reg, r["LIN"] * CPL + r["CYC"] - 1))
        finally:
            for c in cps:
                mon.checkpoint_delete(c.number)
        return out

    # -- picture tier ---------------------------------------------------------------------

    def _shape(self, ptr: int) -> bytes:
        if ptr not in self.shapes:
            self.shapes[ptr] = self.mon.mem_get(ptr * 64, ptr * 64 + 62)
        return self.shapes[ptr]

    def _render(self, sprites: list[dict]) -> dict[tuple[int, int], int]:
        """{(raster line, X): colour} for the sprites; the first in the list is drawn on top."""
        pic: dict[tuple[int, int], int] = {}
        for sp in reversed(sprites):
            data = self._shape(sp["ptr"])
            for row in range(21):
                bits = int.from_bytes(data[row * 3:row * 3 + 3], "big")
                line = sp["y"] + 1 + row
                for b in range(24):
                    if sp["mc"]:
                        pair = (bits >> (22 - (b & ~1))) & 3
                        colour = (None, MC1, sp["col"], MC2)[pair]
                    else:
                        colour = sp["col"] if bits >> (23 - b) & 1 else None
                    if colour is not None:
                        pic[(line, sp["x"] + b)] = colour
        return pic

    def _virtual(self) -> list[dict]:
        m, s = self.mon, self.s
        if self.fixed is None:
            self.fixed = [m.mem_get(s[n], s[n] + 23) for n in ("mux_x_lo", "mux_x_hi", "mux_ptr", "mux_col")]
        xlo, xhi, ptr, col = self.fixed
        ys, fl = m.mem_get(s["mux_y"], s["mux_y"] + 23), m.mem_get(s["mux_flags"], s["mux_flags"] + 23)
        return [{"x": xlo[v] | (xhi[v] & 1) << 8, "y": ys[v], "ptr": ptr[v], "col": col[v] & 15, "mc": fl[v] & 1}
                for v in range(24) if MUX_Y_MIN <= ys[v] <= MUX_Y_MAX]

    def _slots(self) -> list[dict]:
        """The front buffer's slots (what the frame just displayed was built from), hardware sprite order."""
        m, s = self.mon, self.s
        base, end = m.mem_get(s["zp_mux_front"], s["zp_mux_front"])[0], m.mem_get(s["zp_mux_end"], s["zp_mux_end"])[0]
        arr = {n: m.mem_get(s[n], s[n] + 63) for n in ("mux_s_y", "mux_s_xlo", "mux_s_ptr", "mux_s_col",
                                                       "mux_s_d010", "mux_s_d01c")}
        mixed = m.mem_get(s["mux_blk_mode"], s["mux_blk_mode"] + 1)[1 if base else 0]
        uniform_mc = m.mem_get(s["mux_b_d01c"] + base, s["mux_b_d01c"] + base)[0] & 1   # only if not mixed
        out = []
        for k in range(base, end):
            bit = 1 << (k & 7)
            out.append({"hw": k & 7, "x": arr["mux_s_xlo"][k] | (256 if arr["mux_s_d010"][k] & bit else 0),
                        "y": arr["mux_s_y"][k], "ptr": arr["mux_s_ptr"][k], "col": arr["mux_s_col"][k] & 15,
                        "mc": (1 if arr["mux_s_d01c"][k] & bit else 0) if mixed else uniform_mc})
        return sorted(out, key=lambda sp: sp["hw"])

    def picture(self, from_slots: bool) -> list[str]:
        """Compare the 320 x 200 window with the expected picture. Returns the mismatches (text)."""
        run_frames(self.mon, 1)                     # stops on line 0: the buffer holds a whole frame
        sprites = self._slots() if from_slots else self._virtual()
        want = self._render(sprites)
        d = self.mon.display_get()
        bad = []
        for line in range(51, 251):
            row = (line - self.shift) * d.width + d.offset_x
            px = d.pixels[row:row + 320]
            for i in range(320):
                exp = want.get((line, 24 + i), BG)
                if px[i] != exp:
                    bad.append(f"line {line} X {24 + i}: shows colour {px[i]}, expected {exp}")
        self.pictures += 1
        self.bad_pictures += bool(bad)
        return bad


def report(name: str, e: Edge, recs: list[tuple[int, int, int]], frames: int, bad_pics: list[str],
           pics: int, totals: dict) -> None:
    slack = [(y * CPL + UNIFORM - w, k, y, w) for k, y, w in recs]
    on_y = [t for t in slack if t[3] // CPL >= t[2]]
    late = [t for t in slack if t[0] < 0]
    bl = [t for t in slack if badline(t[2])]
    worst = min(slack) if slack else None
    wb = min(bl) if bl else None
    fmt = lambda t: "-" if t is None else f"{t[0]:5d} ({t[0] / CPL:5.2f} lines; slot {t[1] % 32}, Y {t[2]}, last write {t[3] // CPL}:{t[3] % CPL:02d})"  # noqa: E731
    print(f"{name:34s} {frames:5d} fr {len(recs):6d} zone slots | least slack {fmt(worst)} | "
          f"Y on a badline: {len(bl):6d}, least {fmt(wb)} | last write on line Y: {len(on_y)} | "
          f"past Y:{UNIFORM}: {len(late)} | pictures {pics - bool(bad_pics)}/{pics}")
    for b in bad_pics[:5]:
        print(f"      PICTURE: {b}")
    for t in late[:5]:
        print(f"      LATE: slot {t[1] % 32} (hardware sprite {t[1] & 7}) Y {t[2]}: last write at "
              f"{t[3] // CPL}:{t[3] % CPL:02d}, {-t[0]} cycles after Y:{UNIFORM}")
    totals["slots"] += len(recs)
    totals["badline"] += len(bl)
    totals["on_y"] += len(on_y)
    totals["late"] += len(late)
    totals["frames"] += frames
    for t in (worst, wb):
        if t is not None:
            key = "worst_bl" if t is wb and badline(t[2]) else "worst"
            if totals.get(key) is None or t[0] < totals[key][0]:
                totals[key] = (*t, name)
    if worst is not None and (totals.get("worst") is None or worst[0] < totals["worst"][0]):
        totals["worst"] = (*worst, name)
    sys.stdout.flush()


def run_layout(e: Edge, name: str, frames: int, pics: int, from_slots: bool, totals: dict):
    recs, bad = [], []
    chunk = max(1, frames // pics)
    done = 0
    while done < frames:
        recs += e.fast(min(chunk, frames - done))
        done += chunk
        bad += e.picture(from_slots)
    report(name, e, recs, frames, bad, pics, totals)
    return min((y * CPL + UNIFORM - w for _, y, w in recs), default=10 ** 6)


def run_detail(e: Edge, name: str, frames: int, dtot: dict) -> None:
    recs = e.detail(frames)
    by = {}
    for k, y, reg, w in recs:
        sl = deadline(reg, k & 7, y) - w
        if reg not in by or sl < by[reg][0]:
            by[reg] = (sl, k, y, w)
        if sl < 0:
            dtot["late"].append((name, k, y, reg, w))
        if reg == "Y":
            dtot["y_before"] = min(dtot["y_before"], y * CPL - 1 - w)      # cycles before the end of line Y - 1
            if badline(y):
                dtot["y_before_bl"] = min(dtot["y_before_bl"], y * CPL - 1 - w)
        for key, use in (("min", True), ("min_bl", badline(y))):
            if use and (reg not in dtot[key] or sl < dtot[key][reg][0]):
                dtot[key][reg] = (sl, name, k, y, w)
    dtot["writes"] += len(recs)
    print(f"{name:34s} {frames:4d} fr {len(recs):6d} writes | least slack to its own deadline: "
          + ", ".join(f"{r} {by[r][0]}" for r in ("Y", "XLO", "PTR", "COL", "D010", "D01C") if r in by))
    sys.stdout.flush()


def hunt(e: Edge, n: int, frames: int, seed: int) -> int:
    """Look for the layout that brings a badline-Y slot's last write closest to the end of line
    Y - 1 (after which it could only land on line Y + 1): n random staircases, then a hill climb
    from the ten closest (change one step or the base line, keep it if it gets closer)."""
    rng = random.Random(seed)
    flags = [1 if 8 <= v < 16 else 0 for v in range(24)]
    seen: dict[tuple, tuple] = {}

    def score(base: int, steps: list[int]):
        key = (base, tuple(steps))
        if key not in seen:
            e.manual(staircase(base, steps), flags, settle=3)
            recs = [(y * CPL + UNIFORM - w, k % 32, y, w) for k, y, w in e.fast(frames) if badline(y)]
            seen[key] = min(recs) if recs else (10 ** 6, 0, 0, 0)
        return seen[key]

    pool = []
    for _ in range(n):
        base, steps = rng.randint(40, 75), [rng.choice((2, 2, 2, 3, 4)) for _ in range(21)]
        pool.append((score(base, steps), base, steps))
    pool.sort(key=lambda t: t[0])
    print(f"hunt: {n} random staircases, {frames} frames each. Closest ten (slack of a badline-Y slot's last "
          f"write to Y:{UNIFORM}; 63 + 53 - slack = its cycle on line Y - 1):")
    for sc, base, steps in pool[:10]:
        print(f"   slack {sc[0]:4d}  slot {sc[1]:2d} Y {sc[2]:3d} last write {sc[3] // CPL}:{sc[3] % CPL:02d}  base {base} steps {steps}")
    best = pool[0]
    for start in pool[:10]:
        cur = start
        for _ in range(60):
            base, steps = cur[1], list(cur[2])
            if rng.random() < 0.3:
                base = max(32, min(90, base + rng.choice((-2, -1, 1, 2))))
            else:
                steps[rng.randrange(21)] = rng.choice((2, 2, 3, 4))
            sc = score(base, steps)
            if sc[0] <= cur[0][0]:
                cur = (sc, base, steps)
        print(f"   climbed from {start[0][0]} to {cur[0][0]}: slot {cur[0][1]} Y {cur[0][2]} last write "
              f"{cur[0][3] // CPL}:{cur[0][3] % CPL:02d}  base {cur[1]} steps {cur[2]}")
        sys.stdout.flush()
        if cur[0][0] < best[0][0]:
            best = cur
    sc, base, steps = best
    ys = staircase(base, steps)
    print(f"hunt: closest found: slack {sc[0]} (slot {sc[1]}, Y {sc[2]}, last write {sc[3] // CPL}:{sc[3] % CPL:02d}); "
          f"{len(seen)} layouts tried.\n   Y = {ys}\n   Again, 1,000 frames, with every register write:")
    e.manual(ys, flags)
    totals = {"slots": 0, "badline": 0, "on_y": 0, "late": 0, "frames": 0, "worst": None, "worst_bl": None}
    dtot = {"late": [], "min": {}, "min_bl": {}, "writes": 0, "y_before": 10 ** 6, "y_before_bl": 10 ** 6}
    run_layout(e, "hunt best", 1000, 10, False, totals)
    run_detail(e, "hunt best (detail)", 200, dtot)
    for reg in ("Y", "XLO", "PTR", "COL", "D010", "D01C"):
        if reg in dtot["min_bl"]:
            sl, _name, k, y, pos = dtot["min_bl"][reg]
            print(f"      Y on a badline  {reg:5s} slack to its own deadline {sl:4d}  (slot {k % 32}, hardware sprite "
                  f"{k & 7}, Y {y}, written at {pos // CPL}:{pos % CPL:02d})")
    print("   counters: " + ", ".join(f"{k} = {v}" for k, v in e.counters().items()))
    late = totals["late"] or len(dtot["late"]) or e.bad_pictures
    print("hunt RESULT: " + ("a write past a deadline or a wrong picture: FAIL" if late else
                             "no write past a deadline, pictures right"))
    return 1 if late else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=1000)
    ap.add_argument("--sweep-frames", type=int, default=200)
    ap.add_argument("--random", type=int, default=300)
    ap.add_argument("--random-frames", type=int, default=40)
    ap.add_argument("--stairs", type=int, default=300)
    ap.add_argument("--detail-frames", type=int, default=100)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--hunt", type=int, default=0, help="only hunt: this many random staircases, then a hill climb")
    ap.add_argument("--prg", type=Path, default=REPO / "build" / "multiplexer_edge" / "multiplexer_edge.prg")
    a = ap.parse_args()
    if a.quick:
        a.frames, a.sweep_frames, a.random, a.stairs, a.detail_frames = 100, 50, 40, 40, 20
    e = Edge(a.prg)
    if a.hunt:
        try:
            return hunt(e, a.hunt, 20, a.seed)
        finally:
            e.close()
    totals = {"slots": 0, "badline": 0, "on_y": 0, "late": 0, "frames": 0, "worst": None, "worst_bl": None}
    dtot = {"late": [], "min": {}, "min_bl": {}, "writes": 0, "y_before": 10 ** 6, "y_before_bl": 10 ** 6}
    rng = random.Random(a.seed)
    try:
        print(f"multiplexer_edge: {a.prg.name}, {'DEBUG' if e.debug else 'release'} build, VICE {e.mon.vice_info()}. "
              f"Slack = cycles from a slot's LAST register write to cycle {UNIFORM} of its Y line (negative = late).")
        print("\n== Built-in phases (fast tier + picture from the virtual sprites)")
        for p in range(18):
            e.phase(p)
            kind, r, mixed = p // 6, 2 + (p % 6) // 2, p & 1
            run_layout(e, f"phase {p:2d} {TYPES[kind]} yB={96 + r}{' mixed' if mixed else ''}", a.frames, 10, False, totals)
        print("\n== Built-in phases, every register write against its own deadline (detail tier)")
        for p in range(18):
            e.phase(p)
            kind, r, mixed = p // 6, 2 + (p % 6) // 2, p & 1
            run_detail(e, f"phase {p:2d} {TYPES[kind]} yB={96 + r}{' mixed' if mixed else ''}", a.detail_frames, dtot)
        print("\n== Sweep: the three types at yB = 88-103, uniform and mixed (manual mode)")
        for kind in range(3):
            for yb in range(88, 104):
                for mixed in (0, 1):
                    e.manual(layout(kind, yb), [mixed if 8 <= v < 16 else 0 for v in range(24)])
                    run_layout(e, f"sweep {TYPES[kind]} yB={yb}{' mixed' if mixed else ''}", a.sweep_frames, 2, False, totals)
        print("\n== Sweep: reuse on hardware sprite h, yB = 96-103, uniform and mixed (fast tier, then detail)")
        for h in range(8):
            for yb in range(96, 104):
                ys, fl = reuse_h(h, yb)
                for mixed in (0, 1):
                    e.manual(ys, fl if mixed else [0] * 24)
                    name = f"sweep reuse h={h} yB={yb}{' mixed' if mixed else ''}"
                    run_layout(e, name, a.sweep_frames, 2, False, totals)
                    run_detail(e, name, max(10, a.detail_frames // 2), dtot)
        print("\n== Sweep, stairs and rows: detail tier at every yB")
        for kind in (2, 0):
            for yb in range(88, 104):
                e.manual(layout(kind, yb), [1 if 8 <= v < 16 else 0 for v in range(24)])
                run_detail(e, f"sweep {TYPES[kind]} yB={yb} mixed", max(10, a.detail_frames // 4), dtot)
        static = e.counters()                       # every layout so far fits: nothing dropped, no overrun
        print(f"\n== Random staircases (seed {a.seed}): steps of 2-4 lines, rows 25 lines apart where the steps allow")
        tried = []
        for i in range(a.stairs):
            ys = staircase(rng.randint(40, 75), [rng.choice((2, 2, 2, 3, 4)) for _ in range(21)])
            flags = [1 if 8 <= v < 16 else 0 for v in range(24)]
            e.manual(ys, flags)
            sl = run_layout(e, f"stairs {i}", a.random_frames, 2, False, totals)
            tried.append((sl, i, ys, flags))
        print("\n== The five random staircases with the least slack, again, longer, with the detail tier")
        for sl, i, ys, flags in sorted(tried)[:5]:
            e.manual(ys, flags)
            print(f"   stairs {i}: Y = {ys}")
            run_layout(e, f"stairs {i} (again)", a.sweep_frames * 2, 4, False, totals)
            run_detail(e, f"stairs {i} (detail)", max(10, a.detail_frames // 2), dtot)
        static = e.counters()
        print(f"\n== Random dense layouts (seed {a.seed}; picture from the front buffer's slots)")
        tried = []
        for i in range(a.random):
            n, base, span = rng.randint(12, 24), rng.randint(32, 150), rng.randint(30, 120)
            ys = [min(MUX_Y_MAX, base + rng.randint(0, span)) if v < n else MUX_OFF for v in range(24)]
            rng.shuffle(ys)
            mc = rng.random() < 0.5
            pins = rng.randint(0, 4)
            flags = [(rng.randint(0, 1) if mc else 0) | (0x80 if v < pins else 0) for v in range(24)]
            e.manual(ys, flags)
            sl = run_layout(e, f"random {i}", a.random_frames, 2, True, totals)
            tried.append((sl, i, ys, flags))
        print("\n== The five random layouts with the least slack, again, longer")
        for sl, i, ys, flags in sorted(tried)[:5]:
            e.manual(ys, flags)
            print(f"   random {i}: Y = {ys}  flags = {flags}")
            run_layout(e, f"random {i} (again)", a.sweep_frames * 2, 4, True, totals)
            run_detail(e, f"random {i} (detail)", max(10, a.detail_frames // 2), dtot)
        counters = e.counters()
    finally:
        e.close()

    w, wb = totals["worst"], totals["worst_bl"]
    print("\nSUMMARY")
    print(f"  fast tier: {totals['frames']:,} frames, {totals['slots']:,} zone slots, {totals['badline']:,} of them with Y on a badline")
    print(f"  least slack of a last write to Y:{UNIFORM}: {w[0]} cycles ({w[0] / CPL:.2f} lines): {w[4]}, slot {w[1] % 32}, "
          f"Y {w[2]}, last write {w[3] // CPL}:{w[3] % CPL:02d}")
    if wb:
        print(f"  least slack with Y on a badline:   {wb[0]} cycles ({wb[0] / CPL:.2f} lines): {wb[4]}, slot {wb[1] % 32}, "
              f"Y {wb[2]}, last write {wb[3] // CPL}:{wb[3] % CPL:02d}")
    print(f"  slots whose last write is on their own Y line: {totals['on_y']}; past the uniform deadline: {totals['late']}")
    print(f"  detail tier: {dtot['writes']:,} register writes; past a deadline: {len(dtot['late'])}. Least slack "
          "to each register's own deadline (cycles), and where:")
    for key, title in (("min", "any Y"), ("min_bl", "Y on a badline")):
        for reg in ("Y", "XLO", "PTR", "COL", "D010", "D01C"):
            if reg in dtot[key]:
                sl, name, k, y, pos = dtot[key][reg]
                print(f"      {title:15s} {reg:5s} {sl:4d}  ({name}: slot {k % 32}, hardware sprite {k & 7}, Y {y}, "
                      f"written at {pos // CPL}:{pos % CPL:02d})")
    for name, k, y, reg, pos in dtot["late"][:10]:
        print(f"      LATE: {name}: slot {k % 32} (hardware sprite {k & 7}) Y {y}, {reg} written at {pos // CPL}:{pos % CPL:02d}")
    print(f"  the Y write's closest approach to the end of line Y - 1: {dtot['y_before']} cycles before it "
          f"({dtot['y_before'] / CPL:.2f} lines); with Y on a badline: {dtot['y_before_bl']} ({dtot['y_before_bl'] / CPL:.2f} lines)")
    print(f"  pictures: {e.pictures - e.bad_pictures}/{e.pictures} match the expected picture exactly")
    print("  counters after the static layouts (phases, sweeps, staircases: all must be 0): "
          + ", ".join(f"{k} = {v}" for k, v in static.items()))
    print("  counters at the end (the random layouts drop sprites by design, and switching to a new random "
          "layout re-sorts everything, which can overrun a frame: those two are reported, not required): "
          + ", ".join(f"{k} = {v}" for k, v in counters.items()))
    ok = (totals["late"] == 0 and not dtot["late"] and e.bad_pictures == 0 and all(v == 0 for v in static.values())
          and all(v == 0 for k, v in counters.items() if k in ("mux_late_count", "irq_late_count")))
    print("  RESULT: " + ("PASS: no write past a deadline, every picture right" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
