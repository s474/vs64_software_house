"""Joystick-driven checks of Swarm (M4): stage 1's player, player shots, panel and stars, and stage
2 part A's formation (18 enemies, the drift, the animation).

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
  fire-hold    fire held 200 frames: never more than 2 shots; each spawns at (player X, 213),
               moves - 8 a frame, is last seen at Y 53 and lives 21 frames; no two spawns closer
               than 10 frames; the spawn frames are printed (0, 10, 21, 31, 42, ...)
  fire-move    fire + right held: each shot keeps the X the player had when it was fired
  cooldown     fire held while each shot is removed (by this script, through the monitor) the
               frame after it spawns, so a slot is always free: spawns are exactly 10 frames apart
  fire-tap     fire pressed for 1 frame: exactly one shot; pressed again 5 frames later: none
               (cooldown); pressed at 10 frames: a second shot
  no-drop      600 frames of the full formation with the player sweeping between the clamps and
               fire held (2 shots crossing the rows): the positions stay as designed, and in a DEBUG
               build mux_drop_count is 0 in every frame and game_flicker_frames, mux_max_age,
               mux_late_count and game_overrun_count are 0 at the end (a release build has no
               counters: the positions only)
  sprites      the hardware sprite registers the multiplexer wrote, read at line 251 (the end of
               the display): all 8 on, one is the player at its X and Y in its colour and shape,
               the others are enemies in their row's Y, colour and shape; no expansion, all hires

Run from the repo root (build first: make GAME=swarm):

    uv run --package budget-runner python tests/games/swarm/check.py [--prg build/swarm/swarm.prg]

Takes about 15 s. Works on a release build too (make BUILD=release GAME=swarm): the DEBUG
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

        # no-drop: the full formation with the player sweeping and two shots crossing the rows
        settle()
        debug = [(k, n) for k, n in DEBUG_COUNTERS if k in sym]
        stick, errs, drops, most = BITS["right"] | BITS["fire"], [], 0, 0
        x, shots = frame(stick)
        for f in range(600):
            if x >= X_MAX:
                stick = BITS["left"] | BITS["fire"]
            elif x <= X_MIN:
                stick = BITS["right"] | BITS["fire"]
            x, shots = frame(stick)
            fx, fdir, en = enemies()
            if [q[:2] for q in en] != home(fx):
                errs.append(f"frame {f}: enemies not at home")
            most = max(most, 19 + sum(1 for q in shots if q))
            if "mux_drop_count" in sym and mem(sym["mux_drop_count"])[0]:   # the previous frame's mux_update
                drops += 1
        frame(0)
        counts = {k: int.from_bytes(mem(sym[k], n), "little") for k, n in debug}
        rep("no-drop", not errs and drops == 0 and not any(counts.values()) and most == 21,
            f"600 frames, player sweeping {X_MIN}-{X_MAX} with fire held, up to {most} sprites shown: enemies at "
            f"their homes in every frame (errors: {errs[:3] or 'none'}); "
            + (f"frames with mux_drop_count != 0: {drops}; " + ", ".join(f"{k} {c}" for k, c in counts.items())
               if debug else "no DEBUG counters in this build: drops not measured"))

        # sprites: what the multiplexer put in the hardware registers, read at line 251 (chain
        # entry 1), when the zone IRQs have written every slot: the 8 hardware sprites then hold
        # the last 8 in Y order, the player among them. Two idle frames first: the registers show
        # the positions the main loop wrote the frame before.
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
