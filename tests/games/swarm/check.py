"""Joystick-driven checks of Swarm (M4): stage 1's player, player shots, panel and stars, stage 2
part A's formation (18 enemies, the drift, the animation) and part B's collisions (player shots
against the enemies, explosions, the score, the formation coming back after a clear), and stage
3's enemy shots, the player's death, lives, READY and game over, the divers (launcher, wind-up,
the three paths, firing, return), a diver shot mid-dive and the ram.

EARLIER CASES AND STAGE 3. Every case from "setup" to "sprites" was written when nothing dived
and nothing could hit the ship; they assume a formation that stays Parked. They are kept valid
by holding the launcher off: launcher(False) re-writes zp_launch_timer to 255 every 32 frames
(through the monitor), so no dive is ever launched, no enemy shot exists and the ship can't be
hit. Nothing else about them changed, except that the pause after a clear is now zp_clear_timer
(it was zp_state_timer). The stage 3 cases turn the launcher on where they want a dive
(launcher(True), usually for one frame with zp_launch_timer = 1), and safe(True) holds
zp_player_invuln up where a case is about a diver's flight and not about the ship.

`make test` can't press buttons, so this drives joystick port 2 through the VICE monitor (the
"I/O simulation" joyport device, as tests/engine/input/check.py does) on the GAME build (not the
AUTOPLAY budget build). The machine is stopped at game_update_end in EVERY frame (after that
frame's input_read and update routines, before mux_update); the stick is changed while it is
stopped and the state is read at the next stop, so each sample is exactly one game frame later.

Expected values are the design's (docs/games/swarm/design.md): X 24-318, 3 px a frame, start 171,
Y 221; shots spawn at (player X, 213), move 8 a frame, are removed when Y < 46, at most 2, with a
10-frame cooldown. Formation: enemy e = row * 6 + column on virtual sprite 6 + e, at X = 34 + fx +
36 * column, Y = 56 / 96 / 136; fx 0 -> 96 -> 0, 1 pixel every 2 frames, starting at 48 moving right;
types A / B / C by row in purple / yellow / light green, shapes $C3-$C8, swapping every 16 frames.
Collisions: hit boxes player shot columns 11-12, enemy columns 4-19 (so a shot at X hits an enemy at
Xe when -8 <= X - Xe <= 8) and rows 0-7 against 3-17 (a shot fired at frame f is first inside row
2 / 1 / 0 at frame f + 8 / 13 / 18); an explosion is 4 shapes ($C9-$CC) of 4 frames, orange,
stationary, then the sprite is hidden; 50 / 80 / 150 points for a parked enemy of row 2 / 1 / 0.

How the collision cases aim: the script reads the drift's variables, works out where the target
will be in the frame the shot reaches it (predict()), and presses fire in the frame that gives the
offset it wants. Only the stick is used to make a hit or a miss; the monitor is used to read, to
take a missed shot away after an "outside" edge case, to empty the sky for stage 1's shot cases
(which need shots that hit nothing) and to bring the formation back for the later cases through the
game's own pause timer (zp_clear_timer = 1).

Cases (PASS/FAIL each, exit code 1 on any failure):
  setup        $D011 = $5B, $D018 = $1A, $D020/21/22 = black/black/blue, $D017 = $D01D = 0,
               $01 = $35, $DC02 = 0; mux_flags = $80 for sprites 0-3 and 0 for 4-23; player at
               (171, 221), shape $C0; enemy shots and player shots hidden
  formation    18 enemies Parked on sprites 6-23 at (34 + fx + 36 * column, 56 / 96 / 136), unpinned,
               each row in its colour (read from colour_table: purple, yellow, light green) and its
               type's shape for the current animation frame; zp_enemies_alive = 18; fx is 48 in the
               game's first frame and 49, moving right, in the second
  drift        420 frames: fx steps by exactly 1 every 2 frames, turns round at 96 and at 0 (both
               reached, each held 2 frames like every other value), every enemy is at its designed
               X and Y in every frame, and X is never outside 34-310 (reached at fx 0 and 96)
  animation    the same 420 frames: all 18 enemies always show their row's shape for the same
               frame (0 or 1), which swaps every 16 frames exactly; colours never change
  drift-loop2  zp_loop set to 2 through the monitor: 1 pixel every frame (the design's loop 2
               speed), still turning at 0 and 96; back to 1 every 2 frames with zp_loop = 0
  charset      $2800-$29FF is the ROM's glyphs with codes 27-29 patched ('A' and '0' spot-checked
               against known ROM bytes, the three custom glyphs against one-pixel / ship shapes)
  panel        all 40 cells of row 24 hold a code in $40-$7F with white colour RAM; SCORE, HI and
               WAVE at the design's columns; 000000, 005000, 01; ships at 35-36, blank at 37
  stars        exactly 48 star glyphs in rows 0-23, none in columns 10-29 of rows 5, 9, 11, 12,
               13, 16, 19; every star's colour is one of white / light grey / grey / dark grey
  twinkle      over 96 frames exactly one colour RAM cell changes each frame, always a star's,
               each star changes every 48 frames, stepping white > light grey > grey > dark grey
  idle         nothing pressed for 10 frames: X stays 171, no shot
  up-down      up, then down, 10 frames each: nothing moves, no shot
  right        held: X + 3 every frame from 171 to 318 (49 frames), then stays at 318 for 20
  left         held: X - 3 every frame from 318 to 24 in 98 frames (feel target 1), stays for 20
  stop         right for 5 frames, released: X doesn't change in the frame of the release or after
  left+right   both held 10 frames: no movement (the game's choice: they cancel)
  (the enemies are now taken away through the monitor: the next four cases are about shots alone)
  fire-hold    fire held 200 frames: never more than 2 shots; each spawns at (player X, 213),
               moves - 8 a frame, is last seen at Y 53 and lives 21 frames; no two spawns closer
               than 10 frames; the spawn frames are printed (0, 10, 21, 31, 42, ...)
  fire-move    fire + right held: each shot keeps the X the player had when it was fired
  cooldown     fire held while each shot is removed (by this script, through the monitor) the
               frame after it spawns, so a slot is always free: spawns are exactly 10 frames apart
  fire-tap     fire pressed for 1 frame: exactly one shot; pressed again 5 frames later: none
               (cooldown); pressed at 10 frames: a second shot
  (the formation is brought back: zp_clear_timer = 1, the game's own path)
  hit          a shot fired under enemy 15 (row 2, column 3): nothing until frame f + 8, then in that
               frame the enemy is Exploding (timer 16, shape $C9, orange), the shot's slot is free,
               the score is 50 and the panel's score is marked dirty; the panel shows 000050 one
               frame later; the explosion stays where the enemy was for 16 frames, shapes $C9-$CC 4
               frames each, while the others drift on; in the 17th the enemy is Dead, hidden, and
               zp_enemies_alive is 17. The high score doesn't change
  gap          a shot fired between columns 0 and 1 (17-19 pixels right of column 0 when it reaches
               row 2) passes all three rows: it lives 21 frames, nothing explodes, the score stays
  edge-*       one pixel inside the enemy's box hits in the first frame of overlap, one pixel
               outside is a miss in that frame (the shot is then taken away): left edge X - Xe =
               -9 / -8 and right edge + 9 / + 8, on row 2 columns 0 and 1 (all X below 256); again
               on column 5 with the enemy at X 258-262 and the shot below 256 (left edge, row 2)
               and both above 255 (right edge, row 1 through the dead row 2)
  exploding    two shots 10 frames apart at column 2: the first kills row 2; the second is inside
               the explosion's box (the module reports it; the game passes it over) and carries
               on to kill row 1: 50 then 80 points
  dead         a shot at column 2 again: through the dead rows 2 and 1 (their boxes would have
               overlapped it) to row 0: 150 points
  double       two shots in flight hit in the same frame: one fired at enemy 5 (row 0, column 5,
               the rows below it dead), then left held for 10 frames and a second fired at enemy
               16 (row 2, column 4): both Exploding in frame f + 18, not before, + 200
  clear        every enemy left is shot (the player chases each): the score ends at 6 x 280 =
               001680; when the last explosion ends all 18 are Dead and hidden, zp_enemies_alive 0;
               the sky stays empty for 75 frames and in the 75th all 18 are Parked again from fx 48,
               with no bonus, the wave still 01 and the high score still 005000
  score-cap    the score set to 999,960 through the monitor, a 50-point enemy shot: 999,990
  no-drop      600 frames with the player sweeping between the clamps and fire held (2 shots
               crossing the rows, enemies shot away and the formation coming back): every Parked
               enemy is at its home in every frame, every enemy that isn't Parked is Exploding or
               Dead and hidden, and in a DEBUG build mux_drop_count is 0 in every frame and
               game_flicker_frames, mux_max_age, mux_late_count and game_overrun_count are 0 at the
               end (a release build has no counters: the positions only)
  (the formation is brought back again for the last case)
  sprites      the hardware sprite registers the multiplexer wrote, read at line 251 (the end of
               the display): all 8 on, one is the player at its X and Y in its colour and shape,
               the others are enemies in their row's Y, colour and shape; no expansion, all hires

  (stage 3; an enemy shot is placed through the monitor where no diver is wanted)
  eshot-move   three placed shots: Y + 2 and X + dx a frame, removed when Y > 221, clamped at X 0
               and 344, Y + 3 at loop 2; shape, colour, pinned
  eshot-edge-* / eshot-y-*   the ship's box against a shot's: |shot X - ship X| = 6 hits, 7 misses
               (below and above X 255); shot Y 206 misses, 207 hits, 221 hits
  death        the hit's frame and the 99 after: lives, enemy shots removed, markers, the white
               explosion's 4 shapes of 8 frames, hidden from frame 32, no move or fire, the player
               shot in flight carries on
  respawn      frame 100: READY, the ship at 171, controllable at once, READY for 50 frames, the
               flash colour every frame, a shot falling through the ship, hit in frame 150 exactly
  game-over, game-over-timeout, game-over-50, game-over-diving   the last life: the high score
               only then, GAME OVER, held fire doesn't skip, a new press before frame 50 doesn't,
               one in frame 50 or later does, 200 frames otherwise; the new game's state; with a
               diver out GameOver still starts at frame 100 and the diver flies on
  dive-*       each path, as authored and mirrored, launched by the launcher (every other enemy
               taken away) and compared in every frame with a model of the design's tables:
               position, state, colour, fire steps and each shot's dx, lethal steps, wrap, Return
               following the drifting home; again at loops 1 and 3 (2-step frames, wind-up, shots)
  windup       the wobble and the white flash by frame
  aim-*        dx 0 at |d| = 15, 1 pixel a frame toward the ship at 16, both signs
  fire-lost    no free slot at a fire step: no shot then or later
  dying-divers the player hit with a diver out: no shot fired, the launch timer stopped,
               Respawn in the frame after the diver parked
  diver-hit-*  a diver shot in WindUp, Dive (each path) and Return: double score, the explosion
               where it is, divers active - 1 in that frame, its shots carry on
  ram-*        the Hook on the ship: only from Y 210; |diver X - ship X| = 13 rams, 14 doesn't;
               not while invulnerable; a diver shot in the same frame doesn't ram
  fifth-explosion   4 explosions running: a fifth enemy dies at once
  launcher, launcher-halved, launcher-rows   first launch at frame 50, 100 apart, never more than 2
               out, the pick is the first Parked enemy at or after the drawn index, never more
               than 2 rng_next calls a frame (the generator is modelled); 50 apart with 4 alive;
               the wave's rows, and any row when those are empty
  clear-while-dying   the formation's return runs in PlayerDying
  stage3-play  1,500 frames of play: pinned sprites 0-3 never dropped, nothing missing 2 frames
               running, no overrun (DEBUG counters)

Run from the repo root (build first: make GAME=swarm):

    uv run --package budget-runner python tests/games/swarm/check.py [--prg build/swarm/swarm.prg]

Takes about 2 minutes. Works on a release build too (make BUILD=release GAME=swarm): the DEBUG
counters are read only if the build has them. Results of the last run: tests/games/swarm/check_results.txt.
"""

import argparse
import sys
from pathlib import Path

from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice
from vice_monitor import CPU_OP_EXEC  # on sys.path once budget_runner.session is imported

REPO = Path(__file__).resolve().parents[3]
BITS = {"up": 0x01, "down": 0x02, "left": 0x04, "right": 0x08, "fire": 0x10}
JOYPORT_IO_SIMULATION = 37
PORT2 = 1  # the monitor's port index

X_MIN, X_MAX, X_START, PLAYER_Y, SPEED = 24, 318, 171, 221, 3
SHOT_Y0, SHOT_SPEED, SHOT_KILL, COOLDOWN = 213, 8, 46, 10
MUX_OFF = 0xFF
SCREEN, COLOUR = 0x0400, 0xD800
STAR_HI, STAR_LO, SHIP, SPACE, PANEL_BG = 27, 28, 29, 32, 0x40
BAND_ROWS, BAND_COLS = {5, 9, 11, 12, 13, 16, 19}, range(10, 30)
ENEMY0, ENEMIES, COLS = 6, 18, 6
FORM_X0, COL_DX, ROW_Y, FX_MAX, FX_START = 34, 36, [56, 96, 136], 96, 48
ANIM_FRAMES, SHAPE_ENEMY, ENEMY_PARKED = 16, 0xC3, 1
ENEMY_DEAD, ENEMY_EXPLODING, SHAPE_EXPLOSION, EXPLOSION_FRAMES, ORANGE = 0, 0x83, 0xC9, 16, 8
FLIGHT = [18, 13, 8]            # frames from the fire frame to the first frame inside row 0 / 1 / 2's box
ROW_SCORE = [150, 80, 50]
HIT_DX = 8                      # |shot X - enemy X| <= 8 overlaps (columns 11-12 against 4-19)
CLEAR_PAUSE, DRIFT_PERIOD = 75, [2, 2, 1, 1]
PANEL_DIRTY_SCORE = 1
ENEMY_COLOURS = [4, 7, 13]  # purple, yellow, light green (design.md#colours), colour_table 5-7
DEBUG_COUNTERS = [("game_flicker_frames", 2), ("mux_max_age", 1), ("mux_late_count", 1), ("game_overrun_count", 1)]
STAR_COLOURS = [1, 15, 12, 11]


def code(text):
    """Screen codes of a text in capitals, digits and spaces."""
    return [ord(c) - 64 if c.isalpha() else ord(c) for c in text]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prg", default=str(REPO / "build/swarm/swarm.prg"))
    a = ap.parse_args()
    fails = []

    def rep(name, ok, text):
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {text}")
        if not ok:
            fails.append(name)

    v = Vice(Path(a.prg), 0)        # no warm-up: the first stop below is the game's first frame
    try:
        mon, sym = v.mon, v.symbols
        mon.resource_set("JoyPort2Device", JOYPORT_IO_SIMULATION)
        mon.joyport_set(PORT2, 0x1F)
        cp = mon.checkpoint_set(sym["game_update_end"], sym["game_update_end"], CPU_OP_EXEC)

        def mem(addr, n=1):
            return mon.mem_get(addr, addr + n - 1)

        def state():
            x = mem(sym["zp_player_x_lo"], 2)
            ys = mem(sym["mux_y"] + 4, 2)
            xl = mem(sym["mux_x_lo"] + 4, 2)
            xh = mem(sym["mux_x_hi"] + 4, 2)
            shots = [None if ys[i] == MUX_OFF else (xl[i] + 256 * xh[i], ys[i]) for i in range(2)]
            return x[0] + 256 * x[1], shots

        # Values the script holds through the monitor while a case needs a stage 3 feature out of
        # the way: re-written every 32 frames (see launcher() and safe()).
        hold = {"n": 0, "set": {}}

        def launcher(on):
            """Off: zp_launch_timer is kept above 190, so no dive is ever launched (the cases written
            for stages 1 and 2 assume a formation that stays Parked). On: the game's own timer."""
            if on:
                hold["set"].pop("zp_launch_timer", None)
            else:
                hold["set"]["zp_launch_timer"] = 255
                hold["n"] = 0

        def safe(on):
            """On: zp_player_invuln is kept above 100, so the ship can't be hit (it flashes)."""
            if on:
                hold["set"]["zp_player_invuln"] = 149
                hold["n"] = 0
            else:
                hold["set"].pop("zp_player_invuln", None)
                mon.mem_set(sym["zp_player_invuln"], bytes([0]))
                mon.mem_set(sym["mux_col"], mon.mem_get(sym["colour_table"] + 3, sym["colour_table"] + 3))

        def frame(pressed=None):
            """Optionally set the stick (active-high mask), run to the next game_update_end."""
            if hold["set"]:
                hold["n"] -= 1
                if hold["n"] <= 0:
                    for label, value in hold["set"].items():
                        mon.mem_set(sym[label], bytes([value]))
                    hold["n"] = 32
            if pressed is not None:
                mon.joyport_set(PORT2, ~pressed & 0x1F)
            mon.exit()
            if not mon.wait_stopped(STOP_TIMEOUT):
                mon.ping()
                raise MeasureError("game_update_end not reached: jam?")
            return state()

        def settle():
            """Release everything and wait until no shot is in flight and the cooldown is 0."""
            frame(0)
            for _ in range(40):
                x, shots = frame()
                if shots == [None, None] and mem(sym["zp_player_cooldown"])[0] == 0:
                    return x
            raise MeasureError("shots never cleared")

        def enemies():
            """fx, drift direction, and each enemy's (X, Y, shape, colour) from the multiplexer's arrays."""
            xl, xh = mem(sym["mux_x_lo"] + ENEMY0, ENEMIES), mem(sym["mux_x_hi"] + ENEMY0, ENEMIES)
            ys, ps = mem(sym["mux_y"] + ENEMY0, ENEMIES), mem(sym["mux_ptr"] + ENEMY0, ENEMIES)
            cs = mem(sym["mux_col"] + ENEMY0, ENEMIES)
            fx, fdir = mem(sym["zp_fx"], 2)
            return fx, fdir, [(xl[e] + 256 * xh[e], ys[e], ps[e], cs[e] & 15) for e in range(ENEMIES)]

        def home(fx):
            return [(FORM_X0 + fx + COL_DX * (e % COLS), ROW_Y[e // COLS]) for e in range(ENEMIES)]

        launcher(False)                           # until the stage 3 cases: nothing dives
        frame(0)
        first = enemies()                         # after the first formation_update
        frame()

        # setup
        ct = mem(sym["colour_table"], 19)
        regs = {r: mem(r)[0] for r in (0xD011, 0xD018, 0xD017, 0xD01D, 0xD01B, 0xDC02, 0x01)}
        cols = [b & 15 for b in mem(0xD020, 3)]
        flags = list(mem(sym["mux_flags"], 24))
        ys = list(mem(sym["mux_y"], 24))
        x, shots = state()
        ok = (regs[0xD011] & 0x7F == 0x5B and regs[0xD018] & 0xFE == 0x1A and regs[0xD017] == 0
              and regs[0xD01D] == 0 and regs[0xD01B] == 0 and regs[0xDC02] == 0 and regs[0x01] & 7 == 5
              and cols == [ct[0], ct[1], ct[2]] == [0, 0, 6]
              and flags == [0x80] * 4 + [0] * 20
              and x == X_START and ys[0] == PLAYER_Y and all(y == MUX_OFF for y in ys[1:6])
              and mem(sym["mux_ptr"])[0] == 0xC0 and mem(sym["zp_lives"])[0] == 3)
        rep("setup", ok, f"$D011=${regs[0xD011]:02x} $D018=${regs[0xD018]:02x} $D020-22={cols} "
            f"$D017/$D01D/$D01B={regs[0xD017]}/{regs[0xD01D]}/{regs[0xD01B]} $DC02=${regs[0xDC02]:02x} "
            f"$01=${regs[0x01]:02x}; pinned flags {flags[:6]}...; player ({x}, {ys[0]}), "
            f"sprites 1-5 hidden: {all(y == MUX_OFF for y in ys[1:6])}; lives {mem(sym['zp_lives'])[0]}")

        # formation
        fx, fdir, en = enemies()
        states = list(mem(sym["enemy_state"], ENEMIES))
        frames_ = {en[e][2] - SHAPE_ENEMY - 2 * (e // COLS) for e in range(ENEMIES)}
        alive = mem(sym["zp_enemies_alive"])[0]
        ok = ([q[:2] for q in en] == home(fx) and flags[ENEMY0:] == [0] * ENEMIES
              and [q[3] for q in en] == [ENEMY_COLOURS[e // COLS] for e in range(ENEMIES)]
              and ct[5:8] == bytes(ENEMY_COLOURS) and frames_ in ({0}, {1})
              and states == [ENEMY_PARKED] * ENEMIES and alive == ENEMIES
              and first[0] == FX_START and [q[:2] for q in first[2]] == home(FX_START)
              and fx == FX_START + 1 and fdir == 1)
        rep("formation", ok, f"first frame: fx {first[0]} (design: starts at 48), second: fx {fx}, direction {fdir} "
            f"(1 = right); "
            f"18 enemies at their homes for that fx: {[q[:2] for q in en] == home(fx)} "
            f"(row 0: X {[q[0] for q in en[:COLS]]}, Y {sorted({q[1] for q in en[:COLS]})}; rows 1, 2: Y "
            f"{sorted({q[1] for q in en[COLS:2 * COLS]})}, {sorted({q[1] for q in en[2 * COLS:]})}); colours by row "
            f"{[en[r * COLS][3] for r in range(3)]}; shapes by row {[hex(en[r * COLS][2]) for r in range(3)]} "
            f"(animation frame {sorted(frames_)}); unpinned: {flags[ENEMY0:] == [0] * ENEMIES}; "
            f"all Parked: {states == [ENEMY_PARKED] * ENEMIES}; alive {alive}")

        # charset
        cs = mem(0x2800, 512)
        glyph = lambda c: list(cs[c * 8:c * 8 + 8])
        rom_a, rom_0 = [0x18, 0x3C, 0x66, 0x7E, 0x66, 0x66, 0x66, 0x00], [0x3C, 0x66, 0x6E, 0x76, 0x66, 0x66, 0x3C, 0x00]
        bits = lambda g: sum(bin(b).count("1") for b in g)
        hi_rows = [i for i, b in enumerate(glyph(STAR_HI)) if b]
        lo_rows = [i for i, b in enumerate(glyph(STAR_LO)) if b]
        ok = (glyph(1) == rom_a and glyph(48) == rom_0 and glyph(SPACE) == [0] * 8
              and bits(glyph(STAR_HI)) == 1 and bits(glyph(STAR_LO)) == 1 and hi_rows[0] < 4 <= lo_rows[0]
              and bits(glyph(SHIP)) > 10)
        rep("charset", ok, f"'A' and '0' are the ROM's, space empty; star high: 1 pixel in row {hi_rows}, "
            f"star low: 1 pixel in row {lo_rows}; ship {bits(glyph(SHIP))} pixels")

        # panel
        row = list(mem(SCREEN + 960, 40))
        rcol = [b & 15 for b in mem(COLOUR + 960, 40)]
        want = [SPACE] * 40
        for col, text in ((1, "SCORE"), (7, "000000"), (15, "HI"), (18, "005000"), (26, "WAVE"), (31, "01")):
            want[col:col + len(text)] = code(text)
        want[35:37] = [SHIP, SHIP]
        want = [c + PANEL_BG for c in want]
        ok = row == want and rcol == [ct[13]] * 40 == [1] * 40
        shown = "".join("^" if c == SHIP + PANEL_BG else chr((c & 63) + 64) if (c & 63) < 27 else chr(c & 63)
                        for c in row)
        rep("panel", ok, f"row 24 = '{shown}' (^ = ship); all 40 codes in $40-$7F: "
            f"{all(0x40 <= c < 0x80 for c in row)}; colour RAM all white: {rcol == [1] * 40}")

        # stars
        scr = mem(SCREEN, 960)
        colr = [b & 15 for b in mem(COLOUR, 960)]
        stars = [i for i, c in enumerate(scr) if c in (STAR_HI, STAR_LO)]
        other = [i for i, c in enumerate(scr) if c not in (STAR_HI, STAR_LO, SPACE)]
        banned = [i for i in stars if i // 40 in BAND_ROWS and i % 40 in BAND_COLS]
        table = sorted(lo + 256 * hi for lo, hi in zip(mem(sym["star_lo"], 48), mem(sym["star_hi"], 48)))
        badcol = [i for i in stars if colr[i] not in STAR_COLOURS]
        ok = len(stars) == 48 and not banned and not other and table == stars and not badcol
        rep("stars", ok, f"{len(stars)} star cells in rows 0-23 ({sum(scr[i] == STAR_HI for i in stars)} high, "
            f"{sum(scr[i] == STAR_LO for i in stars)} low), {len(banned)} in a text band, {len(other)} other "
            f"non-space cells, same cells as the star table: {table == stars}, colours outside the four: {len(badcol)}")

        # twinkle
        prev, changes, bad = colr, [], []
        for f in range(96):
            frame()
            cur = [b & 15 for b in mem(COLOUR, 960)]
            diff = [i for i in range(960) if cur[i] != prev[i]]
            if len(diff) != 1 or diff[0] not in stars:
                bad.append((f, diff))
            else:
                i = diff[0]
                if STAR_COLOURS[(STAR_COLOURS.index(prev[i]) + 1) % 4] != cur[i]:
                    bad.append((f, i, prev[i], cur[i]))
                changes.append(i)
            prev = cur
        ok = not bad and len(set(changes[:48])) == 48 and changes[:48] == changes[48:]
        rep("twinkle", ok, f"96 frames: one star cell changed colour in each ({len(bad)} exceptions), "
            f"{len(set(changes[:48]))} different stars in 48 frames, the same order again in the next 48, "
            f"each step the next of white/light grey/grey/dark grey")

        # drift and animation: one whole period of the drift (384 frames) and a bit
        hist = [enemies() for _ in range(1) if frame() or True]
        hist += [(frame(), enemies())[1] for _ in range(419)]
        errs, turns, xs_all = [], [], []
        for f, (fx, fdir, en) in enumerate(hist):
            if [q[:2] for q in en] != home(fx):
                errs.append(f"frame {f}: enemies not at home for fx {fx}")
            xs_all += [q[0] for q in en]
            if f:
                pfx, pdir = hist[f - 1][0], hist[f - 1][1]
                step = fx - pfx
                if step not in (0, 1, -1) or (step and step != (1 if pdir == 1 else -1)):
                    errs.append(f"frame {f}: fx {pfx} -> {fx} with direction {pdir}")
                if fdir != pdir:
                    turns.append((f, fx))
                    if fx not in (0, FX_MAX) or step == 0:
                        errs.append(f"frame {f}: turned at fx {fx}")
        runs, start = [], 0                       # how long each fx value was held
        for f in range(1, len(hist) + 1):
            if f == len(hist) or hist[f][0] != hist[start][0]:
                runs.append((hist[start][0], f - start))
                start = f
        held = sorted({n for _, n in runs[1:-1]})
        fxs = [h[0] for h in hist]
        sweep = turns[1][0] - turns[0][0] if len(turns) >= 2 else None
        ok = (not errs and held == [2] and min(fxs) == 0 and max(fxs) == FX_MAX and len(turns) >= 2
              and {t[1] for t in turns} == {0, FX_MAX} and sweep == 2 * FX_MAX
              and min(xs_all) == FORM_X0 and max(xs_all) == FORM_X0 + FX_MAX + COL_DX * (COLS - 1) == 310)
        rep("drift", ok, f"420 frames: fx {min(fxs)}..{max(fxs)}, every value held {held} frames (the extremes "
            f"too), steps of 1 only; turned at (frame, fx) {turns}; one sweep {sweep} frames (design: 96 pixels x 2 = 192); enemy X "
            f"{min(xs_all)}..{max(xs_all)} (design: 34-310); every enemy at 34 + fx + 36 * column and its row's Y "
            f"in every frame; errors: {errs[:3] or 'none'}")

        errs, swaps, prevf = [], [], None
        for f, (fx, fdir, en) in enumerate(hist):
            fr = {en[e][2] - SHAPE_ENEMY - 2 * (e // COLS) for e in range(ENEMIES)}
            if fr not in ({0}, {1}):
                errs.append(f"frame {f}: shapes {[hex(q[2]) for q in en]}")
                continue
            if [q[3] for q in en] != [ENEMY_COLOURS[e // COLS] for e in range(ENEMIES)]:
                errs.append(f"frame {f}: colours changed")
            fr = fr.pop()
            if prevf is not None and fr != prevf:
                swaps.append(f)
            prevf = fr
        gaps = sorted({b - a for a, b in zip(swaps, swaps[1:])})
        rep("animation", not errs and gaps == [ANIM_FRAMES] and len(swaps) >= 25,
            f"420 frames: all 18 on the same animation frame in every frame, shapes $C3/$C4, $C5/$C6, $C7/$C8 by "
            f"row; {len(swaps)} swaps, {gaps} frames apart (design: 16); errors: {errs[:3] or 'none'}")

        # drift-loop2: the design's faster drift, 1 pixel a frame from loop 2
        mon.mem_set(sym["zp_loop"], bytes([2]))
        frame()
        frame()                                   # the timer in progress runs out; then every frame
        fast = [(frame(), enemies())[1] for _ in range(220)]
        steps = sorted({abs(b[0] - a[0]) for a, b in zip(fast, fast[1:])})
        ffx = [h[0] for h in fast]
        okf = (steps == [1] and min(ffx) == 0 and max(ffx) == FX_MAX
               and all([q[:2] for q in h[2]] == home(h[0]) for h in fast))
        mon.mem_set(sym["zp_loop"], bytes([0]))
        frame()
        slow = [(frame(), enemies())[1] for _ in range(20)]
        sruns = [sum(1 for _ in g) for _, g in __import__("itertools").groupby(h[0] for h in slow)]
        rep("drift-loop2", okf and set(sruns[1:-1]) == {2},
            f"zp_loop = 2 for 220 frames: fx changes by {steps} every frame, {min(ffx)}..{max(ffx)}, enemies at "
            f"their homes; zp_loop = 0 again: each fx held {sorted(set(sruns[1:-1]))} frames")

        # idle
        s = [frame() for _ in range(10)]
        rep("idle", all(q == (X_START, [None, None]) for q in s), f"10 frames: X {sorted({q[0] for q in s})}, no shot")

        # up-down
        s = [frame(BITS["up"])] + [frame() for _ in range(9)] + [frame(BITS["down"])] + [frame() for _ in range(9)]
        frame(0)
        rep("up-down", all(q == (X_START, [None, None]) for q in s), f"X {sorted({q[0] for q in s})}, no shot")

        # right
        xs = [frame(BITS["right"])[0]] + [frame()[0] for _ in range(68)]
        want = [min(X_START + SPEED * (i + 1), X_MAX) for i in range(69)]
        rep("right", xs == want, f"+{SPEED} a frame from {X_START}: reaches {X_MAX} after "
            f"{xs.index(X_MAX) + 1} frames, then {sorted(set(xs[49:]))} for 20 more")

        # left
        xs = [frame(BITS["left"])[0]] + [frame()[0] for _ in range(117)]
        want = [max(X_MAX - SPEED * (i + 1), X_MIN) for i in range(118)]
        rep("left", xs == want, f"-{SPEED} a frame from {X_MAX}: reaches {X_MIN} after "
            f"{xs.index(X_MIN) + 1} frames (design: 98), then {sorted(set(xs[98:]))} for 20 more")

        # stop
        xs = [frame(BITS["right"])[0]] + [frame()[0] for _ in range(4)]
        after = [frame(0)[0]] + [frame()[0] for _ in range(4)]
        rep("stop", xs == [X_MIN + SPEED * (i + 1) for i in range(5)] and after == [xs[-1]] * 5,
            f"right 5 frames {xs}, released: {after}")

        # left+right
        x0 = after[-1]
        xs = [frame(BITS["left"] | BITS["right"])[0]] + [frame()[0] for _ in range(9)]
        frame(0)
        rep("left+right", xs == [x0] * 10, f"both held 10 frames: X {sorted(set(xs))} (was {x0})")

        # Stage 1's shot cases want shots that hit nothing: take the enemies away (monitor).
        def empty_sky():
            mon.mem_set(sym["enemy_state"], bytes([ENEMY_DEAD] * ENEMIES))
            mon.mem_set(sym["mux_y"] + ENEMY0, bytes([MUX_OFF] * ENEMIES))
            mon.mem_set(sym["explosion_enemy"], bytes([0xFF] * 4))
            mon.mem_set(sym["zp_clear_timer"], bytes([0]))

        def respawn():
            """The game's own path back to a full formation: the pause timer's last frame."""
            settle()
            mon.mem_set(sym["zp_clear_timer"], bytes([1]))
            frame()

        empty_sky()

        # fire-hold
        px = settle()
        hist = [frame(BITS["fire"])] + [frame() for _ in range(199)]
        spawns, lives, errs = [], [], []
        born = [None, None]
        for f, (x, shots) in enumerate(hist):
            pv = hist[f - 1][1] if f else [None, None]
            for i in range(2):
                moved = pv[i] and (pv[i][0], pv[i][1] - SHOT_SPEED)
                if pv[i] and shots[i] != moved:         # removed (the slot may be fired from in the same frame)
                    lives.append(f - born[i])
                    if moved[1] >= SHOT_KILL:
                        errs.append(f"frame {f}: removed early from Y {pv[i][1]}")
                    if pv[i][1] != 53:
                        errs.append(f"frame {f}: last seen at Y {pv[i][1]}")
                if shots[i] and shots[i] != moved:      # spawned
                    spawns.append(f)
                    born[i] = f
                    if shots[i] != (px, SHOT_Y0):
                        errs.append(f"frame {f}: spawned at {shots[i]}")
            if x != px:
                errs.append(f"frame {f}: player moved")
        gaps = [b - a for a, b in zip(spawns, spawns[1:])]
        ok = (not errs and min(gaps) >= COOLDOWN and set(lives) == {21} and spawns[0] == 0
              and spawns[:5] == [0, 10, 21, 31, 42])
        rep("fire-hold", ok, f"200 frames: {len(spawns)} shots, never more than 2 in flight; spawn frames "
            f"{spawns[:8]}...; gaps {sorted(set(gaps))} (cooldown {COOLDOWN}); each shot lives {sorted(set(lives))} "
            f"frames, Y {SHOT_Y0} down to 53 by {SHOT_SPEED}; errors: {errs[:3] or 'none'}; "
            f"rate {(len(spawns) - 1) * 50 / (spawns[-1] - spawns[0]):.2f} a second (design feel target 2 says 5)")

        # fire-move
        px = settle()
        hist = [frame(BITS["fire"] | BITS["right"])] + [frame() for _ in range(39)]
        errs, n = [], 0
        for f, (x, shots) in enumerate(hist):
            pv = hist[f - 1][1] if f else [None, None]
            for i in range(2):
                moved = pv[i] and (pv[i][0], pv[i][1] - SHOT_SPEED)
                if shots[i] and shots[i] != moved:      # spawned
                    n += 1
                    if shots[i] != (x, SHOT_Y0):
                        errs.append(f"frame {f}: player X {x}, shot {shots[i]}")
        rep("fire-move", not errs and n >= 3, f"fire + right 40 frames: {n} shots, each spawned at the player's X "
            f"that frame (X {hist[0][0]} -> {hist[-1][0]}) and kept it; errors: {errs[:3] or 'none'}")

        # cooldown: remove every shot the frame after it spawns, so only the cooldown limits the rate
        settle()
        spawns = []
        frame(BITS["fire"])
        for f in range(100):
            ys = mem(sym["mux_y"] + 4, 2)
            if any(y == SHOT_Y0 for y in ys):
                spawns.append(f)
            mon.mem_set(sym["mux_y"] + 4, bytes([MUX_OFF, MUX_OFF]))
            frame()
        gaps = [b - a for a, b in zip(spawns, spawns[1:])]
        rep("cooldown", set(gaps) == {COOLDOWN} and len(spawns) == 10,
            f"a slot always free, fire held 100 frames: {len(spawns)} shots, gaps {sorted(set(gaps))}")

        # fire-tap
        settle()
        t = [frame(BITS["fire"]), frame(0)] + [frame() for _ in range(3)]
        n1 = sum(1 for s in t[-1][1] if s)
        t2 = [frame(BITS["fire"]), frame(0)] + [frame() for _ in range(3)]       # 5 frames after the first
        n2 = sum(1 for s in t2[-1][1] if s)
        t3 = [frame(BITS["fire"]), frame(0)]                                      # 10 frames after the first
        n3 = sum(1 for s in t3[-1][1] if s)
        rep("fire-tap", (n1, n2, n3) == (1, 1, 2) and t[0][1][0] == (t[0][0], SHOT_Y0),
            f"1-frame press: {n1} shot; again 5 frames later: {n2} in flight (cooldown); at 10 frames: {n3}")


        # ---------------------------------------------------------------- collisions (part B)
        def estates():
            return list(mem(sym["enemy_state"], ENEMIES))

        def score():
            return int(mem(sym["game_score"], 3).hex())

        def panel_score():
            return "".join(chr(c - PANEL_BG) for c in mem(SCREEN + 960 + 7, 6))

        def predict(n):
            """fx after n more formation_update calls (the drift exactly as formation.asm steps it)."""
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

        def aim(cons, chase=False, x0=None, limit=900):
            """Press fire in the frame that makes every constraint true; returns the shot's X.

            cons: (k, column, lo, hi[, xe_lo, xe_hi]): k frames after the fire frame, the shot's X
            minus that column's enemy X is in lo..hi (and the enemy's X in xe_lo..xe_hi). Until
            then: walk to x0 if given and wait there, or (chase) steer towards the middle of the
            constraints with the stick.
            On return the machine is stopped in the fire frame (the shot is at Y 213), fire down.
            """
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

        def epos(e):
            return (mem(sym["mux_x_lo"] + ENEMY0 + e)[0] + 256 * mem(sym["mux_x_hi"] + ENEMY0 + e)[0],
                    mem(sym["mux_y"] + ENEMY0 + e)[0])

        def kill(e, lo=-4, hi=4):
            """Shoot enemy e (the enemies below it in its column must be dead). Returns the errors."""
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

        respawn()
        fx, fdir, en = enemies()
        if estates() != [ENEMY_PARKED] * ENEMIES or fx != FX_START or score() != 0:
            raise MeasureError(f"the formation didn't come back for the collision cases: fx {fx}, score {score()}")
        ct = mem(sym["colour_table"], 19)
        hi0 = mem(sym["game_hiscore"], 3).hex()

        # hit: the whole life of one hit, on enemy 15 (row 2, column 3)
        e, errs, shapes = 15, [], []
        x = aim([(8, 3, -1, 1)], chase=True)
        frame(0)
        for i in range(1, 8):
            xx, shots = frame() if i > 1 else state()
            if estates() != [ENEMY_PARKED] * ENEMIES or (x, SHOT_Y0 - 8 * i) not in shots or score() != 0:
                errs.append(f"frame f + {i}: something happened early ({shots})")
        home_then = None
        xx, shots = frame()                                      # frame f + 8
        hit_pos = epos(e)
        fxh = mem(sym["zp_fx"])[0]
        dirty = mem(sym["panel_dirty"])[0]
        ok0 = (estates()[e] == ENEMY_EXPLODING and mem(sym["enemy_timer"] + e)[0] == EXPLOSION_FRAMES
               and shots == [None, None] and score() == 50 and dirty & PANEL_DIRTY_SCORE
               and hit_pos == home(fxh)[e] and abs(hit_pos[0] - x) <= 1 and panel_score() == "000000"
               and mem(sym["mux_ptr"] + ENEMY0 + e)[0] == SHAPE_EXPLOSION
               and mem(sym["mux_col"] + ENEMY0 + e)[0] & 15 == ct[10] == ORANGE)
        if not ok0:
            errs.append(f"frame f + 8: state {estates()[e]:#x}, timer {mem(sym['enemy_timer'] + e)[0]}, shots {shots}, "
                        f"score {score()}, dirty {dirty}, at {hit_pos} (home {home(fxh)[e]}, shot X {x})")
        shapes.append(mem(sym["mux_ptr"] + ENEMY0 + e)[0])
        moved = set()
        for i in range(1, EXPLOSION_FRAMES):
            frame()
            fx, fdir, en = enemies()
            moved.add(fx)
            shapes.append(en[e][2])
            if i == 1 and panel_score() != "000050":
                errs.append(f"panel one frame after the hit: {panel_score()}")
            if (estates()[e] != ENEMY_EXPLODING or en[e][:2] != hit_pos or en[e][3] != ORANGE
                    or any(en[j][:2] != home(fx)[j] for j in range(ENEMIES) if j != e)):
                errs.append(f"explosion frame {i}: state {estates()[e]:#x}, at {en[e][:2]}, colour {en[e][3]}")
        alive_before = mem(sym["zp_enemies_alive"])[0]
        frame()
        ok1 = (estates()[e] == ENEMY_DEAD and epos(e)[1] == MUX_OFF and alive_before == ENEMIES
               and mem(sym["zp_enemies_alive"])[0] == ENEMIES - 1 and estates().count(ENEMY_PARKED) == ENEMIES - 1
               and list(mem(sym["explosion_enemy"], 4)) == [0xFF] * 4 and mem(sym["game_hiscore"], 3).hex() == hi0)
        want_shapes = [SHAPE_EXPLOSION + i // 4 for i in range(EXPLOSION_FRAMES)]
        rep("hit", not errs and ok1 and shapes == want_shapes and len(moved) > 4,
            f"shot at X {x} under enemy {e} (row 2, column 3): untouched to frame f + 7; in f + 8 Exploding at "
            f"{hit_pos} (its home, X - Xe = {x - hit_pos[0]}), timer 16, orange, shot slot free, score 50, panel dirty; "
            f"panel {panel_score()} from the next frame; shapes over 16 frames {[hex(p)[2:] for p in shapes]}, "
            f"stationary while fx went {min(moved)}-{max(moved)}; frame 17: Dead and hidden {ok1}, alive "
            f"{mem(sym['zp_enemies_alive'])[0]}, high score {hi0}; errors: {errs[:3] or 'none'}")

        # gap: between columns 0 and 1
        s0, st0 = score(), estates()
        x = aim([(8, 0, 17, 19)], x0=(FORM_X0 + FX_START + COL_DX // 2) // 3 * 3)
        life, offs = 1, []
        for i in range(1, 30):
            xx, shots = frame(0)
            if (x, SHOT_Y0 - 8 * i) not in shots:
                break
            life += 1
            if i in (8, 13, 18):
                offs.append(x - epos((2 - (8, 13, 18).index(i)) * COLS)[0])
        rep("gap", life == 21 and estates() == st0 and score() == s0 and all(HIT_DX < o < COL_DX - HIT_DX for o in offs),
            f"shot at X {x}: {offs} pixels right of column 0 in rows 2, 1, 0 (a hit needs <= {HIT_DX}, column 1 is "
            f"{COL_DX} away); lived {life} frames, states unchanged: {estates() == st0}, score {score()}")

        # edges: (name, enemy, offset, hit expected, player X to stand at, enemy X range)
        edge_cases = [("edge-left-out", 12, -9, False, None, None), ("edge-left-in", 12, -8, True, None, None),
                      ("edge-right-out", 13, 9, False, None, None), ("edge-right-in", 13, 8, True, None, None),
                      ("edge-left-out-x256", 17, -9, False, 252, (258, 262)),
                      ("edge-left-in-x256", 17, -8, True, 252, (258, 262)),
                      ("edge-right-out-x256", 11, 9, False, 288, (256, 400)),
                      ("edge-right-in-x256", 11, 8, True, 288, (256, 400))]
        for name, e, off, want_hit, x0, xr in edge_cases:
            row, col = divmod(e, COLS)
            k = FLIGHT[row]
            if x0 is None:
                x0 = (FORM_X0 + FX_START + COL_DX * col + off) // 3 * 3
            s0 = score()
            x = aim([(k, col, off, off) + (xr or ())], x0=x0)
            frame(0)
            for _ in range(k - 2):
                frame()
            st_before, shots_before = estates()[e], state()[1]
            xx, shots = frame()                                  # frame f + k: the first frame of overlap in Y
            xe, st = epos(e)[0], estates()[e]
            if want_hit:
                ok = (st_before == ENEMY_PARKED and st == ENEMY_EXPLODING and shots == [None, None]
                      and score() == s0 + ROW_SCORE[row] and x - xe == off)
            else:
                ok = (st == ENEMY_PARKED and (x, SHOT_Y0 - 8 * k) in shots and score() == s0 and x - xe == off
                      and estates().count(ENEMY_EXPLODING) == 0)
                mon.mem_set(sym["mux_y"] + 4, bytes([MUX_OFF, MUX_OFF]))    # take the missed shot away
            rep(name, ok, f"enemy {e} (row {row}, column {col}) at X {xe}, shot at X {x}, Y {SHOT_Y0 - 8 * k} in frame "
                f"f + {k}: X - Xe = {x - xe} ({'inside' if want_hit else 'outside'} by one pixel: boxes "
                f"{x + 11}-{x + 12} and {xe + 4}-{xe + 19}); state {st_before:#x} -> {st:#x}, shots {shots}, "
                f"score {s0} -> {score()}")
            for _ in range(EXPLOSION_FRAMES + 1):
                frame()

        # exploding: the second of two shots meets the first one's explosion and carries on
        s0, errs = score(), []
        x = aim([(8, 2, -6, 6), (23, 2, -6, 6)], chase=True)
        for i in range(1, 9):
            frame()                                              # fire stays held: a second shot at f + 10
        ok_a = estates()[14] == ENEMY_EXPLODING and score() == s0 + 50
        boom = epos(14)
        frame()
        xx, shots = frame()                                      # f + 10
        if (x, SHOT_Y0) not in shots:
            errs.append(f"no second shot at f + 10: {shots}")
        frame(0)
        inside = []
        for i in range(12, 23):
            xx, shots = frame()
            live = [q for q in shots if q]
            if len(live) != 1 or estates()[8] != ENEMY_PARKED:
                errs.append(f"frame f + {i}: shots {shots}, enemy 8 state {estates()[8]:#x}")
                continue
            sy = live[0][1]
            if (estates()[14] == ENEMY_EXPLODING and abs(x - boom[0]) <= HIT_DX
                    and sy <= boom[1] + 17 and sy + 7 >= boom[1] + 3):
                inside.append(i)
        xx, shots = frame()                                      # f + 23
        ok_b = estates()[8] == ENEMY_EXPLODING and shots == [None, None] and score() == s0 + 130
        rep("exploding", ok_a and ok_b and not errs and len(inside) >= 2,
            f"column 2, shots at X {x} fired at f and f + 10: enemy 14 (row 2) Exploding in f + 8 (+ 50: {ok_a}); the "
            f"second shot was inside the explosion's box (at {boom}) in frames f + {inside} and wasn't stopped; "
            f"enemy 8 (row 1) Exploding in f + 23, score {s0} -> {score()} (+ 50 + 80); errors: {errs[:3] or 'none'}")
        for _ in range(EXPLOSION_FRAMES + 1):
            frame()

        # dead: through two dead enemies to row 0
        s0, st0 = score(), estates()
        x = aim([(18, 2, -4, 4), (8, 2, -HIT_DX, HIT_DX), (13, 2, -HIT_DX, HIT_DX)], chase=True)
        frame(0)
        through = []
        for i in range(2, 18):
            xx, shots = frame()
            if i in (8, 13):
                through.append(((x, SHOT_Y0 - 8 * i) in shots, x - home(mem(sym["zp_fx"])[0])[2][0]))
        early = estates()[2]
        frame()                                                  # f + 18
        ok = (st0[14] == st0[8] == ENEMY_DEAD and all(t[0] and abs(t[1]) <= HIT_DX for t in through)
              and early == ENEMY_PARKED and estates()[2] == ENEMY_EXPLODING and score() == s0 + 150)
        rep("dead", ok, f"column 2 with rows 2 and 1 Dead: shot at X {x} still flying in f + 8 and f + 13, "
            f"{[t[1] for t in through]} pixels from where those enemies would be (inside their boxes); enemy 2 (row 0) "
            f"Exploding in f + 18, score {s0} -> {score()} (+ 150)")
        for _ in range(EXPLOSION_FRAMES + 1):
            frame()

        # double: two shots hit in the same frame (enemy 5, row 0 column 5; enemy 16, row 2 column 4)
        s0, st0 = score(), estates()
        x = aim([(18, 5, -4, -2)], x0=(FORM_X0 + FX_START + COL_DX * 5) // 3 * 3)
        for i in range(1, 10):
            frame(BITS["left"])
        xb, shots = frame(BITS["left"] | BITS["fire"])           # f + 10: the second shot, 30 pixels left
        spawned = (xb, SHOT_Y0) in shots and xb == x - 30
        frame(0)
        for i in range(12, 18):
            frame()
        before = estates()
        slots_before = sum(1 for q in mem(sym["explosion_enemy"], 4) if q != 0xFF)
        xx, shots = frame()                                      # f + 18
        after = estates()
        slots = sorted(q for q in mem(sym["explosion_enemy"], 4) if q != 0xFF)
        ok = (st0[17] == st0[11] == ENEMY_DEAD and spawned and before[5] == before[16] == ENEMY_PARKED
              and after[5] == after[16] == ENEMY_EXPLODING and shots == [None, None] and score() == s0 + 200
              and slots_before == 0 and slots == [5, 16])
        frame()
        rep("double", ok and panel_score() == f"{s0 + 200:06d}",
            f"shots at X {x} (frame f) and X {xb} (f + 10): in f + 17 enemies 5 and 16 are Parked, in f + 18 both are "
            f"Exploding ({after[5]:#x}, {after[16]:#x}), both shot slots free, explosion slots {slots}, score {s0} -> "
            f"{score()} (+ 150 + 50), panel {panel_score()}")
        for _ in range(EXPLOSION_FRAMES + 1):
            frame()

        # clear: shoot everything that is left, from the bottom of each column up
        errs, shot_down = [], 0
        for col in range(COLS):
            for row in (2, 1, 0):
                e = row * COLS + col
                if estates()[e] == ENEMY_PARKED:
                    errs += kill(e)
                    shot_down += 1
        final = score()
        waited = 0
        while mem(sym["zp_enemies_alive"])[0] and waited < 40:
            frame()
            waited += 1
        fx, fdir, en = enemies()
        gone = (estates() == [ENEMY_DEAD] * ENEMIES and all(q[1] == MUX_OFF for q in en)
                and mem(sym["zp_clear_timer"])[0] == CLEAR_PAUSE)
        empty = 0
        for i in range(1, CLEAR_PAUSE):
            frame()
            fx, fdir, en = enemies()
            empty += all(q[1] == MUX_OFF for q in en) and estates() == [ENEMY_DEAD] * ENEMIES
        frame()                                                  # the 75th frame after the last one went
        fx, fdir, en = enemies()
        row = "".join(chr((c & 63) + 64) if (c & 63) < 27 else chr(c & 63) for c in mem(SCREEN + 960, 34))
        back = (estates() == [ENEMY_PARKED] * ENEMIES and [q[:2] for q in en] == home(FX_START) and fx == FX_START
                and fdir == 1 and mem(sym["zp_enemies_alive"])[0] == ENEMIES
                and [q[3] for q in en] == [ENEMY_COLOURS[j // COLS] for j in range(ENEMIES)]
                and all(q[2] - SHAPE_ENEMY - 2 * (j // COLS) in (0, 1) for j, q in enumerate(en)))
        frame()
        fx2 = mem(sym["zp_fx"])[0]
        rep("clear", not errs and final == 1680 and gone and empty == CLEAR_PAUSE - 1 and back and score() == final
            and row == " SCORE 001680  HI 005000  WAVE 01 " and mem(sym["zp_clear_timer"])[0] == 0 and fx2 == FX_START + 1,
            f"{shot_down} more enemies shot, each for its row's value (errors: {errs[:3] or 'none'}); score {final} "
            f"(6 x 280 = 1680); when the last explosion ended: all Dead and hidden, pause timer {CLEAR_PAUSE}: {gone}; sky "
            f"empty for the next {empty} frames; in frame {CLEAR_PAUSE} all 18 Parked at their homes for fx {fx} in their "
            f"colours: {back}; fx {fx2} a frame later; panel '{row}' (no bonus, wave and high score unchanged)")

        # score-cap
        mon.mem_set(sym["game_score"], bytes([0x99, 0x99, 0x60]))
        errs = kill(12)
        capped = mem(sym["game_score"], 3).hex()
        frame()
        rep("score-cap", capped == "999990" and panel_score() == "999990",
            f"score set to 999960, a 50-point enemy shot: {capped}, panel {panel_score()} (the design stops at 999990)")

        # no-drop: the player sweeping and two shots crossing the rows, enemies being shot away
        respawn()
        debug = [(k, n) for k, n in DEBUG_COUNTERS if k in sym]
        stick, errs, drops, most = BITS["right"] | BITS["fire"], [], 0, 0
        killed, respawns, prev_alive, fewest = set(), 0, ENEMIES, ENEMIES
        x, shots = frame(stick)
        for f in range(600):
            if x >= X_MAX:
                stick = BITS["left"] | BITS["fire"]
            elif x <= X_MIN:
                stick = BITS["right"] | BITS["fire"]
            x, shots = frame(stick)
            fx, fdir, en = enemies()
            st = estates()
            killed |= {j for j in range(ENEMIES) if st[j] != ENEMY_PARKED}
            respawns += prev_alive < ENEMIES == st.count(ENEMY_PARKED)
            prev_alive = st.count(ENEMY_PARKED)
            fewest = min(fewest, prev_alive)
            for j in range(ENEMIES):
                if st[j] == ENEMY_PARKED and en[j][:2] != home(fx)[j]:
                    errs.append(f"frame {f}: enemy {j} not at home")
                elif st[j] == ENEMY_DEAD and en[j][1] != MUX_OFF:
                    errs.append(f"frame {f}: dead enemy {j} shown")
                elif st[j] not in (ENEMY_PARKED, ENEMY_DEAD, ENEMY_EXPLODING):
                    errs.append(f"frame {f}: enemy {j} state {st[j]:#x}")
            most = max(most, 1 + sum(1 for q in en if q[1] != MUX_OFF) + sum(1 for q in shots if q))
            if "mux_drop_count" in sym and mem(sym["mux_drop_count"])[0]:   # the previous frame's mux_update
                drops += 1
        frame(0)
        counts = {k: int.from_bytes(mem(sym[k], n), "little") for k, n in debug}
        rep("no-drop", not errs and drops == 0 and not any(counts.values()) and most <= 21 and len(killed) >= 6,
            f"600 frames, player sweeping {X_MIN}-{X_MAX} with fire held, up to {most} sprites shown, {len(killed)} "
            f"different enemies shot (fewest Parked at once: {fewest}), the formation came back {respawns} times: every Parked enemy at its home, every "
            f"other Exploding or Dead and hidden, in every frame (errors: {errs[:3] or 'none'}); "
            + (f"frames with mux_drop_count != 0: {drops}; " + ", ".join(f"{k} {c}" for k, c in counts.items())
               if debug else "no DEBUG counters in this build: drops not measured"))

        # sprites: what the multiplexer put in the hardware registers, read at line 251 (chain
        # entry 1), when the zone IRQs have written every slot: the 8 hardware sprites then hold
        # the last 8 in Y order, the player among them. Two idle frames first: the registers show
        # the positions the main loop wrote the frame before.
        respawn()                                 # a full formation again
        x = settle()
        frame()
        frame()
        fx = mem(sym["zp_fx"])[0]
        cp2 = mon.checkpoint_set(sym["game_irq_bottom"], sym["game_irq_bottom"], CPU_OP_EXEC)
        mon.exit()
        if not mon.wait_stopped(STOP_TIMEOUT):
            mon.ping()
            raise MeasureError("game_irq_bottom not reached")
        mon.checkpoint_delete(cp2.number)
        d = mem(0xD000, 0x30)
        ptrs = mem(SCREEN + 0x3F8, 8)
        hw = [(d[2 * i] + 256 * ((d[0x10] >> i) & 1), d[2 * i + 1], d[0x27 + i] & 15, ptrs[i]) for i in range(8)
              if d[0x15] >> i & 1]
        players = [q for q in hw if q[1] == PLAYER_Y]
        others = [q for q in hw if q[1] != PLAYER_Y]
        okx = {FORM_X0 + f + COL_DX * c for f in (fx - 1, fx, fx + 1) for c in range(COLS)}
        good = [q for q in others if q[1] in ROW_Y and q[2] == ENEMY_COLOURS[ROW_Y.index(q[1])] and q[0] in okx
                and q[3] - SHAPE_ENEMY - 2 * ROW_Y.index(q[1]) in (0, 1)]
        ok = (len(hw) == 8 and len(players) == 1 and players[0][0] == x and players[0][2:] == (ct[3], 0xC0)
              and len(good) == 7 and d[0x17] == 0 and d[0x1D] == 0 and d[0x1C] == 0)
        rep("sprites", ok, f"at line 251: {len(hw)} hardware sprites on; the player: X, Y, colour, pointer "
            f"{[(q[0], q[1], q[2], hex(q[3])) for q in players]} (player X {x}); the other {len(others)}: "
            f"{len(good)} are enemies in their row's Y, colour and shape (Y {sorted({q[1] for q in others})}); "
            f"$D017/$D01D/$D01C = {d[0x17]}/{d[0x1D]}/{d[0x1C]}")
        frame()


        # ================================================================ stage 3
        GS_PLAY, GS_RESPAWN, GS_DYING, GS_OVER = 0, 1, 2, 3
        ESHOT0, SHAPE_ESHOT, ESHOT_HIT_Y, ESHOT_HIT_DX = 1, 0xC2, 207, 6
        PANEL_DIRTY_LIVES, PANEL_DIRTY_HI = 2, 8
        MSG = SCREEN + 12 * 40

        def poke(label, data, off=0):
            mon.mem_set(sym[label] + off, bytes(data))

        def peek(label, off=0):
            return mem(sym[label] + off)[0]

        def eshots():
            ys, xl, xh = mem(sym["mux_y"] + ESHOT0, 3), mem(sym["mux_x_lo"] + ESHOT0, 3), mem(sym["mux_x_hi"] + ESHOT0, 3)
            return [None if ys[i] == MUX_OFF else (xl[i] + 256 * xh[i], ys[i]) for i in range(3)]

        def put_eshot(i, x, y, dx=0):
            """Place enemy shot i through the monitor (as a diver's fire step would leave it)."""
            poke("mux_x_lo", [x & 255], ESHOT0 + i)
            poke("mux_x_hi", [x >> 8], ESHOT0 + i)
            poke("mux_y", [y], ESHOT0 + i)
            poke("eshot_dx", [dx & 255], i)

        def clear_eshots():
            poke("mux_y", [MUX_OFF] * 3, ESHOT0)

        def gstate():
            return peek("zp_game_state"), peek("zp_state_timer")

        def ship():
            """The ship's multiplexer entry: (X, Y, shape, colour)."""
            return (peek("mux_x_lo") + 256 * peek("mux_x_hi"), peek("mux_y"), peek("mux_ptr"), peek("mux_col") & 15)

        def msg():
            """Row 12 as text, 40 characters; the cells outside the star-free band (columns 10-29) as spaces."""
            return "".join(" " if i not in BAND_COLS else chr((c & 63) + 64) if 0 < (c & 63) < 27 else chr(c & 63)
                           for i, c in enumerate(mem(MSG, 40)))

        def walk_to(x0):
            x = state()[0]
            for _ in range(120):
                if x == x0:
                    frame(0)
                    return
                x = frame(BITS["right"] if x < x0 else BITS["left"])[0]
            raise MeasureError(f"walk_to({x0}): at {x}")

        def revive():
            """After a death: lives back to 3 (monitor), then the game's own PlayerDying and Respawn,
            with the invulnerability taken away (monitor) once Play is back. Returns frames waited."""
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

        respawn()
        ct = mem(sym["colour_table"], 19)

        # eshot-move: placed shots move Y + 2 and X + dx, are removed when Y > 221, and clamp at 0 / 344
        walk_to(X_MIN)
        put_eshot(0, 200, 101, 0)
        put_eshot(1, 254, 100, 1)
        put_eshot(2, 257, 100, -1)
        errs, last = [], [None] * 3
        for k in range(1, 63):
            frame()
            got = eshots()
            want = [(200, 101 + 2 * k) if 101 + 2 * k <= 221 else None,
                    (254 + k, 100 + 2 * k) if 100 + 2 * k <= 221 else None,
                    (257 - k, 100 + 2 * k) if 100 + 2 * k <= 221 else None]
            if got != want:
                errs.append(f"frame {k}: {got}, expected {want}")
            last = [g[1] if g else last[i] for i, g in enumerate(got)]
        look = (list(mem(sym["mux_ptr"] + ESHOT0, 3)), [c & 15 for c in mem(sym["mux_col"] + ESHOT0, 3)],
                list(mem(sym["mux_flags"] + ESHOT0, 3)))
        put_eshot(0, 343, 100, 1)
        put_eshot(1, 1, 100, -1)
        put_eshot(2, 300, 100, 0)
        clamp = []
        for k in range(1, 5):
            frame()
            clamp.append(eshots())
        okc = ([c[0][0] for c in clamp] == [344] * 4 and [c[1][0] for c in clamp] == [0] * 4
               and [c[2] for c in clamp] == [(300, 100 + 2 * k) for k in range(1, 5)])
        clear_eshots()
        poke("zp_loop", [2])
        put_eshot(0, 200, 100, 1)
        fast = [(frame(), eshots()[0])[1] for _ in range(3)]
        poke("zp_loop", [0])
        clear_eshots()
        frame()
        rep("eshot-move", not errs and last == [221, 220, 220] and look == ([SHAPE_ESHOT] * 3, [ct[9]] * 3, [0x80] * 3)
            and ct[9] == 10 and okc and fast == [(201, 103), (202, 106), (203, 109)] and gstate()[0] == GS_PLAY,
            f"three placed shots, dx 0 / + 1 / - 1: Y + 2 and X + dx every frame (X through 255/256 both ways), last "
            f"seen at Y {last}, removed when Y > 221; shape {hex(look[0][0])}, colour {look[1][0]} (light red), pinned "
            f"{look[2] == [0x80] * 3}; clamp: X 343 + 1 -> {[c[0][0] for c in clamp]}, X 1 - 1 -> {[c[1][0] for c in clamp]} "
            f"(the design's 0-344); zp_loop 2: {fast} (Y + 3); errors: {errs[:2] or 'none'}")

        # eshot-edge-*: the player's box (columns 6-17) against a shot's (11-12): a hit when |shot X - ship X| <= 6,
        # and only from shot Y 207 (rows 14-20 against the ship's 6-20 at Y 221)
        def shot_case(name, px, off, y0, frames_, want):
            """Ship at px, shot placed at (px + off, y0) with dx 0: `want` = the frame (1-based) of the hit, or None."""
            walk_to(px)
            lives0 = peek("zp_lives")
            put_eshot(0, px + off, y0, 0)
            seen = None
            for k in range(1, frames_ + 1):
                frame()
                if gstate()[0] == GS_DYING and seen is None:
                    seen = k
            sh = eshots()[0]
            ok = seen == want and peek("zp_lives") == lives0 - (1 if want else 0)
            if want is None:
                ok = ok and sh == (px + off, y0 + 2 * frames_)
            rep(name, ok, f"ship at X {px} (box {px + 6}-{px + 17}, lines 227-241), shot placed at ({px + off}, {y0}) (box "
                f"{px + off + 11}-{px + off + 12}): after {frames_} frame(s) " + (f"hit in frame {seen} at Y {y0 + 2 * seen} "
                f"(lines {y0 + 2 * seen + 14}-{y0 + 2 * seen + 20})" if seen else f"no hit, shot at {sh}") +
                f"; expected {'a hit in frame ' + str(want) if want else 'no hit'}; lives {lives0} -> {peek('zp_lives')}")
            clear_eshots()
            if seen:
                revive()

        shot_case("eshot-edge-left-out", X_START, -7, 209, 6, None)
        shot_case("eshot-edge-left-in", X_START, -6, 209, 1, 1)
        shot_case("eshot-edge-right-out", 252, 7, 209, 6, None)
        shot_case("eshot-edge-right-in", 252, 6, 209, 1, 1)
        shot_case("eshot-edge-right-in-x256", 300, 6, 209, 1, 1)
        shot_case("eshot-y-guard-206", X_START, 0, 202, 2, None)       # Y 204, 206: above the ship's box
        shot_case("eshot-y-207", X_START, 0, 205, 1, 1)                 # Y 207: the first line of overlap
        shot_case("eshot-y-206-then-208", X_START, 0, 204, 2, 2)        # Y 206 misses, 208 hits a frame later
        shot_case("eshot-y-221", X_START, 6, 219, 1, 1)                 # the last Y a shot is shown at

        # death: the player's death, frame by frame
        walk_to(X_START + 30)
        px = settle()
        frame(BITS["fire"])                                   # a player shot in flight when the hit comes
        frame(0)
        for _ in range(3):
            frame()
        pshot0 = [q for q in state()[1] if q][0]
        hi0, lives0 = mem(sym["game_hiscore"], 3).hex(), peek("zp_lives")
        put_eshot(1, px, 205, 0)                              # this one hits
        put_eshot(0, 40, 100, 1)                              # these two are in flight elsewhere
        put_eshot(2, 300, 150, -1)
        errs = []
        x, shots = frame(BITS["right"] | BITS["fire"])        # frame H = frame 0 of PlayerDying; stick held from here
        gs0, dirty = gstate(), peek("panel_dirty")
        row0 = list(mem(SCREEN + 960 + 35, 3))
        if not (gs0 == (GS_DYING, 0) and peek("zp_lives") == lives0 - 1 == 2 and dirty & PANEL_DIRTY_LIVES
                and eshots() == [None] * 3 and ship() == (px, PLAYER_Y, SHAPE_EXPLOSION, ct[11]) and ct[11] == 1
                and x == px and shots.count(None) == 1 and (pshot0[0], pshot0[1] - SHOT_SPEED) in shots
                and row0 == [SHIP + PANEL_BG, SHIP + PANEL_BG, SPACE + PANEL_BG]):
            errs.append(f"frame 0: state {gs0}, lives {peek('zp_lives')}, dirty {dirty}, enemy shots {eshots()}, ship {ship()}, "
                        f"player X {x}, shots {shots}, markers {row0}")
        shapes, hidden_at, pshot_life, respawn_at = [ship()[2]], None, 1, None
        for k in range(1, 100):
            x, shots = frame()
            sp, gs = ship(), gstate()
            if k == 1 and list(mem(SCREEN + 960 + 35, 3)) != [SHIP + PANEL_BG, SPACE + PANEL_BG, SPACE + PANEL_BG]:
                errs.append(f"frame 1: markers {list(mem(SCREEN + 960 + 35, 3))}")
            if k < 32:
                shapes.append(sp[2])
                if sp[:2] != (px, PLAYER_Y) or sp[3] != ct[11]:
                    errs.append(f"frame {k}: ship {sp}")
            elif sp[1] != MUX_OFF:
                errs.append(f"frame {k}: ship not hidden {sp}")
            elif hidden_at is None:
                hidden_at = k
            if any(shots) and (pshot0[0], pshot0[1] - SHOT_SPEED * (k + 1)) in shots:
                pshot_life = k + 1
            if sum(1 for q in shots if q) > (1 if pshot_life == k + 1 else 0) or x != px:
                errs.append(f"frame {k}: the dead ship moved or fired: X {x}, shots {shots}")
            if gs != (GS_DYING, k):
                errs.append(f"frame {k}: state {gs}")
            if k == 50:
                frame_stick = mon.joyport_set(PORT2, 0x1F)       # release before the ship comes back
        want_shapes = [SHAPE_EXPLOSION + k // 8 for k in range(32)]
        ok_death = not errs and shapes == want_shapes and hidden_at == 32
        rep("death", ok_death,
            f"hit at ship X {px} with right + fire held from the hit's frame: frame 0 PlayerDying, lives {lives0} -> "
            f"{lives0 - 1}, all 3 enemy shots removed, markers redrawn in frame 1, white explosion at the ship's X, shapes "
            f"{[hex(p)[2:] for p in shapes[::8]]} 8 frames each: {shapes == want_shapes}; hidden from frame {hidden_at} "
            f"(design: 32); the player shot in flight carried on ({pshot_life} more frames to Y 53); no move, no new shot; "
            f"state PlayerDying with its timer = the frame number through frame 99; errors: {errs[:3] or 'none'}")

        # respawn: frame 100 (no diver out): READY, the ship back at 171, controllable, invulnerable for exactly 150
        errs = []
        x, shots = frame()                                    # frame 100 of PlayerDying = frame 0 of Respawn (R)
        if not (gstate() == (GS_RESPAWN, 0) and x == X_START and ship()[:3] == (X_START, PLAYER_Y, 0xC0)
                and msg()[17:22] == "READY" and msg().strip() == "READY" and peek("zp_player_invuln") == 149):
            errs.append(f"frame R: state {gstate()}, ship {ship()}, row 12 '{msg().strip()}', invuln {peek('zp_player_invuln')}")
        cols, xs, ready_frames, play_at, launch_at_play, n_shots = [ship()[3]], [x], 1, None, None, 0
        through = []
        for k in range(1, 152):
            stick = None
            if k == 5:
                stick = BITS["right"]
            if k == 15:
                stick = BITS["fire"]
            if k == 17:
                stick = 0
            if k == 60:
                put_eshot(0, x, 199, 0)                       # falls through the invulnerable ship (Y 207-221 in R + 63-70)
            if k == 45:
                launcher(True)                                # the game's own timer when Play is entered
            if k == 51:
                launcher(False)
            if k == 148:
                put_eshot(1, x, 207, 0)                       # over the ship in R + 148, 149 (invulnerable) and R + 150
            x, shots = frame(stick)
            gs = gstate()
            xs.append(x)
            n_shots = max(n_shots, sum(1 for q in shots if q))
            if k <= 149:
                cols.append(ship()[3])
            if msg()[17:22] == "READY":
                ready_frames += 1
            if gs[0] == GS_PLAY and play_at is None:
                play_at, launch_at_play = k, peek("zp_launch_timer")
                if msg().strip():
                    errs.append(f"frame R + {k}: Play with row 12 '{msg().strip()}'")
            if 60 < k <= 72:
                through.append(eshots()[0])
            if k < 150 and gs[0] not in (GS_RESPAWN, GS_PLAY):
                errs.append(f"frame R + {k}: state {gs} (hit while invulnerable?)")
            if k == 149 and (gs[0] != GS_PLAY or eshots()[1] != (x, 211) or peek("zp_player_invuln") != 0):
                errs.append(f"frame R + 149: state {gs}, the shot {eshots()[1]}, invuln {peek('zp_player_invuln')}")
            if k == 150 and gs != (GS_DYING, 0):
                errs.append(f"frame R + 150: state {gs}: the first frame the ship can be hit")
        want_cols = [ct[12] if (149 - k) & 4 else ct[3] for k in range(150)]
        moved = xs[5] - xs[4], xs[14] - xs[4]
        ok_thr = through == [(xs[59], 201 + 2 * i) for i in range(1, 11)] + [None, None]
        rep("respawn", not errs and cols == want_cols and ready_frames == 50 and play_at == 50 and moved == (3, 30)
            and n_shots >= 1 and ok_thr and launch_at_play == 49 and (ct[3], ct[12]) == (3, 11),
            f"frame 100 of PlayerDying = Respawn's frame R: ship at X {xs[0]}, READY at columns 17-21; stick right from "
            f"R + 5: X + {moved[0]} in that frame, + {moved[1]} after 10 (controllable during READY), fire at R + 15: "
            f"{n_shots} shot; READY shown {ready_frames} frames, Play in R + {play_at} with the launch timer at "
            f"{launch_at_play} (set to 50, counted once in that frame); colour by frame cyan/dark grey by the timer, 4 frames each: {cols == want_cols} (first 12: "
            f"{cols[:12]}, last 6: {cols[-6:]}); a shot dropped on the ship (Y 207-221 in R + 63-70) passed through to Y 221 and was removed: {ok_thr}; "
            f"a shot over the ship in R + 148 and R + 149 did nothing, the same shot hit in R + 150: invulnerable for "
            f"exactly 150 frames; errors: {errs[:3] or 'none'}")

        # game-over: the last life. The score is put above the high score first (monitor).
        for _ in range(101):
            frame(0)                                          # this death's PlayerDying, then Respawn (lives 1)
        lives_r = peek("zp_lives")
        while gstate()[0] != GS_PLAY:
            frame()
        poke("zp_player_invuln", [0])
        poke("game_score", [0x00, 0x61, 0x50])
        hi_before = mem(sym["game_hiscore"], 3).hex()
        x = state()[0]
        put_eshot(0, x, 205, 0)
        frame(BITS["fire"])                                   # the last hit; fire is held through GameOver's start
        errs = []
        if not (gstate() == (GS_DYING, 0) and peek("zp_lives") == 0 and lives_r == 1):
            errs.append(f"the last hit: state {gstate()}, lives {lives_r} -> {peek('zp_lives')}")
        for k in range(1, 100):
            frame()
            if gstate() != (GS_DYING, k) or mem(sym["game_hiscore"], 3).hex() != hi_before:
                errs.append(f"frame {k}: state {gstate()}, high score {mem(sym['game_hiscore'], 3).hex()}")
        markers = list(mem(SCREEN + 960 + 35, 3))
        frame()                                               # frame 100: GameOver's frame 0 (G)
        hi_after, dirty = mem(sym["game_hiscore"], 3).hex(), peek("panel_dirty")
        if not (gstate() == (GS_OVER, 0) and msg()[15:24] == "GAME OVER" and msg().strip() == "GAME OVER"
                and hi_before == "005000" and hi_after == "006150" and dirty & PANEL_DIRTY_HI
                and markers == [SPACE + PANEL_BG] * 3 and ship()[1] == MUX_OFF):
            errs.append(f"frame G: state {gstate()}, row 12 '{msg().strip()}', high score {hi_before} -> {hi_after}, "
                        f"dirty {dirty}, markers {markers}")
        frame()
        panel_hi = "".join(chr(c - PANEL_BG) for c in mem(SCREEN + 960 + 18, 6))
        for k in range(2, 80):                                # fire still held: not a new press, no skip
            frame()
            if gstate() != (GS_OVER, k):
                errs.append(f"frame G + {k} with fire held since the hit: state {gstate()}")
        frame(0)                                              # G + 80: released
        launcher(True)
        frame(BITS["fire"])                                   # G + 81: a new press
        gs_press = gstate()
        frame()                                               # G + 82: the new game
        fx, fdir, en = enemies()
        new = dict(state=gstate()[0], score=score(), lives=peek("zp_lives"), hi=mem(sym["game_hiscore"], 3).hex(),
                   row12=msg().strip(), ship=ship(), invuln=peek("zp_player_invuln"), fx=fx,
                   parked=estates() == [ENEMY_PARKED] * ENEMIES, home=[q[:2] for q in en] == home(FX_START),
                   launch=peek("zp_launch_timer"), eshots=eshots(), divers=peek("zp_divers_active"),
                   expl=list(mem(sym["explosion_enemy"], 4)))
        ok_new = (new["state"] == GS_PLAY and new["score"] == 0 and new["lives"] == 3 and new["hi"] == "006150"
                  and new["row12"] == "" and new["ship"][:3] == (X_START, PLAYER_Y, 0xC0) and new["ship"][3] == ct[3]
                  and new["invuln"] == 0 and new["fx"] == FX_START and new["parked"] and new["home"]
                  and new["launch"] == 49 and new["eshots"] == [None] * 3 and new["divers"] == 0
                  and new["expl"] == [0xFF] * 4)
        launcher(False)
        frame(0)
        row = "".join("^" if c == SHIP + PANEL_BG else chr((c & 63) + 64) if (c & 63) < 27 else chr(c & 63)
                      for c in mem(SCREEN + 960, 40))
        rep("game-over", not errs and gs_press[0] == GS_OVER and ok_new and panel_hi == "006150"
            and row == " SCORE 000000  HI 006150  WAVE 01  ^^   ",
            f"last life lost with the score at 6150: high score {hi_before} through PlayerDying's 100 frames, GameOver in "
            f"frame 100 with GAME OVER at columns 15-23, no markers, high score {hi_after} (panel {panel_hi} a frame "
            f"later); fire held since the hit didn't skip it in 80 frames; released, then a new press in G + 81: a new "
            f"game in G + 82: {new}; panel '{row}'; errors: {errs[:3] or 'none'}")

        # game-over-early and game-over-timeout: a press before frame 50 does nothing; with no press the
        # screen stays 200 frames and the new game starts in frame 200. Lives set to 1 through the monitor.
        poke("zp_lives", [1])
        x = settle()
        put_eshot(0, x, 205, 0)
        frame()
        for _ in range(100):
            frame()
        errs = []
        if gstate() != (GS_OVER, 0):
            errs.append(f"GameOver not entered: {gstate()}")
        for k in range(1, 200):
            stick = None
            if k in (20, 49):
                stick = BITS["fire"]                          # new presses in G + 20 and G + 49: too early
            if k in (21, 50):
                stick = 0
            frame(stick)
            if gstate() != (GS_OVER, k) or msg().strip() != "GAME OVER":
                errs.append(f"frame G + {k}: state {gstate()}, row 12 '{msg().strip()}'")
        frame()
        rep("game-over-timeout", not errs and gstate()[0] == GS_PLAY and msg().strip() == "" and peek("zp_lives") == 3
            and score() == 0 and mem(sym["game_hiscore"], 3).hex() == "006150",
            f"GameOver again (lives set to 1, a hit): new presses of fire in frames 20 and 49 did nothing; GAME OVER "
            f"stayed through frame 199; frame 200 is the new game (state {gstate()[0]}, lives {peek('zp_lives')}, score "
            f"{score()}, high score kept {mem(sym['game_hiscore'], 3).hex()}); errors: {errs[:3] or 'none'}")
        poke("game_hiscore", [0x00, 0x50, 0x00])


        # ================================================================ stage 3, step 2: divers
        ST_W, ST_D, ST_R = 0x80, 0x81, 0x82
        PATHS = {0: [(0, -1, 6), (1, 2, 20), (2, 3, 20), (1, 3, 16), (0, 2, 9), (2, -1, 24), (2, 0, 0)],   # Plunge
                 1: [(-1, 1, 8), (1, 2, 16), (2, 2, 14), (2, 0, 0)],                                      # Sweep
                 2: [(1, 1, 8), (2, 2, 12), (1, 3, 12), (0, 2, 6), (-2, 0, 12), (-1, -2, 8)]}             # Hook
        FIRE = {0: [26, 36, 46], 1: [24, 38, 62, 86], 2: [8, 16]}
        PATH_NAME = ["Plunge", "Sweep", "Hook"]
        WINDUP, EXTRA, ESHOT_DY, SHOTS_P3 = [24, 20, 16, 12], [0, 4, 2, 2], [2, 2, 3, 3], 2
        DIVE_SCORE = [300, 160, 100]
        DX_MAX, WRAP_Y, LETHAL_Y = 344, 30, 210

        class Dive:
            """The design's diver, stepped one frame at a time beside the game (design.md "Enemy
            behaviour", "Dive paths", "Firing", Stage 3 rules 2-4). Pattern 3: 2 shots at loop 0."""

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

        def aim_dx(d):
            return 0 if abs(d) <= 15 else 1 if d > 0 else -1

        def only(keep):
            """Every enemy but those in `keep` is taken away (monitor): Dead and hidden."""
            st = [ENEMY_PARKED if e in keep else ENEMY_DEAD for e in range(ENEMIES)]
            ys = mem(sym["mux_y"] + ENEMY0, ENEMIES)
            poke("enemy_state", st)
            poke("mux_y", [ys[e] if e in keep else MUX_OFF for e in range(ENEMIES)], ENEMY0)
            poke("zp_enemies_alive", [len(keep)])

        def set_player_x(x):
            poke("zp_player_x_lo", [x & 255, x >> 8])
            poke("mux_x_lo", [x & 255])
            poke("mux_x_hi", [x >> 8])

        def put_pshot(i, x, y):
            poke("mux_x_lo", [x & 255], 4 + i)
            poke("mux_x_hi", [x >> 8], 4 + i)
            poke("mux_y", [y], 4 + i)

        def fly(e, loop=0, player_x=None, before=None, until=None, max_frames=420, invulnerable=True):
            """A full formation back, every enemy but e taken away, the launcher let go for one frame:
            e is launched by the game and followed frame by frame beside the model. `before(k, m)` is
            called at the stop before frame k (frame 0 = the launch) and may poke; `until(k, m, rec)`
            ends the run early. Returns (records, errors, model): a record per frame is a dict."""
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

        # dive-*: each path end to end, unmirrored (ship at the right clamp) and mirrored (at the left)
        windup_rec = None
        for e, px0, mirrored in ((14, X_MAX, False), (15, X_MIN, True), (8, X_MAX, False), (9, X_MIN, True),
                                 (2, X_MAX, False), (3, X_MIN, True)):
            recs, errs, m = fly(e, player_x=px0)
            row = e // COLS
            dive = [r for r in recs if r["st"] == ST_D or (r["step"] and r["st"] == ST_R and r["k"] == recs[[q["st"] for q in recs].index(ST_R)]["k"])]
            first_d = next(r["k"] for r in recs if r["step"] >= 1)
            first_r = next((r["k"] for r in recs if r["st"] == ST_R), None)
            steps = recs[first_r]["step"] if first_r is not None else None
            start = recs[first_d - 1]["home"] if first_d else None
            start_home = (FORM_X0 + recs[first_d]["fx"] + COL_DX * (e % COLS), ROW_Y[row])
            path_recs = [r for r in recs if first_d <= r["k"] <= first_r]
            lethal = [r["step"] for r in path_recs if r["pos"][1] >= LETHAL_Y and (r["k"] < first_r or PATHS[row][-1][2])]
            shots_seen = [(r["step"], r["new"][0][1], r["new"][0][2]) for r in path_recs if r["new"]]
            ret = recs[first_r + 1:]
            drift = sorted({r["home"][0] for r in ret})
            end_ok = (recs[-1]["st"] == ENEMY_PARKED and recs[-1]["pos"] == recs[-1]["home"] and peek("zp_divers_active") == 0
                      and list(mem(sym["diver_enemy"], 3)) == [0xFF] * 3)
            last_fixed = path_recs[sum(n for _, _, n in PATHS[row]) - 1]["pos"]
            off = (last_fixed[0] - start_home[0], last_fixed[1])
            want_off = {0: (124, 192), 1: (36, 164), 2: (12, 200)}[row]
            want_off = (-want_off[0] if mirrored else want_off[0], want_off[1])
            want_lethal = {0: list(range(68, 78)), 1: [], 2: list(range(35, 54))}[row]
            wraps = PATHS[row][-1][2] == 0
            wrap_ok = (not wraps) or (recs[first_r]["pos"] == (recs[first_r]["home"][0], WRAP_Y)
                                      and recs[first_r - 1]["pos"][0] in (2, DX_MAX - 2, 1, DX_MAX - 1))
            want_ret = {0: 13, 1: 33, 2: 32}[row]
            fire_ok = [q[0] for q in shots_seen] == [f for f in FIRE[row][:2]
                                                     if 24 <= next(r for r in path_recs if r["step"] == f)["pos"][0] <= 320]
            ok = (not errs and end_ok and first_d == WINDUP[0] and off == want_off and lethal == want_lethal and wrap_ok
                  and len(ret) == want_ret and fire_ok and (steps == 58 if row == 2 else steps > sum(n for _, _, n in PATHS[row])))
            rep(f"dive-{PATH_NAME[row].lower()}{'-mirrored' if mirrored else ''}", ok,
                f"enemy {e} (row {row}) launched by the launcher with the ship at X {px0}: wind-up frames 0-{first_d - 1}, "
                f"step 1 in frame {first_d} from its home then {start_home}, {'mirrored' if mirrored else 'as authored'}; "
                f"every frame's position, state and colour as the design's table ({len(errs)} differences); after the "
                f"fixed steps at offset {off} (design {want_off}); lethal (Y >= 210) on steps "
                f"{(str(lethal[0]) + '-' + str(lethal[-1])) if lethal else 'none'} (design: "
                f"{(str(want_lethal[0]) + '-' + str(want_lethal[-1])) if want_lethal else 'none'}); {steps} steps; "
                + (f"X reached {recs[first_r - 1]['pos'][0]} -> wrapped to (home X, {WRAP_Y}): {wrap_ok}; " if wraps else
                   "the path ended: Return; ")
                + f"Return took {len(ret)} frames (design {want_ret}) following a home X that drifted {drift[0]}-{drift[-1]}; "
                f"Parked at its home, diver slots free: {end_ok}; shots fired at steps "
                f"{[(q[0], q[1], q[2] - 256 if q[2] > 127 else q[2]) for q in shots_seen]} (step, position, dx); "
                f"errors: {errs[:2] or 'none'}")
            if e == 14:
                windup_rec = recs

        # windup: the wobble and the flash, frame by frame (enemy 14's launch above)
        w = windup_rec[:WINDUP[0] + 1]
        offs = [r["pos"][0] - r["home"][0] for r in w]
        cols = [r["col"] for r in w]
        want_offs = [1 if t % 4 < 2 else -1 for t in range(WINDUP[0])] + [None]
        want_cols = [ct[8] if t % 8 < 4 else ct[7] for t in range(WINDUP[0])] + [ct[7]]
        ok = (offs[:WINDUP[0]] == want_offs[:WINDUP[0]] and cols == want_cols and ct[8] == 1
              and all(r["st"] == ST_W and r["pos"][1] == ROW_Y[2] for r in w[:WINDUP[0]]) and w[WINDUP[0]]["st"] == ST_D)
        rep("windup", ok, f"enemy 14, frames t = 0-23 from the launch frame: X - home X {offs[:WINDUP[0]]} (+ 1 when t mod 4 "
            f"is 0 or 1, - 1 when 2 or 3), colour {cols[:WINDUP[0]]} (white when t mod 8 is 0-3, else light green), Y "
            f"{ROW_Y[2]}, state WindUp; frame 24: Dive, its own colour")

        # dive-loop1 / dive-loop3: the extra path steps (2 in frames whose number mod 4 / mod 2 is 0), the shorter
        # wind-up, the extra shots and the faster shots, against the same model
        for loop, e in ((1, 13), (3, 16), (3, 6)):
            recs, errs, m = fly(e, loop=loop, player_x=X_MAX)
            first_d = next(r["k"] for r in recs if r["step"] >= 1)
            per_frame = [b["step"] - a["step"] for a, b in zip(recs, recs[1:]) if a["st"] == ST_D and b["st"] == ST_D]
            shots_seen = [r["step"] for r in recs if r["new"]]
            rep(f"dive-loop{loop}-{PATH_NAME[e // COLS].lower()}", not errs and first_d == WINDUP[loop] and recs[-1]["st"] == ENEMY_PARKED
                and set(per_frame) == {1, 2} and len(shots_seen) == min(len(FIRE[e // COLS]), SHOTS_P3 + loop),
                f"zp_loop {loop}, enemy {e}: wind-up {first_d} frames (design {WINDUP[loop]}); steps a frame "
                f"{sorted(set(per_frame))}, 2 in {per_frame.count(2)} of {len(per_frame)} frames (every "
                f"{EXTRA[loop]}{'th' if loop == 1 else 'nd'} by the frame number); shots at fire steps {shots_seen} "
                f"(design: the first {SHOTS_P3 + loop} of {FIRE[e // COLS]}), each fired after a step of a 2-step frame "
                f"included; shot dy {ESHOT_DY[loop]}; every frame as the model: {len(errs)} differences {errs[:2] or ''}")

        # aim-*: the shot's dx is fixed when fired, from d = ship X - shot X: 0 if |d| <= 15, else its sign.
        # The ship is put (monitor) at the wanted d from where the Hook will be at its fire steps 8 and 16.
        for d1, d2 in ((15, 16), (-15, -16), (0, -200)):
            wanted = {8: d1, 16: d2}

            def place(k, m, wanted=wanted):
                if m.st == ST_D and m.step + 1 in wanted:
                    dx = PATHS[2][m.seg][0] * (-1 if m.mirror else 1)
                    set_player_x(max(X_MIN, min(X_MAX, m.x + dx + wanted[m.step + 1])))

            recs, errs, m = fly(15, player_x=174, before=place, until=lambda k, m, r: m.step >= 40)
            got = [(r["step"], r["px"] - r["new"][0][1][0], r["new"][0][2] - 256 if r["new"][0][2] > 127 else r["new"][0][2],
                    r["new"][0][1]) for r in recs if r["new"]]
            flown = []
            for stp, d, dx, pos in got:                         # the shots then fly by that dx
                pass
            ok = (not errs and [(g[0], aim_dx(g[1])) for g in got] == [(8, aim_dx(d1)), (16, aim_dx(d2))]
                  and [g[2] for g in got] == [aim_dx(g[1]) for g in got]
                  and (abs(d2) > 100 or [g[1] for g in got] == [d1, d2]))
            rep(f"aim-{d1}-{d2}", ok, f"Hook, enemy 15: shots at (fire step, ship X - shot X, dx, position) {got}: dx 0 "
                f"within 15 pixels, else 1 pixel a frame toward the ship; each shot then moved by its dx and + 2 a frame "
                f"(checked every frame by the model: {len(errs)} differences {errs[:2] or ''})")
            clear_eshots()

        # fire-lost: all three shot slots taken (monitor) at fire step 8: that fire step is lost, not kept for later.
        # Slots freed before step 16: exactly one shot, at step 16
        def block(k, m):
            if m.st == ST_D and m.step == 6:
                for i in range(3):
                    put_eshot(i, 40 + 20 * i, 60, 0)
            if m.st == ST_D and m.step == 12:
                clear_eshots()

        recs, errs, m = fly(14, player_x=X_MAX, before=block, until=lambda k, m, r: m.st == ST_R)
        fired = [(r["step"], r["new"]) for r in recs if r["new"]]
        full_at_8 = next(r for r in recs if r["step"] == 8)["es"]
        rep("fire-lost", not errs and [f[0] for f in fired] == [16] and all(full_at_8),
            f"Hook, enemy 14: three shots in flight at fire step 8 ({full_at_8}): no shot there; slots freed at step 12; "
            f"one shot at step 16 and none after ({[(f[0], f[1][0][1]) for f in fired]}): the lost fire step wasn't "
            f"kept; errors: {errs[:2] or 'none'}")
        clear_eshots()

        # fire-dying / dying-waits: the player is hit just after a Sweep is launched. No diver fires while he is
        # dying; the diver carries on to Parked; the launch timer stops; PlayerDying ends in the first frame, 100 or
        # later, after the frame the last diver parked
        marks = {}

        def kill_player(k, m):
            if k == 30:
                safe(False)
                put_eshot(0, state()[0], 205, 0)
                hold["set"].pop("zp_launch_timer")           # the game's own timer: it must stop by itself
                poke("zp_launch_timer", [77])
            if k == 31:
                marks["hit"] = gstate()
                marks["lives"] = peek("zp_lives")

        def note(k, m, r):
            r["gs"], r["launch"], r["active"] = gstate(), peek("zp_launch_timer"), peek("zp_divers_active")
            return r["gs"][0] == GS_RESPAWN

        poke("zp_lives", [3])
        recs, errs, m = fly(9, player_x=X_MIN, before=kill_player, until=note, invulnerable=True, max_frames=500)
        dying = [r for r in recs if r["gs"][0] == GS_DYING]
        parked_k = next(r["k"] for r in recs if r["st"] == ENEMY_PARKED)
        fire_steps_passed = [f for f in FIRE[1][:2] if any(r["step"] >= f for r in dying)]
        shots_while = [r["step"] for r in dying if r["new"]]
        ok = (not errs and marks["hit"] == (GS_DYING, 0) and dying[0]["k"] == 30 and len(fire_steps_passed) == 2
              and not shots_while and {r["launch"] for r in dying} == {76} and recs[-1]["gs"] == (GS_RESPAWN, 0)
              and recs[-1]["k"] == parked_k + 1 and recs[-2]["gs"] == (GS_DYING, parked_k - 30) and parked_k - 30 >= 100
              and all(r["active"] == 1 for r in dying[:-1]) and dying[-1]["active"] == 0)
        rep("dying-divers", ok,
            f"Sweep (enemy 9) launched, the player hit in its frame 30 (lives {marks['lives']}): the diver flew its whole "
            f"path as the model ({len(errs)} differences), passing fire steps {fire_steps_passed} with no shot "
            f"({shots_while or 'none fired'}); launch timer held at {sorted({r['launch'] for r in dying})}; it Parked in "
            f"PlayerDying's frame {parked_k - 30} (divers active 1 until then) and Respawn began in frame "
            f"{recs[-1]['k'] - 30}: the first frame, 100 or later, with no diver out; errors: {errs[:2] or 'none'}")
        launcher(False)
        revive()

        # game-over-diving: with no lives left PlayerDying ends at frame 100 whatever is diving; the diver flies on
        # through GameOver and nothing is launched or fired there
        def last_life(k, m):
            if k == 30:
                safe(False)
                poke("zp_lives", [1])
                put_eshot(0, state()[0], 205, 0)
                hold["set"].pop("zp_launch_timer")
                poke("zp_launch_timer", [77])

        def note2(k, m, r):
            r["gs"], r["active"], r["launch"] = gstate(), peek("zp_divers_active"), peek("zp_launch_timer")
            return r["st"] == ENEMY_PARKED

        recs, errs, m = fly(9, player_x=X_MIN, before=last_life, until=note2, max_frames=500)
        over_k = next(r["k"] for r in recs if r["gs"][0] == GS_OVER)
        in_over = [r for r in recs if r["gs"][0] == GS_OVER]
        ok = (not errs and over_k == 130 and recs[129]["gs"] == (GS_DYING, 99) and recs[130]["active"] == 1
              and not any(r["new"] for r in recs if r["k"] >= 30) and recs[-1]["gs"][0] == GS_OVER
              and {r["launch"] for r in in_over} == {76} and msg().strip() == "GAME OVER")
        launcher(False)
        rep("game-over-diving", ok,
            f"the last life lost in a Sweep's frame 30: GameOver in PlayerDying's frame {over_k - 30} with the diver "
            f"still out (divers active {recs[130]['active']}); it flew on as the model ({len(errs)} differences) and "
            f"Parked in GameOver's frame {recs[-1]['gs'][1]}; no shot fired, launch timer unchanged "
            f"({sorted({r['launch'] for r in in_over})}); errors: {errs[:2] or 'none'}")
        # game-over-50: a new press in GameOver's frame 50 exactly ends it (frames 20 and 49 didn't, above)
        while gstate()[1] < 49:
            frame(0)
        frame(BITS["fire"])                                   # frame 50
        g50 = gstate()
        frame(0)
        rep("game-over-50", g50[0] == GS_OVER and gstate()[0] == GS_PLAY and peek("zp_lives") == 3
            and peek("zp_divers_active") == 0 and estates() == [ENEMY_PARKED] * ENEMIES,
            f"a new press of fire in GameOver's frame 50: still GameOver in that frame (state {g50}), a new game in the "
            f"next (state {gstate()[0]}, lives {peek('zp_lives')}, all 18 Parked, divers active {peek('zp_divers_active')})")

        # diver-hit-*: a diver shot in WindUp, Dive and Return: the diving value, the explosion where it is,
        # divers active - 1 in the hit's frame, its shot in flight carries on
        for name, e, when in (("windup", 14, lambda m: m.st == ST_W and m.t == 10),
                              ("dive", 14, lambda m: m.st == ST_D and m.step == 20),
                              ("dive-plunge", 2, lambda m: m.st == ST_D and m.step == 50),
                              ("dive-sweep", 8, lambda m: m.st == ST_D and m.step == 45),
                              ("return", 14, lambda m: m.st == ST_R and m.y < 180)):
            box = {}

            def shoot(k, m, when=when, box=box):
                if "k" not in box and when(m):
                    box["k"], box["score"], box["at"] = k, score(), (m.x, m.y)
                    put_pshot(0, m.x, m.y + 14)               # after its move: 6 lines below the diver's Y

            poke("game_score", [0, 0, 0])
            recs, errs, m = fly(e, player_x=X_MAX, before=shoot)
            r = recs[-1]
            row = e // COLS
            at_hit = dict(state=r["st"], pos=r["pos"], col=r["col"], score=score() - box.get("score", 0),
                          active=peek("zp_divers_active"), slots=list(mem(sym["diver_enemy"], 3)),
                          pshot=state()[1][0], alive=peek("zp_enemies_alive"), timer=peek("enemy_timer", e))
            es_at_hit = eshots()
            stay = []
            for i in range(1, EXPLOSION_FRAMES):
                frame()
                stay.append((estates()[e], epos(e)))
            es_later = eshots()
            frame()
            ok = (not errs and r["k"] == box.get("k") and at_hit["state"] == ENEMY_EXPLODING
                  and abs(at_hit["pos"][0] - box["at"][0]) <= 2 and abs(at_hit["pos"][1] - box["at"][1]) <= 3
                  and at_hit["col"] == ORANGE and at_hit["score"] == DIVE_SCORE[row] and at_hit["active"] == 0
                  and at_hit["slots"] == [0xFF] * 3 and at_hit["pshot"] is None and at_hit["alive"] == 1
                  and at_hit["timer"] == EXPLOSION_FRAMES and set(stay) == {(ENEMY_EXPLODING, at_hit["pos"])}
                  and estates()[e] == ENEMY_DEAD and peek("zp_enemies_alive") == 0
                  and all(b is not None and b[1] == a[1] + 2 * (EXPLOSION_FRAMES - 1) and abs(b[0] - a[0]) in (0, EXPLOSION_FRAMES - 1)
                          for a, b in zip(es_at_hit, es_later) if a and a[1] < 190))
            rep(f"diver-hit-{name}", ok,
                f"enemy {e} shot in its frame {box.get('k')} ({['WindUp', 'Dive', 'Return'][recs[-2]['st'] - ST_W]}, at "
                f"{box.get('at')} the frame before): Exploding at {at_hit['pos']} in orange, + {at_hit['score']} (diving value "
                f"{DIVE_SCORE[row]}), divers active {at_hit['active']} and its slot free in that frame, the shot gone, alive "
                f"still {at_hit['alive']}; stationary for 16 frames, then Dead (alive {peek('zp_enemies_alive')}); its own "
                f"shots in flight {es_at_hit} carried on: {es_later}; errors: {errs[:2] or 'none'}")
            clear_eshots()

        # ram-*: the Hook against the ship. Its box (columns 4-19) against the ship's (6-17): |diver X - ship X| <= 13,
        # and only from diver Y 210 (step 35)
        def ram_case(name, offs, want_step, invulnerable=False):
            """offs: {step: ship X - diver X at that step}: the ship is put there (monitor) the frame before."""
            box = {}

            def place(k, m):
                if k == 0 and not invulnerable:
                    safe(False)
                clear_eshots()                                # its own shots are taken away: only the ram is tested
                if m.st == ST_D and m.step + 1 in offs:
                    dx, dy, _ = PATHS[2][m.seg]
                    set_player_x(m.x + (-dx if m.mirror else dx) + offs[m.step + 1])

            def stop(k, m, r):
                r["gs"] = gstate()[0]
                if r["gs"] != GS_PLAY and "k" not in box:
                    box.update(k=k, step=m.step, pos=r["pos"], st=r["st"], px=r["px"])
                return "k" in box or m.step >= 56

            poke("zp_lives", [3])
            poke("game_score", [0, 0, 0])
            recs, errs, m = fly(14, player_x=X_MAX, before=place, until=stop, invulnerable=invulnerable)
            res = dict(step=box.get("step"), state=box.get("st"), score=score(), lives=peek("zp_lives"),
                       active=peek("zp_divers_active"), gs=gstate())
            if want_step is None:
                ok = not errs and "k" not in box and res["lives"] == 3 and res["score"] == 0 and recs[-1]["st"] == ST_D
            else:
                ok = (not errs and res == dict(step=want_step, state=ENEMY_EXPLODING, score=DIVE_SCORE[2], lives=2,
                                               active=0, gs=(GS_DYING, 0)))
            near = [(r["step"], r["px"] - r["pos"][0], r["pos"][1]) for r in recs if r["step"] in offs or r["step"] == box.get("step")]
            near = near if len(near) <= 6 else near[:3] + ["..."] + near[-2:]
            rep(name, ok, f"Hook, enemy 14, ship put at (step, ship X - diver X, diver Y) {near}: "
                + (f"rammed at step {res['step']}: the player hit (lives {res['lives']}, state {res['gs']}), the enemy "
                   f"Exploding, + {res['score']} (its diving value), divers active {res['active']}" if "k" in box else
                   f"no ram through step {recs[-1]['step']}: lives {res['lives']}, score {res['score']}, the diver flew on")
                + f"; expected {'a ram at step ' + str(want_step) if want_step else 'no ram'}; errors: {errs[:2] or 'none'}")
            if "k" in box:
                revive()

        skim = range(36, 41)                                                    # Y 212-216, dx 0 then - 2
        ram_case("ram-y-guard", {33: 0, 34: 0, 35: 0}, 35)                      # Y 206, 208: above the box; 210: a ram
        ram_case("ram-edge-right-in", {**{q: 14 for q in skim}, 41: 13}, 41)    # 14 outside for 5 steps, then 13: inside
        ram_case("ram-edge-right-out", {q: 14 for q in range(36, 56)}, None)    # 14 at every lethal step
        ram_case("ram-edge-left-in", {**{q: -14 for q in skim}, 41: -13}, 41)
        ram_case("ram-edge-left-out", {q: -14 for q in range(36, 56)}, None)
        ram_case("ram-invulnerable", {q: 0 for q in range(34, 56)}, None, invulnerable=True)   # flies through the ship

        # ram-shot-wins: a diver shot in the frame it would ram is Exploding before 6c: the player lives
        box = {}

        def both(k, m):
            if k == 0:
                safe(False)
            if m.st == ST_D and m.step == 34:
                set_player_x(m.x)
                put_pshot(0, m.x, m.y + 2 + 14)
                box["score"] = score()

        poke("zp_lives", [3])
        recs, errs, m = fly(14, player_x=X_MAX, before=both)
        rep("ram-shot-wins", not errs and recs[-1]["st"] == ENEMY_EXPLODING and recs[-1]["step"] == 35 and gstate()[0] == GS_PLAY
            and peek("zp_lives") == 3 and score() - box["score"] == DIVE_SCORE[2],
            f"Hook at step 35 (Y 210) over the ship with a player shot inside its box in the same frame: the enemy "
            f"Exploding ({recs[-1]['st']:#x}), + {score() - box['score']}, the player not hit (state {gstate()[0]}, lives "
            f"{peek('zp_lives')}); errors: {errs[:2] or 'none'}")

        # fifth-explosion: 4 explosions running (monitor), a fifth enemy hit: scored, dead at once, no explosion
        respawn()
        safe(True)
        for i, e in enumerate((0, 1, 2, 3)):
            poke("enemy_state", [ENEMY_EXPLODING], e)
            poke("enemy_timer", [12], e)
        poke("explosion_enemy", [0, 1, 2, 3])
        s0 = score()
        ex, ey = epos(15)
        poke("zp_drift_timer", [2])
        put_pshot(0, ex, ey + 14)
        frame()
        rep("fifth-explosion", estates()[15] == ENEMY_DEAD and epos(15)[1] == MUX_OFF and score() == s0 + 50
            and peek("zp_enemies_alive") == ENEMIES - 1 and sorted(mem(sym["explosion_enemy"], 4)) == [0, 1, 2, 3]
            and state()[1][0] is None,
            f"4 explosion slots taken, enemy 15 shot: state {estates()[15]} (Dead) and hidden in the hit's frame, + "
            f"{score() - s0}, alive {peek('zp_enemies_alive')}, the 4 explosions untouched "
            f"({sorted(mem(sym['explosion_enemy'], 4))})")
        for _ in range(14):
            frame()

        # launcher: a full formation, pattern 3 at loop 0 as the game starts it: launches 100 frames apart from the
        # 50th frame, never more than 2 out, and never more than 2 rng_next calls a frame. The generator is
        # modelled (engine/rng.asm: 16-bit xorshift 7, 9, 8) to count the calls and to check the pick
        def rng_step(lo, hi):
            v = lo | hi << 8
            v ^= (v << 7) & 0xFFFF
            v ^= v >> 9
            v ^= (v << 8) & 0xFFFF
            return v & 255, v >> 8

        respawn()
        safe(True)
        launcher(True)
        poke("zp_launch_timer", [50])
        store = (peek("zp_pattern"), peek("zp_loop"))
        launches, errs, calls_hist, most_out, blocked, waits = [], [], {0: 0, 1: 0, 2: 0}, 0, 0, []
        for f in range(1, 1201):
            r0, st0, act0, tm0 = tuple(mem(sym["zp_rng_lo"], 2)), estates(), peek("zp_divers_active"), peek("zp_launch_timer")
            frame()
            r1, st1, act1 = tuple(mem(sym["zp_rng_lo"], 2)), estates(), peek("zp_divers_active")
            n, r, draws = 0, r0, []
            while r != r1 and n < 3:
                r = rng_step(*r)
                draws.append(r[1])
                n += 1
            if r != r1:
                errs.append(f"frame {f}: more than 2 rng_next calls (or the state was written)")
                continue
            calls_hist[n] += 1
            new = [e for e in range(ENEMIES) if st0[e] == ENEMY_PARKED and st1[e] == ST_W]
            due = tm0 <= 1
            most_out = max(most_out, act1)
            if due and act0 >= 2:
                blocked += 1
            if due and act0 < 2:
                want_r = draws[0] & 31 if draws else None
                if want_r is not None and want_r >= ENEMIES:
                    want_r = draws[1] & 31 if n == 2 else None
                    if want_r is not None and want_r >= ENEMIES:
                        want_r -= ENEMIES
                pick = next(((want_r + i) % ENEMIES for i in range(ENEMIES) if st0[(want_r + i) % ENEMIES] == ENEMY_PARKED), None) \
                    if want_r is not None else None
                if new != [pick] or n not in (1, 2) or (n == 2 and draws[0] & 31 < ENEMIES):
                    errs.append(f"frame {f}: launched {new}, draws {draws}, the pick by the rule {pick}")
                elif peek("zp_launch_timer") != 100:
                    errs.append(f"frame {f}: timer reloaded with {peek('zp_launch_timer')}")
                else:
                    launches.append(f)
                    waits.append(blocked)
                    blocked = 0
            elif new or n:
                errs.append(f"frame {f}: launched {new} with {n} rng calls, timer {tm0}, {act0} out")
        gaps = [b - a for a, b in zip(launches, launches[1:])]
        free_gaps = [g for g, wt in zip(gaps, waits[1:]) if wt == 0]
        ok = (not errs and launches[0] == 50 and most_out == 2 and set(free_gaps) == {100} and len(free_gaps) >= 2
              and all(g == 100 + wt for g, wt in zip(gaps, waits[1:])) and calls_hist[1] + calls_hist[2] == len(launches)
              and store == (2, 0))
        rep("launcher", ok,
            f"1,200 frames from a formation's return, pattern and loop stores {store} (pattern 3, loop 0): first launch in "
            f"frame {launches[0]}, {len(launches)} launches, gaps {gaps} (100 when fewer than 2 were out; longer by the "
            f"frames the timer waited at 0 with 2 out: {waits[1:]}); never more than {most_out} out; rng_next calls a "
            f"frame: {calls_hist} (0 with no launch, 1 or 2 with one); every launched enemy was the first Parked at or "
            f"after the drawn index; errors: {errs[:3] or 'none'}")

        # launcher-halved: the interval is halved with 4 or fewer alive (100 with 5)
        res = {}
        for alive in (5, 4):
            respawn()
            safe(True)
            only(set(range(12, 12 + alive)))
            launcher(True)
            poke("zp_launch_timer", [1])
            frame()
            t_after = peek("zp_launch_timer")
            first = [e for e in range(ENEMIES) if estates()[e] == ST_W]
            n = 0
            while len([e for e in range(ENEMIES) if estates()[e] & 0x80]) < 2 and n < 150:
                frame()
                n += 1
            res[alive] = (t_after, n, first)
            launcher(False)
        rep("launcher-halved", res[5][:2] == (100, 100) and res[4][:2] == (50, 50) and len(res[5][2]) == len(res[4][2]) == 1,
            f"5 enemies alive: the timer reloaded with {res[5][0]} and the next launch came {res[5][1]} frames later; 4 "
            f"alive: {res[4][0]} and {res[4][1]} (design: the interval halved with 4 or fewer)")

        # launcher-rows: with none Parked in the wave's rows the pick falls back to any Parked enemy; pattern 1
        # (monitor: the pattern store) launches only row 2 while it has one
        respawn()
        safe(True)
        poke("zp_pattern", [0])
        launcher(True)
        poke("zp_launch_timer", [1])
        frame()
        launcher(False)
        got1 = [e for e in range(ENEMIES) if estates()[e] == ST_W]
        t1, cap = peek("zp_launch_timer"), None
        poke("zp_launch_timer", [1])
        hold["set"].pop("zp_launch_timer")
        frame()
        cap = [e for e in range(ENEMIES) if estates()[e] == ST_W]
        respawn()
        safe(True)
        only(set(range(0, 12)))
        poke("zp_pattern", [0])
        launcher(True)
        poke("zp_launch_timer", [1])
        frame()
        launcher(False)
        got2 = [e for e in range(ENEMIES) if estates()[e] == ST_W]
        poke("zp_pattern", [2])
        rep("launcher-rows", len(got1) == 1 and got1[0] >= 12 and t1 == 150 and cap == got1 and len(got2) == 1 and got2[0] < 12,
            f"pattern store 0 (Hooks: row 2, 1 at once, interval 150): launched enemy {got1} (row 2), timer {t1}; with it "
            f"out and the timer at 0 again nothing more launched ({cap}); with row 2 all dead: enemy {got2} (any Parked "
            f"enemy)")

        # clear-while-dying: the formation's return runs on its own timer whatever the game state (Stage 3 rule 12)
        respawn()
        safe(False)
        launcher(False)
        x = settle()
        put_eshot(0, x, 205, 0)
        frame()
        empty_sky()
        poke("zp_enemies_alive", [0])
        poke("zp_clear_timer", [3])
        hold["set"].pop("zp_launch_timer")
        seen = []
        for _ in range(3):
            frame()
            seen.append((gstate()[0], estates().count(ENEMY_PARKED), peek("zp_launch_timer")))
        launcher(False)
        rep("clear-while-dying", seen[1][1] == 0 and seen[2] == (GS_DYING, ENEMIES, 50),
            f"the pause timer set to 3 while the player is dying: (state, Parked, launch timer) over 3 frames {seen}: all "
            f"18 back in the third, in PlayerDying, with the launch timer at 50 (it counts only in Play)")
        revive()

        # stage3-play: the game left to itself for 1,500 frames, launcher on, the ship invulnerable, sweeping with
        # fire held: pinned sprites never dropped, nothing missing 2 frames running, no overrun
        respawn()
        safe(True)
        launcher(True)
        stick, most, es_most, launched, bad = BITS["right"] | BITS["fire"], 0, 0, 0, []
        x, shots = frame(stick)
        prev = estates()
        for f in range(1500):
            if x >= X_MAX:
                stick = BITS["left"] | BITS["fire"]
            elif x <= X_MIN:
                stick = BITS["right"] | BITS["fire"]
            x, shots = frame(stick)
            st = estates()
            launched += sum(1 for a, b in zip(prev, st) if a == ENEMY_PARKED and b == ST_W)
            prev = st
            ys = mem(sym["mux_y"], 24)
            most = max(most, sum(1 for y in ys if y != MUX_OFF))
            es_most = max(es_most, sum(1 for q in eshots() if q))
            if any(y != MUX_OFF and not 30 <= y <= PLAYER_Y for y in ys):
                bad.append(f"frame {f}: a sprite at Y {[y for y in ys if y != MUX_OFF and not 30 <= y <= PLAYER_Y]}")
            if peek("zp_divers_active") != sum(1 for q in st if q in (ST_W, ST_D, ST_R)) or peek("zp_divers_active") > 2:
                bad.append(f"frame {f}: divers active {peek('zp_divers_active')}, states {st}")
        frame(0)
        names = [("mux_pin_drop_count", 1), ("mux_pin_excess_count", 1), ("mux_max_age", 1), ("mux_late_count", 1),
                 ("irq_late_count", 1), ("game_overrun_count", 1), ("game_flicker_frames", 2)]
        counts = {k: int.from_bytes(mem(sym[k], n), "little") for k, n in names if k in sym}
        okc = (not counts) or (counts["mux_pin_drop_count"] == 0 and counts["mux_pin_excess_count"] == 0
                               and counts["mux_max_age"] <= 1 and counts["mux_late_count"] == 0
                               and counts["irq_late_count"] == 0 and counts["game_overrun_count"] == 0)
        rep("stage3-play", not bad and okc and launched >= 8 and es_most >= 2 and list(mem(sym["mux_flags"], 24)) == [0x80] * 4 + [0] * 20,
            f"1,500 frames of play at pattern 3, loop 0, the ship invulnerable and sweeping with fire held: {launched} "
            f"launches, up to {es_most} enemy shots and {most} sprites at once; every shown sprite's Y in 30-221; divers "
            f"active always equal to the enemies in WindUp, Dive or Return and never above 2 (errors: {bad[:2] or 'none'}); "
            + (", ".join(f"{k} {c}" for k, c in counts.items()) + " (pinned sprites 0-3 never dropped; nothing missing 2 "
               "frames running)" if counts else "no DEBUG counters in this build: drops not measured"))
        safe(False)
        launcher(False)

        mon.checkpoint_delete(cp.number)
    finally:
        v.close()

    print("\nFAILED: " + ", ".join(fails) if fails else "\nALL PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL (jam/hang): {e}")
        sys.exit(2)
