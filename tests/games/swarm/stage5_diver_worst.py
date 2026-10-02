"""diver_update's worst frame, placed (Swarm, M4 stage 5, the tuned build: commit 2d6cf3f).

Technical Director, 2026-10-02: the figures row 6 of docs/games/swarm/memory-map.md is re-set from.

Why. After the tuning (launch interval 32 at wave 12, 3 shots a dive from loop 0) `make test` read
diver_update at 1,268 and a 6,000-pass look at 1,296 against the row's 1,350 (tuning_long_look.txt).
Those are sampled maxima of the AUTOPLAY build, whose formation is always full. The routine's dear
paths, read from diver.asm, are:

  - a diver in Dive taking 2 path steps (loop 1 and up), one of them a fire step that fires
    (eshot_spawn) and ends a segment;
  - the launcher's scan (diver_launch): 16 cycles an enemy that isn't Parked, about 35 one that is
    Parked but not in the wave's rows (patterns 1 and 2), both rng_next calls, the dive sound;
  - the new diver's first wind-up frame, in the launch's own frame;
  - the enemy shot's sound request at the end.

What can fall in one frame is limited by the launch interval (launches are at least that many
frames apart, halved with 4 or fewer alive) and by the fire steps (Plunge 26/36/46, Sweep
24/38/62/86, Hook 8/16; at loop 2 and up a diver takes 3 steps every 2 frames):

  D0  more than 4 alive (wave 12: interval 32 = 48 steps): two Sweeps 48 steps apart fire together
      (steps 86 and 38), a third diver (an old Plunge on its last segment) takes 2 steps, the
      launcher waits at 0 with the maximum out. The formation is full: what AUTOPLAY can reach
  D1  4 or fewer alive (interval 16 = 24 steps): three Sweeps fire together (steps 86, 62, 38), all
      three shot slots free, the launcher waiting at 0
  D2  3 alive: two Sweeps fire together (86, 62) AND the launcher launches the one Parked enemy,
      17 places past the drawn index, with both rng_next calls; its wind-up frame 0
  D3  pattern 2 (rows 1 and 2 dive), row 0 full and Parked, rows 1 and 2 dead but two Sweeps: one
      fires (step 62), the other takes 2 steps; the launcher scans all 18 (six of them Parked but
      not in the wave's rows) and falls back to a row 0 enemy; both rng_next calls
  D2L, D3L  D2 and D3 with the border work before diver_update loaded as well, so that it starts
      later and runs further into the display: the panel's three fields dirty, a player shot on
      row 0's lines, an enemy shot in flight and moving sideways, the formation on a drift turn and
      an animation swap; in D3L also 3 explosions ending and 1 animating (stage 3's worst
      formation_update: those four count as alive, so 12 are alive before the frame and 9 after)
  J0  D0 with collide_update loaded: a player shot under a firing Sweep, the other under a Parked
      enemy, the third enemy shot on the ship (the player's hit)
  J2  D2 with collide_update loaded: a player shot under a firing Sweep, the other under the enemy
      being launched (in row 1), the third enemy shot on the ship: the hit's second effect replaces
      the dive's pending request (sfx_play's dearest path)
  JX  the dearest pair of diver_update and collide_update found: 3 alive, a Sweep fires at step 86,
      a Hook on its skim reaches the ship (the ram), the launcher launches the third after its
      longest scan; a player shot under the Sweep, the other under the enemy being launched, two
      enemy shots beside the ship (the shot scan's full tests): collide_update's frame C
      (stage3_collide_worst.py) in a launch frame. The launches are 16 frames apart or more, as
      the halved interval of wave 12 allows; the two player shots are 80 lines apart, as the
      cooldown has them

Every case is a frame the game can reach by its own rules (the positions are a Sweep's at those
steps, with X at 256 or more for the step's longer path); none was seen in play. The cases are on
the game's DEBUG build (build/swarm), states set through the monitor at game_update_end, then one
frame measured: raster cycles with IRQ time excluded for diver_update, formation_update,
collide_update, game_update and mux_update, the raster lines diver_update started and ended on,
and that frame's idle cycles (the DEBUG idle loop's count x 16).

Run from the repo root (about 2 minutes):

    uv run --package budget-runner python tests/games/swarm/stage5_diver_worst.py | tee tests/games/swarm/stage5_diver_worst.txt

Results of the last run: tests/games/swarm/stage5_diver_worst.txt. `make test` runs it too, as a
script check in tests/games/swarm/budget.json (with --prg <the game's DEBUG build>): it fails if a
placed frame passes LIMIT, takes another path than the one placed, or a DEBUG counter isn't 0.
"""

import sys
from pathlib import Path

from budget_runner.evaluate import profile_costs
from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice, build_program
from vice_monitor import CPU_OP_EXEC

RUNS = 6
LIMIT = 2020                        # row 6 as re-set at stage 5 (memory-map.md "Row 6: the divers")
ENEMY0, ESHOT0, PSHOT0, MUX_OFF = 6, 1, 4, 0xFF
DEAD, PARKED, WINDUP, DIVE = 0, 1, 0x80, 0x81
GS_PLAY, GS_DYING, GS_OVER = 0, 2, 3
PATH_FIRE_NONE = 3                  # tables.asm: the index of a 0 in path_fire
FIRE_SWEEP = {24: 4, 38: 5, 62: 6, 86: 7}       # a Sweep's fire step -> its index in path_fire
JOYPORT_IO_SIMULATION, PORT2 = 37, 1
SPANS = (("game_update", "game_update_end"), ("formation_update", "formation_update_end"),
         ("diver_update", "diver_update_end"), ("collide_update", "collide_update_end"),
         ("mux_update", "mux_update_end"))


def rng_step(lo, hi):
    """engine/rng.asm: 16-bit xorshift 7, 9, 8; the byte returned is the new high byte."""
    s = lo | hi << 8
    s ^= (s << 7) & 0xFFFF
    s ^= s >> 9
    s ^= (s << 8) & 0xFFFF
    return s & 255, s >> 8


def seed_for(wanted):
    """A generator state from which the launcher makes both rng_next calls and draws an index in `wanted`."""
    for hi in range(1, 256):
        for lo in range(256):
            a = rng_step(lo, hi)
            b = rng_step(*a)
            if a[1] & 31 >= 18 and b[1] & 31 >= 18 and (b[1] & 31) - 18 in wanted:
                return (lo, hi), (b[1] & 31) - 18
    raise MeasureError("no seed")


def main() -> int:
    prg = Path(sys.argv[2]) if len(sys.argv) == 3 and sys.argv[1] == "--prg" else build_program("swarm")
    shown = prg.resolve().relative_to(Path.cwd()) if prg.resolve().is_relative_to(Path.cwd()) else prg
    print(f"# uv run --package budget-runner python tests/games/swarm/stage5_diver_worst.py   "
          f"({shown}, VICE 3.10 x64sc PAL, DEBUG; raster cycles, IRQ time excluded)")
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

        def new_game(pattern, loop):
            """A new game by the stick, its Intro run to Fight (stage3_collide_worst.py's new_game), then
            the wave stores set; stopped at game_update_end of a frame after which a 2-step frame follows."""
            frame()
            poke("zp_game_state", [GS_OVER])
            poke("zp_state_timer", [199])
            frame()
            while peek("zp_state_timer")[0] < 7:
                frame()
            mon.joyport_set(PORT2, 0x0F)
            frame()
            mon.joyport_set(PORT2, 0x1F)
            frame(6)
            frame(50)                                   # the Intro
            if peek("zp_game_state")[0] != GS_PLAY or list(peek("enemy_state", 18)) != [PARKED] * 18:
                raise MeasureError("new_game: no new game")
            poke("zp_launch_timer", [255])
            poke("zp_pattern", [pattern])
            poke("zp_loop", [loop])
            frame(2)
            mask, cmp_ = peek("diver_extra_mask", 1, loop)[0], peek("diver_extra_cmp", 1, loop)[0]
            if (peek("zp_game_frame")[0] + 1) & mask != cmp_:
                frame()                                 # the frame measured must be a 2-step frame
            if (peek("zp_game_frame")[0] + 1) & mask != cmp_:
                raise MeasureError("no 2-step frame")
            poke("zp_launch_timer", [255])

        def sprite(i, x, y):
            poke("mux_x_lo", [x & 255], i)
            poke("mux_x_hi", [x >> 8], i)
            poke("mux_y", [y], i)

        def epos(e):
            return peek("mux_x_lo", 1, ENEMY0 + e)[0] + 256 * peek("mux_x_hi", 1, ENEMY0 + e)[0], peek("mux_y", 1, ENEMY0 + e)[0]

        sweep = peek("path_first", 1, 2)[0]             # row 1, the unmirrored copy: (-1,1,8) (1,2,16) (2,2,14) (2,0,0)
        plunge = peek("path_first", 1, 0)[0]            # row 0: its last segment, (2,0,0), is + 6

        def diver(e, seg, left, step, fire, shots, x, y):
            poke("enemy_state", [DIVE], e)
            poke("enemy_seg", [seg], e)
            poke("enemy_left", [left], e)
            poke("enemy_step", [step], e)
            poke("enemy_fire", [fire], e)
            poke("enemy_shots", [shots], e)
            sprite(ENEMY0 + e, x, y)

        def sweep_firing(e, at, x):
            """Enemy e as a Sweep 2 steps before fire step `at`: it takes them both in the next frame."""
            if at == 38:                                # steps 37 and 38 end the third segment
                diver(e, sweep + 2, 2, 36, FIRE_SWEEP[38], 5, x, 160)
            else:                                       # 62, 86: on the last segment, Y 164
                diver(e, sweep + 3, 0, at - 2, FIRE_SWEEP[at], 4 if at == 62 else 3, x, 164)

        def alive(parked):
            """Every enemy not in `parked` and not a diver is Dead."""
            st = list(peek("enemy_state", 18))
            for e in range(18):
                if st[e] == PARKED and e not in parked:
                    st[e] = DEAD
                    poke("mux_y", [MUX_OFF], ENEMY0 + e)
            poke("enemy_state", st)
            poke("zp_enemies_alive", [sum(1 for s in st if s != DEAD)])

        def player_at(x):
            poke("zp_player_x_lo", [x & 255, x >> 8])
            sprite(0, x, 221)

        def measure(check):
            """The next whole frame: {span: (cost, first line, last line)}, its idle cycles, sfx_request, and
            check() as read at that frame's mux_update_end (before the tick at line 251 takes the requests)."""
            d, r = v.addr("irq_dispatch"), v.addr("irq_exit_rti")
            pairs = [(v.addr(a), v.addr(b)) for a, b in SPANS]
            mux_end = pairs[-1][1]
            events = v.trace(sorted({x for p in pairs for x in p} | {d, r}),
                             lambda ev: sum(1 for e in ev if e.pc == mux_end) >= 2, "a frame")
            first = [i for i, e in enumerate(events) if e.pc == pairs[0][0]][0]
            seg = events[first:]
            row = {}
            for (name, _), (a, b) in zip(SPANS, pairs):
                row[name] = (profile_costs(seg, a, b, d, r)[-1], [e.line for e in seg if e.pc == a][-1],
                             [e.line for e in seg if e.pc == b][-1])
            row["req"] = tuple(peek("sfx_request", 3))
            row["got"] = check()
            frame()
            row["idle"] = int.from_bytes(peek("zp_idle_lo", 2), "little") * 16
            return row

        bad = []

        def case(name, pattern, setup, check):
            rows = []
            for _ in range(RUNS):
                new_game(pattern, 3)
                poke("mux_y", [MUX_OFF] * 3, ESHOT0)
                poke("mux_y", [MUX_OFF] * 2, PSHOT0)
                player_at(60)
                want = setup()
                row = measure(check)
                got = row["got"]
                if got != want:
                    raise MeasureError(f"{name}: the frame didn't take the path placed: {got} (wanted {want})")
                rows.append(row)

            def rng(k):
                c = [r[k][0] for r in rows]
                return f"{min(c)}-{max(c)}"

            du = [r["diver_update"] for r in rows]
            worst = max(c for c, _, _ in du)
            ok = worst <= LIMIT
            bad.append(not ok)
            print(f"[{'PASS' if ok else 'FAIL'}] {name}: {len(rows)} frames, diver_update {rng('diver_update')} raster "
                  f"cycles (limit {LIMIT}), lines {min(a for _, a, _ in du)}-{max(a for _, a, _ in du)} to "
                  f"{min(b for _, _, b in du)}-{max(b for _, _, b in du)}; formation_update {rng('formation_update')}, "
                  f"collide_update {rng('collide_update')}, game_update {rng('game_update')} (to line "
                  f"{max(r['game_update'][2] for r in rows)}), mux_update {rng('mux_update')}, idle in that frame "
                  f"{min(r['idle'] for r in rows)}-{max(r['idle'] for r in rows)}; sfx_request before the tick "
                  f"{sorted({r['req'] for r in rows})}; {got}")

        def shots_out():
            return sum(1 for y in peek("mux_y", 3, ESHOT0) if y != MUX_OFF)

        def load_collide(e_first, e_second):
            """A player shot under diver e_first after its 2 steps (+ 4 in X, Y 164) and one under enemy
            e_second where it stands (row 1: Y 96), and the third enemy shot on the ship: Y 205 + 3."""
            x, _ = epos(e_first)
            sprite(PSHOT0, x + 4, 170 + 8)
            x, y = epos(e_second)
            sprite(PSHOT0 + 1, x, y + 4 + 8)
            sprite(ESHOT0 + 2, 60, 205)
            poke("eshot_dx", [0, 0, 0])
            poke("zp_drift_timer", [2])                 # no drift step in the measured frame

        # ---- D0: the full formation, two Sweeps firing, a third diver stepping, the launcher waiting
        def d0():
            sweep_firing(6, 86, 300)
            sweep_firing(7, 38, 262)
            diver(2, plunge + 6, 0, 132, PATH_FIRE_NONE, 3, 270, 192)
            poke("diver_enemy", [6, 7, 2])
            poke("zp_divers_active", [3])
            poke("zp_launch_timer", [0])
            return {"steps": [86, 38, 134], "shots fired": 2, "launch timer": 0, "alive": 18}

        def d0_check():
            return {"steps": [peek("enemy_step", 1, e)[0] for e in (6, 7, 2)], "shots fired": shots_out(),
                    "launch timer": peek("zp_launch_timer")[0], "alive": peek("zp_enemies_alive")[0]}

        case("D0  18 alive, pattern 3 loop 3: Sweeps at steps 86 and 38 fire, a Plunge takes 2 steps, the launcher "
             "waits at 0", 2, d0, d0_check)

        # ---- D1: 3 alive, three Sweeps 24 steps apart all firing
        def d1():
            sweep_firing(6, 86, 300)
            sweep_firing(7, 62, 280)
            sweep_firing(8, 38, 262)
            poke("diver_enemy", [6, 7, 8])
            poke("zp_divers_active", [3])
            alive(())
            poke("zp_launch_timer", [0])
            return {"steps": [86, 62, 38], "shots fired": 3, "launch timer": 0, "alive": 3}

        def d1_check():
            return {"steps": [peek("enemy_step", 1, e)[0] for e in (6, 7, 8)], "shots fired": shots_out(),
                    "launch timer": peek("zp_launch_timer")[0], "alive": peek("zp_enemies_alive")[0]}

        case("D1  3 alive, pattern 3 loop 3: Sweeps at steps 86, 62 and 38 all fire, the launcher waits at 0",
             2, d1, d1_check)

        # ---- D2: 3 alive, two Sweeps firing and a launch with the longest scan
        seed2, r2 = seed_for(range(9, 13))              # the survivor, 17 places on, is then in row 1 (8-11)
        surv = (r2 + 17) % 18

        def d2(collide=False):
            sweep_firing(6, 86, 300)
            sweep_firing(7, 62, 280)
            poke("diver_enemy", [6, 7, 0xFF])
            poke("zp_divers_active", [2])
            alive((surv,))
            poke("zp_rng_lo", list(seed2))
            poke("zp_launch_timer", [1])
            if collide:
                load_collide(6, surv)
            return {"steps": [86, 62], "shots fired": 2, "launch timer": 16,
                    "launched": "exploding" if collide else "wind-up", "game state": GS_DYING if collide else GS_PLAY}

        def d2_check():
            st = peek("enemy_state", 1, surv)[0]
            return {"steps": [peek("enemy_step", 1, e)[0] for e in (6, 7)],
                    "shots fired": 2 if peek("zp_game_state")[0] == GS_DYING else shots_out(),
                    "launch timer": peek("zp_launch_timer")[0],
                    "launched": {WINDUP: "wind-up", 0x83: "exploding"}.get(st, hex(st)),
                    "game state": peek("zp_game_state")[0]}

        case(f"D2  3 alive, pattern 3 loop 3: Sweeps at steps 86 and 62 fire, and the launcher draws {r2} with 2 rng_next "
             f"calls and scans 17 places to enemy {surv}, which starts its wind-up", 2, d2, d2_check)

        # ---- D3: pattern 2, row 0 Parked and not in the wave's rows: the scan of all 18 and the fallback
        seed3, r3 = seed_for(range(6, 14))

        def d3():
            diver(6, sweep + 3, 0, 120, PATH_FIRE_NONE, 2, 300, 164)
            sweep_firing(7, 62, 280)
            poke("diver_enemy", [6, 7, 0xFF])
            poke("zp_divers_active", [2])
            alive(range(6))
            poke("zp_rng_lo", list(seed3))
            poke("zp_launch_timer", [1])
            return {"steps": [122, 62], "shots fired": 1, "launch timer": 40, "launched": [WINDUP] + [PARKED] * 5,
                    "alive": 8}

        def d3_check():
            return {"steps": [peek("enemy_step", 1, e)[0] for e in (6, 7)], "shots fired": shots_out(),
                    "launch timer": peek("zp_launch_timer")[0], "launched": list(peek("enemy_state", 6)),
                    "alive": peek("zp_enemies_alive")[0]}

        case(f"D3  8 alive, pattern 2 loop 3, row 0 Parked: a Sweep fires at step 62, another takes 2 steps, and the "
             f"launcher draws {r3} with 2 rng_next calls, scans all 18 and falls back to enemy 0", 1, d3, d3_check)

        # ---- D2L and D3L: the same with the border work loaded, so diver_update starts later
        def late(exploding=()):
            poke("panel_dirty", [7])                    # score, lives, wave: 231 in panel_update
            sprite(PSHOT0, 24, 60 + 8)                  # on row 0's lines after its move; left of column 0's box
            sprite(PSHOT0 + 1, 24, 140 + 8)
            sprite(ESHOT0 + 2, 150, 100)
            poke("eshot_dx", [0, 0, 1])
            poke("zp_fx", [95])                         # the drift turns at 96 ...
            poke("zp_drift_dir", [1])
            poke("zp_drift_timer", [1])
            poke("zp_anim_timer", [1])                  # ... on an animation swap frame
            for i, e in enumerate(exploding):
                x, y = 34 + 36 * (e % 6) + 95, 56 + 40 * (e // 6)
                poke("enemy_state", [0x83], e)
                poke("enemy_timer", [1 if i < 3 else 5], e)
                sprite(ENEMY0 + e, x, y)
            if exploding:
                poke("explosion_enemy", list(exploding))
                poke("zp_enemies_alive", [peek("zp_enemies_alive")[0] + len(exploding)])

        def d2l():
            want = d2()
            late()
            return dict(want, **{"shots fired": 3})     # the two fired and the one placed in flight

        def d3l():
            want = d3()
            late((12, 13, 14, 15))
            return dict(want, **{"shots fired": 2, "alive": 9})

        case(f"D2L D2 with the border work loaded (panel 3 fields, a player shot on row 0's lines, an enemy shot moving, "
             f"a drift turn and an animation swap)", 2, d2l, d2_check)
        case("D3L D3 with the border work loaded the same way and 3 explosions ending + 1 animating in formation_update",
             1, d3l, d3_check)

        # ---- J0 and J2: the same frames with collide_update loaded
        def j0():
            want = d0()
            load_collide(6, 9)
            return dict(want, **{"shots fired": 2, "hit": [0x83, 0x83], "game state": GS_DYING, "alive": 18})

        def j0_check():
            return {"steps": [peek("enemy_step", 1, e)[0] for e in (6, 7, 2)], "shots fired": 2,
                    "launch timer": peek("zp_launch_timer")[0], "alive": peek("zp_enemies_alive")[0],
                    "hit": [peek("enemy_state", 1, e)[0] for e in (6, 9)], "game state": peek("zp_game_state")[0]}

        case("J0  D0 with collide_update loaded: a player shot under the Sweep at step 86 and one under Parked enemy 9, "
             "the third enemy shot on the ship", 2, j0, j0_check)
        case(f"J2  D2 with collide_update loaded: a player shot under the Sweep at step 86 and one under enemy {surv} "
             f"as it is launched, the third enemy shot on the ship", 2, lambda: d2(True), d2_check)

        # ---- JX: the launch frame with collide_update's frame C
        hook = peek("path_first", 1, 4)[0]              # row 2, unmirrored: its skim, (-2,0,12), is + 4

        def jx():
            sweep_firing(6, 86, 300)
            diver(12, hook + 4, 6, 40, PATH_FIRE_NONE, 1, 60 + 4, 216)      # on the ship after its 2 steps
            poke("diver_enemy", [6, 12, 0xFF])
            poke("zp_divers_active", [2])
            alive((surv,))
            poke("zp_rng_lo", list(seed2))
            poke("zp_launch_timer", [1])
            sprite(PSHOT0, 304, 173 + 8)                # under the Sweep (Y 164) after both have moved
            x, _ = epos(surv)
            sprite(PSHOT0 + 1, x, 93 + 8)               # under the launched enemy in row 1 (Y 96): 80 lines higher
            sprite(ESHOT0 + 1, 60 + 30, 205)            # beside the ship at Y 208 after their move: tested, no hit
            sprite(ESHOT0 + 2, 60 - 30, 205)
            poke("eshot_dx", [0, 0, 0])
            poke("zp_drift_timer", [2])
            return {"steps": [86, 42], "launch timer": 16, "hit": [0x83, 0x83, 0x83], "game state": GS_DYING,
                    "lives": 2}

        def jx_check():
            return {"steps": [peek("enemy_step", 1, e)[0] for e in (6, 12)], "launch timer": peek("zp_launch_timer")[0],
                    "hit": [peek("enemy_state", 1, e)[0] for e in (6, surv, 12)],
                    "game state": peek("zp_game_state")[0], "lives": peek("zp_lives")[0]}

        case(f"JX  3 alive, pattern 3 loop 3: a Sweep fires at step 86, a Hook rams, enemy {surv} is launched after a scan of "
             f"17; both player shots hit a diver, the shot scan's tests, the ram: collide_update's frame C in a launch frame",
             2, jx, jx_check)

        counts = {k: peek(k)[0] for k in ("game_overrun_count", "mux_late_count", "irq_late_count", "mux_pin_drop_count")}
        print("after all of the above: " + ", ".join(f"{k} {c}" for k, c in counts.items()) + " (all required 0)")
        failed = any(counts.values()) or any(bad)
        print("ALL PASS" if not failed else "FAILED")
        return 1 if failed else 0
    finally:
        v.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL: {e}")
        sys.exit(2)
