"""QA soak of the states the budget build doesn't reach (M4 stage 5, item 3), on the DEBUG build.

Run from the repo root (build first: make GAME=swarm), one scenario at a time (each starts its own
VICE; run several in parallel with qa_soak_all.sh):

    uv run --package budget-runner python tests/games/swarm/qa_soak.py <scenario> [--frames N] [--seed S]

Scenarios (all stop at game_update_end every frame; DEBUG counters read every 500 frames and at the end;
FAIL = a counter non-zero, mux_max_age > 1, an impossible value, a jam):
  wave3-passive, wave3-play, wave12-passive, wave12-play
               the wave is held (every Clear puts the three stores back one wave, so the next Intro is
               the same wave again) and the ship is kept alive (zp_player_invuln held at 149, as check.py's
               safe()). Passive = the bot only dodges and never fires, so the formation stays full and
               the divers keep coming: the model's worst case (design.md: wave 3 11.6%, wave 12 9.0%).
               Play = the bot chases and fires. Reports the share of frames in which the multiplexer dropped
               a sprite (game_flicker_frames), by number of divers out
  thin12, thin30
               wave 12 / 30 held; at each Fight's first frame all but 1-4 Parked enemies are taken away
               (alive <= 4); passive bot, three divers out whenever the launcher allows; counts the divers'
               wraps (a sprite at Y 30 while Diving)
  death3       wave 12 passive, ship vulnerable; whenever three divers are out (Play) an enemy shot is placed
               on the ship (the hit's frame has the most sprites moving); repeated through lives and games
  cycles       lives set to 1 and the ship hit, GameOver, title, new game, 40 times, with the press that
               skips GameOver (frame 50-199) and the one that waits it out, fire held or tapped
  clear        waves cleared at once by the monitor (the last enemy's explosion) after a short Fight: Clear and
               Intro 130 times, so the wave number passes 12 and 99; checks the shown wave, pattern and loop
               stores and the panel text; the score starts at 999,000 and passes 999,990
  fuzz         random sticks for the whole run (games restarted as they end) and a random jump every 400-900 frames
               (a wave, a thinned formation, a score near the cap, the ship's X, the lives)
  fifth        4 explosions running and a shot on a 5th enemy; then 3 running and two shots in one frame

Output: lines starting FAIL / NOTE / RESULT; exit code 1 on any FAIL.
"""

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import *  # noqa: E402,F403
from qa_positions import place_wave  # noqa: E402

ESHOT0 = 1


def bcd(v):
    return (v // 10) * 16 + v % 10


def valid_bcd(b):
    return (b >> 4) <= 9 and (b & 15) <= 9


class Soak:
    def __init__(self, name, prg=DEBUG_PRG, seed=1, safe=False, wave=None):
        self.name = name
        self.g = Game(prg)
        self.rng = random.Random(seed)
        self.safe, self.wave = safe, wave
        self.fails = []
        self.notes = []
        self.f = 0
        self.prev_flick = 0
        self.prev_div = 0
        self.prev_in_fight = False
        self.frames_by_div = Counter()
        self.flick_by_div = Counter()
        self.fight_frames = 0
        self.fight_flick = 0
        self.idle_min = 65535
        self.idle_at = None
        self.hold_n = 0
        self.placed = False
        self.wraps = 0
        self.max_div = 0
        self.state_frames = Counter()
        self.last_y30 = set()
        self.min_alive_seen = 99
        self.seen_flick_pair = 0
        self.prev_flicked = False
        self.consec = 0

    def fail(self, text):
        self.fails.append(f"f{self.f}: {text}")
        if len(self.fails) <= 25:
            print("FAIL", self.fails[-1], "|", self.g.summary(), flush=True)

    # ---- one frame: stick, safe-hold, wave hold, checks
    def frame(self, stick):
        g = self.g
        if self.safe:
            self.hold_n -= 1
            if self.hold_n <= 0:
                g.poke("zp_player_invuln", [149])
                self.hold_n = 8
        g.step(stick)
        self.f += 1
        zp = g.mon.mem_get(0, 0xFF)
        sym = g.sym

        def z(label):
            return zp[sym[label]]
        gs, lives, div, alive = z("zp_game_state"), z("zp_lives"), z("zp_divers_active"), z("zp_enemies_alive")
        wave, ph = z("zp_wave"), z("zp_wave_phase")
        self.state_frames[GS_NAMES[gs] if gs < 5 else f"?{gs}"] += 1
        self.max_div = max(self.max_div, div)
        # flicker: game_flicker_frames at this stop includes the previous frame's mux_update
        if g.debug:
            flick = g.peek16("game_flicker_frames")
            idle = zp[sym["game_idle_min"]] + 256 * zp[sym["game_idle_min"] + 1]
            if self.f > 205 and idle < self.idle_min:
                self.idle_min = idle
                self.idle_at = (self.f, GS_NAMES[gs] if gs < 5 else gs, f"wave {wave:02x}", f"phase {ph}", f"alive {alive}", f"divers {div}")
            d = flick - self.prev_flick
            self.prev_flick = flick
            if self.f > 1 and gs != GS_TITLE:
                self.frames_by_div[self.prev_div] += 1
                if d:
                    self.flick_by_div[self.prev_div] += 1
                    if self.prev_flicked:
                        self.consec += 1
                self.prev_flicked = bool(d)
                if self.prev_in_fight:
                    self.fight_frames += 1
                    self.fight_flick += 1 if d else 0
            self.prev_div = div
            self.prev_in_fight = (ph == PH_FIGHT and gs == GS_PLAY)
        # invariants
        if lives > 3:
            self.fail(f"lives {lives}")
        if div > 3:
            self.fail(f"divers active {div}")
        if alive > 18:
            self.fail(f"enemies alive {alive}")
        if not valid_bcd(wave) or wave == 0:
            self.fail(f"wave {wave:02x}")
        if gs != GS_TITLE and (z("zp_loop") > 3 or z("zp_pattern") > 2):     # power-on RAM until the first game sets them
            self.fail(f"loop {z('zp_loop')} pattern {z('zp_pattern')}")
        sc = g.mem("game_score", 3)
        if not all(valid_bcd(b) for b in sc) or int(sc.hex()) > 999990 or sc[2] & 15:
            self.fail(f"score bytes {sc.hex()}")
        ys = g.mem("mux_y", 24)
        xh = g.mem("mux_x_hi", 24)
        for i in range(24):
            if ys[i] != MUX_OFF and not (30 <= ys[i] <= 221):
                self.fail(f"sprite {i} Y {ys[i]}")
            if xh[i] > 1:
                self.fail(f"sprite {i} x_hi {xh[i]}")
        st = g.mem("enemy_state", ENEMIES)
        for e in range(ENEMIES):
            if st[e] not in (0, 1, 2, 0x80, 0x81, 0x82, 0x83):
                self.fail(f"enemy {e} state {st[e]:#x}")
            # a wrap: a Diving enemy re-entering at Y 30
            if st[e] in (0x81, 0x82) and ys[ENEMY0 + e] == 30 and e not in self.last_y30:
                self.wraps += 1
            if st[e] in (0x81, 0x82) and ys[ENEMY0 + e] == 30:
                self.last_y30.add(e)
            else:
                self.last_y30.discard(e)
        if self.f % 500 == 0:
            self.check_counters()
        # sticky wave / placement
        if self.wave is not None:
            if not self.placed and gs == GS_PLAY and ph == PH_INTRO and z("zp_wave_timer") >= 1:
                place_wave(g, self.wave)
                self.placed = True
            elif ph == PH_CLEAR and self.placed:
                n = self.wave
                if n == 1:
                    g.poke("zp_wave", [0]); g.poke("zp_pattern", [2]); g.poke("zp_loop", [0])
                else:
                    g.poke("zp_wave", [bcd(n - 1)]); g.poke("zp_pattern", [(n - 2) % 3]); g.poke("zp_loop", [min((n - 2) // 3, 3)])
        return gs, ph, div, alive

    def check_counters(self):
        c = self.g.counters()
        if not c:
            return
        for k in ("irq_late_count", "mux_late_count", "game_overrun_count", "mux_pin_drop_count", "mux_pin_excess_count"):
            if c[k]:
                self.fail(f"{k} = {c[k]}")
        if c["mux_max_age"] > 1:
            self.fail(f"mux_max_age = {c['mux_max_age']}")

    def start_game(self, wait=14):
        g = self.g
        for _ in range(wait):
            self.frame(0)
        self.frame(BITS["fire"])
        for _ in range(12):
            self.frame(0)
            if g.gstate() == GS_PLAY:
                return
        self.fail("no game started")

    # ---- the report
    def report(self):
        g = self.g
        c = g.counters()
        self.check_counters()
        print(f"RESULT {self.name}: {self.f} frames; states {dict(self.state_frames)}")
        print(f"RESULT counters {c}; lowest game_idle_min {self.idle_min} (= {self.idle_min * 16} cycles) at {self.idle_at}; floor 45")
        tot = sum(self.frames_by_div.values())
        fl = sum(self.flick_by_div.values())
        print(f"RESULT frames with a dropped sprite (game_flicker_frames): {fl} of {tot} non-title frames = {100.0 * fl / max(1, tot):.2f}%;"
              f" in Fight/Play frames: {self.fight_flick} of {self.fight_frames} = {100.0 * self.fight_flick / max(1, self.fight_frames):.2f}%;"
              f" back-to-back flicker frames: {self.consec} (mux_max_age, not this, is the 'no sprite missing two frames running' rule)")
        for d in sorted(self.frames_by_div):
            n, k = self.frames_by_div[d], self.flick_by_div[d]
            print(f"RESULT   divers out {d}: {k} of {n} frames = {100.0 * k / max(1, n):.2f}%")
        print(f"RESULT max divers {self.max_div}; wraps to Y 30 seen {self.wraps}")
        for n in self.notes:
            print("NOTE", n)
        print(f"RESULT {'FAIL' if self.fails else 'PASS'} ({len(self.fails)} failures)")
        g.close()
        return 1 if self.fails else 0


# ----------------------------------------------------------------------------------------------
def thin(g, keep):
    """Take away all but `keep` Parked enemies (random), as a hit would have, through the monitor."""
    st = list(g.mem("enemy_state", ENEMIES))
    parked = [e for e in range(ENEMIES) if st[e] == ENEMY_PARKED]
    random.shuffle(parked)
    for e in parked[keep:]:
        g.poke("enemy_state", [ENEMY_DEAD], e)
        g.poke("mux_y", [MUX_OFF], ENEMY0 + e)
    st = list(g.mem("enemy_state", ENEMIES))
    g.poke("zp_enemies_alive", [sum(1 for s in st if s != ENEMY_DEAD)])


def run_wave(name, wave, passive, frames, seed):
    s = Soak(name, seed=seed, safe=True, wave=wave)
    s.start_game()
    for _ in range(frames):
        stick = s.g.bot_stick(fire=not passive, chase=not passive)
        s.frame(stick)
    return s.report()


def run_thin(name, wave, frames, seed):
    s = Soak(name, seed=seed, safe=True, wave=wave)
    random.seed(seed)
    s.start_game()
    prev_ph = None
    kept_hist = Counter()
    for _ in range(frames):
        g = s.g
        ph, gs = g.peek("zp_wave_phase"), g.gstate()
        # at each Fight's first frame: thin to 1-4 Parked enemies (and again whenever the formation is back to
        # more than 4 alive, e.g. after a Clear)
        if ph == PH_FIGHT and prev_ph != PH_FIGHT and gs == GS_PLAY:
            k = s.rng.randint(1, 4)
            thin(g, k)
            kept_hist[k] += 1
        prev_ph = ph
        s.frame(g.bot_stick(fire=False, chase=False))
        s.min_alive_seen = min(s.min_alive_seen, g.peek("zp_enemies_alive")) if ph == PH_FIGHT else s.min_alive_seen
    s.notes.append(f"Fight starts thinned to k alive: {dict(sorted(kept_hist.items()))}")
    return s.report()


def run_fuzz(frames, seed):
    """Random sticks (a random mix of directions and fire, changing every 1-25 frames, fire often held), games started
    and restarted as they end, and every 400-900 frames a random jump: a wave from 1 to 130, the formation thinned
    to 1-18, a random score near the cap, or the ship put at a random X."""
    s = Soak("fuzz", seed=seed, safe=False, wave=None)
    g = s.g
    r = s.rng
    s.start_game()
    stick, left = 0, 0
    next_jump = r.randint(400, 900)
    jumps = Counter()
    for _ in range(frames):
        gs = g.gstate()
        if gs == GS_TITLE:
            s.frame(0); s.frame(0)
            s.frame(BITS["fire"] if r.random() < 0.9 else 0)
            continue
        if left <= 0:
            stick = 0
            for b in ("up", "down", "left", "right"):
                if r.random() < 0.35:
                    stick |= BITS[b]
            if r.random() < 0.7:
                stick |= BITS["fire"]
            left = r.randint(1, 25)
        left -= 1
        s.frame(stick)
        next_jump -= 1
        if next_jump <= 0 and g.gstate() in (GS_PLAY, GS_RESPAWN):
            next_jump = r.randint(400, 900)
            k = r.choice(("wave", "thin", "score", "x", "lives"))
            jumps[k] += 1
            if k == "wave":
                place_wave(g, r.randint(1, 99))      # the stores one wave back: the next Intro is that wave
                g.poke("zp_enemies_alive", [0])
                g.poke("diver_enemy", [0xFF] * 3); g.poke("zp_divers_active", [0])     # a Clear has no diver
            elif k == "thin":
                thin(g, r.randint(1, 18))
            elif k == "score":
                g.poke("game_score", [0x99, 0x90 + r.randint(0, 9), 0x00])
            elif k == "x":
                g.poke("zp_player_x_lo", [r.randint(24, 255)]); g.poke("zp_player_x_lo", [0], 1)
            elif k == "lives":
                g.poke("zp_lives", [r.randint(1, 3)])
    s.notes.append(f"random jumps: {dict(jumps)}")
    return s.report()


def put_eshot(g, i, x, y, dx=0):
    g.poke("mux_x_lo", [x & 255], ESHOT0 + i)
    g.poke("mux_x_hi", [x >> 8], ESHOT0 + i)
    g.poke("mux_y", [y], ESHOT0 + i)
    g.poke("eshot_dx", [dx & 255], i)


def run_death3(frames, seed):
    s = Soak("death3", seed=seed, safe=False, wave=12)
    s.start_game()
    hits = 0
    hit_log = []
    for _ in range(frames):
        g = s.g
        gs = g.gstate()
        if gs == GS_TITLE:
            # press again (a new press: up for the frame before)
            s.frame(0); s.frame(0)
            s.frame(BITS["fire"])
            s.placed = False
            continue
        div = g.peek("zp_divers_active")
        if gs == GS_PLAY and div == 3 and g.peek("zp_player_invuln") == 0 and g.peek("zp_wave_phase") == PH_FIGHT:
            put_eshot(g, 0, g.player_x(), 205, 0)
            s.frame(0)
            if g.gstate() == GS_DYING:
                hits += 1
                hit_log.append((s.f, g.peek("zp_lives"), g.peek("zp_divers_active"), g.counters().get("idle_min")))
            continue
        stick = g.bot_stick(fire=False, chase=False)
        if gs == GS_PLAY and g.peek("zp_player_invuln") > 0:
            stick = stick  # still invulnerable after a respawn: wait
        s.frame(stick)
    s.notes.append(f"hits with three divers out: {hits}; (frame, lives after, divers at the hit's end, idle_min): {hit_log[:12]}")
    if hits < 5:
        s.fail(f"only {hits} deaths with three divers placed")
    return s.report()


def run_cycles(frames, seed):
    s = Soak("cycles", seed=seed, safe=False, wave=None)
    s.start_game()
    cycles = 0
    skipped = waited = 0
    while cycles < 40 and s.f < frames:
        g = s.g
        # one game: lives to 1, hit the ship, GameOver, then skip (even cycles) or wait it out
        for _ in range(s.rng.randint(5, 120)):
            s.frame(g.bot_stick())
        g.poke("zp_lives", [1])
        g.poke("zp_player_invuln", [0])
        # wait for Play (not Respawn/Dying)
        n = 0
        while g.gstate() != GS_PLAY and n < 500:
            s.frame(0); n += 1
        g.poke("zp_player_invuln", [0])
        put_eshot(g, 0, g.player_x(), 205, 0)
        s.frame(0)
        if g.gstate() != GS_DYING:
            s.fail("the placed shot did not kill the ship")
        n = 0
        while g.gstate() != GS_OVER and n < 600:
            s.frame(0); n += 1
        if g.gstate() != GS_OVER:
            s.fail("GameOver not reached")
        # held fire through GameOver (cycle 3 mod 4: held to the title and past it)
        mode = cycles % 4
        over_n = 0
        if mode == 0:        # tap at frame 60: skip
            for k in range(70):
                s.frame(BITS["fire"] if k == 60 else 0)
                if g.gstate() == GS_TITLE:
                    break
            skipped += 1
        elif mode == 1:      # fire held from GameOver's start through the title: starts nothing
            for k in range(260):
                s.frame(BITS["fire"])
                if g.gstate() == GS_PLAY:
                    s.fail("a button held through GameOver started a game")
                    break
            if g.gstate() != GS_TITLE:
                s.fail(f"mode 1 expected the title, state {g.gstate()}")
            s.frame(0)
        else:                # wait it out
            for k in range(210):
                s.frame(0)
                if g.gstate() == GS_TITLE:
                    break
            waited += 1
        if g.gstate() != GS_TITLE:
            s.fail(f"cycle {cycles}: not in the title (state {g.gstate()})")
        # title: new game
        s.start_game(wait=s.rng.randint(9, 30))
        if g.peek("zp_lives") != 3 or g.score() != 0:
            s.fail(f"new game: lives {g.peek('zp_lives')} score {g.score()}")
        cycles += 1
    s.notes.append(f"{cycles} game-over/title/new-game cycles ({skipped} skipped, {waited} waited out)")
    return s.report()


def panel_text(g):
    row = g.mon.mem_get(0x0400 + 24 * 40, 0x0400 + 24 * 40 + 39)
    return "".join(chr(c & 0x3F | (0 if (c & 0x3F) >= 32 else 64)) for c in row)


def run_clear(frames, seed):
    s = Soak("clear", seed=seed, safe=True, wave=None)
    s.start_game()
    g = s.g
    g.poke("game_score", [0x99, 0x90, 0x00])           # 999,000: the bonus and the kills pass 999,990
    waves_seen = []
    expect_wave = 1
    pattern, loop = 0, 0
    cleared = 0
    last_wave = g.peek("zp_wave")
    while s.f < frames and cleared < 130:
        # play a short Fight, then kill the last enemy by the monitor (its explosion's last frame)
        n = 0
        while g.peek("zp_wave_phase") != PH_FIGHT and n < 400:
            s.frame(g.bot_stick())
            n += 1
        for _ in range(s.rng.randint(40, 160)):
            s.frame(g.bot_stick())
        st = list(g.mem("enemy_state", ENEMIES))
        # leave one enemy (a parked or none) exploding with its timer at 1
        keep = next((e for e in range(ENEMIES) if st[e] in (ENEMY_PARKED,)), None)
        if keep is None:
            continue
        for e in range(ENEMIES):
            if e != keep:
                g.poke("enemy_state", [ENEMY_DEAD], e)
                g.poke("mux_y", [MUX_OFF], ENEMY0 + e)
        g.poke("diver_enemy", [0xFF] * 3)
        g.poke("zp_divers_active", [0])
        g.poke("enemy_state", [0x83], keep)
        g.poke("enemy_timer", [1], keep)
        g.poke("explosion_enemy", [keep, 0xFF, 0xFF, 0xFF])
        g.poke("zp_enemies_alive", [1])
        for _ in range(3):
            s.frame(g.bot_stick())
        # now Clear; run to the next Intro frame 0 and check the stores
        n = 0
        while g.peek("zp_wave_phase") != PH_INTRO and n < 200:
            s.frame(g.bot_stick())
            n += 1
        cleared += 1
        w, p, l = g.peek("zp_wave"), g.peek("zp_pattern"), g.peek("zp_loop")
        exp_w = min(cleared + 1, 99)
        # the display is BCD, sticks at 99; pattern index cycles; loop sticks at 3
        exp_p = cleared % 3
        exp_l = min(cleared // 3, 3)
        if (w, p, l) != (bcd(exp_w), exp_p, exp_l):
            s.fail(f"after clear {cleared}: wave {w:02x} pattern {p} loop {l}, expected {exp_w:02d} {exp_p} {exp_l}")
        # the panel and the message
        if cleared in (11, 12, 13, 97, 98, 99, 100, 101, 129):
            s.frame(0)
            pt = panel_text(g)
            msg = bytes(g.mon.mem_get(0x0400 + 9 * 40 + 10, 0x0400 + 9 * 40 + 29))
            s.notes.append(f"after {cleared} clears: wave store {w:02x} pattern {p} loop {l}; panel {pt.strip()!r}; row 9 {''.join(chr(64 + c) if 1 <= c <= 26 else chr(c) if c < 128 else '?' for c in msg).strip()!r}; score {g.score()}")
        # the score is capped
        if g.score() > 999990:
            s.fail("score above 999,990")
        if g.gstate() == GS_TITLE:
            s.fail("the game ended")
    s.notes.append(f"waves cleared by the monitor: {cleared}; final score {g.score()}; shown wave {g.peek('zp_wave'):02x}")
    if g.score() != 999990:
        s.notes.append(f"score at the end {g.score()} (expected the cap 999990 after the bonuses)")
        s.fail(f"score at the end {g.score()}, not capped at 999990")
    # a death with the capped score: GameOver compares the high score
    g.poke("zp_lives", [1]); g.poke("zp_player_invuln", [0])
    while g.gstate() != GS_PLAY:
        s.frame(0)
    g.poke("zp_player_invuln", [0])
    put_eshot(g, 0, g.player_x(), 205, 0)
    for _ in range(320):
        s.frame(0)
    s.notes.append(f"after GameOver at the cap: state {GS_NAMES[g.gstate()]}, hiscore {g.hiscore()}, panel {panel_text(g).strip()!r}")
    if g.hiscore() != 999990:
        s.fail(f"high score {g.hiscore()} after a 999,990 game")
    return s.report()


def run_fifth(seed):
    s = Soak("fifth", seed=seed, safe=True, wave=None)
    s.start_game()
    g = s.g
    for _ in range(80):
        s.frame(0)
    # ---- 4 running + a shot on a 5th (row 2, column 3 = enemy 15)
    st = [ENEMY_PARKED] * ENEMIES
    g.poke("enemy_state", st)
    g.poke("diver_enemy", [0xFF] * 3); g.poke("zp_divers_active", [0]); g.poke("zp_enemies_alive", [18])
    g.poke("explosion_enemy", [0, 1, 2, 3])
    for e in (0, 1, 2, 3):
        g.poke("enemy_state", [0x83], e); g.poke("enemy_timer", [12], e)
    g.poke("zp_launch_timer", [255])
    s0 = g.score()
    xl, xh, y = g.peek("mux_x_lo", ENEMY0 + 15), g.peek("mux_x_hi", ENEMY0 + 15), g.peek("mux_y", ENEMY0 + 15)
    g.poke("zp_drift_timer", [2])
    x = xl + 256 * xh
    g.poke("mux_x_lo", [x & 255], 4); g.poke("mux_x_hi", [x >> 8], 4); g.poke("mux_y", [y + 14], 4)
    s.frame(0)
    st1 = list(g.mem("enemy_state", ENEMIES))
    ok1 = st1[15] == ENEMY_DEAD and g.peek("mux_y", ENEMY0 + 15) == MUX_OFF and g.score() == s0 + 50
    s.notes.append(f"4 running + a fifth hit: enemy 15 state {st1[15]:#x}, hidden {g.peek('mux_y', ENEMY0 + 15) == MUX_OFF}, score +{g.score() - s0} (expect Dead, hidden, +50): {'ok' if ok1 else 'WRONG'}")
    if not ok1:
        s.fail("fifth explosion")
    for _ in range(60):
        s.frame(0)
    # ---- 3 running + two shots on two enemies in one frame (enemy 14 and 16, row 2)
    g.poke("enemy_state", [ENEMY_PARKED] * ENEMIES)
    g.poke("zp_enemies_alive", [18]); g.poke("explosion_enemy", [0, 1, 2, 0xFF])
    for e in (0, 1, 2):
        g.poke("enemy_state", [0x83], e); g.poke("enemy_timer", [12], e)
    s0 = g.score()
    g.poke("zp_drift_timer", [2])
    for i, e in enumerate((14, 16)):
        x = g.peek("mux_x_lo", ENEMY0 + e) + 256 * g.peek("mux_x_hi", ENEMY0 + e)
        yy = g.peek("mux_y", ENEMY0 + e)
        g.poke("mux_x_lo", [x & 255], 4 + i); g.poke("mux_x_hi", [x >> 8], 4 + i); g.poke("mux_y", [yy + 14], 4 + i)
    s.frame(0)
    st2 = list(g.mem("enemy_state", ENEMIES))
    nexp = sum(1 for s_ in st2 if s_ == 0x83)
    s.notes.append(f"3 running + two hits in one frame: states of 14 and 16 {st2[14]:#x}/{st2[16]:#x}, explosions now {nexp}, score +{g.score() - s0} (expect +100: one exploding, one dead, 4 explosions)")
    if g.score() - s0 != 100:
        s.fail(f"two hits in one frame scored {g.score() - s0}")
    for _ in range(120):
        s.frame(0)
    st3 = list(g.mem("enemy_state", ENEMIES))
    if any(v == 0x83 for v in st3):
        s.fail(f"an explosion never finished: {[hex(v) for v in st3]}")
    return s.report()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--frames", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    sc = a.scenario
    try:
        if sc.startswith("wave"):
            n = int(sc[4:sc.index("-")])
            return run_wave(sc, n, sc.endswith("passive"), a.frames, a.seed)
        if sc.startswith("thin"):
            return run_thin(sc, int(sc[4:]), a.frames, a.seed)
        if sc == "death3":
            return run_death3(a.frames, a.seed)
        if sc == "cycles":
            return run_cycles(a.frames, a.seed)
        if sc == "clear":
            return run_clear(a.frames, a.seed)
        if sc == "fuzz":
            return run_fuzz(a.frames, a.seed)
        if sc == "fifth":
            return run_fifth(a.seed)
        print("unknown scenario")
        return 2
    except MeasureError as e:
        print(f"FAIL (jam/hang): {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
