"""Measured costs of Swarm stage 4 PART A (M4): waves, the wave-clear bonus, the title, a new game.

What is measured, and against what, is the checklist in docs/games/swarm/memory-map.md "Stage 4:
what must be done to stay in budget", (f). Part A has no sound, so the items that need the sound
module (7 and 9, and the sound requests inside 1, 2, 6 and 8) are part B's; this script measures
the rest and says so on each line. Raster cycles, IRQ time excluded (the budget runner's
profile_excl_irq, engine/README.md#budget-units), with the raster lines each span started and
ended on. Idle figures are the DEBUG idle loop's count for that frame x 16 (zp_idle_lo/hi, read at
the next frame's game_update_end, before the loop runs again).

Part 1, the AUTOPLAY budget build (tests/games/swarm/main.asm, built as `make test` builds it):
no title, the constant seed, wave 12 (pattern 3, loop 3) entered through its Intro, nothing dies.
SAMPLES passes of each of stage 3's spans against the budgets in budget.json, to show that nothing
regressed, then FRAMES more frames and the counters (items 8 and 11, without sound).

Part 2, the game's DEBUG build (build/swarm). States are set through the monitor at
game_update_end and the game then runs by itself; the stick is the monitor's joyport.

  item 1   Clear's first frame: formation_update with 3 explosions ending together (the last
           three alive) on a drift-turn-and-animation-swap frame, so that enemy_kill pays the bonus
           inside it. Limit 750, and it must end above line 49
  item 2   a later wave's Intro frame 0 (the stores advance, the formation reset, WAVE nn, enemy 0):
           game_update, formation_update, idle. One-off rule: <= 4,000, <= 750, idle >= 5,000
  item 3   every frame of an Intro (1-100) with the ship sweeping and firing: game_update, and
           the line formation_update ends on (above 49 in every frame)
  item 4   the new game's frame (from the title's press) and the frame after: game_update,
           formation_update, idle; panel_update with all four fields dirty (limit 350)
  item 5   the title: the frame it is entered in (from GameOver), its drawing frames, a steady
           frame, the two blink frames, the press's frame and the erase frames: game_update, idle,
           and mux_update with the three title sprites. And the seeding: the raster line of the
           $D012 read at the press over 8 presses made in different title frames, and whether two
           presses one frame apart give different generator states
  item 6   GameOver's frame 0 and frame 1 with 3 divers still out (returning), the score above
           the high score: where formation_update ends; panel_update in frame 1
  item 10  a whole session by the stick: title, three waves (each swept with fire held, then the
           rest killed through the monitor), game over, the title, a second game: the DEBUG
           counters, and the lowest idle figure
  item 12  the sizes of the engine block, the game tables and the game code, from the build's
           memory map

Run from the repo root (about 3 minutes):

    uv run --package budget-runner python tests/games/swarm/stage4_costs.py | tee tests/games/swarm/stage4_costs.txt

Results of the last run: tests/games/swarm/stage4_costs.txt.
"""

import re
import subprocess
import sys
from pathlib import Path

from budget_runner.evaluate import SampleCounter, profile_costs
from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice, build_program
from vice_monitor import CPU_OP_EXEC, run_frames

REPO = Path(__file__).resolve().parents[3]
SAMPLES, FRAMES, WARMUP = 600, 3000, 400
RUNS = 8
SPANS = [("eshot_update", "eshot_update_end", 200, "budget, row 7"),
         ("diver_update", "diver_update_end", 1350, "budget, row 6"),
         ("collide_update", "collide_update_end", 2825, "budget, row 8"),
         ("formation_update", "formation_update_end", 750, "budget, row 5"),
         ("player_update", "player_update_end", 365, "budget, row 3"),
         ("pshot_update", "pshot_update_end", 60, "budget, row 4"),
         ("stars_update", "stars_update_end", 60, "budget, row 10"),
         ("panel_update", "panel_update_end", 250, "budget, row 9"),
         ("game_update", "game_update_end", 6050, "budget"),
         ("mux_update", "mux_update_fast", 7400, "engine limit, frames with no overflow; average <= 5,000"),
         ("mux_update", "mux_update_end", 13000, "engine limit, all frames")]
FRAME_SPANS = (("game_update", "game_update_end"), ("panel_update", "panel_update_end"),
               ("formation_update", "formation_update_end"), ("mux_update", "mux_update_end"))
ENEMY0, ESHOT0, PSHOT0, MUX_OFF, ENEMIES = 6, 1, 4, 0xFF, 18
PARKED, DEAD, WAITING, RETURN, EXPLODING = 1, 0, 2, 0x82, 0x83
GS_PLAY, GS_RESPAWN, GS_DYING, GS_OVER, GS_TITLE = 0, 1, 2, 3, 4
PHASE_FIGHT, PHASE_INTRO, PHASE_CLEAR, CLEAR_PAUSE = 0, 1, 2, 75
JOYPORT_IO_SIMULATION, PORT2 = 37, 1
RIGHT, LEFT, FIRE = 0x08, 0x04, 0x10
IDLE_MIN, ONEOFF_GAME, ONEOFF_IDLE, FORMATION, BORDER_LINE, PANEL4 = 650, 4000, 5000, 750, 49, 350


def span(v, start, end, samples):
    """(costs, start lines, end lines) of `samples` passes of start -> end, IRQs excluded."""
    d, r = v.addr("irq_dispatch"), v.addr("irq_exit_rti")
    a, b = v.addr(start), v.addr(end)
    counter = SampleCounter(a, b)
    events = v.trace([a, b, d, r], lambda ev: counter.update(ev) >= samples, f"{start} -> {end}")
    costs = profile_costs(events, a, b, d, r)[:samples]
    return costs, sorted({e.line for e in events if e.pc == a}), sorted({e.line for e in events if e.pc == b})


def bcd(n):
    return (n // 10) * 16 + n % 10


def main() -> int:
    bad = False

    def line(ok, text):
        nonlocal bad
        bad |= not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {text}")

    print("# uv run --package budget-runner python tests/games/swarm/stage4_costs.py   (the AUTOPLAY budget build and "
          "the game's DEBUG build, VICE 3.10 x64sc PAL; stage 4 part A: no sound)")

    # ------------------------------------------------------------------ item 12: sizes
    out = subprocess.run(["make", "-B", "GAME=swarm"], cwd=REPO, capture_output=True, text=True).stdout
    blocks = {m.group(3): (int(m.group(1), 16), int(m.group(2), 16))
              for m in re.finditer(r"\$([0-9a-f]{4})-\$([0-9a-f]{4}) (.+)", out)}
    ends = {"Chain": 0x27FF, "Game tables": 0x3FFF, "Game code": 0x5FFF}
    ok = all(name in blocks and blocks[name][1] <= end for name, end in ends.items())
    line(ok, "item 12, sizes from the build's memory map (DEBUG): "
         + "; ".join(f"{name} ${blocks[name][0]:04X}-${blocks[name][1]:04X} (limit ${end:04X}, "
                     f"{end - blocks[name][1]} bytes spare)" for name, end in ends.items() if name in blocks)
         + f"; the engine block is ${blocks['Engine'][0]:04X}-${blocks['Chain'][1]:04X}, "
           f"{blocks['Chain'][1] - blocks['Engine'][0] + 1} bytes; game tables "
           f"{blocks['Game tables'][1] - blocks['Game tables'][0] + 1} bytes; game code "
           f"{blocks['Game code'][1] - blocks['Game code'][0] + 1} bytes")

    # ------------------------------------------------------------------ Part 1: the AUTOPLAY build
    prg = build_program("swarm_budget", "tests/games/swarm", ["games/swarm/src"])
    v = Vice(prg, WARMUP)
    try:
        for start, end, limit, what in SPANS:
            costs, la, lb = span(v, start, end, SAMPLES)
            line(max(costs) <= limit,
                 f"AUTOPLAY {start} -> {end}: {len(costs)} passes, min {min(costs)}, avg {sum(costs) / len(costs):.1f}, "
                 f"max {max(costs)} raster cycles (limit {limit}: {what}); starts on raster lines {la[0]}-{la[-1]}, "
                 f"ends on {lb[0]}-{lb[-1]}")
            if start == "formation_update":
                line(lb[-1] < BORDER_LINE, f"AUTOPLAY formation_update ended on line {lb[-1]} at the latest (required: above {BORDER_LINE})")
        run_frames(v.mon, FRAMES)

        def rd(label, n=1):
            a = v.addr(label)
            return int.from_bytes(v.mon.mem_get(a, a + n - 1), "little")

        idle = rd("game_idle_min", 2) * 16
        zero = {k: rd(k, n) for k, n in (("game_overrun_count", 1), ("mux_late_count", 1), ("irq_late_count", 1),
                                         ("mux_pin_drop_count", 1), ("mux_pin_excess_count", 1))}
        flicker, age, hits = rd("game_flicker_frames", 2), rd("mux_max_age"), rd("autoplay_player_hits", 2)
        total = WARMUP + len(SPANS) * SAMPLES + FRAMES
        line(idle >= IDLE_MIN and not any(zero.values()) and age <= 1 and flicker >= 1 and hits >= 1
             and (rd("zp_wave"), rd("zp_pattern"), rd("zp_loop"), rd("zp_wave_phase"), rd("zp_enemies_alive")) == (0x12, 2, 3, PHASE_FIGHT, ENEMIES),
             f"AUTOPLAY after {FRAMES} more frames (about {total} in all; items 8 and 11, no sound yet): idle in the "
             f"worst frame {idle} cycles (required >= {IDLE_MIN}); " + ", ".join(f"{k} {x}" for k, x in zero.items())
             + f" (all required 0); mux_max_age {age} (required <= 1); game_flicker_frames {flicker} "
             f"({100 * flicker / total:.1f}% of frames); autoplay_player_hits {hits}; shown wave {rd('zp_wave'):02x}, "
             f"pattern {rd('zp_pattern')}, loop {rd('zp_loop')}, phase {rd('zp_wave_phase')} (Fight), enemies alive "
             f"{rd('zp_enemies_alive')}: it started through wave 12's Intro and the formation is full")
    finally:
        v.close()

    # ------------------------------------------------------------------ Part 2: the game build
    prg = build_program("swarm")
    v = Vice(prg, 0)
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

        def p1(label, off=0):
            return peek(label, 1, off)[0]

        def stick(mask):
            mon.joyport_set(PORT2, ~mask & 0x1F)

        def idle_now():
            return int.from_bytes(peek("zp_idle_lo", 2), "little") * 16

        def frames(n, spans=FRAME_SPANS):
            """The next n whole frames, measured one after another: a list of {span start: (cost, first
            line, last line)} for every span that ran in the frame, with "idle": that frame's idle cycles.
            The machine is left stopped at game_update_end of the frame after the last one measured."""
            d, r = v.addr("irq_dispatch"), v.addr("irq_exit_rti")
            pairs = [(v.addr(a), v.addr(b)) for a, b in spans]
            gu, gu_end = pairs[0]
            idles = []

            def done(events):
                if events and events[-1].pc == gu_end:
                    idles.append(idle_now())      # the idle count of the frame before this one
                return len(idles) > n

            events = v.trace(sorted({x for p in pairs for x in p} | {d, r}), done, f"{n} frames")
            starts = [i for i, e in enumerate(events) if e.pc == gu]
            out = []
            for j in range(n):
                seg = events[starts[j]:starts[j + 1]]
                row = {"idle": idles[j + 1]}
                for (na, _), (a, b) in zip(spans, pairs):
                    if any(e.pc == a for e in seg) and any(e.pc == b for e in seg):
                        row[na] = (profile_costs(seg, a, b, d, r)[-1], [e.line for e in seg if e.pc == a][-1],
                                   [e.line for e in seg if e.pc == b][-1])
                out.append(row)
            return out

        def summary(rows, name):
            if not all(name in r for r in rows):
                return f"{name}: not run"
            c = [r[name][0] for r in rows]
            return (f"{name} {min(c)}-{max(c)} (lines {min(r[name][1] for r in rows)}-{max(r[name][1] for r in rows)} "
                    f"to {min(r[name][2] for r in rows)}-{max(r[name][2] for r in rows)})")

        def worst(rows, name):
            return max(r[name][0] for r in rows)

        def overruns():
            return p1("game_overrun_count")

        def to_title():
            poke("zp_game_state", [GS_OVER])
            poke("zp_state_timer", [199])

        def press_at(title_frame):
            """At the title: wait, then a one-frame press of fire in the title's frame `title_frame` (8 or
            later). Returns with the machine stopped in the press's frame."""
            stick(0)
            while p1("zp_state_timer") + 1 < title_frame:
                frame()
            stick(FIRE)
            frame()
            stick(0)

        def start_game():
            """From anywhere: GameOver's last frame, the title, a press in its frame 8, the new game's frame."""
            stick(0)
            if p1("zp_game_state") != GS_TITLE:
                to_title()
                frame()
            press_at(8)
            frame(6)
            if p1("zp_game_state") != GS_PLAY or (p1("zp_wave_phase"), p1("zp_wave_timer")) != (PHASE_INTRO, 0):
                raise MeasureError("start_game: no new game")

        def next_wave_in(frames_, stores=None):
            poke("enemy_state", [DEAD] * ENEMIES)
            poke("mux_y", [MUX_OFF] * ENEMIES, ENEMY0)
            poke("explosion_enemy", [0xFF] * 4)
            poke("zp_enemies_alive", [0])
            poke("zp_wave_phase", [PHASE_CLEAR])
            poke("zp_wave_timer", [CLEAR_PAUSE - frames_])
            if stores:
                poke("zp_wave", [bcd(stores[0])])
                poke("zp_pattern", [stores[1]])
                poke("zp_loop", [stores[2]])

        def start_wave(n):
            """Wave n (2 or more) run to Fight's first frame by the game's own Intro; the launcher held off."""
            next_wave_in(1, (n - 1, (n - 2) % 3, min((n - 2) // 3, 3)))
            frame(101)
            if p1("zp_wave_phase") != PHASE_FIGHT or list(peek("enemy_state", ENEMIES)) != [PARKED] * ENEMIES:
                raise MeasureError(f"start_wave({n}): phase {p1('zp_wave_phase')}")
            poke("zp_launch_timer", [255])

        def sprite(i, x, y):
            poke("mux_x_lo", [x & 255], i)
            poke("mux_x_hi", [x >> 8], i)
            poke("mux_y", [y], i)

        frame(2)

        # ---- item 5 (first half): the power-on title's frames. We are stopped in its frame 2
        got = frames(68)
        rows = {3 + i: r for i, r in enumerate(got)}
        if p1("zp_state_timer") != 71 or p1("zp_game_state") != GS_TITLE:
            raise MeasureError(f"title: frame count {p1('zp_state_timer')}")
        draw, steady = [rows[f] for f in range(3, 6)], [rows[f] for f in range(8, 71) if f % 16]
        swap, blink = [rows[f] for f in (16, 48)], [rows[f] for f in (32, 64)]
        for name, rs in (("drawing frames 3-5 (one text a frame: 7, 7 and 20 cells)", draw),
                         ("steady frames (frames 8-70 but the swap and blink frames)", steady),
                         ("shape-swap frames 16 and 48", swap),
                         ("blink frames 32 (PRESS FIRE erased) and 64 (written), each also a swap frame", blink)):
            line(worst(rs, "game_update") <= ONEOFF_GAME and min(r["idle"] for r in rs) >= ONEOFF_IDLE,
                 f"item 5, the title, {name}: {len(rs)} frames, {summary(rs, 'game_update')}; {summary(rs, 'mux_update')} "
                 f"with the 3 title sprites; idle {min(r['idle'] for r in rs)}-{max(r['idle'] for r in rs)} cycles "
                 f"(limits: game_update <= {ONEOFF_GAME}, idle >= {ONEOFF_IDLE}; the expectation was under 700)")

        # ---- item 5: the press's frame and the erase frames; item 4: the new game's frame and the frame after
        press_rows, erase_rows, new_rows, after_rows = [], [], [], []
        for i in range(RUNS):
            if i:
                to_title()
                frame()
            stick(0)
            while p1("zp_state_timer") < 7 + i:
                frame()
            stick(FIRE)                           # held from the press on: the new game's 25-frame hold covers it
            got = frames(8)
            stick(0)
            if p1("zp_game_state") != GS_PLAY or (p1("zp_wave_phase"), p1("zp_wave_timer")) != (PHASE_INTRO, 2):
                raise MeasureError(f"new game: state {p1('zp_game_state')}, phase {p1('zp_wave_phase')}/{p1('zp_wave_timer')}")
            if "formation_update" in got[5] or "formation_update" not in got[6] or "panel_update" not in got[7]:
                raise MeasureError("new game: the new game's frame isn't the seventh from the press")
            press_rows.append(got[0])
            erase_rows += got[1:6]
            new_rows.append(got[6])
            after_rows.append(got[7])
        line(worst(press_rows, "game_update") <= ONEOFF_GAME and min(r["idle"] for r in press_rows) >= ONEOFF_IDLE,
             f"item 5, the title, the press's frame (rng_next, rng_seed, 3 sprites hidden, PRESS FIRE erased): {RUNS} "
             f"frames, {summary(press_rows, 'game_update')}; idle {min(r['idle'] for r in press_rows)}-"
             f"{max(r['idle'] for r in press_rows)}")
        line(worst(erase_rows, "game_update") <= ONEOFF_GAME,
             f"item 5, the title, the five erase frames after it: {len(erase_rows)} frames, "
             f"{summary(erase_rows, 'game_update')}; idle {min(r['idle'] for r in erase_rows)}-{max(r['idle'] for r in erase_rows)}")
        ok = (worst(new_rows, "game_update") <= ONEOFF_GAME and worst(new_rows, "formation_update") <= FORMATION
              and min(r["idle"] for r in new_rows) >= ONEOFF_IDLE and overruns() == 0)
        line(ok, f"item 4, the new game's frame (game_new from the title: every init, WAVE 01, enemy 0; a one-off frame): "
             f"{RUNS} frames, {summary(new_rows, 'game_update')}; {summary(new_rows, 'formation_update')}; "
             f"{summary(new_rows, 'mux_update')}; idle {min(r['idle'] for r in new_rows)}-{max(r['idle'] for r in new_rows)} "
             f"(one-off rule: game_update <= {ONEOFF_GAME}, formation_update <= {FORMATION}, idle >= {ONEOFF_IDLE}, no "
             f"overrun: game_overrun_count {overruns()})")
        rows = after_rows
        line(worst(rows, "panel_update") <= PANEL4 and worst(rows, "formation_update") <= FORMATION
             and max(r["formation_update"][2] for r in rows) < BORDER_LINE,
             f"item 4, the frame after the new game (Intro's frame 1, one enemy shown): {RUNS} frames, "
             f"{summary(rows, 'panel_update')} with all four fields dirty (limit {PANEL4}: exempt from row 9's 250); "
             f"{summary(rows, 'game_update')}; {summary(rows, 'formation_update')} (ends above line {BORDER_LINE}); idle "
             f"{min(r['idle'] for r in rows)}-{max(r['idle'] for r in rows)}")

        # ---- item 5: entering the title from GameOver, with a formation and three divers on screen
        rows = []
        for i in range(RUNS):
            start_game()
            start_wave(6)
            for s_, e in enumerate((0, 7, 14)):
                poke("enemy_state", [RETURN], e)
                sprite(ENEMY0 + e, 40 + 100 * s_, 180)
            poke("diver_enemy", [0, 7, 14])
            poke("zp_divers_active", [3])
            frame()
            to_title()
            rows.append(frames(1)[0])
            if p1("zp_game_state") != GS_TITLE or p1("zp_state_timer") != 1:
                raise MeasureError("title entry: not at the title")
        line(worst(rows, "game_update") <= ONEOFF_GAME and min(r["idle"] for r in rows) >= ONEOFF_IDLE,
             f"item 5, entering the title (GameOver's end with 18 enemies shown, 3 of them returning: 24 sprites hidden, "
             f"row 9 erased, 3 sprites placed, PRESS FIRE; a one-off frame): {RUNS} frames, {summary(rows, 'game_update')}; "
             f"{summary(rows, 'mux_update')}; idle {min(r['idle'] for r in rows)}-{max(r['idle'] for r in rows)} "
             f"(limit {ONEOFF_GAME} entering; idle >= {ONEOFF_IDLE})")

        # ---- item 5: the seeding. 8 presses in different title frames: the raster line of the $D012 read (a
        # checkpoint on the instruction that follows it), the generator's state after, and two presses one
        # frame apart
        seeds = []
        press_addr = None
        code = bytes(peek("title_update", 160))
        for i in range(len(code) - 2):
            if code[i:i + 3] == bytes([0xAD, 0x12, 0xD0]):             # lda $d012
                press_addr = sym["title_update"] + i + 3
        if press_addr is None:
            raise MeasureError("the $D012 read wasn't found in title_update")
        for tf in (8, 9, 12, 23, 40, 77, 130, 200):
            if p1("zp_game_state") != GS_TITLE:
                to_title()
                frame()
            stick(0)
            while p1("zp_state_timer") < tf - 1:
                frame()
            stick(FIRE)
            cp = mon.checkpoint_set(press_addr, press_addr, CPU_OP_EXEC)
            mon.exit()
            if not mon.wait_stopped(STOP_TIMEOUT):
                raise MeasureError("the press's $D012 read wasn't reached")
            reg = mon.registers()
            mon.checkpoint_delete(cp.number)
            frame()
            if p1("zp_state_timer") != tf or p1("title_step") != 10:
                raise MeasureError(f"seeding: the press wasn't in title frame {tf}")
            stick(0)
            seeds.append((tf, reg["LIN"], reg["CYC"], reg["A"], tuple(peek("zp_rng_lo", 2))))
            frame(6)
        lines = sorted({s_[1] for s_ in seeds})
        states = [s_[4] for s_ in seeds]
        line(len(set(states)) == len(states) and states[0] != states[1],
             f"item 5, seeding: 8 presses in title frames {[s_[0] for s_ in seeds]}: the $D012 read was on raster line(s) "
             f"{lines} (value read {sorted({s_[3] for s_ in seeds})}; the memory map counted about line 25: it is the "
             f"same line every time, as it said, so the generator's own state is what varies); generator states after "
             f"the press {[f'{hi:02x}{lo:02x}' for lo, hi in states]}: all different, the two presses one frame apart "
             f"(frames 8 and 9) included: {states[0] != states[1]}")

        # ---- item 1: Clear's first frame
        rows = []
        for i in range(RUNS):
            start_game()
            start_wave(3)
            st = [DEAD] * ENEMIES
            ys = list(peek("mux_y", ENEMIES, ENEMY0))
            for e in (0, 7, 14):
                st[e] = EXPLODING
                poke("enemy_timer", [1], e)
            poke("enemy_state", st)
            poke("mux_y", [ys[e] if e in (0, 7, 14) else MUX_OFF for e in range(ENEMIES)], ENEMY0)
            poke("explosion_enemy", [0, 7, 14, 0xFF])
            poke("zp_enemies_alive", [3])
            poke("zp_fx", [95 if i % 2 == 0 else 1])
            poke("zp_drift_dir", [1 if i % 2 == 0 else 0xFF])
            poke("zp_drift_timer", [1])
            poke("zp_anim_timer", [1])
            poke("game_score", [0x99, 0x95, 0x00] if i >= RUNS - 2 else [0, 0, 0])      # the last two: the score stops
            anim0 = p1("zp_anim_frame")
            rows.append(frames(1)[0])
            if (p1("zp_wave_phase"), p1("zp_wave_timer"), p1("zp_enemies_alive")) != (PHASE_CLEAR, 1, 0) \
                    or p1("zp_anim_frame") == anim0 or peek("game_score", 3).hex() != ("999990" if i >= RUNS - 2 else "001000"):
                raise MeasureError(f"clear: phase {p1('zp_wave_phase')}, score {peek('game_score', 3).hex()}")
        ok = worst(rows, "formation_update") <= FORMATION and max(r["formation_update"][2] for r in rows) < BORDER_LINE
        line(ok, f"item 1, Clear's first frame: formation_update with a drift turn, an animation swap and the last 3 "
             f"explosions ending together, the third paying the bonus (game_wave_clear; in 2 of the {RUNS} the score "
             f"stops at 999,990, its longer path): {summary(rows, 'formation_update')} (limit {FORMATION}; it must end "
             f"above line {BORDER_LINE}; no sound request yet: part B adds about 57-75); {summary(rows, 'game_update')}")

        # ---- item 2: a later wave's Intro frame 0
        rows = []
        for i in range(RUNS):
            start_game()
            start_wave(3)
            next_wave_in(2)
            frame()
            rows.append(frames(1)[0])
            if (p1("zp_wave_phase"), p1("zp_wave_timer")) != (PHASE_INTRO, 1) or p1("zp_wave") != 0x04 or p1("zp_loop") != 1:
                raise MeasureError("intro frame 0: not there")
        ok = (worst(rows, "game_update") <= ONEOFF_GAME and worst(rows, "formation_update") <= FORMATION
              and min(r["idle"] for r in rows) >= ONEOFF_IDLE and overruns() == 0)
        line(ok, f"item 2, a later wave's Intro frame 0 (the stores advance, formation_reset, diver_init, WAVE nn, enemy 0; "
             f"a one-off frame): {RUNS} frames, {summary(rows, 'game_update')}; {summary(rows, 'formation_update')}; "
             f"{summary(rows, 'mux_update')}; idle {min(r['idle'] for r in rows)}-{max(r['idle'] for r in rows)} (one-off "
             f"rule: <= {ONEOFF_GAME}, <= {FORMATION}, idle >= {ONEOFF_IDLE}, no overrun: game_overrun_count {overruns()})")

        # ---- item 3: every frame of an Intro, the ship sweeping with fire held
        rows = []
        for i in range(2):
            start_game()
            start_wave(3)
            next_wave_in(1)
            stick(RIGHT | FIRE if i == 0 else LEFT | FIRE)
            frame()                                               # Intro's frame 0
            rows += list(enumerate(frames(100), 1))
            stick(0)
            if p1("zp_wave_phase") != PHASE_FIGHT:
                raise MeasureError("intro: Fight not reached")
        appear = [r for k, r in rows if k % 2 == 0 and k <= 34]
        rest = [r for k, r in rows if not (k % 2 == 0 and k <= 34)]
        last = max(r["formation_update"][2] for _, r in rows)
        line(last < BORDER_LINE and worst([r for _, r in rows], "formation_update") <= FORMATION,
             f"item 3, all of an Intro (frames 1-100, twice, the ship sweeping with fire held and its shots hitting "
             f"enemies as they appear): the 34 frames an enemy appears in: {summary(appear, 'game_update')}, "
             f"{summary(appear, 'formation_update')}; the other {len(rest)}: {summary(rest, 'game_update')}, "
             f"{summary(rest, 'formation_update')}; formation_update ended on line {last} at the latest (required: above "
             f"{BORDER_LINE} in every frame); {summary([r for _, r in rows], 'mux_update')}; idle "
             f"{min(r['idle'] for _, r in rows)}-{max(r['idle'] for _, r in rows)}")

        # ---- item 6: GameOver's frame 0 and frame 1 with 3 divers still out
        rows0, rows1 = [], []

        def last_dying(timer):
            start_game()
            start_wave(6)                                         # pattern 3 at loop 1
            poke("zp_lives", [0])
            poke("game_score", [0x00, 0x61, 0x50])
            poke("game_hiscore", [0x00, 0x50, 0x00])
            poke("zp_game_state", [GS_DYING])
            poke("zp_state_timer", [timer])
            sprite(0, 171, MUX_OFF)
            for s_, e in enumerate((0, 7, 14)):
                poke("enemy_state", [RETURN], e)
                sprite(ENEMY0 + e, (20, 330, 170)[s_], (30, 200, 210)[s_])
            poke("diver_enemy", [0, 7, 14])
            poke("zp_divers_active", [3])
            frame()

        for i in range(RUNS):
            last_dying(98)                                        # stopped in PlayerDying's frame 99
            got = frames(2)                                       # GameOver's frames 0 and 1
            if p1("zp_game_state") != GS_OVER or peek("game_hiscore", 3).hex() != "006150" or p1("zp_divers_active") != 3:
                raise MeasureError(f"GameOver: state {p1('zp_game_state')}, hi {peek('game_hiscore', 3).hex()}")
            rows0.append(got[0])
            rows1.append(dict(got[1], four=False))
        for i in range(RUNS // 2):
            last_dying(99)                                        # stopped in GameOver's frame 0
            if p1("zp_game_state") != GS_OVER or p1("panel_dirty") != 8:
                raise MeasureError(f"GameOver frame 0: state {p1('zp_game_state')}, dirty {p1('panel_dirty')}")
            poke("panel_dirty", [0x0F])                           # all four fields, as the limit is for
            rows1.append(dict(frames(1)[0], four=True))
        hi_only, four = [r for r in rows1 if not r["four"]], [r for r in rows1 if r["four"]]
        ok = (max(r["formation_update"][2] for r in rows0 + rows1) < BORDER_LINE
              and worst(rows1, "panel_update") <= PANEL4 and worst(rows0 + rows1, "formation_update") <= FORMATION)
        line(ok, f"item 6, GameOver with 3 divers still out (returning; wave 6: loop 1), the score above the high score. "
             f"Frame 0 (the compare and copy, GAME OVER written, the dirty flag; no sound request yet): "
             f"{summary(rows0, 'game_update')}; {summary(rows0, 'formation_update')}. Frame 1: panel_update "
             f"{min(r['panel_update'][0] for r in hi_only)}-{max(r['panel_update'][0] for r in hi_only)} with the high "
             f"score alone dirty (what the game asks for) and {min(r['panel_update'][0] for r in four)}-"
             f"{max(r['panel_update'][0] for r in four)} with all four set by the monitor (limit {PANEL4}); "
             f"{summary(rows1, 'formation_update')} (required: formation_update ends above line {BORDER_LINE} in both)")

        # ---- item 10: a whole session by the stick
        to_title()
        frame(3)
        poke("game_idle_min", [0xFF, 0xFF])
        low = {}

        sweep = {"x": RIGHT | FIRE}

        def play(frames_, tag):
            """The ship sweeping between the clamps with fire held; the stick is left held."""
            for _ in range(frames_):
                px = int.from_bytes(peek("zp_player_x_lo", 2), "little")
                if px >= 318:
                    sweep["x"] = LEFT | FIRE
                elif px <= 24:
                    sweep["x"] = RIGHT | FIRE
                stick(sweep["x"])
                frame()
                low[tag] = min(low.get(tag, 99999), idle_now())

        def title_frames(n, tag):
            for _ in range(n):
                frame()
                low[tag] = min(low.get(tag, 99999), idle_now())

        title_frames(60, "title")
        press_at(max(8, p1("zp_state_timer") + 2))
        title_frames(6, "title")
        waves = []
        for w in range(3):
            poke("zp_lives", [3])                                 # the session is about the frames, not the player's skill
            n = 0
            while p1("zp_wave_phase") != PHASE_CLEAR and n < 2000:
                if p1("zp_game_state") == GS_PLAY and p1("zp_lives") < 3:
                    poke("zp_lives", [3])
                play(1, "play")
                n += 1
                if n == 1400 and p1("zp_wave_phase") == PHASE_FIGHT:     # the rest killed through the monitor:
                    st = [DEAD] * ENEMIES                                 # one left, its explosion ending
                    st[17] = EXPLODING
                    poke("enemy_state", st)
                    poke("mux_y", [MUX_OFF] * 17, ENEMY0)
                    poke("enemy_timer", [1], 17)
                    poke("explosion_enemy", [17, 0xFF, 0xFF, 0xFF])
                    poke("diver_enemy", [0xFF] * 3)
                    poke("zp_divers_active", [0])
                    poke("zp_enemies_alive", [1])
            waves.append((p1("zp_wave"), n, peek("game_score", 3).hex()))
            while p1("zp_wave_phase") != PHASE_INTRO:
                play(1, "play")
        poke("zp_lives", [1])
        poke("zp_player_invuln", [0])
        n = 0
        while p1("zp_game_state") != GS_OVER and n < 3000:
            play(1, "play")
            n += 1
            if n % 50 == 0 and p1("zp_game_state") == GS_PLAY:    # make sure the last life goes: a shot on the ship
                px = int.from_bytes(peek("zp_player_x_lo", 2), "little")
                sprite(ESHOT0, px, 205)
                poke("eshot_dx", [0])
                poke("zp_player_invuln", [0])
        while p1("zp_game_state") != GS_TITLE:
            play(1, "game over")
        stick(0)
        title_frames(40, "title")
        press_at(max(8, p1("zp_state_timer") + 2))
        title_frames(6, "title")
        play(600, "play")
        counts = {k: p1(k) for k in ("game_overrun_count", "mux_late_count", "irq_late_count", "mux_pin_drop_count")}
        counts["mux_max_age"] = p1("mux_max_age")
        gmin = int.from_bytes(peek("game_idle_min", 2), "little") * 16
        ok = not any(counts[k] for k in ("game_overrun_count", "mux_late_count", "irq_late_count", "mux_pin_drop_count")) \
            and gmin >= IDLE_MIN
        line(ok, f"item 10, a whole session by the stick: the title, three waves (shown wave, frames, score at each "
             f"clear: {[(f'{w:02x}', n_, s_) for w, n_, s_ in waves]}; the ship sweeping with fire held, lives topped up; a wave "
             f"still going after 1,400 frames is ended through the monitor), the last life lost, GAME OVER, the title, a "
             f"second game for 600 frames: " + ", ".join(f"{k} {c}" for k, c in counts.items())
             + f" (the first four required 0); lowest idle in a frame by state {low}; game_idle_min x 16 over the "
             f"session {gmin} (required >= {IDLE_MIN})")
    finally:
        v.close()
    print("items 7 and 9 (the sound tick, collide_update's placed frames with their sound requests) and the sound "
          "requests inside items 1, 2, 6 and 8 are part B's: there is no sound module in this build")
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL: {e}")
        sys.exit(2)
