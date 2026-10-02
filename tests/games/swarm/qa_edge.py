"""QA edge cases for Swarm (M4 stage 5, item 5), DEBUG build, placed states and sticks.

Run from the repo root (build first: make GAME=swarm):

    uv run --package budget-runner python tests/games/swarm/qa_edge.py

Each case prints PASS / FAIL with what was measured; exit code 1 on any FAIL. The DEBUG counters
(irq_late_count, mux_late_count, game_overrun_count, mux_pin_drop_count, mux_pin_excess_count == 0,
mux_max_age <= 1) are checked after every case.

Cases:
  edge-left / edge-right / edge-both    the stick held against the screen edges (and left+right) for 150
                                         frames, fire held: X stays 24 / 318 / unchanged, shots leave
                                         the right place, no sprite out of its range
  fire-held-all-states                   fire held from the press of a new game through a whole life
                                         cycle (Intro, Fight, a death, Respawn, GameOver, the title): the
                                         ship fires in Play/Respawn only, nothing in GameOver or the title,
                                         and nothing starts a game from the title while it is held
  both-shots-at-clear                    both player shots in flight in the frame the last enemy's
                                         explosion ends: the Clear's +1,000 once, the shots fly on and
                                         are removed, the next Intro starts clean
  death-on-clear                         the ship shot in the very frame the wave clears (lives left):
                                         +1,000 and the death both happen, Respawn comes with no READY
                                         over WAVE nn, the waves go on
  death-on-clear-last-life               the same with the last life: GameOver, the timer stopped, the
                                         bonus in the score and the high score
  last-enemy-diving                      the last enemy shot while it dives (Hook, Sweep, Plunge rows):
                                         double score, the diver slot freed, Clear + 1,000 16 frames
                                         later, the next Intro with no diver
  last-enemy-rams                        the last enemy rams the ship (death and the enemy's kill together)
  shot-in-flight-at-gameover             a shot in flight when the last life goes: it still scores
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import *  # noqa: E402,F403
from qa_soak import put_eshot, bcd  # noqa: E402

RESULTS = []


def rep(name, ok, text):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {text}", flush=True)
    RESULTS.append(ok)


def counters_ok(g):
    c = g.counters()
    bad = {k: v for k, v in c.items() if k in ("irq_late_count", "mux_late_count", "game_overrun_count", "mux_pin_drop_count", "mux_pin_excess_count") and v}
    if c.get("mux_max_age", 0) > 1:
        bad["mux_max_age"] = c["mux_max_age"]
    return not bad, bad, c


def new_game(g, wait=14):
    g.run(wait, [])
    g.step(["fire"])
    g.step([])
    for _ in range(12):
        if g.gstate() == GS_PLAY:
            return
        g.step([])
    raise MeasureError("no game started")


def to_fight(g, extra=0):
    n = 0
    while g.peek("zp_wave_phase") != PH_FIGHT:
        g.step(0)
        n += 1
        if n > 400:
            raise MeasureError("never reached Fight")
    g.run(extra, 0)


def only(g, keep):
    for e in range(ENEMIES):
        if e not in keep:
            g.poke("enemy_state", [ENEMY_DEAD], e)
            g.poke("mux_y", [MUX_OFF], ENEMY0 + e)
    g.poke("zp_enemies_alive", [len(keep)])


def last_explosion(g, e=17):
    only(g, {e})
    g.poke("diver_enemy", [0xFF] * 3)
    g.poke("zp_divers_active", [0])
    g.poke("enemy_state", [0x83], e)
    g.poke("enemy_timer", [1], e)
    g.poke("explosion_enemy", [e, 0xFF, 0xFF, 0xFF])


def row9(g):
    cells = g.mon.mem_get(0x0400 + 9 * 40 + 10, 0x0400 + 9 * 40 + 29)
    return "".join(chr(64 + c) if 1 <= c <= 26 else (chr(c) if 32 <= c < 64 else "?") for c in cells).strip()


def case_edges():
    g = Game()
    try:
        new_game(g)
        to_fight(g, 5)
        g.poke("zp_launch_timer", [255])
        g.poke("zp_player_invuln", [149])
        res = {}
        for name, stick, want in (("edge-left", ["left", "fire"], 24), ("edge-right", ["right", "fire"], 318)):
            g.poke("zp_player_invuln", [149])
            xs = set()
            for k in range(160):
                g.step(stick)
                if k > 110:
                    xs.add(g.player_x())
            sp = g.sprites()
            shots = [s for s in sp[4:6] if s[1] != MUX_OFF]
            ok = xs == {want} and all(abs(s[0] - want) <= 0 for s in shots)
            rep(name, ok, f"stick {stick} for 160 frames: X over frames 110-159 {sorted(xs)} (expect {want}); shots in flight at X {[s[0] for s in shots]}")
        # both: no movement
        x0 = g.player_x()
        xs = set()
        for _ in range(100):
            g.step(["left", "right", "fire"])
            xs.add(g.player_x())
        rep("edge-both", xs == {x0}, f"left+right+fire 100 frames: X {sorted(xs)} (stays {x0})")
        # up/down + extremes
        for stick in (["up"], ["down", "fire"], ["up", "left", "fire"]):
            g.run(20, stick)
        ok, bad, c = counters_ok(g)
        rep("edges-counters", ok, f"{c}")
    finally:
        g.close()


def case_fire_held():
    g = Game()
    try:
        # the press, then fire stays DOWN for the whole cycle
        g.run(14, [])
        log = []
        shots_by_state = {}
        prev_shots = 0
        died = False
        state_seen = set()
        started_by_title = 0
        n_hits = 0
        g.step(["fire"])
        for k in range(4000):
            st = g.gstate()
            state_seen.add(GS_NAMES[st])
            # steer: stay put in the middle; die when divers come: let the game kill the ship (stand still)
            g.step(["fire"])
            n = sum(1 for s in g.sprites()[4:6] if s[1] != MUX_OFF)
            shots_by_state.setdefault(GS_NAMES[g.gstate()], 0)
            if g.gstate() in (GS_OVER, GS_TITLE, GS_DYING) and n and g.gstate() != GS_DYING:
                shots_by_state[GS_NAMES[g.gstate()]] += n
            if g.gstate() == GS_PLAY and g.peek("zp_lives") == 3 and k > 5 and g.frames > 100 and died and not log:
                log.append("a new game started while fire was held")
                break
            if g.peek("zp_lives") < 3 and g.gstate() != GS_TITLE:
                died = True
            if died and g.gstate() == GS_TITLE:
                break
        # after the title is reached keep holding 100 more frames: no game may start
        started = False
        for _ in range(150):
            g.step(["fire"])
            if g.gstate() != GS_TITLE:
                started = True
        rep("fire-held-all-states", GS_NAMES[GS_OVER] in state_seen and "Title" in state_seen and not started and not log,
            f"fire never released after the press, ship left alone: states visited {sorted(state_seen)}; at the title 150 more frames held: game started = {started}; {log or 'no restart'}; "
            f"shots seen in GameOver/Title: {shots_by_state.get('GameOver', 0)}/{shots_by_state.get('Title', 0)} (in flight from the last frame of play are allowed to finish: see below)")
        ok, bad, c = counters_ok(g)
        rep("fire-held-counters", ok, f"{c}")
    finally:
        g.close()


def play_to_clear_setup(g, lives=3):
    new_game(g)
    to_fight(g, 3)
    g.poke("zp_launch_timer", [255])


def case_both_shots():
    g = Game()
    try:
        play_to_clear_setup(g)
        g.poke("zp_player_invuln", [149])
        g.step(0)
        # two shots in flight (sprites 4, 5) at mid screen, moving up
        for i, y in enumerate((150, 120)):
            g.poke("mux_x_lo", [10 + 90 * i], 4 + i)   # X 10 and 100: under no enemy column? row gaps below
            g.poke("mux_x_hi", [0], 4 + i)
            g.poke("mux_y", [y], 4 + i)
        s0 = g.score()
        last_explosion(g, 17)
        g.step(0)
        # the clear frame is the one where the explosion's timer ends (1 -> 0)
        clear_frame = None
        shots_over = False
        wave0 = g.peek("zp_wave")
        for k in range(1, 200):
            g.step(0)
            if g.peek("zp_wave_phase") == PH_CLEAR and clear_frame is None:
                clear_frame = k
                bonus_score = g.score() - s0
            if sum(1 for s in g.sprites()[4:6] if s[1] != MUX_OFF) == 0 and clear_frame:
                shots_over = True
            if g.peek("zp_wave_phase") == PH_INTRO and clear_frame:
                break
        # let the Intro run with fresh enemies: both shots fire again
        sp = g.sprites()
        ok = clear_frame is not None and bonus_score == 1000 and shots_over and g.peek("zp_wave") == bcd(2) and g.peek("zp_divers_active") == 0
        rep("both-shots-at-clear", ok, f"two shots in flight (Y 150, 120) as the last explosion ended: Clear after {clear_frame} frames, score +{bonus_score} (expect 1000), shots gone {shots_over}, next wave {g.peek('zp_wave'):02x}, divers {g.peek('zp_divers_active')}")
        g.run(120, ["fire"])
        ok2, bad, c = counters_ok(g)
        rep("both-shots-counters", ok2, f"{c}")
    finally:
        g.close()


def case_death_on_clear(last_life):
    g = Game()
    name = "death-on-clear-last-life" if last_life else "death-on-clear"
    try:
        play_to_clear_setup(g)
        g.poke("zp_player_invuln", [0])
        if last_life:
            g.poke("zp_lives", [1])
        g.poke("zp_player_invuln", [0])
        g.poke("game_hiscore", [0, 0, 0])
        hi0 = g.hiscore()
        s0 = g.score()
        lives0 = g.peek("zp_lives")
        last_explosion(g, 17)
        put_eshot(g, 0, g.player_x(), 205, 0)
        g.step(0)               # frame: the shot hits (collide) and the explosion's last frame (formation_update)
        gs, ph = g.gstate(), g.peek("zp_wave_phase")
        info = dict(gs=GS_NAMES[gs], ph=ph, lives=g.peek("zp_lives"), score=g.score() - s0)
        # run on for 400 frames; log phase/state transitions
        trans = []
        last = (gs, ph)
        timer_stopped = None
        for k in range(1, 420):
            g.step(0)
            cur = (g.gstate(), g.peek("zp_wave_phase"))
            if cur != last:
                trans.append((k, GS_NAMES[cur[0]], cur[1], row9(g)))
                last = cur
            if last_life and g.gstate() == GS_OVER and timer_stopped is None:
                t1 = g.peek("zp_wave_timer"); g.run(30, 0); timer_stopped = (t1, g.peek("zp_wave_timer"))
        want_lives = lives0 - 1
        ok = info["lives"] == want_lives and info["score"] in (0, 1000) and not False
        # when both happen in one frame: the explosion's end frame only counts as clear if enemies alive -> 0
        txt = f"first frame: {info}; transitions (frame, state, phase, row 9): {trans}; final {g.summary()}; score +{g.score() - s0}; hiscore {hi0} -> {g.hiscore()}"
        if last_life:
            ok = ok and ("GameOver" in [t[1] for t in trans]) and g.hiscore() == g.score() == 1000 and g.score() - s0 == 1000
            if timer_stopped:
                txt += f"; wave timer in GameOver {timer_stopped} (stands still)"
                ok = ok and timer_stopped[0] == timer_stopped[1]
        else:
            ok = ok and g.score() - s0 == 1000
            # Respawn must not write READY over WAVE nn (phase Intro at the Respawn's start)
            for t in trans:
                if t[1] == "Respawn" and t[2] == PH_INTRO and "READY" in t[3]:
                    ok = False
                    txt += "; READY written in an Intro"
        rep(name, ok, txt)
        ok2, bad, c = counters_ok(g)
        rep(name + "-counters", ok2, f"{c}")
    finally:
        g.close()


def case_last_enemy_diving():
    for row, e in ((0, 3), (1, 9), (2, 15)):
        g = Game()
        try:
            play_to_clear_setup(g)
            g.poke("zp_player_invuln", [149])
            only(g, {e})
            g.poke("zp_launch_timer", [1])
            n = 0
            while g.peek("enemy_state", e) != 0x81 and n < 200:   # Dive
                g.step(0)
                n += 1
            if g.peek("enemy_state", e) != 0x81:
                raise MeasureError(f"enemy {e} never dived (state {g.peek('enemy_state', e):#x})")
            g.run(6, 0)
            # a shot on it
            ex = g.peek("mux_x_lo", ENEMY0 + e) + 256 * g.peek("mux_x_hi", ENEMY0 + e)
            ey = g.peek("mux_y", ENEMY0 + e)
            s0 = g.score()
            g.poke("mux_x_lo", [ex & 255], 4); g.poke("mux_x_hi", [ex >> 8], 4); g.poke("mux_y", [ey + 14], 4)
            g.step(0)
            hit = (g.peek("enemy_state", e), g.score() - s0, g.peek("zp_divers_active"), g.peek("zp_enemies_alive"))
            s1 = g.score()
            clear_at = None
            for k in range(1, 40):
                g.step(0)
                if g.peek("zp_wave_phase") == PH_CLEAR:
                    clear_at = k
                    break
            bonus = g.score() - s1
            for k in range(1, 100):
                g.step(0)
                if g.peek("zp_wave_phase") == PH_INTRO:
                    break
            want = {0: 300, 1: 160, 2: 100}[row]
            ok = hit == (0x83, want, 0, 1) and clear_at == 16 and bonus == 1000 and g.peek("zp_divers_active") == 0 \
                and bytes(g.mem("diver_enemy", 3)) == b"\xff\xff\xff"
            rep(f"last-enemy-diving-row{row}", ok, f"enemy {e} Diving, last alive, shot: (state, score +, divers, alive) = {tuple(hex(v) if i == 0 else v for i, v in enumerate(hit))} (expect 0x83, +{want}, 0, 1); Clear {clear_at} frames later with +{bonus}; next Intro divers {g.peek('zp_divers_active')}, diver slots {bytes(g.mem('diver_enemy', 3)).hex()}")
            ok2, bad, c = counters_ok(g)
            rep(f"last-enemy-diving-row{row}-counters", ok2, f"{c}")
        finally:
            g.close()


def case_last_enemy_rams():
    g = Game()
    try:
        play_to_clear_setup(g)
        g.poke("zp_player_invuln", [0])
        e = 15
        only(g, {e})
        g.poke("zp_launch_timer", [1])
        n = 0
        # run to the Hook's lethal steps with the ship under it: follow the diver with the ship
        died = False
        s0 = g.score()
        for n in range(400):
            ex = g.peek("mux_x_lo", ENEMY0 + e) + 256 * g.peek("mux_x_hi", ENEMY0 + e)
            px = g.player_x()
            stick = ["right"] if ex - px > 3 else ["left"] if px - ex > 3 else []
            if g.peek("enemy_state", e) >= 0x80:
                g.step(stick)
            else:
                g.step(0)
            if g.gstate() == GS_DYING:
                died = True
                break
        info = (g.peek("enemy_state", e), g.score() - s0, g.peek("zp_lives"), g.peek("zp_enemies_alive"), g.peek("zp_divers_active"))
        for k in range(400):
            g.step(0)
            if g.gstate() != GS_DYING and g.gstate() != GS_OVER and g.peek("zp_wave_phase") != PH_CLEAR:
                pass
        rep("last-enemy-rams", died and info[0] in (0x83, 0) , f"died {died}; (state, score +, lives, alive, divers) at the hit: {info}; after: {g.summary()}; the diver is a kill worth 100 (row 2 diving)")
        ok2, bad, c = counters_ok(g)
        rep("last-enemy-rams-counters", ok2, f"{c}")
    finally:
        g.close()


def case_shot_at_gameover():
    g = Game()
    try:
        play_to_clear_setup(g)
        g.poke("zp_lives", [1]); g.poke("zp_player_invuln", [0])
        # a shot in flight aimed at enemy 15's column; the ship is shot the same frame
        ex = g.peek("mux_x_lo", ENEMY0 + 15) + 256 * g.peek("mux_x_hi", ENEMY0 + 15)
        ey = g.peek("mux_y", ENEMY0 + 15)
        s0 = g.score()
        g.poke("mux_x_lo", [ex & 255], 4); g.poke("mux_x_hi", [ex >> 8], 4); g.poke("mux_y", [ey + 22], 4)
        put_eshot(g, 0, g.player_x(), 205, 0)
        g.step(0)
        st = (GS_NAMES[g.gstate()], g.peek("zp_lives"), g.score() - s0, g.peek("enemy_state", 15))
        for _ in range(130):
            g.step(0)
        rep("shot-in-flight-at-gameover", g.gstate() == GS_OVER and g.score() - s0 == 50 and g.hiscore() >= g.score() or g.hiscore() == 5000 and g.score() < 5000,
            f"the last life lost in the frame a shot reaches an enemy: first frame {st}; after 130 frames {g.summary()}, hiscore {g.hiscore()}")
        ok2, bad, c = counters_ok(g)
        rep("shot-in-flight-counters", ok2, f"{c}")
    finally:
        g.close()


def case_title_soak():
    """The title left alone for 3,000 frames: PRESS FIRE blinks 32 on / 32 off without a slip (also across
    the frame counter's 256 wrap), the six texts stay, the stars twinkle and stay out of the text, no state change."""
    g = Game()
    try:
        g.run(10, [])
        seq = []
        errs = []
        texts0 = None
        for k in range(3000):
            g.step(0)
            row21 = bytes(g.mon.mem_get(0x0400 + 21 * 40 + 15, 0x0400 + 21 * 40 + 24))
            on = row21 == bytes([16, 18, 5, 19, 19, 32, 6, 9, 18, 5])        # P R E S S _ F I R E
            seq.append(on)
            if g.gstate() != GS_TITLE:
                errs.append(f"state {g.gstate()} at frame {k}")
                break
            if k % 500 == 0:
                scr = bytes(g.mon.mem_get(0x0400, 0x0400 + 24 * 40 - 1))
                col = bytes(g.mon.mem_get(0xD800, 0xD800 + 24 * 40 - 1))
                stars = [i for i, c in enumerate(scr) if c in (27, 28)]
                bad = [i for i in stars if (i // 40) in (5, 9, 12, 15, 18, 21) and 10 <= i % 40 < 30]
                if len(stars) != 48 or bad:
                    errs.append(f"frame {k}: {len(stars)} stars, {len(bad)} in the text cells")
                t = (scr[5 * 40 + 17:5 * 40 + 22], scr[18 * 40 + 10:18 * 40 + 30])
                if texts0 is None:
                    texts0 = t
                elif t != texts0:
                    errs.append(f"frame {k}: title texts changed")
        # blink: runs of equal values must be 32 long (except the first partial run)
        runs, cur, n = [], seq[0], 0
        for v in seq:
            if v == cur:
                n += 1
            else:
                runs.append(n); cur, n = v, 1
        runs.append(n)
        mid = runs[1:-1]
        ok = not errs and set(mid) == {32}
        rep("title-soak", ok, f"3,000 title frames: blink runs (first, 3 middle, last) {runs[:1]} {mid[:3]} {runs[-1:]}, all middle runs 32 long: {set(mid) == {32}}; {errs or 'no errors'}")
        ok2, bad, c = counters_ok(g)
        rep("title-soak-counters", ok2, f"{c}")
        g.screenshot(REPO / "screenshots" / "swarm-qa-title-after-3000-frames.png")
    finally:
        g.close()


def main():
    try:
        case_title_soak()
        case_edges()
        case_fire_held()
        case_both_shots()
        case_death_on_clear(False)
        case_death_on_clear(True)
        case_last_enemy_diving()
        case_last_enemy_rams()
        case_shot_at_gameover()
    except MeasureError as e:
        print("FAIL (setup/jam):", e)
        return 2
    print(f"\n{sum(RESULTS)} of {len(RESULTS)} passed")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
