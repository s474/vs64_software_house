"""A longer look at the routines the stage 4 tuning loads harder (Swarm, M4): diver_update,
collide_update and game_update on the AUTOPLAY budget build (wave 12: pattern 3 at loop 3, 3 divers,
launch interval 32 since the tuning, 50 before), SAMPLES passes each instead of `make test`'s 600.

Why: after the tuning `make test` read diver_update at 1,268 against its limit of 1,350 (987 before
the tuning, same 600 samples). A routine in the display lands on different raster lines every frame,
so 600 samples are a look, not a proof (budget.json's notes); this is ten times the look, without
running make test-long. Raster cycles, IRQ time excluded, as stage4_costs.py's part 1 measures them
(its span() is used).

Run from the repo root (about 2 minutes):

    uv run --package budget-runner python tests/games/swarm/tuning_long_look.py | tee tests/games/swarm/tuning_long_look.txt

Results of the last run: tests/games/swarm/tuning_long_look.txt.

The limits are the budget's since the long run (memory-map.md "Frame budget", 2026-10-03):
diver_update 2,020 (1,350 until stage 5), collide_update 2,750 (2,825), game_update 6,720 (6,050).
tuning_long_look.txt is from the run of 2026-10-02, against the old limits, and was not rerun
when they moved.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from budget_runner.session import MeasureError, Vice, build_program  # noqa: E402
from stage4_costs import WARMUP, span  # noqa: E402

SAMPLES = 6000
SPANS = [("diver_update", "diver_update_end", 2020), ("collide_update", "collide_update_end", 2750),
         ("game_update", "game_update_end", 6720)]


def main() -> int:
    print(f"# uv run --package budget-runner python tests/games/swarm/tuning_long_look.py   (the AUTOPLAY budget build, "
          f"VICE 3.10 x64sc PAL; after the stage 4 tuning; {SAMPLES} passes of each span)")
    prg = build_program("swarm_budget", "tests/games/swarm", ["games/swarm/src"])
    v = Vice(prg, WARMUP)
    bad = False
    try:
        for start, end, limit in SPANS:
            costs, la, lb = span(v, start, end, SAMPLES)
            top = sorted(costs)[-5:]
            near = sum(1 for c in costs if c > 0.9 * limit)
            ok = max(costs) <= limit
            bad |= not ok
            print(f"[{'PASS' if ok else 'FAIL'}] AUTOPLAY {start} -> {end}: {len(costs)} passes, min {min(costs)}, avg "
                  f"{sum(costs) / len(costs):.1f}, max {max(costs)} raster cycles (limit {limit}); the five largest {top}; "
                  f"{near} passes above 90% of the limit ({int(0.9 * limit)}); starts on raster lines {la[0]}-{la[-1]}, "
                  f"ends on {lb[0]}-{lb[-1]}")
    finally:
        v.close()
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL: {e}")
        sys.exit(1)
