"""Measured costs of Swarm stage 2 part A (M4): the formation with the player sweeping and firing.

Builds the AUTOPLAY budget build (tests/games/swarm/main.asm: full formation drifting every frame
as in loop 3, scripted stick sweeping with fire held, three panel fields redrawn every frame) the
way `make test` does, and measures, in raster cycles with IRQ time excluded (the budget runner's
profile_excl_irq, engine/README.md#budget-units):

  formation_update -> formation_update_end   (budget 750, memory-map.md row 5)
  game_update -> game_update_end             (budget 5,765)
  mux_update -> mux_update_fast              (frames with no overflow)
  mux_update -> mux_update_end               (all frames)

then runs FRAMES more frames and reads the DEBUG counters: game_overrun_count, game_idle_min,
game_flicker_frames (frames in which the multiplexer dropped or evicted a sprite), mux_max_age,
mux_late_count, irq_late_count. This stands in for the stage 2 checks of budget.json, which stay
PENDING until part B bumps "stage" (they include collide_update, which doesn't exist yet).

Run from the repo root (about 1 minute):

    uv run --package budget-runner python tests/games/swarm/stage2a_costs.py

Results of the last run: tests/games/swarm/stage2a_costs.txt.
"""

import sys

from budget_runner.evaluate import SampleCounter, profile_costs
from budget_runner.session import Vice, build_program
from vice_monitor import run_frames

SAMPLES, FRAMES, WARMUP = 600, 3000, 400
SPANS = [("formation_update", "formation_update_end", 750),
         ("game_update", "game_update_end", 5765),
         ("mux_update", "mux_update_fast", 7400),
         ("mux_update", "mux_update_end", 13000)]


def main() -> int:
    prg = build_program("swarm_budget", "tests/games/swarm", ["games/swarm/src"])
    v = Vice(prg, WARMUP)
    bad = False
    try:
        d, r = v.addr("irq_dispatch"), v.addr("irq_exit_rti")
        for start, end, limit in SPANS:
            a, b = v.addr(start), v.addr(end)
            counter = SampleCounter(a, b)
            events = v.trace([a, b, d, r], lambda ev: counter.update(ev) >= SAMPLES, f"{start} -> {end}")
            costs = profile_costs(events, a, b, d, r)[:SAMPLES]
            lines = sorted({e.line for e in events if e.pc == a}), sorted({e.line for e in events if e.pc == b})
            ok = max(costs) <= limit
            bad |= not ok
            print(f"[{'PASS' if ok else 'FAIL'}] {start} -> {end}: {len(costs)} passes, min {min(costs)}, "
                  f"avg {sum(costs) / len(costs):.1f}, max {max(costs)} raster cycles (limit {limit}); "
                  f"starts on raster lines {lines[0][0]}-{lines[0][-1]}, ends on {lines[1][0]}-{lines[1][-1]}")
        run_frames(v.mon, FRAMES)

        def rd(label, n=1):
            a = v.addr(label)
            return int.from_bytes(v.mon.mem_get(a, a + n - 1), "little")

        idle = rd("game_idle_min", 2) * 16
        vals = {k: rd(k, n) for k, n in (("game_overrun_count", 1), ("game_flicker_frames", 2), ("mux_max_age", 1),
                                         ("mux_late_count", 1), ("irq_late_count", 1))}
        ok = idle >= 935 and not any(vals.values())
        bad |= not ok
        print(f"[{'PASS' if ok else 'FAIL'}] after {FRAMES} more frames: idle in the worst frame {idle} cycles "
              f"(required >= 935); " + ", ".join(f"{k} {x}" for k, x in vals.items()) + " (all expected 0)")
    finally:
        v.close()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
