"""Zone IRQ per-slot cost and per-frame IRQ time of the `multiplexer` spike, for any build of it
(M3 follow-up, task B: the release build, whose zone blocks are different code at a different page
offset). It measures the multiplexer spike, not the multiplexer_edge probe.

One trace through the budget runner's Vice session (so raster times are the same as `make test`),
stopping at each zone block's entry (mux_zone_0-7 and the mixed set mux_zone_m0-7: one stop per
slot written by a zone IRQ), mux_irq_zone, mux_irq_top, mux_zone_done, mux_zone_rearm,
irq_dispatch and irq_exit_rti. It prints, in raster cycles:

  - one zone slot, block to block (entry of one block to entry of the next in the same IRQ): the
    MINIMUM is the code's own cost for a slot whose successor is free already (DMA and the in-IRQ
    wait for the next sprite to free can only add), with how many slots sit on it, and the spread
  - mux_irq_zone -> irq_exit_rti per IRQ, mux_irq_top -> irq_exit_rti, slots per zone IRQ
  - all IRQ time per frame (the runner's definition: irq_dispatch - 7 to irq_exit_rti + 6)

Run from the repo root:

    make BUILD=release GAME=multiplexer SRC_DIR=tests/engine/multiplexer
    uv run --package budget-runner python tests/engine/multiplexer_edge/irq_costs.py [frames=3000] [warmup=100] [--mixed] [--prg PATH]
    make GAME=multiplexer SRC_DIR=tests/engine/multiplexer      # put the DEBUG build back: make test uses it

  --mixed  sets mux_flags bit 0 of the odd-numbered sprites before the trace (mixed multicolour:
           the mux_zone_m blocks, which also write $D01C)
  --prg    another build (default build/multiplexer/multiplexer.prg; its main.vs must be beside it)

Measured 2026-10-01, VICE 3.10 x64sc PAL, stage 4 engine (HEAD 0ef44d8), frames after 100 warm-up,
raster cycles, min / avg / max:

                                     release, 20,000      release, 3,000     DEBUG, 3,000
  one zone slot, block to block      53 / 102 / 295       53 / 102 / 294     62 / 107 / 301
    slots on the minimum             35,073 of 198,897    4,869 of 29,484    4,965 of 29,526
  mux_irq_zone -> irq_exit_rti       146 / 542 / 2,752    146 / 536 / 1,518  155 / 567 / 1,528
  slots per zone IRQ                 1 / 4 / 14           1 / 4 / 8          1 / 4 / 8
  mux_irq_top -> irq_exit_rti        378 x19,972, 393 x28 378 x2,999, 393 x1 378 x2,999, 393 x1
  all IRQ time per frame             522 / 2,147 / 3,700  535 / 2,150 / 3,653 535 / 2,231 / 3,691
  (DEBUG over 20,000 frames, the Technical Director's stage 4 trace: zone IRQ 155 / 574 / 2,763,
  per frame 522 / 2,227 / 3,779.)

  --mixed, 1,000 frames              release                                 DEBUG
  one zone slot, block to block      61 / 107 / 294 (1,427 on the minimum)   70 / 113 / 313 (1,470)
  mux_irq_zone -> irq_exit_rti       154 / 557 / 1,465                       163 / 596 / 1,494
  all IRQ time per frame             535 / 2,167 / 3,541                     535 / 2,256 / 3,624

20,000 frames take about 3 minutes.
"""

import sys
from collections import Counter
from pathlib import Path

from budget_runner.evaluate import irq_time_by_frame, profile_costs
from budget_runner.session import Vice

REPO = Path(__file__).resolve().parents[3]


def stats(xs: list[int]) -> str:
    return f"{min(xs):,} / {sum(xs) / len(xs):,.0f} / {max(xs):,}  (n={len(xs):,})" if xs else "(none)"


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    mixed = "--mixed" in sys.argv
    prg = REPO / "build" / "multiplexer" / "multiplexer.prg"
    if "--prg" in sys.argv:
        prg = Path(sys.argv[sys.argv.index("--prg") + 1])
        args.remove(str(prg))
    frames = int(args[0]) if args else 3000
    warmup = int(args[1]) if len(args) > 1 else 100
    v = Vice(prg, warmup)
    try:
        s = v.symbols
        debug = "mux_late_count" in s
        if mixed:
            cp = v.mon.checkpoint_set(s["mux_update"], s["mux_update"])
            v.mon.exit()
            v.mon.wait_stopped(5)
            v.mon.checkpoint_delete(cp.number)
            flags = v.mon.mem_get(s["mux_flags"], s["mux_flags"] + 23)
            v.mon.mem_set(s["mux_flags"], bytes((f & 0xFE) | (i & 1) for i, f in enumerate(flags)))
            for _ in range(4):                  # both buffers rebuilt in the new mode
                v.trace([s["mux_irq_top"]], lambda e: len(e) >= 2, "mux_irq_top")
        blocks = {s[f"mux_zone_{m}{j}"]: (m, j) for m in ("", "m") for j in range(8)}
        top, zone, done, rearm, d, r = (s[n] for n in ("mux_irq_top", "mux_irq_zone", "mux_zone_done",
                                                       "mux_zone_rearm", "irq_dispatch", "irq_exit_rti"))
        seen = [0, 0]                           # events counted so far, mux_irq_top hits among them

        def enough(e) -> bool:                  # incremental: a rescan per stop is quadratic
            seen[1] += sum(1 for x in e[seen[0]:] if x.pc == top)
            seen[0] = len(e)
            return seen[1] > frames

        ev = v.trace(list(blocks) + [top, zone, done, rearm, d, r], enough, "mux_irq_top")
        counters = {n: v.mon.mem_get(s[n], s[n])[0] for n in ("mux_late_count", "irq_late_count",
                                                                "spike_overrun_count") if n in s}
    finally:
        v.close()

    slot = {"": [], "m": []}                    # block to block, by block set
    last = {"": [], "m": []}                    # last block of an IRQ to mux_zone_done / mux_zone_rearm
    per_irq, n = [], 0
    for a, b in zip(ev, ev[1:]):
        if a.pc in blocks:
            n += 1
            if b.pc in blocks:
                slot[blocks[a.pc][0]].append(b.t - a.t)
            elif b.pc in (done, rearm):
                last[blocks[a.pc][0]].append(b.t - a.t)
        elif a.pc == r and n:
            per_irq.append(n)
            n = 0
    print(f"{prg}  ({'DEBUG' if debug else 'release'} build{', mixed multicolour' if mixed else ''}), "
          f"{frames} frames after {warmup}; raster cycles, min / avg / max")
    for m, name in (("", "uniform blocks"), ("m", "mixed blocks")):
        xs = slot[m]
        if not xs:
            continue
        c = Counter(xs)
        lo = min(xs)
        srt = sorted(xs)
        print(f"  one zone slot, block to block, {name}: {stats(xs)}")
        print(f"      minimum {lo}: {c[lo]:,} slots ({100 * c[lo] / len(xs):.1f}%); "
              f"median {srt[len(xs) // 2]}, 90% <= {srt[len(xs) * 9 // 10]}, 99% <= {srt[len(xs) * 99 // 100]}")
        print(f"      lowest values: " + ", ".join(f"{k} x{c[k]}" for k in sorted(c)[:6]))
        print(f"      last slot of an IRQ, block entry to mux_zone_done / mux_zone_rearm: {stats(last[m])}")
    print(f"  slots per zone IRQ: {stats(per_irq)}")
    print(f"  mux_irq_zone -> irq_exit_rti: {stats(profile_costs(ev, zone, r))}")
    tops = Counter(profile_costs(ev, top, r))
    print("  mux_irq_top -> irq_exit_rti: " + ", ".join(f"{k} x{n:,}" for k, n in sorted(tops.items())))
    print(f"  all IRQ time per frame: {stats(irq_time_by_frame(ev, d, r, frames - 1))}")
    print("  " + (", ".join(f"{k} = {x}" for k, x in counters.items()) or "(no DEBUG counters in this build)"))


if __name__ == "__main__":
    main()
