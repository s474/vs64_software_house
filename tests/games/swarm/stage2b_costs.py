"""Measured costs of Swarm stage 2 part B (M4): player shots against the formation, explosions, score.

Part 1, the AUTOPLAY budget build (tests/games/swarm/main.asm, built the way `make test` does: full
formation drifting every frame as in loop 3, scripted stick sweeping with fire held so 2 shots are
in flight, three panel fields redrawn every frame; a hit is detected, scored and the shot removed
but the enemy stays, so the formation is always full). Raster cycles, IRQ time excluded (the budget
runner's profile_excl_irq, engine/README.md#budget-units), SAMPLES passes each, with the raster
lines each span started and ended on:

  collide_update -> collide_update_end       (budget 2,825, memory-map.md row 8; part B's trigger for
                                              the grid fallback: max over 2,050)
  formation_update -> formation_update_end   (budget 750, row 5)
  player_update, stars_update                (budgets 200 and 100: after the collisions now, so in
                                              the display for the first time)
  game_update -> game_update_end             (budget 6,115)
  mux_update -> mux_update_fast / _end       (the engine's limits)

then FRAMES more frames and the DEBUG counters.

Part 2, the game's DEBUG build (build/swarm), for what AUTOPLAY leaves out because nothing dies
there. The states are set through the monitor at game_update_end, then the game runs by itself:

  explosions   4 enemies put in ENEMY_EXPLODING with timer 16 and all 4 explosion slots taken,
               zp_loop = 3 (a drift step every frame): formation_update over the 16 frames that
               follow (15 animating all four, the 16th ending all four), EXPL_RUNS times in a row, so
               the passes include drift turns and animation swaps
  two hits     both shots placed so that, after their move in the next frame, shot 0 is inside
               enemy 0 (row 0, column 0: the last target of the scan, after 12 rejects and 6 full
               tests) and shot 1 inside enemy 12 (row 2, column 0: 6 full tests): collide_update
               for that one frame, both hits answered (score, explosion start). HIT_RUNS times
  free         no shot in flight: collide_update's fixed cost

Run from the repo root (about 2 minutes):

    uv run --package budget-runner python tests/games/swarm/stage2b_costs.py

Results of the last run: tests/games/swarm/stage2b_costs.txt.
"""

import sys

from budget_runner.evaluate import SampleCounter, profile_costs
from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice, build_program
from vice_monitor import CPU_OP_EXEC, run_frames

SAMPLES, FRAMES, WARMUP = 600, 3000, 400
EXPL_RUNS, HIT_RUNS = 16, 8
SPANS = [("collide_update", "collide_update_end", 2050, "the fallback trigger; budget 2,825"),
         ("formation_update", "formation_update_end", 750, "budget"),
         ("player_update", "player_update_end", 200, "budget"),
         ("stars_update", "stars_update_end", 100, "budget"),
         ("game_update", "game_update_end", 6115, "budget"),
         ("mux_update", "mux_update_fast", 7400, "engine limit; average <= 5,000"),
         ("mux_update", "mux_update_end", 13000, "engine limit")]
ENEMY0, MUX_OFF, EXPLODING = 6, 0xFF, 0x83


def span(v, start, end, samples):
    """(costs, start lines, end lines) of `samples` passes of start -> end, IRQs excluded."""
    d, r = v.addr("irq_dispatch"), v.addr("irq_exit_rti")
    a, b = v.addr(start), v.addr(end)
    counter = SampleCounter(a, b)
    events = v.trace([a, b, d, r], lambda ev: counter.update(ev) >= samples, f"{start} -> {end}")
    costs = profile_costs(events, a, b, d, r)[:samples]
    return costs, sorted({e.line for e in events if e.pc == a}), sorted({e.line for e in events if e.pc == b})


def show(tag, start, end, costs, la, lb, limit, what):
    ok = max(costs) <= limit
    print(f"[{'PASS' if ok else 'FAIL'}] {tag}{start} -> {end}: {len(costs)} passes, min {min(costs)}, "
          f"avg {sum(costs) / len(costs):.1f}, max {max(costs)} raster cycles (limit {limit}: {what}); "
          f"starts on raster lines {la[0]}-{la[-1]}, ends on {lb[0]}-{lb[-1]}")
    return ok


def main() -> int:
    bad = False

    # Part 1: the AUTOPLAY budget build
    prg = build_program("swarm_budget", "tests/games/swarm", ["games/swarm/src"])
    v = Vice(prg, WARMUP)
    try:
        for start, end, limit, what in SPANS:
            costs, la, lb = span(v, start, end, SAMPLES)
            bad |= not show("AUTOPLAY ", start, end, costs, la, lb, limit, what)
        run_frames(v.mon, FRAMES)

        def rd(label, n=1):
            a = v.addr(label)
            return int.from_bytes(v.mon.mem_get(a, a + n - 1), "little")

        idle = rd("game_idle_min", 2) * 16
        vals = {k: rd(k, n) for k, n in (("game_overrun_count", 1), ("game_flicker_frames", 2), ("mux_max_age", 1),
                                         ("mux_late_count", 1), ("irq_late_count", 1))}
        score = v.mon.mem_get(v.addr("game_score"), v.addr("game_score") + 2).hex()
        ok = idle >= 585 and not any(vals.values())
        bad |= not ok
        print(f"[{'PASS' if ok else 'FAIL'}] AUTOPLAY after {FRAMES} more frames: idle in the worst frame {idle} cycles "
              f"(required >= 585); " + ", ".join(f"{k} {x}" for k, x in vals.items()) + " (all expected 0); "
              f"score {score} (hits are scored: it stops at 999990), enemies alive {rd('zp_enemies_alive')}")
    finally:
        v.close()

    # Part 2: the game build, with states set through the monitor
    prg = build_program("swarm")
    v = Vice(prg, 100)
    try:
        mon, sym = v.mon, v.symbols
        end = sym["game_update_end"]

        def stop_at_frame_end():
            cp = mon.checkpoint_set(end, end, CPU_OP_EXEC)
            mon.exit()
            if not mon.wait_stopped(STOP_TIMEOUT):
                mon.ping()
                raise MeasureError("game_update_end not reached")
            mon.checkpoint_delete(cp.number)

        def poke(label, data, off=0):
            mon.mem_set(sym[label] + off, bytes(data))

        def peek(label, n=1, off=0):
            return mon.mem_get(sym[label] + off, sym[label] + off + n - 1)

        # free: no shot in flight
        costs, la, lb = span(v, "collide_update", "collide_update_end", 50)
        bad |= not show("game, no shot in flight: ", "collide_update", "collide_update_end", costs, la, lb, 2050,
                        "the fallback trigger")

        # two hits in one frame, each at the far end of its scan
        hits = []
        for _ in range(HIT_RUNS):
            stop_at_frame_end()
            poke("zp_state_timer", [1])            # the game's own respawn: all 18 parked next frame
            stop_at_frame_end()
            stop_at_frame_end()
            poke("zp_drift_timer", [2])            # no drift step in the next frame: X stays as read
            xl, xh = peek("mux_x_lo", 18, ENEMY0), peek("mux_x_hi", 18, ENEMY0)
            ys = peek("mux_y", 18, ENEMY0)
            for shot, e in ((0, 0), (1, 12)):
                poke("mux_x_lo", [xl[e]], 4 + shot)
                poke("mux_x_hi", [xh[e]], 4 + shot)
                poke("mux_y", [ys[e] + 5 + 8], 4 + shot)    # after the move: 5 lines below the enemy's Y
            poke("zp_player_cooldown", [5])        # the player doesn't fire into the measurement
            score0 = peek("game_score", 3).hex()
            costs, la, lb = span(v, "collide_update", "collide_update_end", 1)
            st = peek("enemy_state", 18)
            if st[0] != EXPLODING or st[12] != EXPLODING or list(peek("mux_y", 2, 4)) != [MUX_OFF, MUX_OFF]:
                raise MeasureError(f"the two hits didn't happen: states {st.hex()}")
            hits.append((costs[0], la[0], lb[0], score0, peek("game_score", 3).hex()))
        costs = [h[0] for h in hits]
        ok = max(costs) <= 2050
        bad |= not ok
        print(f"[{'PASS' if ok else 'FAIL'}] game, two hits in one frame (enemy 0 after 12 rejects + 6 full tests, enemy 12 "
              f"after 6 full tests; score and explosion start for both): collide_update -> collide_update_end, "
              f"{len(costs)} frames: min {min(costs)}, max {max(costs)} raster cycles (limit 2050: the fallback trigger); "
              f"started on lines {min(h[1] for h in hits)}-{max(h[1] for h in hits)}, ended on "
              f"{min(h[2] for h in hits)}-{max(h[2] for h in hits)}; score {hits[0][3]} -> {hits[0][4]} in the first")

        # explosions: all 4 slots animating, EXPL_RUNS explosions of 15 animated frames each
        stop_at_frame_end()
        poke("zp_state_timer", [1])
        stop_at_frame_end()
        stop_at_frame_end()
        poke("zp_loop", [3])
        four, costs, la, lb = [0, 7, 14, 17], [], [], []
        for _ in range(EXPL_RUNS):
            stop_at_frame_end()
            for e in four:
                poke("enemy_state", [EXPLODING], e)
                poke("enemy_timer", [16], e)
            poke("explosion_enemy", four)
            poke("zp_enemies_alive", [18])         # never 0: no respawn during the run
            c, a, b = span(v, "formation_update", "formation_update_end", 16)
            if list(peek("explosion_enemy", 4)) != [0xFF] * 4 or peek("enemy_state", 1, 17)[0] != 0:
                raise MeasureError("the 4 explosions didn't run their 16 frames")
            costs, la, lb = costs + c, la + a, lb + b
        bad |= not show("game, 4 explosions animating (15 frames) and ending together (the 16th), drift every frame: ",
                        "formation_update", "formation_update_end", costs, sorted(la), sorted(lb), 750, "budget")
    finally:
        v.close()
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL: {e}")
        sys.exit(2)
