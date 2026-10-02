"""Measured costs of engine/collision.asm in its spike: the figures in engine/collision.md#results.

One trace of --frames frames (default 768: three of the spike's 256-frame cycles) with execution
checkpoints on the spans below. Raster cycles (line x 63 + cycle), as vice_profile and the budget
runner measure them, so DMA is included; "excl. IRQ" subtracts the IRQs nested in the span, as the
runner's profile_excl_irq does.

  spike_collide -> spike_collide_end   the game's 42 tests, by phase: M (moving) and W (the
                                       contract's worst mix), with the lines it ran on
  collision_begin -> collision_begin_end   every call (display and border), and the border calls alone
  spike_mix / spike_begin / spike_reject / spike_full / spike_one -> their _end   the five border
                                       passes (spike_mix: the worst mix of 42 tests with no DMA)
  spike_frame_done                     the line on which a frame's work ended, by phase

Run from the repo root (build first: make GAME=collision SRC_DIR=tests/engine/collision):

    uv run --package budget-runner python tests/engine/collision/measure.py [--prg ...] [--frames 768] [--out FILE]

About 25 s. --out writes the same text to a file (the committed copy is measure_results.txt).
Works on a release build (no DEBUG label used).
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from budget_runner.evaluate import CYCLES_PER_LINE, FRAME, Event, profile_costs
from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice
from vice_monitor import CPU_OP_EXEC  # on sys.path once budget_runner.session is imported

REPO = Path(__file__).resolve().parents[3]
SPANS = [("spike_mix", "spike_mix_end"), ("spike_begin", "spike_begin_end"), ("spike_reject", "spike_reject_end"),
         ("spike_full", "spike_full_end"), ("spike_one", "spike_one_end")]


def stats(c):
    return f"min {min(c)}, avg {sum(c) / len(c):.1f}, max {max(c)} ({len(c)} passes)" if c else "no passes"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prg", default=str(REPO / "build/collision/collision.prg"))
    ap.add_argument("--frames", type=int, default=768)
    ap.add_argument("--out")
    a = ap.parse_args()
    lines = []

    def out(s=""):
        print(s)
        lines.append(s)

    v = Vice(Path(a.prg), 50)
    try:
        mon, sym = v.mon, v.symbols
        names = ["spike_collide", "spike_collide_end", "collision_begin", "collision_begin_end",
                 "spike_frame_done", "irq_dispatch", "irq_exit_rti"] + [n for s in SPANS for n in s]
        cps = [mon.checkpoint_set(sym[n], sym[n], CPU_OP_EXEC) for n in names]
        events, phase_at, base, prev, frames = [], {}, 0, -1, 0
        while frames < a.frames:
            mon.exit()
            if not mon.wait_stopped(STOP_TIMEOUT):
                mon.ping()
                raise MeasureError("timed out waiting for a checkpoint")
            r = mon.registers()
            t = r["LIN"] * CYCLES_PER_LINE + r["CYC"]
            if t < prev:
                base += FRAME
            prev = t
            events.append(Event(r["PC"], base + t, r["LIN"], r["CYC"]))
            if r["PC"] in (sym["spike_collide"], sym["spike_frame_done"]):
                st = mon.mem_get(sym["spike_t"], sym["spike_t"])[0]
                phase_at[len(events) - 1] = "M" if st < 224 else "W" if st < 240 else "B"
                frames += r["PC"] == sym["spike_frame_done"]
        for c in cps:
            mon.checkpoint_delete(c.number)
        over = mon.mem_get(sym["spike_overrun_count"], sym["spike_overrun_count"])[0]
        mism = mon.mem_get(sym["spike_mismatch_count"], sym["spike_mismatch_count"])[0]
    finally:
        v.close()

    d, x = sym["irq_dispatch"], sym["irq_exit_rti"]
    out(f"engine/collision.asm in tests/engine/collision: {a.frames} frames, {Path(a.prg).name}. Raster cycles.")
    out()
    # the 42 tests, by phase
    cs, ce = sym["spike_collide"], sym["spike_collide_end"]
    for ph, what in (("M", "moving"), ("W", "the contract's worst mix: 21 full tests, 21 rejects, 4 hits")):
        idx = [i for i, e in enumerate(events) if e.pc == cs and phase_at.get(i) == ph]
        incl, excl, l0, l1 = [], [], [], []
        for i in idx:
            j = next((k for k in range(i + 1, len(events)) if events[k].pc == ce), None)
            if j is None:
                continue
            seg = events[i:j + 1]
            incl += profile_costs(seg, cs, ce)
            excl += profile_costs(seg, cs, ce, d, x)
            l0.append(events[i].line)
            l1.append(events[j].line)
        out(f"spike_collide -> spike_collide_end, phase {ph} ({what})")
        out(f"    excl. IRQ: {stats(excl)}")
        out(f"    incl. IRQ: {stats(incl)}")
        if l0:
            out(f"    starts on line {min(l0)}-{max(l0)}, ends on line {min(l1)}-{max(l1)}")
    # collision_begin
    b0, b1 = sym["collision_begin"], sym["collision_begin_end"]
    allc, border = [], []
    for i, e in enumerate(events):
        if e.pc == b0:
            j = next((k for k in range(i + 1, min(i + 6, len(events))) if events[k].pc == b1), None)
            if j is not None and not any(events[k].pc == d for k in range(i, j)):
                c = events[j].t - e.t
                allc.append(c)
                if e.line >= 251:
                    border.append(c)
    out(f"collision_begin -> collision_begin_end (its rts), calls with no IRQ inside")
    out(f"    all calls: {stats(allc)}; {sum(1 for c in allc if c == min(allc))} at the minimum")
    out(f"    histogram: {dict(sorted(Counter(allc).items()))}")
    out(f"    border calls (line >= 251): {stats(border)}")
    for s, e in SPANS:
        c = profile_costs(events, sym[s], sym[e])
        ls = sorted({ev.line for ev in events if ev.pc == sym[s]})
        le = sorted({ev.line for ev in events if ev.pc == sym[e]})
        out(f"{s} -> {e} (border): {stats(c)}; starts on line {ls[0]}-{ls[-1]}, ends on {le[0]}-{le[-1]}")
    for ph in "MWB":
        ln = [events[i].line for i, p in phase_at.items() if p == ph and events[i].pc == sym["spike_frame_done"]]
        if ln:
            # lines 0-15 belong to the end of the frame (the tick is on line 16)
            late = [l + 312 if l < 16 else l for l in ln]
            out(f"spike_frame_done, phase {ph}: line {min(late)}-{max(late)} ({len(ln)} frames; over 311 = into the next top border, the tick is at 328)")
    out(f"spike_overrun_count {over}, spike_mismatch_count {mism}")
    if a.out:
        Path(a.out).write_text("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL (jam/hang): {e}")
        sys.exit(2)
