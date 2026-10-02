"""collide_update's worst frame with the grid lookup (Swarm, M4 stage 3 as built, commit d5586da).

Technical Director, 2026-10-02: the figure row 8 of docs/games/swarm/memory-map.md is re-set from.

stage3_costs.py's "placed worst frame" (1,846) was placed for the box scan it replaced: both shots
at the far ends of their scans, and all three divers at Y 216 for the player's scan. With the grid
lookup a parked enemy's place in the scan no longer matters, and that frame never takes the path
the lookup added: collision_begin + a collision_one for every diver slot, once for EACH player
shot that has a diver in its 22-line Y band (collide.asm, "!box"). A diver can't be both in a
shot's band and low enough to ram (the lowest shot tested is at Y 205: band Y 188-209; a ram needs
Y >= 210), so the worst frame splits the three divers: one in each shot's band, one ramming.

Cases, on the game's DEBUG build (build/swarm), states set through the monitor at game_update_end
as stage3_costs.py does, RUNS frames each, raster cycles collide_update -> collide_update_end with
IRQs excluded, and the raster lines it started and ended on:

  A  stage3_costs.py's placed worst frame again (the cross-check: 1,846)
  B  shots one move from enemies 0 and 12 (rows 0 and 2: 80 lines apart, as the cooldown has
     them); diver 13 at row 0's height and diver 14 at row 2's, each in a shot's band but off its
     column (box-tested, missed); diver 15 on the ship at Y 216 (the ram); 3 enemy shots at Y 207
     beside the ship (the shot scan, 3 full tests, no hit). 2 parked hits + the ram + the player
  C  as B, but divers 13 and 14 are ON enemies 0 and 12, so each shot has a Parked candidate and
     a diver under it and the diver (the higher sprite) is hit: 3 diver hits (diving score,
     diver_free, explosion) + the player's. The dearest frame the code has

Run from the repo root (about 1 minute):

    uv run --package budget-runner python tests/games/swarm/stage3_collide_worst.py | tee tests/games/swarm/stage3_collide_worst.txt

Results of the last run: tests/games/swarm/stage3_collide_worst.txt.

The same three frames on the box scan this code replaced (commit 039ad26), for what the switch
bought: build that commit's game in a worktree and pass its PRG (its main.vs is read from beside it):

    git worktree add /tmp/swarm_boxscan 039ad26 && make -C /tmp/swarm_boxscan GAME=swarm
    uv run --package budget-runner python tests/games/swarm/stage3_collide_worst.py \
        --prg /tmp/swarm_boxscan/build/swarm/swarm.prg | tee tests/games/swarm/stage3_collide_worst_boxscan.txt
    git worktree remove --force /tmp/swarm_boxscan
"""

import sys
from pathlib import Path

from budget_runner.evaluate import SampleCounter, profile_costs
from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice, build_program
from vice_monitor import CPU_OP_EXEC

RUNS = 8
ENEMY0, ESHOT0, PSHOT0, MUX_OFF = 6, 1, 4, 0xFF
PARKED, DIVE, EXPLODING = 1, 0x81, 0x83
GS_PLAY, GS_DYING, GS_OVER = 0, 2, 3
JOYPORT_IO_SIMULATION, PORT2 = 37, 1


def main() -> int:
    prg = Path(sys.argv[2]) if len(sys.argv) == 3 and sys.argv[1] == "--prg" else build_program("swarm")
    shown = prg.resolve().relative_to(Path.cwd()) if prg.resolve().is_relative_to(Path.cwd()) else prg
    print(f"# uv run --package budget-runner python tests/games/swarm/stage3_collide_worst.py   ({shown}, VICE 3.10 x64sc PAL, DEBUG)")
    v = Vice(prg, 60)
    try:
        mon, sym = v.mon, v.symbols
        end = sym["game_update_end"]
        mon.resource_set("JoyPort2Device", JOYPORT_IO_SIMULATION)
        mon.joyport_set(PORT2, 0x1F)

        def frame(n=1):
            for _ in range(n):
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

        def new_game():
            frame()
            poke("zp_game_state", [GS_OVER])
            poke("zp_state_timer", [199])
            frame()
            if peek("zp_game_state")[0] != GS_PLAY or list(peek("enemy_state", 18)) != [PARKED] * 18:
                raise MeasureError("new_game: no new game")
            poke("zp_launch_timer", [255])
            frame(2)

        def sprite(i, x, y):
            poke("mux_x_lo", [x & 255], i)
            poke("mux_x_hi", [x >> 8], i)
            poke("mux_y", [y], i)

        def epos(e):
            return peek("mux_x_lo", 1, ENEMY0 + e)[0] + 256 * peek("mux_x_hi", 1, ENEMY0 + e)[0], peek("mux_y", 1, ENEMY0 + e)[0]

        def player_x():
            p = peek("zp_player_x_lo", 2)
            return p[0] + 256 * p[1]

        skim = peek("path_first", 1, 4)[0] + 4          # the Hook's (-2, 0) segment, unmirrored copy

        def divers_at(enemies, places):
            """`enemies` as divers in the Hook's skim, at `places` after the next frame's step."""
            for e, (x, y) in zip(enemies, places):
                poke("enemy_state", [DIVE], e)
                poke("enemy_seg", [skim], e)
                poke("enemy_left", [6], e)
                poke("enemy_step", [40], e)
                poke("enemy_fire", [3], e)              # PATH_FIRE_NONE
                sprite(ENEMY0 + e, x + 2, y)
            poke("diver_enemy", list(enemies))
            poke("zp_divers_active", [len(enemies)])

        def shots_hit(e0, e1):
            poke("zp_drift_timer", [2])                 # no drift step in the next frame
            for i, e in enumerate((e0, e1)):
                x, y = epos(e)
                sprite(PSHOT0 + i, x, y + 5 + 8)
            poke("zp_player_cooldown", [5])

        def eshots_beside(px):
            for i, dx in enumerate((30, -30, 60)):
                sprite(ESHOT0 + i, px + dx, 205)        # Y 207 after the move
            poke("eshot_dx", [0, 0, 0])

        def one():
            d, r = v.addr("irq_dispatch"), v.addr("irq_exit_rti")
            a, b = v.addr("collide_update"), v.addr("collide_update_end")
            counter = SampleCounter(a, b)
            events = v.trace([a, b, d, r], lambda ev: counter.update(ev) >= 1, "collide_update")
            cost = profile_costs(events, a, b, d, r)[0]
            frame()
            return cost, [e.line for e in events if e.pc == a][0], [e.line for e in events if e.pc == b][0]

        def case(name, shots, divers, places, want):
            runs = []
            for _ in range(RUNS):
                new_game()
                px = player_x()
                e0, e1 = shots
                pos = {"px": px, "e0": epos(e0), "e1": epos(e1)}
                shots_hit(e0, e1)
                eshots_beside(px)
                divers_at(divers, places(pos))
                score0 = peek("game_score", 3).hex()
                r = one()
                st = peek("enemy_state", 18)
                got = {e: st[e] for e in want}
                if got != want or peek("zp_game_state")[0] != GS_DYING or peek("zp_lives")[0] != 2:
                    raise MeasureError(f"{name}: states {st.hex()}, game state {peek('zp_game_state')[0]}")
                runs.append(r)
                score1 = peek("game_score", 3).hex()
            costs = [r[0] for r in runs]
            print(f"{name}: {len(costs)} frames, min {min(costs)}, max {max(costs)} raster cycles; started on lines "
                  f"{min(r[1] for r in runs)}-{max(r[1] for r in runs)}, ended on {min(r[2] for r in runs)}-"
                  f"{max(r[2] for r in runs)}; score {score0} -> {score1}; divers active after: {peek('zp_divers_active')[0]}")

        case("A  stage3_costs.py's placed worst frame (shots on enemies 0 and 6, 3 divers at Y 216, the last rams)",
             (0, 6), (12, 13, 14),
             lambda p: [(p["px"] + 40, 216), (p["px"] - 40, 216), (p["px"], 216)],
             {0: EXPLODING, 6: EXPLODING, 14: EXPLODING, 12: DIVE, 13: DIVE})
        case("B  a diver in each shot's band, missed; 2 parked hits; the third diver rams",
             (0, 12), (13, 14, 15),
             lambda p: [(p["e0"][0] + 100, p["e0"][1]), (p["e1"][0] + 100, p["e1"][1]), (p["px"], 216)],
             {0: EXPLODING, 12: EXPLODING, 15: EXPLODING, 13: DIVE, 14: DIVE})
        case("C  a diver under each shot, over a parked enemy: 2 diver hits; the third diver rams",
             (0, 12), (13, 14, 15),
             lambda p: [p["e0"], p["e1"], (p["px"], 216)],
             {0: PARKED, 12: PARKED, 13: EXPLODING, 14: EXPLODING, 15: EXPLODING})
        counts = {k: peek(k)[0] for k in ("game_overrun_count", "mux_late_count", "irq_late_count", "mux_pin_drop_count")}
        print("after all of the above: " + ", ".join(f"{k} {c}" for k, c in counts.items()) + " (all required 0)")
        return 1 if any(counts.values()) else 0
    finally:
        v.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL: {e}")
        sys.exit(2)
