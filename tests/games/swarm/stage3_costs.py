"""Measured costs of Swarm stage 3 (M4): enemy shots, divers, the player's death, the game states.

Raster cycles, IRQ time excluded (the budget runner's profile_excl_irq, engine/README.md#budget-units),
with the raster lines each span started and ended on. What is measured, and against what, is the
checklist in docs/games/swarm/memory-map.md "Stage 3: what the gameplay-engineer must do", item 6.

Part 1, the AUTOPLAY budget build (tests/games/swarm/main.asm, built the way `make test` does):
wave 12 (pattern 3, loop 3: 3 divers, 2 path steps every other frame, shots at dy 3, the drift every
frame), the scripted stick sweeping with fire held, the respawn flash in every frame, three panel
fields redrawn every frame; hits on enemies are scored but nothing dies, hits on the player are
counted in autoplay_player_hits and not answered. SAMPLES passes of each span:

  eshot_update, diver_update, collide_update, formation_update, player_update, game_update,
  mux_update -> mux_update_fast (frames with no overflow) and -> mux_update_end (all frames)

then FRAMES more frames and the counters: game_idle_min x 16 (idle in the worst frame),
game_flicker_frames, mux_max_age, the late and overrun counters, autoplay_player_hits.

Part 2, the game's DEBUG build (build/swarm), for what AUTOPLAY can't show because nothing dies
there (memory-map.md "What AUTOPLAY cannot measure"). States are set through the monitor at
game_update_end and the game then runs by itself; each case starts from a new game (the game's
own game_new, reached by putting GameOver at its last frame):

  collide worst    both player shots hit in one frame, each at the far end of its scan (enemy 0
                   after 12 rejects and 6 full tests, enemy 6 after 6 rejects and 6 full tests); 3
                   enemy shots at Y 207 beside the ship (the shot scan: 3 full tests, no hit); 3
                   divers at Y 216, two beside the ship and the last one on it (the diver scan: 3
                   collision_one, the last a ram): 3 enemy explosions started, 3 scores, the
                   player's hit. One diver more than a frame of play can have at loop 0
  collide band     both player shots hit as above, with the 3 divers at row 1's height beside
                   shot 1's column (15 full tests in the shots' scans); no enemy shot or diver low
                   enough for the player's scans (the guards only)
  shot hit / ram   the player's hit alone: an enemy shot on the ship; a diver on the ship
  player_update    in each state: Play (right + fire held, no flash, launcher off), Respawn's
                   flash (invulnerability held, right + fire, divers flying), dying (the 32
                   explosion frames) and hidden
  formation        3 explosions ending and 1 animating in a frame with a drift turn and an
                   animation swap (counted 627)
  launcher         17 dead, the survivor 17 places after the drawn index, both rng_next calls
                   (the generator's state is set so): diver_update on the launch frame
  formation_init   the frame a cleared formation comes back, and the frame a new game starts:
                   game_update, and where formation_update ended in it

Run from the repo root (about 3 minutes):

    uv run --package budget-runner python tests/games/swarm/stage3_costs.py | tee tests/games/swarm/stage3_costs.txt

Results of the last run: tests/games/swarm/stage3_costs.txt.

STAGE 4 NOTE: this script is for the stage 3 build (commit d5586da). Its Part 2 starts each case
with GameOver's last frame giving a new game, and measures the frame a cleared formation comes
back; from stage 4 GameOver ends in the title and a wave starts with an Intro, so on a later build
it stops at "no new game". The stage 4 measurements are tests/games/swarm/stage4_costs.py.
"""

import sys

from budget_runner.evaluate import SampleCounter, profile_costs
from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice, build_program
from vice_monitor import CPU_OP_EXEC, run_frames

SAMPLES, FRAMES, WARMUP = 600, 3000, 400
RUNS = 8
SPANS = [("eshot_update", "eshot_update_end", 200, "budget, row 7"),
         ("diver_update", "diver_update_end", 1350, "budget, row 6"),
         ("collide_update", "collide_update_end", 2825, "budget, row 8: over it switches to the grid lookup"),
         ("formation_update", "formation_update_end", 750, "budget, row 5"),
         ("player_update", "player_update_end", 290, "budget, row 3"),
         ("pshot_update", "pshot_update_end", 60, "budget, row 4"),
         ("stars_update", "stars_update_end", 60, "budget, row 10"),
         ("panel_update", "panel_update_end", 250, "budget, row 9"),
         ("game_update", "game_update_end", 6075, "budget"),
         ("mux_update", "mux_update_fast", 7400, "engine limit, frames with no overflow; average <= 5,000"),
         ("mux_update", "mux_update_end", 13000, "engine limit, all frames")]
ENEMY0, ESHOT0, PSHOT0, MUX_OFF = 6, 1, 4, 0xFF
PARKED, DEAD, DIVE, EXPLODING = 1, 0, 0x81, 0x83
GS_PLAY, GS_RESPAWN, GS_DYING, GS_OVER = 0, 1, 2, 3
JOYPORT_IO_SIMULATION, PORT2 = 37, 1
RIGHT_FIRE = 0x18
IDLE_MIN = 625


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


def rng_step(lo, hi):
    """engine/rng.asm: 16-bit xorshift 7, 9, 8; the byte returned is the new high byte."""
    s = lo | hi << 8
    s ^= (s << 7) & 0xFFFF
    s ^= s >> 9
    s ^= (s << 8) & 0xFFFF
    return s & 255, s >> 8


def main() -> int:
    bad = False

    # ------------------------------------------------------------------ Part 1: the AUTOPLAY build
    prg = build_program("swarm_budget", "tests/games/swarm", ["games/swarm/src"])
    v = Vice(prg, WARMUP)
    try:
        for start, end, limit, what in SPANS:
            costs, la, lb = span(v, start, end, SAMPLES)
            bad |= not show("AUTOPLAY ", start, end, costs, la, lb, limit, what)
            if start == "formation_update" and lb[-1] >= 49:
                print(f"[FAIL] AUTOPLAY formation_update ended on line {lb[-1]}: the border rows assume it ends above 49")
                bad = True
        run_frames(v.mon, FRAMES)

        def rd(label, n=1):
            a = v.addr(label)
            return int.from_bytes(v.mon.mem_get(a, a + n - 1), "little")

        idle = rd("game_idle_min", 2) * 16
        zero = {k: rd(k, n) for k, n in (("game_overrun_count", 1), ("mux_late_count", 1), ("irq_late_count", 1),
                                         ("mux_pin_drop_count", 1), ("mux_pin_excess_count", 1))}
        flicker, age, hits = rd("game_flicker_frames", 2), rd("mux_max_age"), rd("autoplay_player_hits", 2)
        ok = idle >= IDLE_MIN and not any(zero.values()) and age <= 1 and flicker >= 1 and hits >= 1
        bad |= not ok
        total = WARMUP + len(SPANS) * SAMPLES + FRAMES
        print(f"[{'PASS' if ok else 'FAIL'}] AUTOPLAY after {FRAMES} more frames (about {total} in all): idle in the worst "
              f"frame {idle} cycles (required >= {IDLE_MIN}); " + ", ".join(f"{k} {x}" for k, x in zero.items())
              + f" (all required 0); mux_max_age {age} (required <= 1); game_flicker_frames {flicker} "
              f"({100 * flicker / total:.1f}% of frames; required >= 1); autoplay_player_hits {hits} (required >= 1); "
              f"divers active {rd('zp_divers_active')}, enemies alive {rd('zp_enemies_alive')}, "
              f"pattern {rd('zp_pattern')}, loop {rd('zp_loop')}")
    finally:
        v.close()

    # ------------------------------------------------------------------ Part 2: the game build
    prg = build_program("swarm")
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

        def stick(mask):
            mon.joyport_set(PORT2, ~mask & 0x1F)

        def new_game():
            """The game's own game_new: GameOver's last frame, then one frame. Launcher held off."""
            stick(0)
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

        def divers_at(places):
            """Enemies 12, 13, 14 as divers in the Hook's skim (one step of dx - 2, dy 0 a frame),
            placed so that after the next frame's step they are at `places`."""
            for s, (x, y) in enumerate(places):
                e = 12 + s
                poke("enemy_state", [DIVE], e)
                poke("enemy_seg", [skim], e)
                poke("enemy_left", [6], e)
                poke("enemy_step", [40], e)
                poke("enemy_fire", [3], e)              # PATH_FIRE_NONE
                sprite(ENEMY0 + e, x + 2, y)
            poke("diver_enemy", [12, 13, 14])
            poke("zp_divers_active", [3])

        def shots_hit(e0, e1):
            """Both player shots one move away from the middle of enemies e0 and e1."""
            poke("zp_drift_timer", [2])                 # no drift step in the next frame
            for i, e in enumerate((e0, e1)):
                x, y = epos(e)
                sprite(PSHOT0 + i, x, y + 5 + 8)
            poke("zp_player_cooldown", [5])             # the player doesn't fire into the measurement

        def one(start, endl):
            costs, la, lb = span(v, start, endl, 1)
            frame()                                     # stop at the end of that frame
            return costs[0], la[0], lb[0]

        def report(name, runs, limit, what, extra=""):
            nonlocal bad
            costs = [r[0] for r in runs]
            ok = max(costs) <= limit
            bad |= not ok
            print(f"[{'PASS' if ok else 'FAIL'}] game, {name}: {len(costs)} frames, min {min(costs)}, max {max(costs)} raster "
                  f"cycles (limit {limit}: {what}); started on lines {min(r[1] for r in runs)}-{max(r[1] for r in runs)}, "
                  f"ended on {min(r[2] for r in runs)}-{max(r[2] for r in runs)}{extra}")

        # collide_update's placed worst frame
        runs = []
        for _ in range(RUNS):
            new_game()
            px = player_x()
            shots_hit(0, 6)
            for i, dx in enumerate((30, -30, 60)):
                sprite(ESHOT0 + i, px + dx, 205)        # Y 207 after the move, beside the ship
            poke("eshot_dx", [0, 0, 0])
            divers_at([(px + 40, 216), (px - 40, 216), (px, 216)])
            score0 = peek("game_score", 3).hex()
            r = one("collide_update", "collide_update_end")
            st = peek("enemy_state", 18)
            if (st[0], st[6], st[14], st[12], st[13]) != (EXPLODING, EXPLODING, EXPLODING, DIVE, DIVE) \
                    or peek("zp_game_state")[0] != GS_DYING or peek("zp_lives")[0] != 2 or peek("zp_divers_active")[0] != 2:
                raise MeasureError(f"collide worst: states {st.hex()}, game state {peek('zp_game_state')[0]}")
            runs.append(r)
            score1 = peek("game_score", 3).hex()
        report("collide_update's placed worst frame (2 shot hits at the far ends of their scans, the shot scan with 3 "
               "full tests, the diver scan with 3 collision_one and a ram: 3 explosions, 3 scores, the player's hit)",
               runs, 2825, "budget, row 8: over it switches to the grid lookup", f"; score {score0} -> {score1}")

        runs = []
        for _ in range(RUNS):
            new_game()
            shots_hit(0, 6)
            x6 = epos(6)[0]
            divers_at([(x6 + 100, 96), (x6 + 136, 96), (x6 + 172, 96)])   # row 1's height, off shot 1's column
            r = one("collide_update", "collide_update_end")
            st = peek("enemy_state", 18)
            if (st[0], st[6]) != (EXPLODING, EXPLODING) or peek("zp_game_state")[0] != GS_PLAY:
                raise MeasureError(f"collide band: states {st.hex()}")
            runs.append(r)
        report("collide_update, 2 shot hits with the 3 divers in shot 1's band (15 full tests), the player's scans "
               "stopped by their guards", runs, 2825, "budget, row 8")

        runs = []
        for _ in range(RUNS):
            new_game()
            poke("zp_player_cooldown", [5])
            sprite(ESHOT0 + 2, player_x(), 205)
            poke("eshot_dx", [0, 0, 0])
            r = one("collide_update", "collide_update_end")
            if peek("zp_game_state")[0] != GS_DYING or list(peek("mux_y", 3, ESHOT0)) != [MUX_OFF] * 3:
                raise MeasureError("shot hit: the player wasn't hit")
            runs.append(r)
        report("the player's hit by an enemy shot, alone (guards, collision_begin, the range of 3, player_hit)",
               runs, 2825, "budget, row 8; the answer itself is budgeted about 100 CPU")

        runs = []
        for _ in range(RUNS):
            new_game()
            poke("zp_player_cooldown", [5])
            px = player_x()
            divers_at([(px + 40, 216), (px - 40, 216), (px, 216)])
            r = one("collide_update", "collide_update_end")
            if peek("zp_game_state")[0] != GS_DYING or peek("enemy_state", 1, 14)[0] != EXPLODING:
                raise MeasureError("ram: the player wasn't rammed")
            runs.append(r)
        report("a ram, alone (guards, collision_begin, 3 collision_one, the enemy's hit and the player's)",
               runs, 2825, "budget, row 8")

        # player_update in each state
        def passes(n, chunk, keep):
            costs, la, lb = [], [], []
            while len(costs) < n:
                keep()
                c, a, b = span(v, "player_update", "player_update_end", chunk)
                costs, la, lb = costs + c, la + a, lb + b
            return costs, sorted(la), sorted(lb)

        new_game()
        stick(RIGHT_FIRE)
        costs, la, lb = passes(300, 30, lambda: poke("zp_launch_timer", [255]))
        if peek("zp_game_state")[0] != GS_PLAY:
            raise MeasureError("player Play: not in Play")
        bad |= not show("game, Play, right + fire held, no flash, nothing diving: ", "player_update", "player_update_end",
                        costs, la, lb, 290, "budget, row 3")
        new_game()
        poke("zp_launch_timer", [1])
        stick(RIGHT_FIRE)
        costs, la, lb = passes(600, 30, lambda: poke("zp_player_invuln", [149]))
        bad |= not show("game, the respawn flash every frame (invulnerability held), right + fire held, divers flying: ",
                        "player_update", "player_update_end", costs, la, lb, 290, "budget, row 3")
        stick(0)
        new_game()
        sprite(ESHOT0, player_x(), 205)
        poke("eshot_dx", [0])
        frame()
        if peek("zp_game_state")[0] != GS_DYING:
            raise MeasureError("player dying: not hit")
        costs, la, lb = span(v, "player_update", "player_update_end", 31)
        bad |= not show("game, dying: the explosion's shapes (frames 1-31): ", "player_update", "player_update_end",
                        costs, la, lb, 290, "budget, row 3")
        costs, la, lb = span(v, "player_update", "player_update_end", 40)
        bad |= not show("game, dying: the frame the ship is hidden, then hidden: ", "player_update", "player_update_end",
                        costs, la, lb, 290, "budget, row 3")

        # formation_update: 3 explosions ending + 1 animating on a turn-and-swap frame
        runs = []
        for i in range(RUNS):
            new_game()
            for e, t in ((0, 1), (7, 1), (14, 1), (17, 9)):
                poke("enemy_state", [EXPLODING], e)
                poke("enemy_timer", [t], e)
            poke("explosion_enemy", [0, 7, 14, 17])
            poke("zp_fx", [95 if i % 2 == 0 else 1])
            poke("zp_drift_dir", [1 if i % 2 == 0 else 0xFF])
            poke("zp_drift_timer", [1])
            poke("zp_anim_timer", [1])
            anim0 = peek("zp_anim_frame")[0]
            r = one("formation_update", "formation_update_end")
            st = peek("enemy_state", 18)
            if (st[0], st[7], st[14], st[17]) != (DEAD, DEAD, DEAD, EXPLODING) or peek("zp_anim_frame")[0] == anim0 \
                    or peek("zp_fx")[0] not in (96, 0) or peek("zp_drift_dir")[0] != (0xFF if i % 2 == 0 else 1):
                raise MeasureError(f"formation: states {st.hex()}, fx {peek('zp_fx')[0]}")
            runs.append(r)
        report("formation_update with 3 explosions ending and 1 animating, a drift turn and an animation swap in one "
               "frame (counted 627)", runs, 750, "budget, row 5")

        # the launcher: one survivor 17 places after the drawn index, both rng_next calls
        seed = next((lo, hi) for hi in range(1, 256) for lo in range(256)
                    if rng_step(lo, hi)[1] & 31 >= 18 and rng_step(*rng_step(lo, hi))[1] & 31 >= 19)
        r_drawn = (rng_step(*rng_step(*seed))[1] & 31) - 18
        survivor = (r_drawn + 17) % 18
        runs = []
        for _ in range(RUNS):
            new_game()
            st = [DEAD] * 18
            st[survivor] = PARKED
            ys = list(peek("mux_y", 18, ENEMY0))
            poke("enemy_state", st)
            poke("mux_y", [ys[e] if e == survivor else MUX_OFF for e in range(18)], ENEMY0)
            poke("zp_enemies_alive", [1])
            poke("zp_rng_lo", list(seed))
            poke("zp_launch_timer", [1])
            r = one("diver_update", "diver_update_end")
            if peek("enemy_state", 1, survivor)[0] != 0x80 or peek("zp_launch_timer")[0] != 50 \
                    or tuple(peek("zp_rng_lo", 2)) != rng_step(*rng_step(*seed)):
                raise MeasureError(f"launcher: state {peek('enemy_state', 1, survivor)[0]:#x}, timer {peek('zp_launch_timer')[0]}")
            runs.append(r)
        report(f"the launcher with one survivor (enemy {survivor}) 17 places after the drawn index {r_drawn}, 2 rng_next "
               f"calls, the halved interval, and its first wind-up frame: diver_update", runs, 1350, "budget, row 6")

        # the frame a cleared formation comes back, and the frame a new game starts
        runs, flines = [], []
        for _ in range(RUNS):
            new_game()
            poke("enemy_state", [DEAD] * 18)
            poke("mux_y", [MUX_OFF] * 18, ENEMY0)
            poke("zp_enemies_alive", [0])
            poke("zp_clear_timer", [2])
            frame()
            d, r = v.addr("irq_dispatch"), v.addr("irq_exit_rti")
            a, b, fe = sym["game_update"], sym["game_update_end"], sym["formation_update_end"]
            counter = SampleCounter(a, b)
            events = v.trace([a, b, fe, d, r], lambda ev: counter.update(ev) >= 1, "game_update")
            cost = profile_costs(events, a, b, d, r)[0]
            frame()
            if list(peek("enemy_state", 18)) != [PARKED] * 18 or peek("zp_launch_timer")[0] > 50:
                raise MeasureError("formation_init frame: the formation didn't come back")
            runs.append((cost, [e.line for e in events if e.pc == a][0], [e.line for e in events if e.pc == b][0]))
            flines.append([e.line for e in events if e.pc == fe][0])
        report("the frame a cleared formation comes back (formation_init inside game_state_update): game_update",
               runs, 6075, "budget", f"; formation_update ended on line {min(flines)}-{max(flines)} in that frame (below "
               f"the first badline: a frame with nothing diving and nothing to hit)")
        runs, flines = [], []
        for _ in range(RUNS):
            new_game()
            poke("zp_game_state", [GS_OVER])
            poke("zp_state_timer", [199])
            d, r = v.addr("irq_dispatch"), v.addr("irq_exit_rti")
            a, b, fe = sym["game_update"], sym["game_update_end"], sym["formation_update_end"]
            counter = SampleCounter(a, b)
            events = v.trace([a, b, fe, d, r], lambda ev: counter.update(ev) >= 1, "game_update")
            cost = profile_costs(events, a, b, d, r)[0]
            frame()
            runs.append((cost, [e.line for e in events if e.pc == a][0], [e.line for e in events if e.pc == b][0]))
            flines.append([e.line for e in events if e.pc == fe][0])
        report("the frame a new game starts (game_new inside game_state_update): game_update", runs, 6075, "budget",
               f"; formation_update ended on line {min(flines)}-{max(flines)} in that frame")
        counts = {k: int.from_bytes(peek(k, n), "little") for k, n in (("game_overrun_count", 1), ("mux_late_count", 1),
                                                                         ("irq_late_count", 1), ("mux_pin_drop_count", 1))}
        ok = not any(counts.values())
        bad |= not ok
        print(f"[{'PASS' if ok else 'FAIL'}] game build after all of the above: " + ", ".join(f"{k} {c}" for k, c in counts.items())
              + " (all required 0)")
    finally:
        v.close()
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL: {e}")
        sys.exit(2)
