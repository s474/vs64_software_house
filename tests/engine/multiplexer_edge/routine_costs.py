"""Costs behind the routine headers of engine/multiplexer.asm and engine/multiplexer_flicker.asm
(M3 follow-up, task A). It measures the `multiplexer` spike, not the multiplexer_edge probe: it lives
here because this folder is the raster-engineer's for the follow-up.

Part 1, mux_select per slot (the counted figures in mux_select's header, checked by measurement).
  Stops at mux_sel_l1 and mux_sel_l2 (the top of each loop iteration: X = the slot), at the end of
  the fast walk (mux_sel_done / mux_sel_fail) and at irq_dispatch. The time from one iteration's
  stop to the next is that slot's cost in raster cycles. Sprite DMA and badlines can only add to
  it, and an iteration with an IRQ inside is thrown away, so the MINIMUM of each class is the code's
  own CPU cost. Classes, decided from the slot arrays read at the end of the walk:
    loop 1 (slots 0-7), X bit 8 clear / set
    loop 2 new IRQ (free + MUX_IRQ_LINES >= done[k-1]), X bit 8 clear / set
    loop 2 carry on, done = y (beq) / done < y (bcc), X bit 8 clear / set
  It prints min, how many samples sit on the min, and the next values up.

Part 2, the slow-path helpers with no label at their end (start label -> their rts), IRQs inside
  the span excluded, as the budget runner's profile_excl_irq does: mux_fill_kept, mux_rebuild (and
  its first 43 bytes, the restore of the pinned ages), mux_mixed_d01c, mux_set_blocks.
  The spike as shipped is uniform hires, so the last two never run: after the first half of the
  frames the script sets mux_flags bit 0 of the odd-numbered sprites (mixed multicolour) while the
  machine is stopped at mux_update, and flips between that and all-hires every 25 frames, so
  mux_set_blocks runs twice per flip (once per buffer).

Run from the repo root (build first: make GAME=multiplexer SRC_DIR=tests/engine/multiplexer):

    uv run --package budget-runner python tests/engine/multiplexer_edge/routine_costs.py \
        [frames=600] [warmup=100] [prg=build/multiplexer/multiplexer.prg]

Measured 2026-10-01, VICE 3.10 x64sc PAL, DEBUG build of the stage 4 engine (HEAD 0ef44d8), 600
frames after 100 (about 20 s):

  mux_select per slot: min, samples on the min, next values up
    loop 1, X bit 8 clear / set                        74 (x1,764) / 76 (x488); next 78-80
    loop 1, the last (falls into loop 2), clear / set  76 (x264) / 78 (x77)
    loop 2 new IRQ, clear / set                        108 (x583) / 110 (x206); next 112-115
    loop 2 carry on, done = y (beq), clear / set       122 (x13) / 124 (x5)
    loop 2 carry on, done < y (bcc), clear / set       124 (x425) / 126 (x135)
  Equal to the instruction counts with the three page crossings (two reads of mux_s_done - 1,x and
  the taken bcc !carry). The old header said 68-70 / 108 / 124.

  Helpers, raster cycles, IRQs excluded, min / avg / max
    mux_fill_kept -> rts                               149 / 356 / 753      (n=335)
    mux_rebuild -> rts                                 542 / 1,162 / 2,170  (n=276)
    mux_rebuild, pinned ages restored                  60 / 75 / 160        (n=276)
    mux_mixed_d01c -> rts                              444 / 1,161 / 1,996  (n=150)
    mux_set_blocks -> rts                              1,136 / 1,289 / 1,611 (n=24)
  mux_late_count, irq_late_count, spike_overrun_count: 0
"""

import sys
from collections import Counter, defaultdict
from pathlib import Path

from budget_runner.evaluate import FRAME, profile_costs
from budget_runner.session import Vice

REPO = Path(__file__).resolve().parents[3]
CPL = 63
MUX_FREE_AFTER, MUX_IRQ_LINES, MUX_WRITE_LINES = 22, 1, 2


def low_hist(values: list[int], n: int = 4) -> str:
    c = Counter(values)
    return ", ".join(f"{k} x{c[k]}" for k in sorted(c)[:n])


def stats(xs: list[int]) -> str:
    if not xs:
        return "(never ran)"
    return f"{min(xs):,} / {sum(xs) / len(xs):,.0f} / {max(xs):,}  (n={len(xs):,})"


def select_slots(v: Vice, frames: int) -> None:
    s, mon = v.symbols, v.mon
    l1, l2, done, fail, disp = (s[n] for n in ("mux_sel_l1", "mux_sel_l2", "mux_sel_done", "mux_sel_fail",
                                               "irq_dispatch"))
    cps = [mon.checkpoint_set(a, a) for a in (l1, l2, done, fail, disp)]
    classes: dict[str, list[int]] = defaultdict(list)
    hits: list[tuple[int, int, int]] = []       # (pc, t, x) of this frame's walk
    irqs: list[int] = []
    base, prev, seen, walking = 0, -1, 0, False
    try:
        while seen < frames:
            mon.exit()
            if not mon.wait_stopped(5):
                raise SystemExit("timed out")
            r = mon.registers()
            t = r["LIN"] * CPL + r["CYC"]
            if t < prev:
                base += FRAME
            prev = t
            t += base
            pc = r["PC"]
            if pc == disp:
                irqs.append(t)
                continue
            if pc in (l1, l2):
                if pc == l1 and not walking:
                    hits, irqs, walking = [], [], True
                if walking:
                    hits.append((pc, t, r["X"]))
                continue
            if not walking:
                continue                        # mux_sel_done again, after the slow path
            walking = False
            seen += 1
            y, free, dn, d010 = (mon.mem_get(s[n], s[n] + 63) for n in
                                 ("mux_s_y", "mux_s_free", "mux_s_done", "mux_s_d010"))
            for (pc0, t0, k), (pc1, t1, k1) in zip(hits, hits[1:]):
                if k1 != k + 1 or any(t0 < i < t1 for i in irqs):
                    continue
                bit = "X bit 8 set" if d010[k] & (1 << (k & 7)) else "X bit 8 clear"
                if pc0 == l1:
                    name = f"loop 1{' (last: falls into loop 2)' if pc1 == l2 else ''}, {bit}"
                elif free[k] + MUX_IRQ_LINES >= dn[k - 1]:
                    name = f"loop 2 new IRQ, {bit}"
                else:
                    name = f"loop 2 carry on, {'done = y (beq)' if dn[k] == y[k] else 'done < y (bcc)'}, {bit}"
                classes[name].append(t1 - t0)
    finally:
        for c in cps:
            mon.checkpoint_delete(c.number)
    print(f"mux_select per slot, {frames} frames: min (the code's own cost), samples on the min, next values")
    for name in sorted(classes):
        xs = classes[name]
        print(f"  {name:55s} min {min(xs):3d}   {low_hist(xs)}   (n={len(xs):,})")


def helpers(v: Vice, frames: int) -> None:
    s, mon = v.symbols, v.mon
    spans = {
        "mux_fill_kept -> rts": (s["mux_fill_kept"], s["mux_rebuild"] - 1),
        "mux_rebuild -> rts": (s["mux_rebuild"], s["mux_mixed_d01c"] - 1),
        "mux_rebuild, pinned ages restored (first 43 bytes)": (s["mux_rebuild"], s["mux_rebuild"] + 43),
        "mux_mixed_d01c -> rts": (s["mux_mixed_d01c"], s["mux_set_blocks"] - 1),
        "mux_set_blocks -> rts": (s["mux_set_blocks"], s["mux_irq_top"] - 1),
    }
    for name, (a, b) in spans.items():
        if name.endswith("rts") and mon.mem_get(b, b)[0] != 0x60:
            raise SystemExit(f"{name}: ${b:04x} is not an rts: the layout changed")
    upd, d, r = s["mux_update"], s["irq_dispatch"], s["irq_exit_rti"]
    flags = bytearray(mon.mem_get(s["mux_flags"], s["mux_flags"] + 23))
    addrs = [upd, d, r] + [x for ab in spans.values() for x in ab]
    state = {"n": 0, "mixed": False}

    def done(ev) -> bool:
        if not ev or ev[-1].pc != upd:
            return False
        state["n"] += 1
        n = state["n"]
        if n > frames // 2 and (n - frames // 2) % 25 == 1:      # stopped at mux_update: no race
            state["mixed"] = not state["mixed"]
            new = bytes((f & 0xFE) | (i & 1 if state["mixed"] else 0) for i, f in enumerate(flags))
            mon.mem_set(s["mux_flags"], new)
        return n > frames

    ev = v.trace(addrs, done, "mux_update")
    print(f"\nSlow-path helpers, raster cycles, IRQs inside excluded, min / avg / max, {frames} frames "
          f"(second half flips between all-hires and mixed multicolour every 25 frames):")
    for name, (a, b) in spans.items():
        print(f"  {name:52s} {stats(profile_costs(ev, a, b, d, r))}")
    for n in ("mux_late_count", "irq_late_count", "spike_overrun_count"):
        if n in s:
            print(f"  {n} = {mon.mem_get(s[n], s[n])[0]}")


def main() -> None:
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    warmup = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    prg = Path(sys.argv[3]) if len(sys.argv) > 3 else REPO / "build" / "multiplexer" / "multiplexer.prg"
    v = Vice(prg, warmup)
    try:
        select_slots(v, frames)
        helpers(v, frames)
    finally:
        v.close()


if __name__ == "__main__":
    main()
