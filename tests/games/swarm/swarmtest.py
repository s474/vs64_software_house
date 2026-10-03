"""Swarm's part of its behaviour tests: the game's constants, readers of its state, helpers that place it
in a state through the monitor, and its clean-state guard. The generic parts (VICE on a free port,
frames, stick, labels, the case runner) are tools/gametest; the cases are check.py.

Not run by itself. Used by check.py (and open to the QA scripts: qa_lib.py is the older, smaller copy).
Everything public here is star-imported by check.py.
"""

from budget_runner.session import STOP_TIMEOUT, MeasureError
from vice_monitor import CPU_OP_EXEC, CPU_OP_STORE  # on sys.path once budget_runner.session is imported

from gametest import BITS, Handoff, Rig


X_MIN, X_MAX, X_START, PLAYER_Y, SPEED = 24, 318, 171, 221, 3
SHOT_Y0, SHOT_SPEED, SHOT_KILL, COOLDOWN = 213, 8, 46, 10
MUX_OFF = 0xFF
SCREEN, COLOUR = 0x0400, 0xD800
STAR_HI, STAR_LO, SHIP, SPACE, PANEL_BG = 27, 28, 29, 32, 0x40
BAND_ROWS, BAND_COLS = {5, 9, 12, 15, 18, 21}, range(10, 30)
MSG_ROW = 9                     # WAVE nn, READY, GAME OVER (design "Text cells and the star rule"; row 12 until stage 4)
ENEMY0, ENEMIES, COLS = 6, 18, 6
FORM_X0, COL_DX, ROW_Y, FX_MAX, FX_START = 34, 36, [56, 96, 136], 96, 48
ANIM_FRAMES, SHAPE_ENEMY, ENEMY_PARKED = 16, 0xC3, 1
ENEMY_WAITING = 2               # stage 4: hidden until its turn in the wave's Intro
PHASE_FIGHT, PHASE_INTRO, PHASE_CLEAR = 0, 1, 2
INTRO_FRAMES, INTRO_MSG_FRAMES = 50, 49           # design, Stage 4 rule 2 (100 and 75 until the tuning after the stage 4 playtest)
FIGHT_LAUNCH_DELAY = 10         # the launch timer at Fight (Stage 4 rule 3; 50 until the tuning): first wind-up in wave frame 60
FIRST_LAUNCH = INTRO_FRAMES + FIGHT_LAUNCH_DELAY
PLAY_LAUNCH_TIMER = 50          # the launch timer when Play is entered (Stage 3 rule 10): not changed by the tuning
ROW9_LINES = range(51 + 8 * MSG_ROW, 59 + 8 * MSG_ROW)     # raster lines 123-130
GS_PLAY, GS_RESPAWN, GS_DYING, GS_OVER, GS_TITLE = 0, 1, 2, 3, 4
# The title's texts in the order it draws them (text 0 in its frame 0, then one a frame): text, row, first column
TITLE_TEXTS = [("PRESS FIRE", 21, 15), ("SWARM", 5, 17), ("150 PTS", 9, 17), (" 80 PTS", 12, 17), (" 50 PTS", 15, 17),
               ("DIVING SCORES DOUBLE", 18, 10)]
TITLE_FIRE_FRAME, TITLE_SPRITES, NEW_GAME_COOLDOWN = 8, [(120, 115), (120, 139), (120, 163)], 25
ENEMY_DEAD, ENEMY_EXPLODING, SHAPE_EXPLOSION, EXPLOSION_FRAMES, ORANGE = 0, 0x83, 0xC9, 16, 8
FLIGHT = [18, 13, 8]            # frames from the fire frame to the first frame inside row 0 / 1 / 2's box
ROW_SCORE = [150, 80, 50]
HIT_DX = 8                      # |shot X - enemy X| <= 8 overlaps (columns 11-12 against 4-19)
CLEAR_PAUSE, DRIFT_PERIOD = 75, [2, 2, 1, 1]
PANEL_DIRTY_SCORE = 1
ENEMY_COLOURS = [4, 7, 13]  # purple, yellow, light green (design.md#colours), colour_table 5-7
HOLD_EVERY = 8                  # frames between the script's re-writes of a held value: fewer than FIGHT_LAUNCH_DELAY,
                                # so a launcher held off stays off through a Fight's start (32 until the stage 4 tuning,
                                # when Fight set the timer to 50)
DEBUG_COUNTERS = [("game_flicker_frames", 2), ("mux_max_age", 1), ("mux_late_count", 1), ("game_overrun_count", 1)]
STAR_COLOURS = [1, 15, 12, 11]


def code(text):
    """Screen codes of a text in capitals, digits and spaces."""
    return [ord(c) - 64 if c.isalpha() else ord(c) for c in text]




# ================================================================ stage 3
ESHOT0, SHAPE_ESHOT, ESHOT_HIT_Y, ESHOT_HIT_DX = 1, 0xC2, 207, 6
PANEL_DIRTY_LIVES, PANEL_DIRTY_HI = 2, 8
MSG = SCREEN + MSG_ROW * 40
# ================================================================ stage 3, step 2: divers
ST_W, ST_D, ST_R = 0x80, 0x81, 0x82
PATHS = {0: [(0, -1, 6), (1, 2, 20), (2, 3, 20), (1, 3, 16), (0, 2, 9), (2, -1, 24), (2, 0, 0)],   # Plunge
         1: [(-1, 1, 8), (1, 2, 16), (2, 2, 14), (2, 0, 0)],                                      # Sweep
         2: [(1, 1, 8), (2, 2, 12), (1, 3, 12), (0, 2, 6), (-2, 0, 12), (-1, -2, 8)]}             # Hook
FIRE = {0: [26, 36, 46], 1: [24, 38, 62, 86], 2: [8, 16]}
PATH_NAME = ["Plunge", "Sweep", "Hook"]
WINDUP, EXTRA, ESHOT_DY, SHOTS_P3 = [24, 20, 16, 12], [0, 4, 2, 2], [2, 2, 3, 3], 3    # SHOTS_P3: 2 until the stage 4 tuning
CAP_P3, INTERVAL_P3 = 3, 64       # pattern 3 at loop 0 (design "Waves"): divers at once, launch interval (2 and 100 until the tuning)
DIVE_SCORE = [300, 160, 100]
DX_MAX, WRAP_Y, LETHAL_Y = 344, 30, 210
class Dive:
    """The design's diver, stepped one frame at a time beside the game (design.md "Enemy
    behaviour", "Dive paths", "Firing", Stage 3 rules 2-4). Pattern 3: 3 shots at loop 0 (never
    more than the path's fire steps: a Hook has 2)."""

    def __init__(self, e, loop):
        self.e, self.loop = e, loop
        self.row, self.col = divmod(e, COLS)
        self.st, self.t, self.white, self.step = ST_W, 0, True, 0
        self.shots = FIRE[self.row][:SHOTS_P3 + loop]
        self.x = self.y = None

    def frame(self, fx, px, gf):
        """One frame: fx as formation_update left it, px the player's X as diver_update sees
        it, gf the frame number. Returns the positions at which a fire step was taken."""
        hx, hy = FORM_X0 + fx + COL_DX * self.col, ROW_Y[self.row]
        fires = []
        if self.st == ST_W:
            if self.t < WINDUP[self.loop]:
                self.x, self.y = hx + (1 if self.t % 4 < 2 else -1), hy
                self.white = self.t % 8 < 4
                self.t += 1
                return fires
            self.st, self.x, self.y, self.mirror = ST_D, hx, hy, px < hx
            self.seg, self.left = 0, PATHS[self.row][0][2]
        self.white = False
        if self.st == ST_D:
            for _ in range(2 if EXTRA[self.loop] and gf % EXTRA[self.loop] == 0 else 1):
                if self.st != ST_D:
                    break
                dx, dy, cnt = PATHS[self.row][self.seg]
                self.x = max(0, min(DX_MAX, self.x + (-dx if self.mirror else dx)))
                self.y += dy
                self.step += 1
                if self.step in self.shots:
                    fires.append((self.x, self.y))
                if cnt == 0:
                    if self.x in (0, DX_MAX):
                        self.st, self.x, self.y = ST_R, hx, WRAP_Y
                else:
                    self.left -= 1
                    if self.left == 0:
                        self.seg += 1
                        if self.seg == len(PATHS[self.row]):
                            self.st = ST_R
                        else:
                            self.left = PATHS[self.row][self.seg][2]
        elif self.st == ST_R:
            self.x += max(-2, min(2, hx - self.x))
            self.y += max(-2, min(2, hy - self.y))
            if (self.x, self.y) == (hx, hy):
                self.st = ENEMY_PARKED
        return fires
# ================================================================ stage 4 part A: waves
WAVE_ROWS = [{2}, {1, 2}, {0, 1, 2}]                                    # by pattern index
WAVE_MAX_DIVERS = [[2, 2, 2, 2], [2, 3, 3, 3], [3, 3, 3, 3]]            # by pattern, loop (design "Waves", after the stage 4 tuning)
WAVE_INTERVAL = [[100, 80, 64, 50], [80, 64, 50, 40], [64, 50, 40, 32]]
WAVE_SHOTS = [2, 3, 3]                                                  # at loop 0; + 1 a loop


def home(fx):
    return [(FORM_X0 + fx + COL_DX * (e % COLS), ROW_Y[e // COLS]) for e in range(ENEMIES)]

def bcd(n):
    return (n // 10) * 16 + n % 10

def text_cells(texts):
    out = {}
    for text, row_, col in texts:
        out.update({row_ * 40 + col + i: c for i, c in enumerate(code(text)) if c != SPACE})
    return out

def title_texts(f):
    """What the title shows in its frame f: text i from frame i on, PRESS FIRE by the blink."""
    return text_cells([t for i, t in enumerate(TITLE_TEXTS) if (i and f >= i) or (i == 0 and f % 64 < 32)])

def title_sprites(f):
    return {ENEMY0 + r * COLS: TITLE_SPRITES[r] + (SHAPE_ENEMY + 2 * r + (f >> 4 & 1), ENEMY_COLOURS[r]) for r in range(3)}

def rng_step(lo, hi):
    v = lo | hi << 8
    v ^= (v << 7) & 0xFFFF
    v ^= v >> 9
    v ^= (v << 8) & 0xFFFF
    return v & 255, v >> 8

def aim_dx(d):
    return 0 if abs(d) <= 15 else 1 if d > 0 else -1

def want_stores(n):
    return min(n, 99), (n - 1) % 3, min((n - 1) // 3, 3)

def by_frame(got):
    return dict((k, v) for k, v in got.items() if isinstance(k, int))


class SwarmRig(Rig):
    """The game's rig: Rig plus Swarm's state readers and placing helpers (the methods below). One
    frame() is one game frame; it returns the player's X and the two player shots, and re-writes the
    values the script holds (launcher(), safe()). `ns` carries values from one case to a later one."""

    def __init__(self, prg, warmup_frames=0):
        super().__init__(prg, frame_label="game_update_end", warmup_frames=warmup_frames,
                         debug_labels=("mux_late_count",))
        # Values the script holds through the monitor while a case needs a stage 3 feature out of
        # the way: re-written every HOLD_EVERY frames (see launcher() and safe()).
        self.hold = {"n": 0, "set": {}}
        self.row9 = {}                      # message -> no Parked enemy's lines touch row 9's (123-130)
        self.ns = Handoff()         # what one case hands to a later one (title -> title-press, ...)
        self.sfx_trace = False              # True once sfx_enable() has run (the sound cases)
        self.calls, self.vol_writes = [], [0]
        self.cp_play = self.cp_vol = None
        self._ct = None

    @property
    def cp(self):
        """The checkpoint that stops the machine at the end of every game frame."""
        return self.frame_stop

    @property
    def ct(self):
        """The game's colour_table (19 bytes), read once."""
        if self._ct is None:
            self._ct = self.mem(self.sym["colour_table"], 19)
        return self._ct

    def frame(self, pressed=None):
        """Optionally set the stick (active-high mask), run to the next game_update_end; returns state().
        With sfx_trace (the sound cases) also `calls` = the effects (+ 1) sfx_play was called with in
        this frame, in order, and every store to $D418 is counted in vol_writes."""
        hold, mon, sym, calls = self.hold, self.mon, self.sym, self.calls
        if self.sfx_trace:
            calls.clear()
        if hold["set"]:
            hold["n"] -= 1
            if hold["n"] <= 0:
                for label, value in hold["set"].items():
                    mon.mem_set(sym[label], bytes([value]))
                hold["n"] = HOLD_EVERY
        if pressed is not None:
            self.set_stick(pressed)
        while True:
            regs = self.resume("game_update_end", registers=self.sfx_trace)
            if not self.sfx_trace or regs["PC"] == sym["game_update_end"]:
                return self.state()
            if regs["PC"] == sym["sfx_play"]:
                calls.append((regs["A"] & 255) + 1)
            else:
                self.vol_writes[0] += 1

    def sfx_enable(self):
        """From here every execution of sfx_play also stops the machine (so a frame sees each CALL, in order,
        with the effect in A) and so does a store to $D418 (the volume), which must never happen."""
        sym = self.sym
        self.SFX = {n: sym["SFX_" + n] + 1 for n in ("PLAYER_SHOT", "ENEMY_SHOT", "DIVE", "ENEMY_EXPLOSION", "PLAYER_HIT_A",
                                                     "PLAYER_HIT_B", "WAVE_START", "WAVE_CLEAR", "START", "GAME_OVER")}
        self.SFX_NAME = {v: k.lower() for k, v in self.SFX.items()}
        self.SFX_NAME[0] = "-"
        SFX = self.SFX
        self.PS, self.ES, self.DV, self.EX = SFX["PLAYER_SHOT"], SFX["ENEMY_SHOT"], SFX["DIVE"], SFX["ENEMY_EXPLOSION"]
        self.HA, self.HB, self.WS, self.WC = SFX["PLAYER_HIT_A"], SFX["PLAYER_HIT_B"], SFX["WAVE_START"], SFX["WAVE_CLEAR"]
        self.ST, self.GO = SFX["START"], SFX["GAME_OVER"]
        self.calls.clear()
        self.vol_writes[0] = 0
        self.cp_play = self.watch("sfx_play")
        self.cp_vol = self.watch(0xD418, "store")
        self.sfx_trace = True

    def state(self):
        mem, sym = self.mem, self.sym
        x = mem(sym["zp_player_x_lo"], 2)
        ys = mem(sym["mux_y"] + 4, 2)
        xl = mem(sym["mux_x_lo"] + 4, 2)
        xh = mem(sym["mux_x_hi"] + 4, 2)
        shots = [None if ys[i] == MUX_OFF else (xl[i] + 256 * xh[i], ys[i]) for i in range(2)]
        return x[0] + 256 * x[1], shots

    def launcher(self, on):
        """Off: zp_launch_timer is kept above 190, so no dive is ever launched (the cases written
        for stages 1 and 2 assume a formation that stays Parked). On: the game's own timer."""
        hold = self.hold
        if on:
            hold["set"].pop("zp_launch_timer", None)
        else:
            hold["set"]["zp_launch_timer"] = 255
            hold["n"] = 0

    def safe(self, on):
        """On: zp_player_invuln is kept above 100, so the ship can't be hit (it flashes)."""
        hold, mon, sym = self.hold, self.mon, self.sym
        if on:
            hold["set"]["zp_player_invuln"] = 149
            hold["n"] = 0
        else:
            hold["set"].pop("zp_player_invuln", None)
            mon.mem_set(sym["zp_player_invuln"], bytes([0]))
            mon.mem_set(sym["mux_col"], mon.mem_get(sym["colour_table"] + 3, sym["colour_table"] + 3))

    def settle(self):
        """Release everything and wait until no shot is in flight and the cooldown is 0."""
        frame, mem, sym = self.frame, self.mem, self.sym
        frame(0)
        for _ in range(40):
            x, shots = frame()
            if shots == [None, None] and mem(sym["zp_player_cooldown"])[0] == 0:
                return x
        raise MeasureError("shots never cleared")

    def enemies(self):
        """fx, drift direction, and each enemy's (X, Y, shape, colour) from the multiplexer's arrays."""
        mem, sym = self.mem, self.sym
        xl, xh = mem(sym["mux_x_lo"] + ENEMY0, ENEMIES), mem(sym["mux_x_hi"] + ENEMY0, ENEMIES)
        ys, ps = mem(sym["mux_y"] + ENEMY0, ENEMIES), mem(sym["mux_ptr"] + ENEMY0, ENEMIES)
        cs = mem(sym["mux_col"] + ENEMY0, ENEMIES)
        fx, fdir = mem(sym["zp_fx"], 2)
        return fx, fdir, [(xl[e] + 256 * xh[e], ys[e], ps[e], cs[e] & 15) for e in range(ENEMIES)]

    def phase(self):
        peek = self.peek
        return peek("zp_wave_phase"), peek("zp_wave_timer")

    def next_wave_in(self, frames_, stores=None):
        """Through the monitor: the sky emptied and the wave phase put in Clear so that Intro's
        frame 0 is `frames_` frames from now (1 = the next frame). stores = (shown wave, pattern
        index, loop) as they must be BEFORE the game advances them, or None to leave them."""
        poke = self.poke
        poke("enemy_state", [ENEMY_DEAD] * ENEMIES)
        poke("mux_y", [MUX_OFF] * ENEMIES, ENEMY0)
        poke("explosion_enemy", [0xFF] * 4)
        poke("zp_enemies_alive", [0])
        poke("zp_wave_phase", [PHASE_CLEAR])
        poke("zp_wave_timer", [CLEAR_PAUSE - frames_])
        if stores:
            poke("zp_wave", [bcd(stores[0])])
            poke("zp_pattern", [stores[1]])
            poke("zp_loop", [stores[2]])

    def to_fight(self):
        """Run the game's own Intro to the first frame of Fight (and a Clear before it, if the case
        before ended in one)."""
        frame, phase = self.frame, self.phase
        for _ in range(CLEAR_PAUSE + INTRO_FRAMES + 2):
            if phase()[0] == PHASE_FIGHT:
                return
            frame()
        raise MeasureError(f"to_fight: the phase is still {phase()}")

    def start_wave(self, n, run=True):
        """Wave n (1 or more) from Intro's frame 0, by the game's own path: the stores are put at
        wave n - 1's values and the Clear at its last frame, so the game advances them itself.
        (Wave 1 has no wave before it: the loop store is put back to 0 after the advance; loops 0
        and 1 drift at the same speed, so the reset formation is the same.) On return the
        machine is in Intro's frame 0, or in Fight's first frame with run=True."""
        frame, next_wave_in, poke, to_fight = self.frame, self.next_wave_in, self.poke, self.to_fight
        if n == 1:
            next_wave_in(1, (0, 2, 0))
        else:
            next_wave_in(1, (n - 1, (n - 2) % 3, min((n - 2) // 3, 3)))
        frame()
        if n == 1:
            poke("zp_loop", [0])
        if run:
            to_fight()

    def row9_free(self):
        mem, sym = self.mem, self.sym
        st, ys = list(mem(sym["enemy_state"], ENEMIES)), mem(sym["mux_y"] + ENEMY0, ENEMIES)
        return all(not (set(range(ys[e] + 1, ys[e] + 22)) & set(ROW9_LINES)) for e in range(ENEMIES) if st[e] == ENEMY_PARKED)

    def legacy_wave(self, run=True):
        frame, next_wave_in, to_fight = self.frame, self.next_wave_in, self.to_fight
        next_wave_in(1, (0, 1, 0))            # the game advances these to 01, pattern 2, loop 0
        frame()
        if run:
            to_fight()

    def legacy_stores(self):
        """Call every frame of a case that clears waves by itself: the stores back to stage 3's
        in a new wave's first frame."""
        phase, poke = self.phase, self.poke
        if phase() == (PHASE_INTRO, 0):
            poke("zp_pattern", [2])
            poke("zp_loop", [0])

    def start_game(self, tap_frame=None):
        """From the title to the new game's frame (Intro's frame 0) by the stick: wait until
        fire is read (the title's frame 8, or tap_frame if given), a one-frame press, then the
        six erase frames. Returns the title frame the press was made in."""
        frame, peek, phase = self.frame, self.peek, self.phase
        if peek("zp_game_state") != GS_TITLE:
            raise MeasureError(f"start_game: not at the title: state {peek('zp_game_state')}")
        n = 0
        while peek("zp_state_timer") + 1 < (tap_frame or TITLE_FIRE_FRAME):
            frame(0)
            n += 1
            if n > 300:
                raise MeasureError("start_game: the title never read fire")
        frame(BITS["fire"])
        pressed_in = peek("zp_state_timer")
        for _ in range(8):
            frame(0)
            if peek("zp_game_state") == GS_PLAY:
                break
        if peek("zp_game_state") != GS_PLAY or phase() != (PHASE_INTRO, 0):
            raise MeasureError(f"start_game: no new game: state {peek('zp_game_state')}, phase {phase()}")
        return pressed_in

    def to_title(self):
        """From a game to the title's frame 0 by the game's own path: GameOver's last frame."""
        frame, peek, poke = self.frame, self.peek, self.poke
        poke("zp_game_state", [GS_OVER])
        poke("zp_state_timer", [199])
        frame(0)
        if peek("zp_game_state") != GS_TITLE:
            raise MeasureError(f"to_title: state {peek('zp_game_state')}")

    def screen_text(self):
        """Every play-area cell that isn't a space or a star: {cell: screen code}."""
        mem = self.mem
        return {i: c for i, c in enumerate(mem(SCREEN, 960)) if c not in (SPACE, STAR_HI, STAR_LO)}

    def sprites24(self):
        mem, sym = self.mem, self.sym
        xl, xh, ys = mem(sym["mux_x_lo"], 24), mem(sym["mux_x_hi"], 24), mem(sym["mux_y"], 24)
        ps, cs = mem(sym["mux_ptr"], 24), mem(sym["mux_col"], 24)
        return {i: (xl[i] + 256 * xh[i], ys[i], ps[i], cs[i] & 15) for i in range(24) if ys[i] != MUX_OFF}

    def panel_row(self):
        mem = self.mem
        return "".join("^" if c == SHIP + PANEL_BG else chr((c & 63) + 64) if (c & 63) < 27 else chr(c & 63)
                       for c in mem(SCREEN + 960, 40))

    def respawn(self):
        """The game's own path back to a full formation: the Clear's last frame, then the next
        wave's Intro run to Fight, with the stores at stage 3's values (legacy_wave)."""
        legacy_wave, settle = self.legacy_wave, self.settle
        settle()
        legacy_wave()

    # ---------------------------------------------------------------- collisions (part B)
    def estates(self):
        mem, sym = self.mem, self.sym
        return list(mem(sym["enemy_state"], ENEMIES))

    def score(self):
        mem, sym = self.mem, self.sym
        return int(mem(sym["game_score"], 3).hex())

    def panel_score(self):
        mem = self.mem
        return "".join(chr(c - PANEL_BG) for c in mem(SCREEN + 960 + 7, 6))

    def predict(self, n):
        """fx after n more formation_update calls (the drift exactly as formation.asm steps it)."""
        mem, sym = self.mem, self.sym
        fx, d, timer = mem(sym["zp_fx"])[0], mem(sym["zp_drift_dir"])[0], mem(sym["zp_drift_timer"])[0]
        period = DRIFT_PERIOD[mem(sym["zp_loop"])[0]]
        d = 1 if d == 1 else -1
        for _ in range(n):
            timer -= 1
            if timer == 0:
                timer = period
                fx += d
                if fx in (0, FX_MAX):
                    d = -d
        return fx

    def aim(self, cons, chase=False, x0=None, limit=900):
        """Press fire in the frame that makes every constraint true; returns the shot's X.

        cons: (k, column, lo, hi[, xe_lo, xe_hi]): k frames after the fire frame, the shot's X
        minus that column's enemy X is in lo..hi (and the enemy's X in xe_lo..xe_hi). Until
        then: walk to x0 if given and wait there, or (chase) steer towards the middle of the
        constraints with the stick.
        On return the machine is stopped in the fire frame (the shot is at Y 213), fire down.
        """
        frame, predict, settle = self.frame, self.predict, self.settle
        x = settle()
        for _ in range(limit):
            ok = x0 is None or x == x0
            for k, col, lo, hi, *xr in cons:
                xe = FORM_X0 + predict(k + 1) + COL_DX * col
                ok = ok and lo <= x - xe <= hi and (not xr or xr[0] <= xe <= xr[1])
            if ok:
                x2, shots = frame(BITS["fire"])
                if x2 != x or (x, SHOT_Y0) not in shots:
                    raise MeasureError(f"aim: no shot at ({x}, {SHOT_Y0}): {shots}")
                return x
            stick = 0
            if x0 is not None:
                stick = BITS["right"] if x < x0 else BITS["left"] if x > x0 else 0
            elif chase:
                d = sum(x - (FORM_X0 + predict(c[0] + 2) + COL_DX * c[1]) - (c[2] + c[3]) / 2 for c in cons) / len(cons)
                stick = BITS["left"] if d > 1 else BITS["right"] if d < -1 else 0
            x, _ = frame(stick)
        raise MeasureError(f"aim: constraints {cons} never met")

    def epos(self, e):
        mem, sym = self.mem, self.sym
        return (mem(sym["mux_x_lo"] + ENEMY0 + e)[0] + 256 * mem(sym["mux_x_hi"] + ENEMY0 + e)[0],
                mem(sym["mux_y"] + ENEMY0 + e)[0])

    def kill(self, e, lo=-4, hi=4):
        """Shoot enemy e (the enemies below it in its column must be dead). Returns the errors."""
        aim, estates, frame, score = self.aim, self.estates, self.frame, self.score
        row, col = divmod(e, COLS)
        k = FLIGHT[row]
        s0 = score()
        aim([(k, col, lo, hi)], chase=True)
        frame(0)
        for _ in range(k - 2):
            frame()
        before = estates()[e]
        frame()
        errs = []
        if before != ENEMY_PARKED or estates()[e] != ENEMY_EXPLODING:
            errs.append(f"enemy {e}: state {before} then {estates()[e]} in frame f + {k}")
        if score() != s0 + ROW_SCORE[row]:
            errs.append(f"enemy {e}: score {s0} -> {score()}")
        return errs

    def eshots(self):
        mem, sym = self.mem, self.sym
        ys, xl, xh = mem(sym["mux_y"] + ESHOT0, 3), mem(sym["mux_x_lo"] + ESHOT0, 3), mem(sym["mux_x_hi"] + ESHOT0, 3)
        return [None if ys[i] == MUX_OFF else (xl[i] + 256 * xh[i], ys[i]) for i in range(3)]

    def put_eshot(self, i, x, y, dx=0):
        """Place enemy shot i through the monitor (as a diver's fire step would leave it)."""
        poke = self.poke
        poke("mux_x_lo", [x & 255], ESHOT0 + i)
        poke("mux_x_hi", [x >> 8], ESHOT0 + i)
        poke("mux_y", [y], ESHOT0 + i)
        poke("eshot_dx", [dx & 255], i)

    def clear_eshots(self):
        poke = self.poke
        poke("mux_y", [MUX_OFF] * 3, ESHOT0)

    def gstate(self):
        peek = self.peek
        return peek("zp_game_state"), peek("zp_state_timer")

    def ship(self):
        """The ship's multiplexer entry: (X, Y, shape, colour)."""
        peek = self.peek
        return (peek("mux_x_lo") + 256 * peek("mux_x_hi"), peek("mux_y"), peek("mux_ptr"), peek("mux_col") & 15)

    def msg(self):
        """Row 9 (the message row) as text, 40 characters; the cells outside the star-free band (columns 10-29) as spaces."""
        mem = self.mem
        return "".join(" " if i not in BAND_COLS else chr((c & 63) + 64) if 0 < (c & 63) < 27 else chr(c & 63)
                       for i, c in enumerate(mem(MSG, 40)))

    def walk_to(self, x0):
        frame, poke, state = self.frame, self.poke, self.state
        x = state()[0]
        for _ in range(120):
            if x == x0:
                frame(0)
                return
            if abs(x - x0) < SPEED:                       # off the 3-pixel grid (a case before put the ship
                poke("zp_player_x_lo", [x0 & 255, x0 >> 8])   # somewhere through the monitor): put it there
                poke("mux_x_lo", [x0 & 255])
                poke("mux_x_hi", [x0 >> 8])
                x = x0
                continue
            x = frame(BITS["right"] if x < x0 else BITS["left"])[0]
        raise MeasureError(f"walk_to({x0}): at {x}")

    def revive(self):
        """After a death: lives back to 3 (monitor), then the game's own PlayerDying and Respawn,
        with the invulnerability taken away (monitor) once Play is back. Returns frames waited."""
        frame, gstate, poke = self.frame, self.gstate, self.poke
        poke("zp_lives", [3])
        n = 0
        while gstate()[0] != GS_PLAY:
            frame(0)
            n += 1
            if n > 400:
                raise MeasureError(f"revive: still in state {gstate()}")
        poke("zp_player_invuln", [0])
        frame()
        return n

    def end_game(self):
        """From GameOver to the next game's first frame (Intro's frame 0), by the game's own path:
        GameOver's last frame, the title, a press of fire."""
        gstate, start_game, to_title = self.gstate, self.start_game, self.to_title
        if gstate()[0] != GS_OVER:
            raise MeasureError(f"end_game: not in GameOver: {gstate()}")
        to_title()
        start_game()

    def only(self, keep):
        """Every enemy but those in `keep` is taken away (monitor): Dead and hidden."""
        mem, poke, sym = self.mem, self.poke, self.sym
        st = [ENEMY_PARKED if e in keep else ENEMY_DEAD for e in range(ENEMIES)]
        ys = mem(sym["mux_y"] + ENEMY0, ENEMIES)
        poke("enemy_state", st)
        poke("mux_y", [ys[e] if e in keep else MUX_OFF for e in range(ENEMIES)], ENEMY0)
        poke("zp_enemies_alive", [len(keep)])

    def set_player_x(self, x):
        poke = self.poke
        poke("zp_player_x_lo", [x & 255, x >> 8])
        poke("mux_x_lo", [x & 255])
        poke("mux_x_hi", [x >> 8])

    def put_pshot(self, i, x, y):
        poke = self.poke
        poke("mux_x_lo", [x & 255], 4 + i)
        poke("mux_x_hi", [x >> 8], 4 + i)
        poke("mux_y", [y], 4 + i)

    def fly(self, e, loop=0, player_x=None, before=None, until=None, max_frames=420, invulnerable=True):
        """A full formation back, every enemy but e taken away, the launcher let go for one frame:
        e is launched by the game and followed frame by frame beside the model. `before(k, m)` is
        called at the stop before frame k (frame 0 = the launch) and may poke; `until(k, m, rec)`
        ends the run early. Returns (records, errors, model): a record per frame is a dict."""
        ct, epos, eshots, estates, frame = self.ct, self.epos, self.eshots, self.estates, self.frame
        gstate, launcher, mem, only, peek = self.gstate, self.launcher, self.mem, self.only, self.peek
        poke, respawn, safe, state, sym = self.poke, self.respawn, self.safe, self.state, self.sym
        walk_to = self.walk_to
        respawn()
        if player_x is not None:
            walk_to(player_x)
        only({e})
        poke("zp_loop", [loop])
        safe(invulnerable)
        launcher(True)
        poke("zp_launch_timer", [1])
        m, recs, errs = Dive(e, loop), [], []
        dy = ESHOT_DY[loop]
        for k in range(max_frames):
            if before:
                before(k, m)
            px = state()[0]
            gs_before = gstate()[0]
            es0, dxs = eshots(), [b - 256 if b > 127 else b for b in mem(sym["eshot_dx"], 3)]
            moved = [None if q is None or q[1] + dy > PLAYER_Y else (max(0, min(DX_MAX, q[0] + dxs[i])), q[1] + dy)
                     for i, q in enumerate(es0)]
            frame()
            if k == 0:
                launcher(False)                           # one launch only
            fx, gf = peek("zp_fx"), peek("zp_game_frame")
            was = (m.st, m.x, m.y)
            fires = m.frame(fx, px, gf)
            got = (estates()[e], epos(e), peek("mux_col", ENEMY0 + e) & 15)
            rec = dict(k=k, st=got[0], pos=got[1], col=got[2], step=m.step, fx=fx, es=eshots(), new=[], px=px,
                       home=(FORM_X0 + fx + COL_DX * m.col, ROW_Y[m.row]), t=m.t, fires=fires)
            es1 = rec["es"]
            rec["new"] = [(i, es1[i], peek("eshot_dx", i)) for i in range(3) if es1[i] != moved[i] and es1[i]]
            hit = got[0] == ENEMY_EXPLODING or gstate()[0] != gs_before
            if not hit and any(es1[i] is None and moved[i] for i in range(3)):
                errs.append(f"frame {k}: an enemy shot vanished: {es0} -> {es1}")
            if not hit:
                want_col = ct[8] if m.white else ct[5 + m.row]
                if got != (m.st, (m.x, m.y), want_col):
                    errs.append(f"frame {k}: enemy {got}, the design ({m.st:#x}, ({m.x}, {m.y}), {want_col})")
                want_new = []
                for fpos in fires:                        # at most one fire step a frame in these paths
                    free = [i for i in range(3) if moved[i] is None]
                    if gs_before == GS_PLAY and 24 <= fpos[0] <= 320 and free:
                        want_new.append((free[0], fpos, aim_dx(px - fpos[0]) & 255))
                if rec["new"] != want_new:
                    errs.append(f"frame {k} (step {m.step}): new enemy shots {rec['new']}, expected {want_new}")
            recs.append(rec)
            if (until and until(k, m, rec)) or (not until and (hit or m.st == ENEMY_PARKED)):
                break
        poke("zp_loop", [0])
        return recs, errs, m

    def stores(self):
        peek = self.peek
        return int(f"{peek('zp_wave'):02x}"), peek("zp_pattern"), peek("zp_loop")

    def panel_wave(self):
        mem = self.mem
        return "".join(chr(c - PANEL_BG) for c in mem(SCREEN + 960 + 31, 2))

    def last_explosion(self, e=17):
        """Through the monitor: enemy e is the last one alive and its explosion ends in the next
        frame (the game's own enemy_kill then runs, inside formation_update)."""
        only, poke = self.only, self.poke
        only({e})
        poke("enemy_state", [ENEMY_EXPLODING], e)
        poke("enemy_timer", [1], e)
        poke("explosion_enemy", [e, 0xFF, 0xFF, 0xFF])

    def repark_all(self):
        """Through the monitor: all 18 Parked again and no diver (after forced launches)."""
        ct, poke = self.ct, self.poke
        poke("enemy_state", [ENEMY_PARKED] * ENEMIES)
        poke("mux_y", [ROW_Y[e // COLS] for e in range(ENEMIES)], ENEMY0)
        poke("mux_col", [ct[5 + e // COLS] for e in range(ENEMIES)], ENEMY0)
        poke("mux_x_hi", [0] * ENEMIES, ENEMY0)       # formation_update writes columns 4 and 5 every frame
        poke("diver_enemy", [0xFF] * 3)
        poke("zp_divers_active", [0])
        poke("zp_enemies_alive", [ENEMIES])
        poke("explosion_enemy", [0xFF] * 4)

    def hit_player(self):
        """An enemy shot placed on the ship: the next frame is frame 0 of PlayerDying."""
        frame, gstate, poke, put_eshot, state = self.frame, self.gstate, self.poke, self.put_eshot, self.state
        poke("zp_player_invuln", [0])
        put_eshot(0, state()[0], 205, 0)
        frame()
        if gstate() != (GS_DYING, 0):
            raise MeasureError(f"hit_player: state {gstate()}")

    # wave-timeline: the design's worked case (Stage 4 rule 8). The player rams the last enemy in frame d
    def ram_last(self, lives):
        estates, frame, gstate, only, peek = self.estates, self.frame, self.gstate, self.only, self.peek
        poke, score, settle, start_wave = self.poke, self.score, self.settle, self.start_wave
        start_wave(3)
        poke("zp_lives", [lives])
        poke("game_score", [0, 0, 0])
        px = settle()
        only({14})
        poke("enemy_state", [ST_D], 14)
        poke("enemy_seg", [peek("path_first", 4) + 4], 14)        # the Hook's skim: (-2, 0)
        poke("enemy_left", [6], 14)
        poke("enemy_step", [40], 14)
        poke("enemy_fire", [3], 14)                               # PATH_FIRE_NONE
        poke("mux_x_lo", [(px + 2) & 255], ENEMY0 + 14)
        poke("mux_x_hi", [(px + 2) >> 8], ENEMY0 + 14)
        poke("mux_y", [216], ENEMY0 + 14)
        poke("diver_enemy", [14, 0xFF, 0xFF])
        poke("zp_divers_active", [1])
        poke("zp_player_invuln", [0])
        frame()                                           # frame d
        return gstate(), estates()[14], score(), peek("zp_lives")

    def req(self):
        mem, sym = self.mem, self.sym
        return tuple(mem(sym["sfx_request"], 3))

    def cur(self):
        mem, sym = self.mem, self.sym
        return tuple(mem(sym["sfx_cur"], 3))

    def nm(self, t):
        SFX_NAME = self.SFX_NAME
        return "(" + ", ".join(SFX_NAME.get(x, hex(x)) for x in t) + ")"

    def quiet(self):
        """Nothing pressed until no voice is playing, nothing is asked for and no player shot is in flight."""
        cur, frame, peek, req = self.cur, self.frame, self.peek, self.req
        for _ in range(300):
            _, shots = frame(0)
            if cur() == (0, 0, 0) and req() == (0, 0, 0) and shots == [None, None] and peek("zp_player_cooldown") == 0:
                return
        raise MeasureError(f"quiet: still playing {cur()}")

    def held(self, v):
        """Frames voice v goes on playing what it plays now, this stop included (nothing pressed)."""
        cur, frame = self.cur, self.frame
        what, n = cur()[v], 0
        while cur()[v] == what and n < 200:
            frame(0)
            n += 1
        return n

    def put_diver(self, slot, e, x, y, fire):
        """Through the monitor: enemy e in Dive in diver slot `slot`, on its path's first segment;
        with fire, its next step is its first fire step (eshot_spawn runs in the next frame)."""
        peek, poke = self.peek, self.poke
        row = e // COLS
        poke("enemy_state", [ST_D], e)
        poke("enemy_seg", [peek("path_first", row * 2)], e)
        poke("enemy_left", [PATHS[row][0][2]], e)
        poke("enemy_step", [FIRE[row][0] - 1 if fire else 60], e)
        poke("enemy_fire", [peek("path_fire_first", row) if fire else 3], e)      # 3: PATH_FIRE_NONE
        poke("enemy_shots", [2], e)
        poke("mux_x_lo", [x & 255], ENEMY0 + e)
        poke("mux_x_hi", [x >> 8], ENEMY0 + e)
        poke("mux_y", [y], ENEMY0 + e)
        poke("diver_enemy", [e], slot)

    def pshot_under(self, i, e):
        """Player shot i placed so that it is inside enemy e's box in the next frame."""
        epos, put_pshot = self.epos, self.put_pshot
        x, y = epos(e)
        put_pshot(i, x, y + 18)


# What the guard checks for each `needs` (check.py's NEEDS table; "fight" is the default)
def swarm_guard(rig, case):
    """The clean-state guard, run before every case: returns the problems with the state the case starts in.

    needs "fight" (default): Play, wave phase Fight, a lives left, and a quiet sky: no enemy shot, explosion or diver.
    needs "play": the game state is Play, whatever the wave's phase.
    needs "title": the title shows.
    needs "dying": PlayerDying (a frame-exact continuation of the case before); "over": GameOver (the same).
    needs None: no requirement (the case puts everything in place itself).
    Cases get here after the case before them (and its clean-up), so one that only works on what the last case
    left fails here, naming it, instead of passing by luck."""
    needs = case.needs
    if needs is None:
        return []
    peek, mem, sym = rig.peek, rig.mem, rig.sym
    gs, problems = peek("zp_game_state"), []
    if needs in ("title", "dying", "over"):
        want = {"title": GS_TITLE, "dying": GS_DYING, "over": GS_OVER}[needs]
        if gs != want:
            problems.append(f"game state {gs}, expected {want} ({needs}); 0 Play, 1 Respawn, 2 Dying, 3 GameOver, 4 Title")
        return problems
    if gs != GS_PLAY:
        problems.append(f"game state {gs} (0 = Play)")
    if needs == "play":
        return problems
    assert needs == "fight", f"unknown guard need {needs!r} in case {case.name}"
    if peek("zp_wave_phase") != PHASE_FIGHT:
        problems.append(f"wave phase {peek('zp_wave_phase')} (0 = Fight)")
    if peek("zp_lives") == 0:
        problems.append("no lives left")
    if any(y != MUX_OFF for y in mem(sym["mux_y"] + 1, 3)):
        problems.append(f"enemy shots in flight, mux_y 1-3 = {list(mem(sym['mux_y'] + 1, 3))}")
    if any(e != 0xFF for e in mem(sym["explosion_enemy"], 4)):
        problems.append(f"explosions running, explosion_enemy = {list(mem(sym['explosion_enemy'], 4))}")
    if peek("zp_divers_active") or any(s & 0x80 for s in mem(sym["enemy_state"], ENEMIES)):
        problems.append(f"divers out: {peek('zp_divers_active')} active, states "
                        f"{[hex(s) for s in mem(sym['enemy_state'], ENEMIES) if s & 0x80]}")
    return problems
