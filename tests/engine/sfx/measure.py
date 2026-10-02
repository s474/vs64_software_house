"""Measured costs of engine/sfx.asm in its spike: the figures in engine/sfx.md#results and in the
module's header.

Two traces with execution checkpoints, raster cycles (line x 63 + cycle), as vice_profile and the
budget runner measure them:

  PHASES (spike_mode 1, --frames frames, default 400 = five of the spike's 80-frame cycles)
    for each of the spike's seven call sites: the whole call (the jsr to the label after it) and
    the profile span inside it (sfx_update -> sfx_update_end, sfx_play -> sfx_play_end), with the
    raster lines it ran on; the sound tick IRQ (spike_bottom -> irq_exit_rti) by kind of tick;
    where spike_bottom and sfx_update start (line, cycle).
  DISPLAY (spike_mode 3, set through the monitor, 256 frames)
    sfx_play by its three paths called on lines 100-110 with a badline (107) among them, at a
    start position that changes every frame: whole call and profile span, with a histogram.

Run from the repo root (build first: make GAME=sfx SRC_DIR=tests/engine/sfx):

    uv run --package budget-runner python tests/engine/sfx/measure.py [--prg ...] [--frames 400] [--out FILE]

About 20 s. --out writes the same text to a file: the committed copies are measure_results.txt
(DEBUG) and measure_results_release.txt (make BUILD=release GAME=sfx SRC_DIR=tests/engine/sfx,
then this script with --out; rebuild without BUILD=release afterwards for make test).
Exit code 1 if a path that should be constant isn't.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from budget_runner.session import MeasureError, Vice

REPO = Path(__file__).resolve().parents[3]
TICKS = ["spike_tick_idle", "spike_tick_slide", "spike_tick_start3", "spike_tick_other"]
PLAYS = ["spike_play_take", "spike_play_replace", "spike_play_keep"]
DISP = ["spike_disp_take", "spike_disp_replace", "spike_disp_keep"]


def stats(c):
    if not c:
        return "no passes"
    return (f"{min(c)} every pass ({len(c)})" if min(c) == max(c)
            else f"min {min(c)}, avg {sum(c) / len(c):.1f}, max {max(c)} ({len(c)} passes)")


def spans(events, sym, site, inner):
    """For every pass through call site `site`: (whole call, inner profile span, start line, end line)."""
    a, b, i0, i1 = sym[site], sym[site + "_end"], sym[inner], sym[inner + "_end"]
    res, start, s_in, in_cost = [], None, None, None
    for e in events:
        if e.pc == a:
            start, s_in, in_cost = e, None, None
        elif start is not None and e.pc == i0 and s_in is None:
            s_in = e.t
        elif start is not None and e.pc == i1 and s_in is not None and in_cost is None:
            in_cost = e.t - s_in
        elif start is not None and e.pc == b:
            res.append((e.t - start.t, in_cost, start.line, e.line))
            start = None
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prg", default=str(REPO / "build/sfx/sfx.prg"))
    ap.add_argument("--frames", type=int, default=400)
    ap.add_argument("--out")
    a = ap.parse_args()
    lines, bad = [], []

    def out(s=""):
        print(s, flush=True)
        lines.append(s)

    v = Vice(Path(a.prg), 20)
    try:
        sym = v.symbols
        debug = "sfx_shadow" in sym
        names = (["sfx_update", "sfx_update_end", "sfx_play", "sfx_play_end", "spike_bottom", "irq_exit_rti", "spike_frame"]
                 + [n + s for n in TICKS + PLAYS for s in ("", "_end")])
        addrs = [sym[n] for n in names]
        ev = v.trace(addrs, lambda e: sum(1 for x in e if x.pc == sym["spike_frame"]) > a.frames, "the phases trace")
        triple = int.from_bytes(v.mon.mem_get(sym["spike_triple_count"], sym["spike_triple_count"] + 1), "little")
        late = v.mon.mem_get(sym["irq_late_count"], sym["irq_late_count"])[0] if "irq_late_count" in sym else None

        out(f"engine/sfx.asm in tests/engine/sfx: {Path(a.prg).name}, {'DEBUG' if debug else 'release'} build. Raster cycles.")
        out(f"Code {sym['sfx_code_end'] - sym['sfx_start']} bytes (sfx_update {sym['sfx_play'] - sym['sfx_update']}, "
            f"sfx_play {sym['sfx_init'] - sym['sfx_play']}, sfx_init {sym['sfx_code_end'] - sym['sfx_init']}), state "
            f"{sym['sfx_state_end'] - sym['sfx_state']}" + (", shadow 25" if debug else "") + f"; effect tables "
            f"{sym['sfx_tables_end'] - sym['sfx_voice']} bytes ({sym['SFX_COUNT']} effects, {sym['SFX_STEPS']} steps).")
        out()
        out(f"PHASES, {a.frames} frames (spike_triple_count {triple}, irq_late_count {late})")
        out("  the tick: whole call (jsr sfx_update to the label after it) | profile span (sfx_update -> sfx_update_end)")
        for site in TICKS:
            r = spans(ev, sym, site, "sfx_update")
            whole, inner = [x[0] for x in r], [x[1] for x in r]
            ls = sorted({x[2] for x in r} | {x[3] for x in r})
            out(f"    {site:18s} {stats(whole):42s} | {stats(inner)}" + (f"   lines {ls[0]}-{ls[-1]}" if ls else ""))
            if site != "spike_tick_other" and (not whole or min(whole) != max(whole)):
                bad.append(f"{site} is not constant")
        other = Counter(x[1] for x in spans(ev, sym, "spike_tick_other", "sfx_update"))
        out(f"      spike_tick_other's profile spans: {dict(sorted(other.items()))}")
        allspan = [e2.t - e1.t for e1, e2 in zip(ev, ev[1:]) if e1.pc == sym["sfx_update"] and e2.pc == sym["sfx_update_end"]]
        out(f"    sfx_update -> sfx_update_end, every tick: {stats(allspan)}")
        out("  sfx_play, top border: whole call | profile span (sfx_play -> sfx_play_end)")
        for site in PLAYS:
            r = spans(ev, sym, site, "sfx_play")
            whole, inner = [x[0] for x in r], [x[1] for x in r]
            ls = sorted({x[2] for x in r} | {x[3] for x in r})
            out(f"    {site:18s} {stats(whole):42s} | {stats(inner)}" + (f"   lines {ls[0]}-{ls[-1]}" if ls else ""))
            if not whole or min(whole) != max(whole):
                bad.append(f"{site} is not constant")
        out("  the sound tick IRQ: spike_bottom -> irq_exit_rti, by the call site it took")
        cur, site_of = None, {sym[s]: s for s in TICKS}
        irq = {s: [] for s in TICKS}
        t0 = None
        for e in ev:
            if e.pc == sym["spike_bottom"]:
                t0, cur = e.t, None
            elif e.pc in site_of and t0 is not None:
                cur = site_of[e.pc]
            elif e.pc == sym["irq_exit_rti"] and t0 is not None and cur:
                irq[cur].append(e.t - t0)
                t0 = None
        for s in TICKS:
            out(f"    {s:18s} {stats(irq[s])}")
        every = [c for s in TICKS for c in irq[s]]
        out(f"    every tick: {stats(every)}")
        sb = [(e.line, e.cycle) for e in ev if e.pc == sym["spike_bottom"]]
        su = [(e.line, e.cycle) for e in ev if e.pc == sym["sfx_update"]]
        se = [(e.line, e.cycle) for e in ev if e.pc == sym["sfx_update_end"]]
        out(f"  spike_bottom starts on line {min(sb)[0]}-{max(sb)[0]}, cycle {min(c for _, c in sb)}-{max(c for _, c in sb)}; "
            f"sfx_update starts on line {min(su)[0]}-{max(su)[0]}; its rts is reached on line {min(se)[0]}-{max(se)[0]} "
            f"(latest: line {max(se)[0]} cycle {max(se)[1]})")
        if late:
            bad.append("irq_late_count is not 0")
        if triple < 1:
            bad.append("spike_triple_count is 0")

        # DISPLAY
        v.mon.mem_set(sym["spike_mode"], bytes([3]))
        names = ["sfx_play", "sfx_play_end", "spike_frame", "irq_dispatch"] + [n + s for n in DISP for s in ("", "_end")]
        ev = v.trace([sym[n] for n in names], lambda e: sum(1 for x in e if x.pc == sym["spike_frame"]) > 258,
                     "the display trace")
        first = next(i for i, e in enumerate(ev) if e.pc == sym["spike_disp_take"])
        ev = ev[first:]
        out()
        out("DISPLAY, 256 frames: sfx_play called on lines 100-110 (badline 107: 43 cycles stolen), no sprites")
        out("  whole call | profile span | start line")
        for site in DISP:
            r = spans(ev, sym, site, "sfx_play")
            whole, inner = [x[0] for x in r], [x[1] for x in r]
            out(f"    {site:20s} {stats(whole):40s} | {stats(inner)}   lines {min(x[2] for x in r)}-{max(x[3] for x in r)}")
            out(f"      whole calls: {dict(sorted(Counter(whole).items()))}")
        irqs = sum(1 for e in ev if e.pc == sym["irq_dispatch"] and 100 <= e.line <= 111)
        out(f"  IRQs dispatched on lines 100-111 during the trace: {irqs} (the spans above hold no IRQ)")
    finally:
        v.close()

    out()
    out("FAILED: " + "; ".join(bad) if bad else "OK")
    if a.out:
        Path(a.out).write_text("\n".join(lines) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL (jam/hang): {e}")
        sys.exit(2)
