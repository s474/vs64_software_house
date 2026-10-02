"""Swarm's one-off frames (M4 stage 3 as built, commit d5586da): the frames in which the state
machine runs an init before formation_update, so the border work ends below the first badline.

Technical Director, 2026-10-02: the figures behind the ruling in docs/games/swarm/memory-map.md
"One-off frames". stage3_costs.py measured game_update for the two frames (2,875 and 3,713) and
where formation_update ended (lines 64 and 86). This adds what the ruling's conditions need:
formation_update's own cost there (it meets badlines and the new formation's sprites, which row
5's 750 doesn't allow for), collide_update's, the idle cycles left in that frame (its mux_update
sorts 18 sprites that all appeared at once) and that no frame overran.

Cases, on the game's DEBUG build (build/swarm), states set through the monitor at game_update_end
as stage3_costs.py does, RUNS frames each; raster cycles, IRQs excluded:

  return        the frame a cleared formation comes back (formation_init), nothing else on screen
  return+shots  the same with both player shots one move from the returning enemies 0 and 12 (an
                enemy can be hit in the frame it is first shown: design, Stage 2 rule 6)
  new game      the frame after GameOver's last (game_new)

The idle figure is the DEBUG idle loop's count for that frame x 16 (zp_idle_lo/hi, read at the
next frame's game_update_end, before the loop runs again).

Run from the repo root (about 1 minute):

    uv run --package budget-runner python tests/games/swarm/stage3_oneoff.py | tee tests/games/swarm/stage3_oneoff.txt

Results of the last run: tests/games/swarm/stage3_oneoff.txt.

STAGE 4 NOTE: this script is for the stage 3 build (commit d5586da). Its Part 2 starts each case
with GameOver's last frame giving a new game, and measures the frame a cleared formation comes
back; from stage 4 GameOver ends in the title and a wave starts with an Intro, so on a later build
it stops at "no new game". The stage 4 measurements are tests/games/swarm/stage4_costs.py.
"""

import sys

from budget_runner.evaluate import SampleCounter, profile_costs
from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice, build_program
from vice_monitor import CPU_OP_EXEC

RUNS = 8
ENEMY0, PSHOT0, MUX_OFF = 6, 4, 0xFF
PARKED, DEAD, EXPLODING = 1, 0, 0x83
GS_PLAY, GS_OVER = 0, 3
JOYPORT_IO_SIMULATION, PORT2 = 37, 1
SPANS = (("game_update", "game_update_end"), ("formation_update", "formation_update_end"),
         ("collide_update", "collide_update_end"), ("mux_update", "mux_update_end"))


def main() -> int:
    prg = build_program("swarm")
    print("# uv run --package budget-runner python tests/games/swarm/stage3_oneoff.py   (build/swarm/swarm.prg, "
          "VICE 3.10 x64sc PAL, DEBUG)")
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

        def one_frame():
            """The next whole frame: every span's (cost, first line, last line), then that frame's idle cycles."""
            d, r = v.addr("irq_dispatch"), v.addr("irq_exit_rti")
            pairs = [(v.addr(a), v.addr(b)) for a, b in SPANS]
            gu_end, mux_end = pairs[0][1], pairs[-1][1]

            def done(events):                   # stop at the mux_update_end that follows the frame's game_update_end
                pcs = [e.pc for e in events]
                if pairs[0][0] not in pcs:
                    return False
                rest = pcs[pcs.index(pairs[0][0]):]
                return gu_end in rest and mux_end in rest[rest.index(gu_end):]

            flat = sorted({x for p in pairs for x in p} | {d, r})
            events = v.trace(flat, done, "the frame")
            out = []
            for a, b in pairs:
                cost = profile_costs(events, a, b, d, r)[-1]        # the last pass: this frame's
                out.append((cost, [e.line for e in events if e.pc == a][-1], [e.line for e in events if e.pc == b][-1]))
            frame()
            out.append(int.from_bytes(peek("zp_idle_lo", 2), "little") * 16)
            return out

        def case(name, setup, check):
            rows = []
            for _ in range(RUNS):
                new_game()
                setup()
                rows.append(one_frame())
                check()
            for i, (a, b) in enumerate(SPANS):
                costs = [r[i][0] for r in rows]
                print(f"{name}: {a} -> {b}: {RUNS} frames, min {min(costs)}, max {max(costs)} raster cycles; started on "
                      f"lines {min(r[i][1] for r in rows)}-{max(r[i][1] for r in rows)}, ended on "
                      f"{min(r[i][2] for r in rows)}-{max(r[i][2] for r in rows)}")
            idle = [r[-1] for r in rows]
            print(f"{name}: idle in that frame: min {min(idle)}, max {max(idle)} cycles")

        homes = {}

        def clear(shots):
            def setup():
                for e in (0, 12):
                    homes[e] = (peek("mux_x_lo", 1, ENEMY0 + e)[0], peek("mux_y", 1, ENEMY0 + e)[0])
                fx0, t0 = peek("zp_fx")[0], peek("zp_drift_timer")[0]
                poke("enemy_state", [DEAD] * 18)
                poke("mux_y", [MUX_OFF] * 18, ENEMY0)
                poke("zp_enemies_alive", [0])
                poke("zp_clear_timer", [2])
                frame()
                if shots:                       # formation_init puts fx back to 48: the homes are a new game's
                    for i, e in enumerate((0, 12)):
                        x, y = homes[e]
                        sprite(PSHOT0 + i, x + 48 - fx0, y + 5 + 8)
                    poke("zp_player_cooldown", [5])
            return setup

        def back(hit):
            def check():
                st = list(peek("enemy_state", 18))
                want = [PARKED] * 18
                if hit:
                    want[0] = want[12] = EXPLODING
                if st != want or peek("zp_launch_timer")[0] > 50:
                    raise MeasureError(f"return: states {bytes(st).hex()}")
            return check

        def over():
            poke("zp_game_state", [GS_OVER])
            poke("zp_state_timer", [199])

        def started():
            if peek("zp_game_state")[0] != GS_PLAY or list(peek("enemy_state", 18)) != [PARKED] * 18:
                raise MeasureError("new game: not started")

        case("return", clear(False), back(False))
        case("return+shots", clear(True), back(True))
        case("new game", over, started)
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
