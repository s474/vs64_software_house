"""Joystick-driven checks of Swarm (M4): stage 1's player, player shots, panel and stars, stage 2
part A's formation (18 enemies, the drift, the animation) and part B's collisions (player shots
against the enemies, explosions, the score, the formation coming back after a clear).

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

Run from the repo root (build first: make GAME=swarm):

    uv run --package budget-runner python tests/games/swarm/check.py [--prg build/swarm/swarm.prg]

Takes about 40 s. Works on a release build too (make BUILD=release GAME=swarm): the DEBUG
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

        def frame(pressed=None):
            """Optionally set the stick (active-high mask), run to the next game_update_end."""
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
            and n_shots >= 1 and ok_thr and launch_at_play in (49, 50) and (ct[3], ct[12]) == (3, 11),
            f"frame 100 of PlayerDying = Respawn's frame R: ship at X {xs[0]}, READY at columns 17-21; stick right from "
            f"R + 5: X + {moved[0]} in that frame, + {moved[1]} after 10 (controllable during READY), fire at R + 15: "
            f"{n_shots} shot; READY shown {ready_frames} frames, Play in R + {play_at} with the launch timer at "
            f"{launch_at_play}; colour by frame cyan/dark grey by the timer, 4 frames each: {cols == want_cols} (first 12: "
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
                  and new["launch"] in (49, 50) and new["eshots"] == [None] * 3 and new["divers"] == 0
                  and new["expl"] == [0xFF] * 4)
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
