"""Per-frame costs of the multiplexer's slow path and pinning in the multiplexer spike (M3 stage 4).

One trace (the budget runner's own Vice.trace and profile_costs, so figures match `make test`),
stopping at the mux_update, slow-path and IRQ labels, then per frame:

  - mux_update cost (IRQs inside it excluded), whether it was a fast frame
  - evictions (mux_ev_remove hits), and how many were made for a pinned sprite (mux_pin_fail hits)
  - idle-loop time left (spike_idle_start to the next spike_main), for the free-CPU promise
And per event: the pinned pre-pass (mux_pin_pass -> mux_pin_pass_end), one removal
(mux_ev_remove -> the next mux_slow_loop), a pinned fail's decision (mux_pin_fail ->
mux_ev_remove), the slow part of a frame (mux_slow -> mux_sel_done).

    uv run --package budget-runner python tests/engine/multiplexer/measure_pin.py [frames] [warmup] [prg]

Needs a build first: make GAME=multiplexer SRC_DIR=tests/engine/multiplexer
"""

import sys
from collections import Counter
from pathlib import Path

from budget_runner.evaluate import FRAME, profile_costs
from budget_runner.session import Vice

REPO = Path(__file__).resolve().parents[3]
LABELS = ["mux_update", "mux_update_end", "mux_update_fast", "mux_slow", "mux_sel_done",
          "mux_pin_pass", "mux_pin_pass_end", "mux_ev_remove", "mux_slow_loop", "mux_pin_fail",
          "mux_slow_fail", "spike_idle_start", "spike_main", "irq_dispatch", "irq_exit_rti"]
COUNTERS = [("mux_max_age", 1), ("mux_pin_drop_count", 1), ("mux_pin_excess_count", 1),
            ("mux_late_count", 1), ("irq_late_count", 1), ("spike_overrun_count", 1),
            ("spike_idle_min_normal", 2), ("spike_idle_min_stress", 2),
            ("spike_idle_min", 2),  # builds before the stage 4 labels
            ("spike_drop_total", 2),
            ("spike_flicker_frames", 2)]


def stats(xs) -> str:
    if not xs:
        return "(none)"
    return f"{min(xs):,} / {sum(xs) / len(xs):,.0f} / {max(xs):,}  (n={len(xs):,})"


def main() -> None:
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    warmup = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    prg = Path(sys.argv[3]) if len(sys.argv) > 3 else REPO / "build" / "multiplexer" / "multiplexer.prg"
    v = Vice(prg, warmup)
    try:
        a = {n: v.addr(n) for n in LABELS if n in v.symbols}  # stage 3 builds lack the pin labels
        for n in LABELS:
            a.setdefault(n, -1)
        upd = a["mux_update"]
        ev = v.trace([x for x in a.values() if x >= 0], lambda e: sum(1 for x in e if x.pc == upd) > frames, "mux_update")
        mem = {n: int.from_bytes(v.mon.mem_get(v.addr(n), v.addr(n) + s - 1), "little")
               for n, s in COUNTERS if n in v.symbols}
    finally:
        v.close()
    d, r = a["irq_dispatch"], a["irq_exit_rti"]

    def cost(s, e):
        return profile_costs(ev, a[s], a[e], d, r)

    print(f"multiplexer (stage 4 probe): {frames} mux_update passes after {warmup} warm-up frames")
    print("  counters:", ", ".join(f"{n} {x}" for n, x in mem.items()), "(x 16: " + ", ".join(f"{n} {mem[n] * 16:,}" for n in mem if n.startswith("spike_idle_min")) + ")")
    print("  min / avg / max, raster cycles, IRQs excluded:")
    print("   mux_update, all        ", stats(cost("mux_update", "mux_update_end")))
    print("   mux_update, fast frames", stats(cost("mux_update", "mux_update_fast")))
    print("   pinned pre-pass        ", stats(cost("mux_pin_pass", "mux_pin_pass_end")))
    print("   slow part (mux_slow -> mux_sel_done)", stats(cost("mux_slow", "mux_sel_done")))
    print("   one removal (mux_ev_remove -> mux_slow_loop)", stats(cost("mux_ev_remove", "mux_slow_loop")))
    print("   pinned decision (mux_pin_fail -> mux_ev_remove)", stats(cost("mux_pin_fail", "mux_ev_remove")))
    print("   fail decision, any (mux_slow_fail -> mux_ev_remove)", stats(cost("mux_slow_fail", "mux_ev_remove")))

    # Per frame: from each mux_update to the next.
    rows, cur = [], None
    for e in ev:
        if e.pc == upd:
            if cur:
                rows.append(cur)
            cur = {"t": e.t, "ev": 0, "pin": 0, "fail": 0, "fast": False, "idle": None, "idle_t": None}
        elif cur is None:
            continue
        elif e.pc == a["mux_ev_remove"]:
            cur["ev"] += 1
        elif e.pc == a["mux_pin_fail"]:
            cur["pin"] += 1
        elif e.pc == a["mux_slow_fail"]:
            cur["fail"] += 1
        elif e.pc == a["mux_update_fast"]:
            cur["fast"] = True
        elif e.pc == a["spike_idle_start"]:
            cur["idle_t"] = e.t
        elif e.pc == a["spike_main"] and cur["idle_t"] is not None and cur["idle"] is None:
            cur["idle"] = e.t - cur["idle_t"]
    ucost = cost("mux_update", "mux_update_end")
    for row, c in zip(rows, ucost):
        row["cost"] = c
    rows = [x for x in rows if "cost" in x]
    slow = [x for x in rows if not x["fast"]]
    print(f"  frames: {len(rows)}, fast {len(rows) - len(slow)}, slow {len(slow)}")
    print("  evictions per slow frame:", sorted(Counter(x["ev"] for x in slow).items()))
    print("  pinned fails per frame:", sorted(Counter(x["pin"] for x in rows).items()))
    print("  idle raster span per frame (incl. IRQs):", stats([x["idle"] for x in rows if x["idle"]]))
    print("  10 most expensive mux_update frames (cost, fails, evictions, pinned fails, idle span, frame):")
    for x in sorted(rows, key=lambda x: -x["cost"])[:10]:
        print(f"    {x['cost']:>6,}  {x['fail']:>3} {x['ev']:>3} {x['pin']:>3}  {x['idle']}  {x['t'] // FRAME}")


if __name__ == "__main__":
    main()
