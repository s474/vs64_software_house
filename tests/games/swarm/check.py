"""Joystick-driven checks of Swarm (M4): stage 1's player, player shots, panel and stars, stage 2
part A's formation (18 enemies, the drift, the animation) and part B's collisions (player shots
against the enemies, explosions, the score), stage 3's enemy shots, the player's death, lives,
READY and game over, the divers (launcher, wind-up, the three paths, firing, return), a diver
shot mid-dive and the ram, and stage 4 part A's title screen, the start of a game, the seeding,
the waves (Intro, Fight, Clear, the bonus, the three stores, each wave's settings) and the end of
a game in the title.

HOW THE EARLIER CASES STAY VALID.
Stage 3: every case from "setup" to "sprites" was written when nothing dived and nothing could hit
the ship; they assume a formation that stays Parked. They are kept valid by holding the launcher
off: launcher(False) re-writes zp_launch_timer to 255 every 8 frames (through the monitor: fewer than
the 10 Fight sets it to), so no
dive is ever launched, no enemy shot exists and the ship can't be hit. The stage 3 cases turn the
launcher on where they want a dive (launcher(True), usually for one frame with zp_launch_timer =
1), and safe(True) holds zp_player_invuln up where a case is about a diver's flight and not about
the ship.
Stage 4: the cases of stages 1 to 3 were written for a game that starts in Play with a full
formation, plays pattern 3 at loop 0 on every formation and brings a cleared formation straight
back. Now the script starts a game from the title with the stick (start_game), and those cases run
in a wave whose stores are put at the stage 3 values through the monitor (shown wave 01, pattern
index 2, loop 0) after the game's own Intro has run to Fight. Where a case wants a full formation
again, respawn() puts the Clear phase at its last frame with the stores one wave back, so the game
itself advances them to those values and runs its Intro (legacy_wave); a case that clears waves by
itself puts the stores back in each new wave's first frame (legacy_stores). Where a case ended a
game it now goes through the title to the next one (end_game). The stage 4 cases set a wave the
same way (start_wave(n)), kill a formation by leaving one enemy with its explosion's last frame to
run (last_explosion: the game's own enemy_kill pays the bonus), and reach the title by GameOver's
last frame (to_title).

`make test` can't press buttons, so this drives joystick port 2 through the VICE monitor (the
"I/O simulation" joyport device, as tests/engine/input/check.py does) on the GAME build (not the
AUTOPLAY budget build). The machine is stopped at game_update_end in EVERY frame (after that
frame's input_read and update routines, before mux_update); the stick is changed while it is
stopped and the state is read at the next stop, so each sample is exactly one game frame later.

Expected values are the design's (docs/games/swarm/design.md), with the wave's start and the wave
tables as changed by "Tuning after the stage 4 playtest" (Intro 50 frames, WAVE nn for 49, the
launch timer 10 at Fight, the new intervals, divers at once and shots a dive): X 24-318, 3 px a frame, start 171,
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
  stars        exactly 48 star glyphs in rows 0-23, none in columns 10-29 of rows 5, 9, 12, 15,
               18, 21 (the six text rows); every star's colour is one of white / light grey / grey / dark grey
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
  title, title-press, new-game   (first, from power-on) the title frame by frame: what is shown,
               the three title enemies, PRESS FIRE's blink, rng_next once a frame, the power-on
               panel, a tap while it is drawn and a held button starting nothing; the new press:
               the seed, the erase, the new game 6 frames later; the new-game reset list item by
               item (junk put in every store first) and the 25-frame fire hold
  clear        every enemy left is shot (the player chases each): the score ends at 6 x 280 =
               001680; when the last explosion ends all 18 are Dead and hidden, zp_enemies_alive 0;
               + 1,000 in that frame (002680) and the phase is Clear; the sky stays empty for 75
               frames and in the 75th the next wave's Intro starts (enemy 0 Parked at fx 48, 17
               Waiting, the stores advanced, the panel's WAVE 02); the high score still 005000
  score-cap    the score set to 999,960 through the monitor, a 50-point enemy shot: 999,990
  no-drop      600 frames with the player sweeping between the clamps and fire held (2 shots
               crossing the rows, enemies shot away and the formation coming back): every Parked
               enemy is at its home in every frame, every enemy that isn't Parked is Exploding, or
               Dead or Waiting and hidden, and in a DEBUG build mux_drop_count is 0 in every frame and
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
               one in frame 50 or later does, 200 frames otherwise; then the title (stage 4); with
               a diver out GameOver still starts at frame 100 and the diver flies on
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
  launcher, launcher-halved, launcher-rows   first launch at frame 50 (the script's timer), 64 apart,
               up to 3 out and never more, the pick is the first Parked enemy at or after the drawn
               index, never more than 2 rng_next calls a frame (the generator is modelled); 32 apart
               with 4 alive; the wave's rows (pattern 1: 2 at once, 100 apart), and any row when
               those are empty
  stage3-play  1,500 frames of play: pinned sprites 0-3 never dropped, nothing missing 2 frames
               running, no overrun (DEBUG counters)

  (stage 4 part A)
  autoplay-seed   (run first, on the AUTOPLAY budget build) two runs from power-on are the same game
  wave-intro   an Intro frame by frame: enemy k Parked in frame 2k, 18 alive and the diver slots
               free from frame 0, WAVE nn in frames 0-48, Fight in frame 50 with the launch timer
               at 10, no rng_next call and no launch before frame 60
  wave-stores  the shown wave, the pattern index and the loop over waves 1-15, and 97-99-99-99
  waves-played waves 1-4 played through, each formation killed through the monitor: the bonus in
               Clear's frame 0, the 75-frame pause, the next wave's stores
  wave-clear-* the bonus in PlayerDying (lives left), in Respawn (READY showing) and with the last
               life gone (the timer stops, GameOver over an empty sky, the high score has the
               bonus); READY written only in Fight and erased only if written; WAVE nn untouched
               by a Respawn's end; Fight before Play: Play's 50 stands (first wind-up Play's frame
               49); Play before Fight: Fight's 10 stands (first wind-up 10 frames after Fight)
  clear-shot   an enemy shot in flight in a Clear still kills
  wave-timeline, wave-timeline-last-life   the design's worked case (Stage 4 rule 8), frame by frame
  wave-settings-N   waves 1, 2, 3, 6, 9, 12: the rows that dive, divers at once, the launch
               interval, 2-step frames, shots a dive, shot speed, wind-up frames, drift speed
  seed         two games started in different title frames: different seeds and launches
  row9-uncovered   no Parked enemy's lines touch row 9 while WAVE nn, READY or GAME OVER shows
  (stage 4 part B: sound. Asked for = sfx_request at game_update_end and every call of sfx_play
  in the frame, in order; playing = sfx_cur one frame later)
  sfx-idle     nothing happens for 120 frames: no call, no request, nothing playing
  sfx-player-shot, sfx-enemy-shot, sfx-enemy-shot-x3 (three spawned in a frame: one call),
  sfx-shots-same-frame (the later call, the player's, survives; the two cut each other off),
  sfx-dive (and a second launch restarts it), sfx-explosion, sfx-explosion-x2 (one call),
  sfx-player-hit (A then B; an explosion asked for in the 60 frames after it is dropped),
  sfx-hit-and-explosion, sfx-ram (the hit's two calls and no explosion call),
  sfx-wave-start, sfx-wave-clear (voice 3: the player's shot plays on voice 1 beside them),
  sfx-start (no call at the title; the press; over before the ship can fire), sfx-game-over,
  sfx-volume   $D418 is never written after sfx_init (a store checkpoint through all of these)
  (and in the cases above: game-over ends in the title, the press that skipped it starts nothing
  while held, a tap in the title's frame 7 isn't read and one in frame 8 is, the high score is
  compared once, in GameOver's frame 0)

Run from the repo root (build first: make GAME=swarm):

    uv run --package budget-runner python tests/games/swarm/check.py [--prg build/swarm/swarm.prg]

Takes about 1.5 minutes. Works on a release build too (make BUILD=release GAME=swarm): the DEBUG
counters are read only if the build has them. Results of the last run: tests/games/swarm/check_results.txt.
"""

import argparse
import sys
from pathlib import Path

from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice, build_program
from vice_monitor import CPU_OP_EXEC, CPU_OP_STORE  # on sys.path once budget_runner.session is imported

REPO = Path(__file__).resolve().parents[3]
BITS = {"up": 0x01, "down": 0x02, "left": 0x04, "right": 0x08, "fire": 0x10}
JOYPORT_IO_SIMULATION = 37
PORT2 = 1  # the monitor's port index

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


def autoplay_seed(rep):
    """autoplay-seed: the AUTOPLAY budget build has no title and keeps the constant seed: two runs
    from power-on are the same game (the generator, every sprite, the score and the launches)."""
    prg = build_program("swarm_budget", "tests/games/swarm", ["games/swarm/src"])
    runs = []
    for _ in range(2):
        v = Vice(prg, 0)
        try:
            mon, sym = v.mon, v.symbols
            mon.checkpoint_set(sym["game_update_end"], sym["game_update_end"], CPU_OP_EXEC)

            def get(label, n=1):
                return bytes(mon.mem_get(sym[label], sym[label] + n - 1))

            def step():
                mon.exit()
                if not mon.wait_stopped(STOP_TIMEOUT):
                    mon.ping()
                    raise MeasureError("autoplay-seed: game_update_end not reached")

            step()
            first = (get("zp_rng_lo", 2).hex(), get("zp_game_state")[0], get("zp_wave")[0], get("zp_pattern")[0],
                     get("zp_loop")[0], get("zp_wave_phase")[0])
            launches, prev = [], get("enemy_state", ENEMIES)
            for f in range(1, 700):
                step()
                st = get("enemy_state", ENEMIES)
                launches += [(f, e) for e in range(ENEMIES) if prev[e] == ENEMY_PARKED and st[e] == 0x80]
                prev = st
            snap = (get("zp_rng_lo", 2), st, get("mux_x_lo", 24), get("mux_x_hi", 24), get("mux_y", 24),
                    get("game_score", 3), get("zp_player_x_lo", 2), get("zp_wave_phase"))
            runs.append((first, launches, snap))
        finally:
            v.close()
    a, b = runs
    rep("autoplay-seed", a == b and a[0] == ("5a1d", GS_PLAY, 0x12, 2, 3, PHASE_INTRO) and len(a[1]) >= 5 and a[2][7][0] == PHASE_FIGHT,
        f"the AUTOPLAY budget build, two runs of 700 frames from power-on: no title (first frame: generator, state, "
        f"shown wave, pattern, loop, phase {a[0]}: the constant seed $1D5A, Play, wave 12's Intro); the same in both "
        f"runs: {a == b} (the generator's state, all 18 enemy states, all 24 sprites, the score, the ship's X); "
        f"launches (frame, enemy) {a[1][:6]}... {len(a[1])} in all, the first after the Intro")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prg", default=str(REPO / "build/swarm/swarm.prg"))
    a = ap.parse_args()
    fails = []

    def rep(name, ok, text):
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {text}")
        if not ok:
            fails.append(name)

    autoplay_seed(rep)

    v = Vice(Path(a.prg), 0)        # no warm-up: the first stop below is the title's frame 1
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
        # the way: re-written every HOLD_EVERY frames (see launcher() and safe()).
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
                    hold["n"] = HOLD_EVERY
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

        # ---- helpers for the wave phase (stage 4), used by the start-up below and by every case
        def poke(label, data, off=0):
            mon.mem_set(sym[label] + off, bytes(data))

        def peek(label, off=0):
            return mem(sym[label] + off)[0]

        def bcd(n):
            return (n // 10) * 16 + n % 10

        def phase():
            return peek("zp_wave_phase"), peek("zp_wave_timer")

        def next_wave_in(frames_, stores=None):
            """Through the monitor: the sky emptied and the wave phase put in Clear so that Intro's
            frame 0 is `frames_` frames from now (1 = the next frame). stores = (shown wave, pattern
            index, loop) as they must be BEFORE the game advances them, or None to leave them."""
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

        def to_fight():
            """Run the game's own Intro to the first frame of Fight (and a Clear before it, if the case
            before ended in one)."""
            for _ in range(CLEAR_PAUSE + INTRO_FRAMES + 2):
                if phase()[0] == PHASE_FIGHT:
                    return
                frame()
            raise MeasureError(f"to_fight: the phase is still {phase()}")

        def start_wave(n, run=True):
            """Wave n (1 or more) from Intro's frame 0, by the game's own path: the stores are put at
            wave n - 1's values and the Clear at its last frame, so the game advances them itself.
            (Wave 1 has no wave before it: the loop store is put back to 0 after the advance; loops 0
            and 1 drift at the same speed, so the reset formation is the same.) On return the
            machine is in Intro's frame 0, or in Fight's first frame with run=True."""
            if n == 1:
                next_wave_in(1, (0, 2, 0))
            else:
                next_wave_in(1, (n - 1, (n - 2) % 3, min((n - 2) // 3, 3)))
            frame()
            if n == 1:
                poke("zp_loop", [0])
            if run:
                to_fight()

        # HOW THE EARLIER CASES STAY VALID IN STAGE 4. The cases of stages 1 to 3 were written for a
        # game that starts in Play with a full formation, plays pattern 3 at loop 0 on every
        # formation and brings a cleared formation straight back. They now run in a wave whose
        # stores are put at the stage 3 values (shown wave 01, pattern index 2, loop 0) through the
        # monitor, after the game's own Intro has run to Fight; respawn() below starts such a wave
        # again where a case wants a full formation, and legacy_stores() puts the stores back when
        # a case clears a wave by itself. The launcher is still held off for them (launcher(False)).
        row9 = {}                                 # message -> no Parked enemy's lines touch row 9's (123-130)

        def row9_free():
            st, ys = list(mem(sym["enemy_state"], ENEMIES)), mem(sym["mux_y"] + ENEMY0, ENEMIES)
            return all(not (set(range(ys[e] + 1, ys[e] + 22)) & set(ROW9_LINES)) for e in range(ENEMIES) if st[e] == ENEMY_PARKED)

        def legacy_wave(run=True):
            next_wave_in(1, (0, 1, 0))            # the game advances these to 01, pattern 2, loop 0
            frame()
            if run:
                to_fight()

        def legacy_stores():
            """Call every frame of a case that clears waves by itself: the stores back to stage 3's
            in a new wave's first frame."""
            if phase() == (PHASE_INTRO, 0):
                poke("zp_pattern", [2])
                poke("zp_loop", [0])

        def start_game(tap_frame=None):
            """From the title to the new game's frame (Intro's frame 0) by the stick: wait until
            fire is read (the title's frame 8, or tap_frame if given), a one-frame press, then the
            six erase frames. Returns the title frame the press was made in."""
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

        def to_title():
            """From a game to the title's frame 0 by the game's own path: GameOver's last frame."""
            poke("zp_game_state", [GS_OVER])
            poke("zp_state_timer", [199])
            frame(0)
            if peek("zp_game_state") != GS_TITLE:
                raise MeasureError(f"to_title: state {peek('zp_game_state')}")

        def screen_text():
            """Every play-area cell that isn't a space or a star: {cell: screen code}."""
            return {i: c for i, c in enumerate(mem(SCREEN, 960)) if c not in (SPACE, STAR_HI, STAR_LO)}

        def text_cells(texts):
            out = {}
            for text, row_, col in texts:
                out.update({row_ * 40 + col + i: c for i, c in enumerate(code(text)) if c != SPACE})
            return out

        def title_texts(f):
            """What the title shows in its frame f: text i from frame i on, PRESS FIRE by the blink."""
            return text_cells([t for i, t in enumerate(TITLE_TEXTS) if (i and f >= i) or (i == 0 and f % 64 < 32)])

        def sprites24():
            xl, xh, ys = mem(sym["mux_x_lo"], 24), mem(sym["mux_x_hi"], 24), mem(sym["mux_y"], 24)
            ps, cs = mem(sym["mux_ptr"], 24), mem(sym["mux_col"], 24)
            return {i: (xl[i] + 256 * xh[i], ys[i], ps[i], cs[i] & 15) for i in range(24) if ys[i] != MUX_OFF}

        def title_sprites(f):
            return {ENEMY0 + r * COLS: TITLE_SPRITES[r] + (SHAPE_ENEMY + 2 * r + (f >> 4 & 1), ENEMY_COLOURS[r]) for r in range(3)}

        def rng_step(lo, hi):
            v = lo | hi << 8
            v ^= (v << 7) & 0xFFFF
            v ^= v >> 9
            v ^= (v << 8) & 0xFFFF
            return v & 255, v >> 8

        def panel_row():
            return "".join("^" if c == SHIP + PANEL_BG else chr((c & 63) + 64) if (c & 63) < 27 else chr(c & 63)
                           for c in mem(SCREEN + 960, 40))

        launcher(False)                           # until the stage 3 cases: nothing dives
        frame(0)                                  # the title's frame 1 (frame 0 was drawn before the first frame)

        # title: the power-on title, frame by frame. A one-frame tap of fire in frame 3 (while it is being
        # drawn), then fire held from frame 6 to frame 139 (down before fire is first read, in frame 8: never a
        # new press), released, and a new press in frame 142
        PRESS = 142
        sched = {3: BITS["fire"], 4: 0, 6: BITS["fire"], 140: 0, PRESS: BITS["fire"], PRESS + 1: 0}
        errs, blink, rng_bad, prev_rng = [], [], 0, None
        power_on = (panel_row(), peek("zp_lives"), mem(sym["game_score"], 3).hex(), mem(sym["game_hiscore"], 3).hex())
        for f in range(1, PRESS):
            if f > 1:
                frame(sched.get(f))
            got = (peek("zp_game_state"), peek("zp_state_timer"), screen_text(), sprites24())
            want = (GS_TITLE, f, title_texts(f), title_sprites(f))
            if got != want:
                errs.append(f"frame {f}: state {got[0]}, timer {got[1]}, texts as designed {got[2] == want[2]}, "
                            f"sprites {got[3]}")
            pf = all(got[2].get(cell) == c for cell, c in text_cells(TITLE_TEXTS[:1]).items())
            if not blink or blink[-1][1] != pf:
                blink.append((f, pf))
            r = tuple(mem(sym["zp_rng_lo"], 2))
            if prev_rng is not None and r != rng_step(*prev_rng):
                rng_bad += 1
            prev_rng = r
        stars_now = {i for i, c in enumerate(mem(SCREEN, 960)) if c in (STAR_HI, STAR_LO)}
        under = stars_now & set(text_cells(TITLE_TEXTS))
        ok = (not errs and blink == [(1, True), (32, False), (64, True), (96, False), (128, True)] and rng_bad == 0
              and power_on == (" SCORE 000000  HI 005000  WAVE 01       ", 0, "000000", "005000") and not under
              and len(stars_now) == 48)
        rep("title", ok,
            f"power-on, frames 1-{PRESS - 1}: state Title, the frame count in zp_state_timer; SWARM on row 5 from frame 1, "
            f"150 PTS / 80 PTS / 50 PTS on rows 9, 12, 15 from frames 2, 3, 4, DIVING SCORES DOUBLE on row 18 from frame 5 "
            f"(one text a frame; nothing else in the play area but the 48 stars, {len(under)} of them under a text); the "
            f"only sprites are 6, 12, 18 at (120, 115 / 139 / 163) in purple / yellow / light green, shapes swapping "
            f"every 16 frames; PRESS FIRE (row 21) changes at (frame, shown) {blink}: on 32, off 32; rng_next once a "
            f"frame ({rng_bad} frames otherwise); panel '{power_on[0]}', lives {power_on[1]} (no markers); a tap of fire "
            f"in frame 3 and fire held from frame 6 to 139 started nothing; errors: {errs[:2] or 'none'}")

        # title-press: the new press in frame 142: the seed, the sprites gone at once, the six texts erased one a
        # frame, and the new game in the frame after the last erase
        frame(sched[PRESS])
        stepped = rng_step(*prev_rng)
        seeded, irq_f = tuple(mem(sym["zp_rng_lo"], 2)), peek("zp_irq_frame")
        seed_line = seeded[1] ^ stepped[1]
        errs = []
        if not (peek("zp_game_state") == GS_TITLE and sprites24() == {} and seeded[0] == stepped[0] ^ irq_f
                and screen_text() == text_cells(TITLE_TEXTS[1:])):
            errs.append(f"the press's frame: sprites {sprites24()}, rng {prev_rng} -> {seeded} (stepped {stepped}, frame {irq_f})")
        for i in range(1, 6):
            frame(0)
            if peek("zp_game_state") != GS_TITLE or screen_text() != text_cells(TITLE_TEXTS[i + 1:]) or sprites24():
                errs.append(f"press + {i}: texts left {len(screen_text())} cells, state {peek('zp_game_state')}")
            if tuple(mem(sym["zp_rng_lo"], 2)) != seeded:
                errs.append(f"press + {i}: the generator moved after the seed")
        rep("title-press", not errs and 0 < seed_line < 60,
            f"a new press in frame {PRESS} (fire up in 140 and 141): in that frame the three sprites are hidden and the "
            f"generator is seeded: low byte = its stepped state ^ zp_irq_frame ({stepped[0]:#04x} ^ {irq_f:#04x} = "
            f"{seeded[0]:#04x}), high byte = its stepped state ^ the raster line read (line {seed_line}); the texts are "
            f"erased one a frame (PRESS FIRE in the press's frame, DIVING SCORES DOUBLE last, 5 frames later), the "
            f"generator untouched after the seed; errors: {errs[:2] or 'none'}")

        # new-game: the reset list of Stage 4 rule 10, item by item. Junk is put in everything it must reset
        # (monitor), in the frame before; fire is held from the new game's frame to time the 25-frame hold
        poke("game_score", [0x12, 0x34, 0x50])
        poke("game_hiscore", [0x00, 0x77, 0x70])
        poke("zp_wave", [0x47])
        poke("zp_pattern", [1])
        poke("zp_loop", [2])
        poke("zp_lives", [0])
        poke("mux_y", [100, 110, 120, 130, 140], 1)       # three enemy shots and two player shots "in flight"
        poke("explosion_enemy", [1, 2, 3, 4])
        poke("diver_enemy", [5, 6, 7])
        poke("zp_divers_active", [3])
        poke("zp_player_invuln", [77])
        poke("zp_player_x_lo", [100, 0])
        poke("zp_player_cooldown", [3])
        poke("game_ready", [1])
        poke("zp_launch_timer", [7])
        x, shots = frame(BITS["fire"])                    # the new game's frame, N
        first = enemies()                                 # after the game's first formation_update
        first_states = list(mem(sym["enemy_state"], ENEMIES))
        ng = dict(state=peek("zp_game_state"), score=mem(sym["game_score"], 3).hex(), lives=peek("zp_lives"),
                  stores=(peek("zp_wave"), peek("zp_pattern"), peek("zp_loop")),
                  shots=list(mem(sym["mux_y"] + 1, 5)), expl=list(mem(sym["explosion_enemy"], 4)),
                  divers=(peek("zp_divers_active"), list(mem(sym["diver_enemy"], 3))),
                  ship=sprites24().get(0), x=x, invuln=peek("zp_player_invuln"), cooldown=peek("zp_player_cooldown"),
                  dirty=peek("panel_dirty"), hi=mem(sym["game_hiscore"], 3).hex(), phase=phase(),
                  text=screen_text() == text_cells([("WAVE 01", MSG_ROW, 16)]), alive=peek("zp_enemies_alive"),
                  states=first_states == [ENEMY_PARKED] + [ENEMY_WAITING] * (ENEMIES - 1), ready=peek("game_ready"),
                  launch=peek("zp_launch_timer"), rng=tuple(mem(sym["zp_rng_lo"], 2)) == seeded)
        want_ng = dict(state=GS_PLAY, score="000000", lives=3, stores=(1, 0, 0), shots=[MUX_OFF] * 5, expl=[0xFF] * 4,
                       divers=(0, [0xFF] * 3), ship=(X_START, PLAYER_Y, 0xC0, 3), x=X_START, invuln=0,
                       cooldown=NEW_GAME_COOLDOWN, dirty=0x0F, hi="007770", phase=(PHASE_INTRO, 0), text=True,
                       alive=ENEMIES, states=True, ready=0, launch=50, rng=True)
        frame()
        second = enemies()
        row1 = panel_row()
        fired = None
        for k in range(2, 40):
            x, shots = frame(None if fired is None else 0)
            if any(shots) and fired is None:
                fired = k
                mon.mem_set(sym["mux_y"] + 4, bytes([MUX_OFF, MUX_OFF]))    # taken away: it must hit nothing
        frame(0)
        poke("game_hiscore", [0x00, 0x50, 0x00])
        poke("panel_dirty", [8])
        rep("new-game", ng == want_ng and row1 == " SCORE 000000  HI 007770  WAVE 01  ^^   " and fired == NEW_GAME_COOLDOWN,
            f"the frame after the last erase (press + 6) is the new game, all in that frame, with junk put in every "
            f"store first: {ng}; differences from the design's list: "
            f"{ {k: (ng[k], want_ng[k]) for k in ng if ng[k] != want_ng[k]} or 'none'}; panel a frame later '{row1}' (all "
            f"four fields redrawn, the high score kept); fire held from the new game's frame: the first shot in its frame "
            f"{fired} (the 25-frame hold: none in frames 0-24)")

        poke("zp_pattern", [2])                   # stage 3's stand-in for waves: pattern 3 at loop 0
        to_fight()
        settle()

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
              and first[0] == FX_START and first[2][0][:2] == home(FX_START)[0]
              and first_states == [ENEMY_PARKED] + [ENEMY_WAITING] * (ENEMIES - 1)
              and second[0] == FX_START + 1 and second[1] == 1)
        rep("formation", ok, f"the game's first frame (Intro's frame 0): fx {first[0]} (design: starts at 48), enemy 0 "
            f"Parked at its home and the other 17 Waiting; second: fx {second[0]}, direction {second[1]} (1 = right); "
            f"after the Intro, fx {fx}: "
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

        def respawn():
            """The game's own path back to a full formation: the Clear's last frame, then the next
            wave's Intro run to Fight, with the stores at stage 3's values (legacy_wave)."""
            settle()
            legacy_wave()

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
        if estates() != [ENEMY_PARKED] * ENEMIES or score() != 0 or (peek("zp_pattern"), peek("zp_loop")) != (2, 0):
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
        bonus = score() - final                                  # paid in the frame the last explosion ended
        gone = (estates() == [ENEMY_DEAD] * ENEMIES and all(q[1] == MUX_OFF for q in en)
                and phase() == (PHASE_CLEAR, 0))
        empty = 0
        for i in range(1, CLEAR_PAUSE):
            frame()
            fx, fdir, en = enemies()
            empty += all(q[1] == MUX_OFF for q in en) and estates() == [ENEMY_DEAD] * ENEMIES and phase() == (PHASE_CLEAR, i)
        frame()                                                  # the 75th frame after the last one went
        fx, fdir, en = enemies()
        st = estates()
        back = (st == [ENEMY_PARKED] + [ENEMY_WAITING] * (ENEMIES - 1) and en[0][:2] == home(FX_START)[0] and fx == FX_START
                and fdir == 1 and mem(sym["zp_enemies_alive"])[0] == ENEMIES and phase() == (PHASE_INTRO, 0)
                and all(q[1] == MUX_OFF for q in en[1:]))
        stores = (mem(sym["zp_wave"])[0], peek("zp_pattern"), peek("zp_loop"))
        frame()
        fx2 = mem(sym["zp_fx"])[0]
        row = "".join(chr((c & 63) + 64) if (c & 63) < 27 else chr(c & 63) for c in mem(SCREEN + 960, 34))
        rep("clear", not errs and final == 1680 and bonus == 1000 and gone and empty == CLEAR_PAUSE - 1 and back
            and score() == final + 1000 and row == " SCORE 002680  HI 005000  WAVE 02 " and fx2 == FX_START + 1
            and stores == (0x02, 0, 1),
            f"{shot_down} more enemies shot, each for its row's value (errors: {errs[:3] or 'none'}); score {final} "
            f"(6 x 280 = 1680); when the last explosion ended: all Dead and hidden, the phase Clear at its frame 0, "
            f"+ {bonus} in that frame: {gone}; sky empty for the next {empty} frames; in frame {CLEAR_PAUSE} the next "
            f"wave's Intro: enemy 0 Parked at its home for fx {fx}, the other 17 Waiting and hidden, alive 18: {back}; "
            f"stores (shown wave, pattern, loop) {stores} (the wave before was the script's 01, pattern 2, loop 0); "
            f"fx {fx2} a frame later; panel '{row}' (the bonus, the wave; the high score unchanged)")
        respawn()                                                # the stage 3 stores again

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
            legacy_stores()
            fx, fdir, en = enemies()
            st = estates()
            killed |= {j for j in range(ENEMIES) if st[j] in (ENEMY_EXPLODING, ENEMY_DEAD)}
            respawns += prev_alive < ENEMIES == st.count(ENEMY_PARKED)
            prev_alive = st.count(ENEMY_PARKED)
            fewest = min(fewest, prev_alive)
            for j in range(ENEMIES):
                if st[j] == ENEMY_PARKED and en[j][:2] != home(fx)[j]:
                    errs.append(f"frame {f}: enemy {j} not at home")
                elif st[j] in (ENEMY_DEAD, ENEMY_WAITING) and en[j][1] != MUX_OFF:
                    errs.append(f"frame {f}: dead or waiting enemy {j} shown")
                elif st[j] not in (ENEMY_PARKED, ENEMY_DEAD, ENEMY_EXPLODING, ENEMY_WAITING):
                    errs.append(f"frame {f}: enemy {j} state {st[j]:#x}")
            most = max(most, 1 + sum(1 for q in en if q[1] != MUX_OFF) + sum(1 for q in shots if q))
            if "mux_drop_count" in sym and mem(sym["mux_drop_count"])[0]:   # the previous frame's mux_update
                drops += 1
        frame(0)
        counts = {k: int.from_bytes(mem(sym[k], n), "little") for k, n in debug}
        rep("no-drop", not errs and drops == 0 and not any(counts.values()) and most <= 21 and len(killed) >= 6,
            f"600 frames, player sweeping {X_MIN}-{X_MAX} with fire held, up to {most} sprites shown, {len(killed)} "
            f"different enemies shot (fewest Parked at once: {fewest}), the formation came back {respawns} times: every Parked enemy at its home, every "
            f"other Exploding, or Dead or Waiting and hidden, in every frame (errors: {errs[:3] or 'none'}); "
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
        ESHOT0, SHAPE_ESHOT, ESHOT_HIT_Y, ESHOT_HIT_DX = 1, 0xC2, 207, 6
        PANEL_DIRTY_LIVES, PANEL_DIRTY_HI = 2, 8
        MSG = SCREEN + MSG_ROW * 40

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
            """Row 9 (the message row) as text, 40 characters; the cells outside the star-free band (columns 10-29) as spaces."""
            return "".join(" " if i not in BAND_COLS else chr((c & 63) + 64) if 0 < (c & 63) < 27 else chr(c & 63)
                           for i, c in enumerate(mem(MSG, 40)))

        def walk_to(x0):
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

        def end_game():
            """From GameOver to the next game's first frame (Intro's frame 0), by the game's own path:
            GameOver's last frame, the title, a press of fire."""
            if gstate()[0] != GS_OVER:
                raise MeasureError(f"end_game: not in GameOver: {gstate()}")
            to_title()
            start_game()

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

        # death: the player's death, frame by frame. The ship stands at the left clamp: a shot from X 24 can hit
        # nothing (column 0 is never left of X 34, and a hit needs |dx| <= 8), so the shot in flight at the hit
        # carries on to the top and the formation is whole for row9-uncovered, wherever the drift is
        walk_to(X_MIN)
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
            errs.append(f"frame R: state {gstate()}, ship {ship()}, row 9 '{msg().strip()}', invuln {peek('zp_player_invuln')}")
        row9["READY"] = row9_free() and estates().count(ENEMY_PARKED) == ENEMIES
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
                mon.mem_set(sym["mux_y"] + 4, bytes([MUX_OFF, MUX_OFF]))    # the shot seen in R + 15 and 16 is taken
                                                              # away: it must hit nothing (GAME OVER's row 9 check
                                                              # below wants all 18 Parked)
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
                    errs.append(f"frame R + {k}: Play with row 9 '{msg().strip()}'")
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
        poke("panel_dirty", [PANEL_DIRTY_SCORE])              # the panel shows what the script put in the score
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
            errs.append(f"frame G: state {gstate()}, row 9 '{msg().strip()}', high score {hi_before} -> {hi_after}, "
                        f"dirty {dirty}, markers {markers}")
        row9["GAME OVER"] = row9_free() and estates().count(ENEMY_PARKED) == ENEMIES
        frame()
        panel_hi = "".join(chr(c - PANEL_BG) for c in mem(SCREEN + 960 + 18, 6))
        for k in range(2, 80):                                # fire still held: not a new press, no skip
            frame()
            if gstate() != (GS_OVER, k):
                errs.append(f"frame G + {k} with fire held since the hit: state {gstate()}")
        frame(0)                                              # G + 80: released
        before_end = sprites24()
        frame(BITS["fire"])                                   # G + 81: a new press, and fire stays down
        gs_press = gstate()
        frame()                                               # G + 82: the title's frame 0
        t0 = dict(state=gstate(), sprites=sprites24() == title_sprites(0), row9=msg().strip(),
                  texts=screen_text() == title_texts(0), score=score(), lives=peek("zp_lives"),
                  hi=mem(sym["game_hiscore"], 3).hex(), phase=phase()[0], step=peek("title_step"))
        ok_title = t0 == dict(state=(GS_TITLE, 0), sprites=True, row9="", texts=True, score=6150, lives=0, hi="006150",
                              phase=t0["phase"], step=0) and len(before_end) > 15
        held = []
        for k in range(1, 30):                                # the press that skipped GameOver is still down
            frame()
            held.append((gstate()[0], screen_text() == title_texts(k), sprites24() == title_sprites(k)))
        row = panel_row()
        frame(0)
        frame()
        pressed_in = start_game()
        frame()
        row_new = panel_row()
        rep("game-over", not errs and gs_press[0] == GS_OVER and ok_title and panel_hi == "006150"
            and set(held) == {(GS_TITLE, True, True)} and row == " SCORE 006150  HI 006150  WAVE 01       "
            and row_new == " SCORE 000000  HI 006150  WAVE 01  ^^   ",
            f"last life lost with the score at 6150: high score {hi_before} through PlayerDying's 100 frames, GameOver in "
            f"frame 100 with GAME OVER at columns 15-23, no markers, high score {hi_after} (panel {panel_hi} a frame "
            f"later); fire held since the hit didn't skip it in 80 frames; released, then a new press in G + 81 ended "
            f"it: G + 82 is the title's frame 0: {t0} ({len(before_end)} sprites were shown the frame before: the "
            f"formation vanished at once), panel '{row}' as the game ended; that press, still held for 29 title frames "
            f"(past frame 8), started nothing and the title drew itself as at power-on; released and pressed again in "
            f"title frame {pressed_in}: a new game, panel '{row_new}'; errors: {errs[:3] or 'none'}")

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
            if k == 10:
                poke("game_score", [0x00, 0x90, 0x00])        # above the high score, after GameOver's frame 0
            frame(stick)
            if gstate() != (GS_OVER, k) or msg().strip() != "GAME OVER":
                errs.append(f"frame G + {k}: state {gstate()}, row 9 '{msg().strip()}'")
        hi_mid = mem(sym["game_hiscore"], 3).hex()
        frame()                                               # frame 200: the title's frame 0
        t0 = (gstate(), msg().strip(), peek("zp_lives"), score(), mem(sym["game_hiscore"], 3).hex())
        taps = []
        for k in range(1, 31):                                # a one-frame tap in the title's frame 7: not read
            frame(BITS["fire"] if k == 7 else 0)
            taps.append(gstate()[0])
        rep("game-over-timeout", not errs and t0 == ((GS_TITLE, 0), "", 0, 9000, "006150") and hi_mid == "006150"
            and set(taps) == {GS_TITLE},
            f"GameOver again (lives set to 1, a hit): new presses of fire in frames 20 and 49 did nothing; GAME OVER "
            f"stayed through frame 199; frame 200 is the title's frame 0 (state, row 9, lives, score, high score) {t0}: "
            f"the score was put up to 9,000 in GameOver's frame 10 (monitor) and the high score stayed {hi_mid}: it is "
            f"compared once, in GameOver's frame 0; a one-frame tap of fire in the title's frame 7 started nothing in "
            f"30 frames (fire is read from frame 8); errors: {errs[:3] or 'none'}")
        start_game()
        poke("game_hiscore", [0x00, 0x50, 0x00])


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
            fire_ok = [q[0] for q in shots_seen] == [f for f in FIRE[row][:SHOTS_P3]
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
        fire_steps_passed = [f for f in FIRE[1][:SHOTS_P3] if any(r["step"] >= f for r in dying)]
        shots_while = [r["step"] for r in dying if r["new"]]
        ok = (not errs and marks["hit"] == (GS_DYING, 0) and dying[0]["k"] == 30 and len(fire_steps_passed) == SHOTS_P3
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
        frame(0)                                              # the title's frame 0
        t0 = (gstate(), sprites24() == title_sprites(0), peek("zp_divers_active"))
        for k in range(1, 8):
            frame(0)
        frame(BITS["fire"])                                   # a one-frame tap in the title's frame 8: read
        t8 = (gstate(), peek("title_step"))
        for k in range(6):
            frame(0)
        rep("game-over-50", g50[0] == GS_OVER and t0[:2] == ((GS_TITLE, 0), True) and t8 == ((GS_TITLE, 8), 10)
            and gstate()[0] == GS_PLAY and phase() == (PHASE_INTRO, 0) and peek("zp_lives") == 3
            and peek("zp_divers_active") == 0 and estates() == [ENEMY_PARKED] + [ENEMY_WAITING] * (ENEMIES - 1)
            and list(mem(sym["diver_enemy"], 3)) == [0xFF] * 3,
            f"a new press of fire in GameOver's frame 50: still GameOver in that frame (state {g50}), the title's frame 0 "
            f"in the next ({t0[0]}, only the three title sprites: {t0[1]}); a one-frame tap in the title's frame 8, the "
            f"first frame fire is read: the erase began in that frame (state, title_step {t8}) and the new game came 6 "
            f"frames later (state {gstate()[0]}, lives {peek('zp_lives')}, Intro's frame 0, divers active "
            f"{peek('zp_divers_active')} and every diver slot free)")

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
                  and abs(at_hit["pos"][0] - box["at"][0]) <= 3 and abs(at_hit["pos"][1] - box["at"][1]) <= 3   # a frame's move: the wobble's 2 + the drift's 1
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
            clear_eshots()                                    # its own shots are taken away (as ram_case does): the
                                                              # ship is vulnerable, and one of them would kill it later
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

        # launcher: a full formation, pattern 3 at loop 0: launches 64 frames apart (100 until the stage 4 tuning)
        # from the 50th frame (the script puts the timer at 50), up to 3 out and never more (2 until the tuning),
        # and never more than 2 rng_next calls a frame. The generator is
        # modelled (engine/rng.asm: 16-bit xorshift 7, 9, 8) to count the calls and to check the pick
        def rng_step(lo, hi):
            v = lo | hi << 8
            v ^= (v << 7) & 0xFFFF
            v ^= v >> 9
            v ^= (v << 8) & 0xFFFF
            return v & 255, v >> 8

        respawn()
        if gstate()[0] != GS_PLAY:                # the timer counts only in Play: a death left over from a case
            raise MeasureError(f"launcher: not in Play: state {gstate()}")   # before would delay the first launch
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
            if due and act0 >= CAP_P3:
                blocked += 1
            if due and act0 < CAP_P3:
                want_r = draws[0] & 31 if draws else None
                if want_r is not None and want_r >= ENEMIES:
                    want_r = draws[1] & 31 if n == 2 else None
                    if want_r is not None and want_r >= ENEMIES:
                        want_r -= ENEMIES
                pick = next(((want_r + i) % ENEMIES for i in range(ENEMIES) if st0[(want_r + i) % ENEMIES] == ENEMY_PARKED), None) \
                    if want_r is not None else None
                if new != [pick] or n not in (1, 2) or (n == 2 and draws[0] & 31 < ENEMIES):
                    errs.append(f"frame {f}: launched {new}, draws {draws}, the pick by the rule {pick}")
                elif peek("zp_launch_timer") != INTERVAL_P3:
                    errs.append(f"frame {f}: timer reloaded with {peek('zp_launch_timer')}")
                else:
                    launches.append(f)
                    waits.append(blocked)
                    blocked = 0
            elif new or n:
                errs.append(f"frame {f}: launched {new} with {n} rng calls, timer {tm0}, {act0} out")
        gaps = [b - a for a, b in zip(launches, launches[1:])]
        free_gaps = [g for g, wt in zip(gaps, waits[1:]) if wt == 0]
        ok = (not errs and launches[0] == 50 and most_out == CAP_P3 and set(free_gaps) == {INTERVAL_P3} and len(free_gaps) >= 2
              and all(g == INTERVAL_P3 + wt for g, wt in zip(gaps, waits[1:])) and calls_hist[1] + calls_hist[2] == len(launches)
              and store == (2, 0))
        rep("launcher", ok,
            f"1,200 frames from a formation's return, pattern and loop stores {store} (pattern 3, loop 0): first launch in "
            f"frame {launches[0]}, {len(launches)} launches, gaps {sorted(set(gaps))} (design {INTERVAL_P3} when fewer than {CAP_P3} were out; "
            f"longer by the frames the timer waited at 0 with {CAP_P3} out: {sorted(set(waits[1:]))}); most out at once {most_out} "
            f"(design: up to {CAP_P3}); rng_next calls a "
            f"frame: {calls_hist} (0 with no launch, 1 or 2 with one); every launched enemy was the first Parked at or "
            f"after the drawn index; errors: {errs[:3] or 'none'}")

        # launcher-halved: the interval is halved with 4 or fewer alive (64 with 5, 32 with 4)
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
        rep("launcher-halved", res[5][:2] == (INTERVAL_P3, INTERVAL_P3) and res[4][:2] == (INTERVAL_P3 // 2, INTERVAL_P3 // 2) and len(res[5][2]) == len(res[4][2]) == 1,
            f"5 enemies alive: the timer reloaded with {res[5][0]} and the next launch came {res[5][1]} frames later; 4 "
            f"alive: {res[4][0]} and {res[4][1]} (design: {INTERVAL_P3}, halved with 4 or fewer: {INTERVAL_P3 // 2})")

        # launcher-rows: with none Parked in the wave's rows the pick falls back to any Parked enemy; pattern 1
        # (monitor: the pattern store) launches only row 2 while it has one: 2 at once (1 until the stage 4
        # tuning), interval 100 (150 until then), and no third
        respawn()
        safe(True)
        poke("zp_pattern", [0])
        launcher(True)
        poke("zp_launch_timer", [1])
        frame()
        got1 = [e for e in range(ENEMIES) if estates()[e] == ST_W]
        t1 = peek("zp_launch_timer")
        poke("zp_launch_timer", [1])
        frame()
        second = [e for e in range(ENEMIES) if estates()[e] == ST_W]
        t2 = peek("zp_launch_timer")
        poke("zp_launch_timer", [1])
        frame()
        cap = [e for e in range(ENEMIES) if estates()[e] == ST_W]
        t3 = peek("zp_launch_timer")
        launcher(False)
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
        rep("launcher-rows", len(got1) == 1 and got1[0] >= 12 and (t1, t2, t3) == (100, 100, 0) and len(second) == 2
            and set(got1) < set(second) and min(second) >= 12 and cap == second and len(got2) == 1 and got2[0] < 12,
            f"pattern store 0 (Hooks: row 2, 2 at once, interval 100): launched enemy {got1} (row 2), timer {t1}; the "
            f"timer at 0 again with it out: a second, {sorted(set(second) - set(got1))} (row 2), timer {t2}; with 2 out "
            f"and the timer at 0 again nothing more launched ({cap}, the timer stays {t3}); with row 2 all dead: enemy "
            f"{got2} (any Parked enemy)")

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
            legacy_stores()
            st = estates()
            launched += sum(1 for a, b in zip(prev, st) if a == ENEMY_PARKED and b == ST_W)
            prev = st
            ys = mem(sym["mux_y"], 24)
            most = max(most, sum(1 for y in ys if y != MUX_OFF))
            es_most = max(es_most, sum(1 for q in eshots() if q))
            if any(y != MUX_OFF and not 30 <= y <= PLAYER_Y for y in ys):
                bad.append(f"frame {f}: a sprite at Y {[y for y in ys if y != MUX_OFF and not 30 <= y <= PLAYER_Y]}")
            if peek("zp_divers_active") != sum(1 for q in st if q in (ST_W, ST_D, ST_R)) or peek("zp_divers_active") > CAP_P3:
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
            f"active always equal to the enemies in WindUp, Dive or Return and never above {CAP_P3} (errors: {bad[:2] or 'none'}); "
            + (", ".join(f"{k} {c}" for k, c in counts.items()) + " (pinned sprites 0-3 never dropped; nothing missing 2 "
               "frames running)" if counts else "no DEBUG counters in this build: drops not measured"))
        safe(False)
        launcher(False)


        # ================================================================ stage 4 part A: waves
        WAVE_ROWS = [{2}, {1, 2}, {0, 1, 2}]                                    # by pattern index
        WAVE_MAX_DIVERS = [[2, 2, 2, 2], [2, 3, 3, 3], [3, 3, 3, 3]]            # by pattern, loop (design "Waves", after the stage 4 tuning)
        WAVE_INTERVAL = [[100, 80, 64, 50], [80, 64, 50, 40], [64, 50, 40, 32]]
        WAVE_SHOTS = [2, 3, 3]                                                  # at loop 0; + 1 a loop

        def stores():
            return int(f"{peek('zp_wave'):02x}"), peek("zp_pattern"), peek("zp_loop")

        def want_stores(n):
            return min(n, 99), (n - 1) % 3, min((n - 1) // 3, 3)

        def panel_wave():
            return "".join(chr(c - PANEL_BG) for c in mem(SCREEN + 960 + 31, 2))

        def last_explosion(e=17):
            """Through the monitor: enemy e is the last one alive and its explosion ends in the next
            frame (the game's own enemy_kill then runs, inside formation_update)."""
            only({e})
            poke("enemy_state", [ENEMY_EXPLODING], e)
            poke("enemy_timer", [1], e)
            poke("explosion_enemy", [e, 0xFF, 0xFF, 0xFF])

        def repark_all():
            """Through the monitor: all 18 Parked again and no diver (after forced launches)."""
            poke("enemy_state", [ENEMY_PARKED] * ENEMIES)
            poke("mux_y", [ROW_Y[e // COLS] for e in range(ENEMIES)], ENEMY0)
            poke("mux_col", [ct[5 + e // COLS] for e in range(ENEMIES)], ENEMY0)
            poke("mux_x_hi", [0] * ENEMIES, ENEMY0)       # formation_update writes columns 4 and 5 every frame
            poke("diver_enemy", [0xFF] * 3)
            poke("zp_divers_active", [0])
            poke("zp_enemies_alive", [ENEMIES])
            poke("explosion_enemy", [0xFF] * 4)

        def hit_player():
            """An enemy shot placed on the ship: the next frame is frame 0 of PlayerDying."""
            poke("zp_player_invuln", [0])
            put_eshot(0, state()[0], 205, 0)
            frame()
            if gstate() != (GS_DYING, 0):
                raise MeasureError(f"hit_player: state {gstate()}")

        safe(False)
        launcher(True)                                # from here the game's own launch timer

        # wave-intro: a wave's Intro, frame by frame (Stage 4 rules 2 and 3). The wave is 5 (pattern
        # index 1, loop 1); the diver slots are filled with junk first, to show the Intro frees them
        to_fight()                                    # the case before may have ended in an Intro
        settle()
        clear_eshots()                                # and left enemy shots in flight
        next_wave_in(2, (4, 0, 1))
        poke("diver_enemy", [3, 0xFF, 5])
        poke("zp_divers_active", [2])
        frame()                                               # Clear's last frame
        before = (phase(), stores(), msg().strip())
        rng0 = tuple(mem(sym["zp_rng_lo"], 2))
        errs, shown_at, launch_at, wave_text, uncovered = [], {}, None, [], True
        for k in range(0, FIRST_LAUNCH + 2):
            frame()
            ph, st = phase(), estates()
            fx, fdir, en = enemies()
            p = FX_START + (k + 1) // 2
            want_fx = p if p <= FX_MAX else 2 * FX_MAX - p
            for e in range(ENEMIES):
                if st[e] == ENEMY_PARKED and e not in shown_at:
                    shown_at[e] = k
                    if en[e][:2] != home(fx)[e] or en[e][3] != ENEMY_COLOURS[e // COLS]:
                        errs.append(f"frame {k}: enemy {e} appeared at {en[e][:2]}, home {home(fx)[e]}")
                if st[e] == ENEMY_WAITING and en[e][1] != MUX_OFF:
                    errs.append(f"frame {k}: waiting enemy {e} shown")
                if st[e] == ENEMY_PARKED and (en[e][:2] != home(fx)[e] or en[e][2] != SHAPE_ENEMY + 2 * (e // COLS) + ((k + 1) // ANIM_FRAMES) % 2):
                    errs.append(f"frame {k}: enemy {e} at {en[e][:2]} shape {en[e][2]:#x}")
            if k < FIRST_LAUNCH and any(q not in (ENEMY_PARKED, ENEMY_WAITING) for q in st):
                errs.append(f"frame {k}: states {st}")
            if launch_at is None and ST_W in st:
                launch_at = k
            if fx != want_fx or peek("zp_enemies_alive") != ENEMIES:
                errs.append(f"frame {k}: fx {fx} (expected {want_fx}), alive {peek('zp_enemies_alive')}")
            if ph != ((PHASE_INTRO, k) if k < INTRO_FRAMES else (PHASE_FIGHT, ph[1])):
                errs.append(f"frame {k}: phase {ph}")
            if msg().strip() == "WAVE 05" and msg()[16:23] == "WAVE 05":
                wave_text.append(k)
                uncovered = uncovered and row9_free()
            elif msg().strip():
                errs.append(f"frame {k}: row 9 '{msg().strip()}'")
            if k == 0 and not (stores() == (5, 1, 1) and peek("zp_divers_active") == 0 and peek("panel_dirty") & 4
                               and list(mem(sym["diver_enemy"], 3)) == [0xFF] * 3 and eshots() == [None] * 3):
                errs.append(f"frame 0: stores {stores()}, divers {peek('zp_divers_active')}, slots {list(mem(sym['diver_enemy'], 3))}")
            if k == 1 and panel_wave() != "05":
                errs.append(f"frame 1: the panel's wave '{panel_wave()}'")
            if k == INTRO_FRAMES:
                t_fight = peek("zp_launch_timer")
            if k < FIRST_LAUNCH and tuple(mem(sym["zp_rng_lo"], 2)) != rng0:
                errs.append(f"frame {k}: rng_next was called")
        row9["WAVE nn"] = uncovered and len(shown_at) == ENEMIES
        launched = [e for e in range(ENEMIES) if estates()[e] & 0x80]
        ok = (not errs and before == ((PHASE_CLEAR, CLEAR_PAUSE - 1), (4, 0, 1), "")
              and [shown_at.get(e) for e in range(ENEMIES)] == [2 * e for e in range(ENEMIES)]
              and wave_text == list(range(INTRO_MSG_FRAMES)) and t_fight == FIGHT_LAUNCH_DELAY and launch_at == FIRST_LAUNCH
              and len(launched) == 1 and launched[0] // COLS in WAVE_ROWS[1])
        rep("wave-intro", ok,
            f"Clear's last frame {before}, then Intro frame by frame for wave 5: frame 0 has the stores at {(5, 1, 1)}, all "
            f"18 alive, divers active 0 and the junk diver slots freed; enemy k Parked at its home in frame "
            f"{[shown_at.get(e) for e in range(ENEMIES)]} (design 2k: the last in 34), the others Waiting and hidden; fx 48 "
            f"in frame 0 and + 1 every 2 frames, the shapes swapping every 16; 'WAVE 05' at columns 16-22 in frames "
            f"{wave_text[0]}-{wave_text[-1]}, erased in {wave_text[-1] + 1}; the panel's wave 05 from frame 1; phase Intro "
            f"through frame {INTRO_FRAMES - 1}, Fight in frame {INTRO_FRAMES} with the launch timer at {t_fight} (design "
            f"{FIGHT_LAUNCH_DELAY}); no rng_next call and no launch before frame {launch_at} (design: {FIRST_LAUNCH} frames after "
            f"the wave appears), enemy {launched} (row "
            f"{[e // COLS for e in launched]}, pattern 2's rows 1-2); errors: {errs[:3] or 'none'}")
        repark_all()

        # wave-stores: 15 waves and the stop at 99, by putting the Clear at its last frame each time
        start_wave(1, run=False)
        seq, errs = [(stores(), msg().strip(), None)], []
        for n in range(2, 16):
            next_wave_in(1)
            frame()
            got = (stores(), msg().strip(), phase())
            frame()
            seq.append(got + (panel_wave(),))
            if got != (want_stores(n), f"WAVE {n:02d}", (PHASE_INTRO, 0)) or panel_wave() != f"{n:02d}":
                errs.append(f"wave {n}: {got}, panel {panel_wave()}")
        poke("zp_wave", [0x97])
        top = []
        for n in range(98, 102):
            next_wave_in(1)
            frame()
            got = (stores(), msg().strip())
            frame()
            top.append(got + (panel_wave(),))
        ok = (not errs and seq[0][:2] == ((1, 0, 0), "WAVE 01")
              and [t[0][0] for t in top] == [98, 99, 99, 99] and [t[1] for t in top] == ["WAVE 98", "WAVE 99", "WAVE 99", "WAVE 99"]
              and [t[2] for t in top] == ["98", "99", "99", "99"] and [t[0][1] for t in top] == [0, 1, 2, 0]
              and all(t[0][2] == 3 for t in top))
        rep("wave-stores", ok,
            f"waves 1-15, (shown wave, pattern index, loop) at each Intro's frame 0: {[q[0] for q in seq]} (pattern cycles "
            f"0-2, loop + 1 when it wraps, sticking at 3 from wave 10), WAVE nn on row 9 and the panel's wave each time; "
            f"from 97: {top} (the shown wave stops at 99, on row 9 and the panel; the pattern carries on cycling); "
            f"errors: {errs[:3] or 'none'}")

        # waves-played: waves 1 to 4 played through, each formation killed through the monitor (17 taken away, the
        # last one's explosion ending by the game's own enemy_kill): the bonus, the pause and the next wave's stores
        start_wave(1, run=False)
        poke("game_score", [0, 0, 0])
        errs, log = [], []
        for n in range(1, 5):
            if stores() != want_stores(n) or msg().strip() != f"WAVE {n:02d}":
                errs.append(f"wave {n}: stores {stores()}, row 9 '{msg().strip()}'")
            to_fight()
            hold_fight = (phase()[0], peek("zp_launch_timer"), msg().strip())
            last_explosion()
            s0 = score()
            frame()                                           # Clear's frame 0
            c0 = (phase(), score() - s0, peek("zp_enemies_alive"), estates().count(ENEMY_DEAD))
            for i in range(1, CLEAR_PAUSE):
                frame()
                if phase() != (PHASE_CLEAR, i) or estates() != [ENEMY_DEAD] * ENEMIES:
                    errs.append(f"wave {n}, Clear frame {i}: phase {phase()}")
            frame()
            log.append((n, hold_fight, c0, phase(), stores()))
            if hold_fight != (PHASE_FIGHT, FIGHT_LAUNCH_DELAY, "") or c0 != ((PHASE_CLEAR, 0), 1000, 0, ENEMIES) or phase() != (PHASE_INTRO, 0):
                errs.append(f"wave {n}: {log[-1]}")
        frame()
        rep("waves-played", not errs and stores() == want_stores(5) and score() == 4000 and panel_score() == "004000"
            and gstate()[0] == GS_PLAY,
            f"waves 1-4 from a wave 1 Intro, in Play: each ran its Intro to Fight (launch timer {FIGHT_LAUNCH_DELAY}, row 9 empty), its last "
            f"explosion ended (17 taken away by the monitor): Clear's frame 0 with + 1,000 in that frame, 74 more frames of "
            f"empty sky, then the next Intro; stores at each wave's end {[q[4] for q in log]}; score {score()}, panel "
            f"{panel_score()}; errors: {errs[:3] or 'none'}")

        # wave-clear-*: the bonus in the frame the last explosion ends, in each game state the design allows, the
        # 75-frame pause whatever the state, and row 9's one message (Stage 4 rules 4 and 6)
        def clear_case(name, lives, when, want):
            """The player is hit (lives as given before the hit); the last explosion ends in PlayerDying's
            frame `when` (frame 0 = the hit). want: {frame: (game state, phase, row 9)} to compare; a
            phase given as PHASE_FIGHT alone is compared without the wave timer (it isn't counted in
            Fight). got["windup"] is the first frame with an enemy in WindUp, got["launch"] the launch
            timer by frame."""
            start_wave(4)
            poke("zp_lives", [lives])
            poke("game_score", [0x00, 0x45, 0x00])
            settle()
            hit_player()
            errs, got = [], {"windup": None, "launch": {}}
            for k in range(1, max(want) + 1):
                if k == when:
                    last_explosion()
                    s0 = score()
                frame()
                if k == when:
                    got["clear"] = (gstate()[0], phase(), score() - s0, peek("panel_dirty") & PANEL_DIRTY_SCORE)
                got["launch"][k] = peek("zp_launch_timer")
                if got["windup"] is None and ST_W in estates():
                    got["windup"] = k
                if k in want:
                    got[k] = (gstate()[0], PHASE_FIGHT if want[k][1] == PHASE_FIGHT == phase()[0] else phase(), msg().strip())
                    if got[k] != want[k]:
                        errs.append(f"frame {k}: {got[k]}, expected {want[k]}")
                if msg().strip() not in ("", "READY", "GAME OVER", "WAVE 05"):
                    errs.append(f"frame {k}: row 9 '{msg().strip()}'")
            return errs, got

        def by_frame(got):
            return dict((k, v) for k, v in got.items() if isinstance(k, int))

        # (a) dying, lives left: the Clear in frame 5, Intro's frame 0 in frame 80, Respawn in frame 100 (Intro's
        # frame 20) with no READY, WAVE nn erased on time in Intro's frame 49 (frame 129, in Respawn), Fight in frame
        # 130 with the state Respawn, Play in frame 150, whose end erases nothing. Fight came first, so Play's 50
        # stands (Stage 4 rules 3 and 8): the timer reads 49 at the end of Play's frame 0 and the first wind-up is
        # Play's frame 49, frame 199. (Until the stage 4 tuning the Intro was 100 frames: Play fell in its frame 70.)
        errs, got = clear_case("dying", 3, 5, {
            79: (GS_DYING, (PHASE_CLEAR, 74), ""), 80: (GS_DYING, (PHASE_INTRO, 0), "WAVE 05"),
            100: (GS_RESPAWN, (PHASE_INTRO, 20), "WAVE 05"), 128: (GS_RESPAWN, (PHASE_INTRO, 48), "WAVE 05"),
            129: (GS_RESPAWN, (PHASE_INTRO, 49), ""), 130: (GS_RESPAWN, PHASE_FIGHT, ""),
            149: (GS_RESPAWN, PHASE_FIGHT, ""), 150: (GS_PLAY, PHASE_FIGHT, ""), 200: (GS_PLAY, PHASE_FIGHT, "")})
        rep("wave-clear-dying", not errs and got["clear"] == (GS_DYING, (PHASE_CLEAR, 0), 1000, PANEL_DIRTY_SCORE)
            and got["launch"][150] == PLAY_LAUNCH_TIMER - 1 and got["windup"] == 150 + PLAY_LAUNCH_TIMER - 1,
            f"the last explosion ended in PlayerDying's frame 5 (lives left): (state, phase, bonus, score dirty) "
            f"{got['clear']}; (state, phase, row 9) by frame (a phase of 0 alone is Fight): {by_frame(got)}: the "
            f"pause ran 75 frames while he was dying, Respawn began in Intro's frame 20 and wrote no READY, WAVE 05 was "
            f"erased in Intro's frame 49 (frame 129) and Fight began in frame 130, both in Respawn, whose end (frame "
            f"150) erased nothing; the launch timer read {got['launch'][130]} at the end of Fight's first frame (not "
            f"counted: the state is Respawn) and {got['launch'][150]} at the end of Play's first frame (Play's 50, set "
            f"later, stands); first wind-up in frame {got['windup']} (design: Play's frame 49 = 199); errors: "
            f"{errs[:3] or 'none'}")

        # (b) Respawn's first frame in a Clear: no READY then or later; WAVE nn written during Respawn stays through
        # Respawn's end (frame 150 = Intro's frame 15) to Intro's frame 49 (frame 184). This is Stage 4 rule 8's
        # "other order", Play entered before Fight: Fight's 10 stands, and the first wind-up is 10 frames after
        # Fight (frame 185): frame 195
        errs, got = clear_case("dying-late", 3, 60, {
            100: (GS_RESPAWN, (PHASE_CLEAR, 40), ""), 134: (GS_RESPAWN, (PHASE_CLEAR, 74), ""),
            135: (GS_RESPAWN, (PHASE_INTRO, 0), "WAVE 05"), 150: (GS_PLAY, (PHASE_INTRO, 15), "WAVE 05"),
            183: (GS_PLAY, (PHASE_INTRO, 48), "WAVE 05"), 184: (GS_PLAY, (PHASE_INTRO, 49), ""),
            185: (GS_PLAY, PHASE_FIGHT, ""), 196: (GS_PLAY, PHASE_FIGHT, "")})
        rep("wave-clear-respawn-in-clear", not errs and got["clear"] == (GS_DYING, (PHASE_CLEAR, 0), 1000, PANEL_DIRTY_SCORE)
            and got["launch"][185] == FIGHT_LAUNCH_DELAY and got["windup"] == 185 + FIGHT_LAUNCH_DELAY,
            f"the last explosion ended in PlayerDying's frame 60: {got['clear']}; Respawn's frame 0 fell in Clear's frame "
            f"40: row 9 empty through Respawn (no READY); the Intro wrote WAVE 05 in Respawn's frame 35 and Respawn's end "
            f"left it, until Intro's frame 49: {by_frame(got)}; Play was entered before Fight (the design's \"other "
            f"order\"): launch timer {got['launch'][185]} at the end of Fight's first frame (frame 185), first wind-up in "
            f"frame {got['windup']} (design: 10 frames after Fight = 195); errors: {errs[:3] or 'none'}")

        # (c) in Respawn, READY showing (written in Fight): the bonus; READY erased at Respawn's end, the Intro later
        start_wave(4)
        poke("game_score", [0, 0, 0])
        settle()
        hit_player()
        for _ in range(110):
            frame()
        r10 = (gstate(), phase(), msg().strip())
        last_explosion()
        frame()                                               # Respawn's frame 11
        c0 = (gstate(), phase(), score(), msg().strip())
        seen = {}
        for k in range(12, 90):
            frame()
            seen[k] = (gstate()[0], phase(), msg().strip())
        ok = (r10 == ((GS_RESPAWN, 10), (PHASE_FIGHT, r10[1][1]), "READY") and c0 == ((GS_RESPAWN, 11), (PHASE_CLEAR, 0), 1000, "READY")
              and seen[49] == (GS_RESPAWN, (PHASE_CLEAR, 38), "READY") and seen[50] == (GS_PLAY, (PHASE_CLEAR, 39), "")
              and seen[85] == (GS_PLAY, (PHASE_CLEAR, 74), "") and seen[86] == (GS_PLAY, (PHASE_INTRO, 0), "WAVE 05"))
        rep("wave-clear-respawn", ok,
            f"Respawn began in Fight: READY written ({r10}); the last explosion ended in its frame 11: {c0} (+ 1,000 in "
            f"Respawn); READY erased at Respawn's end {seen[49]} -> {seen[50]}; Intro 75 frames after the Clear: "
            f"{seen[85]} -> {seen[86]}")

        # (d) the last life: the bonus is still paid, the wave timer stops, GameOver over an empty sky, and the
        # high score (taken in GameOver's frame 0) has the bonus in it
        errs, got = clear_case("last", 1, 16, {
            17: (GS_DYING, (PHASE_CLEAR, 0), ""), 99: (GS_DYING, (PHASE_CLEAR, 0), ""),
            100: (GS_OVER, (PHASE_CLEAR, 0), "GAME OVER"), 250: (GS_OVER, (PHASE_CLEAR, 0), "GAME OVER")})
        hi = mem(sym["game_hiscore"], 3).hex()
        rep("wave-clear-last-life", not errs and got["clear"] == (GS_DYING, (PHASE_CLEAR, 0), 1000, PANEL_DIRTY_SCORE)
            and hi == "005500" and estates() == [ENEMY_DEAD] * ENEMIES and peek("zp_lives") == 0,
            f"the last life lost, the last explosion ending in PlayerDying's frame 16: {got['clear']} (+ 1,000 paid to a "
            f"player with no lives); the wave timer stood still from then on: "
            f"{by_frame(got)}; GameOver in frame 100 over an empty sky, no Intro and "
            f"no WAVE nn; high score {hi} (score 4,500 + the bonus, taken in GameOver's frame 0); errors: {errs[:3] or 'none'}")
        poke("game_hiscore", [0x00, 0x50, 0x00])
        poke("panel_dirty", [peek("panel_dirty") | 8])
        end_game()                                            # GameOver's end: a new game for the cases below

        # clear-shot: what can hit the player outside Fight (rule 7): an enemy shot still in flight in a Clear
        start_wave(2)
        settle()
        last_explosion()
        frame()
        for _ in range(9):
            frame()
        lives0, ph0 = peek("zp_lives"), phase()
        put_eshot(0, state()[0], 205, 0)
        frame()
        rep("clear-shot", ph0 == (PHASE_CLEAR, 9) and gstate() == (GS_DYING, 0) and peek("zp_lives") == lives0 - 1
            and phase() == (PHASE_CLEAR, 10),
            f"an enemy shot over the ship in Clear's frame 10: state {gstate()}, lives {lives0} -> {peek('zp_lives')}: an "
            f"ordinary death, the Clear carrying on ({phase()})")
        revive()

        # wave-timeline: the design's worked case (Stage 4 rule 8). The player rams the last enemy in frame d
        def ram_last(lives):
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

        d0 = ram_last(3)
        t, first_w = {}, None
        for k in range(1, 252):
            frame()
            t[k] = dict(gs=gstate(), ph=phase(), msg=msg().strip(), score=score(), ship=ship()[:2],
                        launch=peek("zp_launch_timer"), inv=peek("zp_player_invuln"))
            if first_w is None and ST_W in estates():
                first_w = k
        # Stage 4 rule 8 after the tuning: d + 140 WAVE nn erased, d + 141 Fight (the state is Respawn: the launch
        # timer isn't counted, and its value there can't be seen in play, so it is printed, not judged), d + 150
        # Play, which sets the timer to 50 (it reads 49 at that frame's end, as built in stage 3), d + 199 the
        # first launch. (As first built: erased d + 166, Fight d + 191, launch d + 241.)
        ok = (d0 == ((GS_DYING, 0), ENEMY_EXPLODING, 100, 2)
              and t[15]["ph"][0] == PHASE_FIGHT and t[16]["ph"] == (PHASE_CLEAR, 0) and (t[15]["score"], t[16]["score"]) == (100, 1100)
              and t[90]["ph"] == (PHASE_CLEAR, 74) and t[91]["ph"] == (PHASE_INTRO, 0) and (t[90]["msg"], t[91]["msg"]) == ("", "WAVE 04")
              and t[99]["gs"] == (GS_DYING, 99) and t[100]["gs"] == (GS_RESPAWN, 0) and t[100]["ship"] == (X_START, PLAYER_Y)
              and t[100]["msg"] == "WAVE 04" and t[139]["msg"] == "WAVE 04" and t[140]["msg"] == ""
              and t[140]["ph"] == (PHASE_INTRO, 49) and t[141]["ph"][0] == PHASE_FIGHT and t[141]["gs"][0] == GS_RESPAWN
              and t[149]["gs"][0] == GS_RESPAWN and t[150]["gs"][0] == GS_PLAY and t[150]["msg"] == ""
              and t[150]["launch"] == PLAY_LAUNCH_TIMER - 1
              and first_w == 199 and t[248]["inv"] == 1 and t[249]["inv"] == 0)
        rep("wave-timeline", ok,
            f"the design's worked case: the last enemy rams in frame d (state, enemy, score, lives {d0}); d + 16: Clear "
            f"{t[16]['ph']}, score {t[15]['score']} -> {t[16]['score']}; d + 91: Intro {t[91]['ph']}, row 9 '{t[91]['msg']}'; "
            f"d + 100: Respawn {t[100]['gs']}, the ship at {t[100]['ship']}, row 9 still '{t[100]['msg']}' (no READY); "
            f"WAVE nn last shown in d + 139, erased in d + 140; d + 141: Fight, in Respawn {t[141]['gs']}, the launch "
            f"timer {t[141]['launch']} and not counted (still {t[149]['launch']} in d + 149); d + 150: Play {t[150]['gs']}, "
            f"launch timer {t[150]['launch']} (set to 50, counted once in that frame); first launch in d + {first_w} "
            f"(design 199); invulnerability timer {t[248]['inv']} at the end of d + 248 and {t[249]['inv']} at the end of "
            f"d + 249: the first frame he can be hit is d + 250")
        safe(True)
        repark_all()

        d0 = ram_last(1)
        t = {}
        for k in range(1, 131):
            frame()
            t[k] = (gstate(), phase(), msg().strip(), score(), estates().count(ENEMY_DEAD))
        ok = (d0 == ((GS_DYING, 0), ENEMY_EXPLODING, 100, 0) and t[16] == ((GS_DYING, 16), (PHASE_CLEAR, 0), "", 1100, ENEMIES)
              and t[99] == ((GS_DYING, 99), (PHASE_CLEAR, 0), "", 1100, ENEMIES)
              and t[100] == ((GS_OVER, 0), (PHASE_CLEAR, 0), "GAME OVER", 1100, ENEMIES) and t[130][1:] == t[100][1:])
        rep("wave-timeline-last-life", ok,
            f"the same with the last life: d + 16 {t[16]} (Clear and + 1,000), the wave timer stopped; d + 100 {t[100]}: "
            f"GameOver over an empty sky (18 Dead), still so in d + 130")
        end_game()
        safe(False)

        # wave-settings-*: what each wave's settings are in force, against the design's tables, for waves 1, 2, 3, 6,
        # 9 and 12. Launches are forced by putting the launch timer at 1 (the launcher's own code then decides)
        for n in (1, 2, 3, 6, 9, 12):
            start_wave(n)
            pat, loop = want_stores(n)[1:]
            safe(True)
            poke("zp_launch_timer", [200])                    # Fight's own first launch (10 frames in) is held off
                                                              # through the 17 measuring frames: every launch below
                                                              # is one the script asks for
            fxs = [peek("zp_fx")] + [(frame(), peek("zp_fx"))[1] for _ in range(8)]
            drift = sum(1 for a_, b_ in zip(fxs, fxs[1:]) if a_ != b_)
            two = sum((frame(), peek("diver_two") >> 7)[1] for _ in range(8))
            put_eshot(0, 100, 100, 0)
            frame()
            dy = eshots()[0][1] - 100
            clear_eshots()
            poke("zp_rng_lo", [0x5A, 0x1D])
            picked, reloads = [], set()
            for i in range(5):                                # until the wave's maximum are out, and past it
                st0 = estates()
                poke("zp_launch_timer", [1])
                frame()
                new = [e for e in range(ENEMIES) if st0[e] == ENEMY_PARKED and estates()[e] == ST_W]
                picked += new
                if new:
                    reloads.add(peek("zp_launch_timer"))
                    if len(picked) == 1:
                        t_launch = i
            cap, e0 = peek("zp_divers_active"), picked[0]
            windup = 4 - t_launch                             # frames since e0's launch frame (t = 0)
            while estates()[e0] == ST_W and windup < 40:
                frame()
                windup += 1
            shots = peek("enemy_shots", e0)
            repark_all()
            frame()
            forced = {}
            others = [r for r in range(3) if r not in WAVE_ROWS[pat]]
            for r in sorted(WAVE_ROWS[pat]):                  # a wave row and a row that isn't: the wave row is picked
                for q in others:
                    only(set(range(r * COLS, r * COLS + COLS)) | set(range(q * COLS, q * COLS + COLS)))
                    for i in range(3):
                        poke("zp_launch_timer", [1])
                        frame()
                    forced[(r, q)] = sorted({e // COLS for e in range(ENEMIES) if estates()[e] & 0x80})
                    repark_all()
                    frame()
            want = dict(rows=WAVE_ROWS[pat], cap=WAVE_MAX_DIVERS[pat][loop], interval={WAVE_INTERVAL[pat][loop]},
                        two=[0, 2, 4, 4][loop], shots=WAVE_SHOTS[pat] + loop, dy=ESHOT_DY[loop], windup=WINDUP[loop],
                        drift=8 // DRIFT_PERIOD[loop])
            got = dict(rows={e // COLS for e in picked}, cap=cap, interval=reloads, two=two, shots=shots, dy=dy,
                       windup=windup, drift=drift)
            ok = (stores() == want_stores(n) and got["rows"] <= want["rows"] and len(picked) == want["cap"]
                  and all(got[k] == want[k] for k in want if k != "rows") and all(v == [r] for (r, q), v in forced.items()))
            rep(f"wave-settings-{n}", ok,
                f"wave {n} (stores {stores()}): rows that dive {sorted(got['rows'])} of {sorted(want['rows'])}"
                + (f", and with a wave row and another row Parked the wave row was picked: {forced}" if forced else "")
                + f"; divers at once {got['cap']} ({len(picked)} launched in 5 tries; design {want['cap']}); launch interval "
                f"{sorted(got['interval'])} (design {sorted(want['interval'])}); frames in 8 with 2 path steps {got['two']} "
                f"(design {want['two']}: path speed x {[1, 1.25, 1.5, 1.5][loop]}); shots this dive {got['shots']} (design "
                f"{want['shots']}, capped by the path's fire steps: Hook 2, Sweep 4, Plunge 3, as dive-loop*); enemy shot dy "
                f"{got['dy']} (design {want['dy']}); wind-up {got['windup']} frames (design {want['windup']}); drift steps "
                f"in 8 frames {got['drift']} (design {want['drift']})")
        safe(False)

        # seed: two games started in different title frames get different seeds and launch different enemies
        # (wave 1: a launch every 100 frames from wave frame 60, each a row 2 enemy: 8 in 760 frames, at 60, 160, ...
        # 760. A Hook is out for 114 frames, so never 2 out when the timer runs out. Until the stage 4 tuning: every
        # 150 from frame 150, 5 launches)
        seqs = {}
        for tap in (TITLE_FIRE_FRAME, 41):
            safe(False)
            to_title()
            pressed = start_game(tap_frame=tap)
            seed = tuple(mem(sym["zp_rng_lo"], 2))
            safe(True)
            picks, at, prev = [], [], estates()
            for f in range(1, 761):                           # f = the wave's frame (the new game's frame is 0)
                frame()
                st = estates()
                new = [e for e in range(ENEMIES) if prev[e] == ENEMY_PARKED and st[e] == ST_W]
                picks += new
                at += [f] * len(new)
                prev = st
            seqs[tap] = (pressed, seed, picks, at)
        safe(False)
        a_, b_ = seqs[TITLE_FIRE_FRAME], seqs[41]
        rep("seed", (a_[0], b_[0]) == (TITLE_FIRE_FRAME, 41) and a_[1] != b_[1] and a_[2] != b_[2] and len(a_[2]) == len(b_[2]) == 8
            and all(e // COLS == 2 for e in a_[2] + b_[2]) and a_[3] == b_[3] == [FIRST_LAUNCH + 100 * i for i in range(8)],
            f"a game started by a press in the title's frame {a_[0]}: generator state after the press {a_[1]}, the first "
            f"eight enemies launched {a_[2]}; one started in the title's frame {b_[0]}: {b_[1]}, {b_[2]} (different "
            f"seeds, different launch sequences; all row 2, wave 1's); launched in wave frames {a_[3]} in both (design: "
            f"the first wind-up in frame 60, then every 100)")

        rep("row9-uncovered", row9 == {"READY": True, "GAME OVER": True, "WAVE nn": True},
            f"with all 18 enemies Parked, no Parked enemy's lines (Y + 1 to Y + 21) touch row 9's (123-130), while each "
            f"message showed: {row9}")

        # ================================================================ stage 4 part B: sound
        # What is ASKED FOR is read from sfx_request at game_update_end (before the tick takes it), what
        # PLAYS from sfx_cur at the next stop (after the tick), both effect + 1, one byte a voice (the
        # module's voices 0-2 = the design's 1-3). The SID can't be read back. From here every
        # execution of sfx_play also stops the machine, so the script sees each CALL in a frame, in
        # order, with the effect in A; and a store to $D418 (the volume) would stop it too.
        SFX = {n: sym["SFX_" + n] + 1 for n in ("PLAYER_SHOT", "ENEMY_SHOT", "DIVE", "ENEMY_EXPLOSION", "PLAYER_HIT_A",
                                                "PLAYER_HIT_B", "WAVE_START", "WAVE_CLEAR", "START", "GAME_OVER")}
        SFX_NAME = {v: k.lower() for k, v in SFX.items()}
        SFX_NAME[0] = "-"
        PS, ES, DV, EX = SFX["PLAYER_SHOT"], SFX["ENEMY_SHOT"], SFX["DIVE"], SFX["ENEMY_EXPLOSION"]
        HA, HB, WS, WC = SFX["PLAYER_HIT_A"], SFX["PLAYER_HIT_B"], SFX["WAVE_START"], SFX["WAVE_CLEAR"]
        ST, GO = SFX["START"], SFX["GAME_OVER"]
        calls, vol_writes = [], [0]
        cp_play = mon.checkpoint_set(sym["sfx_play"], sym["sfx_play"], CPU_OP_EXEC)
        cp_vol = mon.checkpoint_set(0xD418, 0xD418, CPU_OP_STORE)

        def frame(pressed=None):      # replaces frame() for every helper from here on
            """As frame() above, and: `calls` = the effects (+ 1) sfx_play was called with in this frame, in order."""
            calls.clear()
            if hold["set"]:
                hold["n"] -= 1
                if hold["n"] <= 0:
                    for label, value in hold["set"].items():
                        mon.mem_set(sym[label], bytes([value]))
                    hold["n"] = HOLD_EVERY
            if pressed is not None:
                mon.joyport_set(PORT2, ~pressed & 0x1F)
            while True:
                mon.exit()
                if not mon.wait_stopped(STOP_TIMEOUT):
                    mon.ping()
                    raise MeasureError("game_update_end not reached: jam?")
                regs = mon.registers()
                if regs["PC"] == sym["game_update_end"]:
                    return state()
                if regs["PC"] == sym["sfx_play"]:
                    calls.append((regs["A"] & 255) + 1)
                else:
                    vol_writes[0] += 1

        def req():
            return tuple(mem(sym["sfx_request"], 3))

        def cur():
            return tuple(mem(sym["sfx_cur"], 3))

        def nm(t):
            return "(" + ", ".join(SFX_NAME.get(x, hex(x)) for x in t) + ")"

        def quiet():
            """Nothing pressed until no voice is playing, nothing is asked for and no player shot is in flight."""
            for _ in range(300):
                _, shots = frame(0)
                if cur() == (0, 0, 0) and req() == (0, 0, 0) and shots == [None, None] and peek("zp_player_cooldown") == 0:
                    return
            raise MeasureError(f"quiet: still playing {cur()}")

        def held(v):
            """Frames voice v goes on playing what it plays now, this stop included (nothing pressed)."""
            what, n = cur()[v], 0
            while cur()[v] == what and n < 200:
                frame(0)
                n += 1
            return n

        def put_diver(slot, e, x, y, fire):
            """Through the monitor: enemy e in Dive in diver slot `slot`, on its path's first segment;
            with fire, its next step is its first fire step (eshot_spawn runs in the next frame)."""
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

        def pshot_under(i, e):
            """Player shot i placed so that it is inside enemy e's box in the next frame."""
            x, y = epos(e)
            put_pshot(i, x, y + 18)

        # sfx-idle: nothing happens (the formation parked and drifting, the ship still, then moving): nothing is
        # asked for and nothing plays
        safe(False)
        launcher(False)
        respawn()
        quiet()
        bad = []
        for f in range(120):
            frame(BITS["left"] if 40 <= f < 60 else BITS["right"] if 60 <= f < 80 else 0)
            if req() != (0, 0, 0) or cur() != (0, 0, 0) or calls:
                bad.append((f, req(), cur(), list(calls)))
        rep("sfx-idle", not bad and gstate()[0] == GS_PLAY and phase()[0] == PHASE_FIGHT,
            f"120 frames of Play and Fight with a full formation drifting and animating, the ship still, then moving "
            f"left and right, no fire: sfx_play never called, sfx_request (0, 0, 0) and sfx_cur (0, 0, 0) in every "
            f"frame; exceptions: {bad[:2] or 'none'}")

        # sfx-player-shot
        frame(BITS["fire"])
        r0, c0, shot0 = req(), list(calls), state()[1]
        frame(0)
        r1, k1 = req(), cur()
        n = held(0)
        rep("sfx-player-shot", r0 == (PS, 0, 0) and c0 == [PS] and r1 == (0, 0, 0) and k1 == (PS, 0, 0) and shot0[0] is not None,
            f"a shot spawns: in that frame sfx_play is called once, with {nm(c0)}, sfx_request {nm(r0)}; one frame later "
            f"the request is taken {nm(r1)} and sfx_cur is {nm(k1)}: the player shot on voice 1; it holds the voice "
            f"for {n} frames after the tick that started it (design: 8)")

        # sfx-enemy-shot, sfx-enemy-shot-x3, sfx-shots-same-frame: divers placed at a fire step (monitor); the shots
        # are spawned by the game's eshot_spawn
        safe(True)
        respawn()
        quiet()
        clear_eshots()
        put_diver(0, 12, 100, 150, True)
        poke("zp_divers_active", [1])
        frame(0)
        r0, c0, e0 = req(), list(calls), eshots()
        frame(0)
        k1 = cur()
        n = held(0)
        rep("sfx-enemy-shot", r0 == (ES, 0, 0) and c0 == [ES] and sum(x is not None for x in e0) == 1 and k1 == (ES, 0, 0),
            f"a diver's fire step spawns a shot ({e0}): sfx_play called once, with {nm(c0)}, sfx_request {nm(r0)}; one "
            f"frame later sfx_cur {nm(k1)}: the enemy shot on voice 1, for {n} frames (design: 6)")
        clear_eshots()
        for slot, (e, x) in enumerate([(0, 60), (6, 150), (12, 240)]):
            put_diver(slot, e, x, 150, True)
        poke("zp_divers_active", [3])
        frame(0)
        r0, c0, e0 = req(), list(calls), eshots()
        frame(0)
        k1 = cur()
        rep("sfx-enemy-shot-x3", r0 == (ES, 0, 0) and c0 == [ES] and sum(x is not None for x in e0) == 3 and k1 == (ES, 0, 0)
            and peek("eshot_fired") == 0,
            f"three divers fire in one frame (three shots spawned: {e0}): sfx_play is called ONCE, with {nm(c0)} "
            f"(the flag eshot_spawn sets, tested at diver_update's end, and cleared: {peek('eshot_fired')}); "
            f"sfx_request {nm(r0)}, then sfx_cur {nm(k1)}")
        respawn()
        quiet()
        clear_eshots()
        put_diver(0, 12, 100, 150, True)
        poke("zp_divers_active", [1])
        frame(BITS["fire"])
        r0, c0, e0, p0 = req(), list(calls), eshots(), state()[1]
        frame(0)
        k1 = cur()
        frame(0)
        frame(0)
        put_diver(0, 12, 100, 150, True)          # 3 frames into the player's shot sound: an enemy shot
        frame(0)
        r2, c2 = req(), list(calls)
        frame(0)
        k2 = cur()
        rep("sfx-shots-same-frame", r0 == (PS, 0, 0) and c0 == [ES, PS] and k1 == (PS, 0, 0) and sum(x is not None for x in e0) == 1
            and p0[0] is not None and r2 == (ES, 0, 0) and c2 == [ES] and k2 == (ES, 0, 0),
            f"an enemy shot and a player shot spawn in the same frame: sfx_play calls in order {nm(c0)} (diver_update, "
            f"then player_update), sfx_request {nm(r0)}: equal priority on voice 1, the later call survives, and "
            f"sfx_cur is {nm(k1)}: the player's shot is heard (the design's same-frame rule). 4 frames later, the "
            f"player's shot sound still running, an enemy shot spawns: asked {nm(r2)}, then sfx_cur {nm(k2)}: the "
            f"two shots cut each other off")

        # sfx-dive: the game's own launcher (the launch timer put at 1)
        respawn()
        quiet()
        launcher(True)
        poke("zp_launch_timer", [1])
        frame(0)
        r0, c0, w0 = req(), list(calls), estates().count(ST_W)
        frame(0)
        k1 = cur()
        for _ in range(4):
            frame(0)
        poke("zp_launch_timer", [1])
        frame(0)
        r2, c2, w2 = req(), list(calls), peek("zp_divers_active")
        frame(0)
        k2 = cur()
        launcher(False)
        n = held(2)
        rep("sfx-dive", r0 == (0, 0, DV) and c0 == [DV] and w0 == 1 and k1 == (0, 0, DV) and r2 == (0, 0, DV) and c2 == [DV]
            and w2 == 2 and k2 == (0, 0, DV),
            f"a launch (WindUp's frame 0, {w0} enemy in WindUp): sfx_play called once, with {nm(c0)}, sfx_request "
            f"{nm(r0)}, then sfx_cur {nm(k1)}: the dive on voice 3; a second launch 6 frames later ({w2} divers out) "
            f"asks again {nm(r2)} and the dive sound restarts: sfx_cur {nm(k2)}, held {n} frames from that start "
            f"(design: 30, running on into the dive: wind-up 24 frames at loop 0)")

        # sfx-explosion, sfx-explosion-x2: player shots placed (monitor) one frame below an enemy's box
        respawn()
        quiet()
        pshot_under(0, 15)
        frame(0)
        r0, c0, s0 = req(), list(calls), estates()[15]
        frame(0)
        k1 = cur()
        n = held(1)
        rep("sfx-explosion", r0 == (0, EX, 0) and c0 == [EX] and s0 == ENEMY_EXPLODING and k1 == (0, EX, 0),
            f"a player shot hits enemy 15 (Exploding: {s0 == ENEMY_EXPLODING}): sfx_play called once, with {nm(c0)}, "
            f"sfx_request {nm(r0)}, then sfx_cur {nm(k1)}: the enemy explosion on voice 2, for {n} frames (design: 16)")
        quiet()
        pshot_under(0, 16)
        pshot_under(1, 14)
        frame(0)
        r0, c0, s0 = req(), list(calls), [estates()[e] for e in (16, 14)]
        frame(0)
        k1 = cur()
        rep("sfx-explosion-x2", r0 == (0, EX, 0) and c0 == [EX] and s0 == [ENEMY_EXPLODING] * 2 and k1 == (0, EX, 0),
            f"two shots hit enemies 16 and 14 in the same frame (both Exploding: {s0 == [ENEMY_EXPLODING] * 2}): "
            f"sfx_play is called ONCE, with {nm(c0)} (collide_hit, tested at collide_update's end); sfx_request "
            f"{nm(r0)}, sfx_cur {nm(k1)}: one explosion sound")

        # sfx-player-hit: an enemy shot on the ship; then, in PlayerDying, an enemy is shot: asked for, not heard
        safe(False)
        respawn()
        poke("zp_lives", [3])
        quiet()
        hit_player()
        r0, c0 = req(), list(calls)
        frame(0)
        k1 = cur()
        for _ in range(8):
            frame(0)
        pshot_under(0, 15)
        frame(0)
        r2, c2, s2 = req(), list(calls), estates()[15]
        frame(0)
        k2 = cur()
        n = 10 + held(1)
        rep("sfx-player-hit", r0 == (0, HA, HB) and c0 == [HA, HB] and k1 == (0, HA, HB) and r2 == (0, EX, 0) and c2 == [EX]
            and s2 == ENEMY_EXPLODING and k2 == (0, HA, HB),
            f"the player is hit by a shot (frame 0 of PlayerDying): sfx_play called twice, {nm(c0)}, A then B; "
            f"sfx_request {nm(r0)}, then sfx_cur {nm(k1)}: the hit on voices 2 and 3 together. 10 frames later a "
            f"shot still in flight kills enemy 15: the explosion is asked for {nm(r2)} and dropped at the tick "
            f"(priority 2 under 3): sfx_cur stays {nm(k2)}; the hit holds voice 2 for {n} frames (design: 60, in "
            f"which no explosion or dive is heard)")
        revive()

        # sfx-hit-and-explosion: a shot kills an enemy in the frame an enemy shot kills the player
        quiet()
        pshot_under(0, 14)
        poke("zp_player_invuln", [0])
        put_eshot(0, state()[0], 205, 0)
        frame(0)
        r0, c0, g0, s0 = req(), list(calls), gstate(), estates()[14]
        frame(0)
        k1 = cur()
        rep("sfx-hit-and-explosion", r0 == (0, HA, HB) and c0 == [HA, HB] and g0 == (GS_DYING, 0) and s0 == ENEMY_EXPLODING
            and k1 == (0, HA, HB),
            f"a player shot kills enemy 14 and an enemy shot kills the player in the same frame (PlayerDying frame 0: "
            f"{g0 == (GS_DYING, 0)}, the enemy Exploding: {s0 == ENEMY_EXPLODING}): sfx_play calls {nm(c0)}: the hit's "
            f"two and NO explosion request; sfx_request {nm(r0)}, sfx_cur {nm(k1)}")
        revive()

        # sfx-ram: a diver on the ship: the player hit, not the enemy explosion
        respawn()
        quiet()
        px = state()[0]
        put_diver(0, 14, px + 2, 216, False)
        poke("enemy_seg", [peek("path_first", 4) + 4], 14)        # the Hook's skim: (-2, 0)
        poke("enemy_left", [6], 14)
        poke("zp_divers_active", [1])
        poke("zp_player_invuln", [0])
        sc0 = score()
        frame(0)
        r0, c0, g0, s0, sc1 = req(), list(calls), gstate(), estates()[14], score()
        frame(0)
        k1 = cur()
        rep("sfx-ram", r0 == (0, HA, HB) and c0 == [HA, HB] and g0 == (GS_DYING, 0) and s0 == ENEMY_EXPLODING and k1 == (0, HA, HB)
            and sc1 == sc0 + DIVE_SCORE[2],
            f"a diver rams the ship (PlayerDying frame 0: {g0 == (GS_DYING, 0)}; the diver Exploding and scored, "
            f"+ {sc1 - sc0}): sfx_play calls {nm(c0)}: the hit's two and NO explosion request (the design: a ram plays "
            f"the player hit, not the enemy explosion); sfx_request {nm(r0)}, sfx_cur {nm(k1)}")
        revive()

        # sfx-wave-start: Intro's frame 0 of a later wave; the player's shot is heard over it
        safe(True)
        quiet()
        start_wave(5, run=False)
        r0, c0, ph0 = req(), list(calls), phase()
        frame(0)
        k1 = cur()
        frame(BITS["fire"])
        r2 = req()
        frame(0)
        k2 = cur()
        n = 2 + held(2)
        rep("sfx-wave-start", r0 == (0, 0, WS) and c0 == [WS] and ph0 == (PHASE_INTRO, 0) and k1 == (0, 0, WS) and r2 == (PS, 0, 0)
            and k2 == (PS, 0, WS),
            f"Intro's frame 0 (wave 5): sfx_play called once, with {nm(c0)}, sfx_request {nm(r0)}, then sfx_cur "
            f"{nm(k1)}: wave start on voice 3; a shot fired while it plays: sfx_cur {nm(k2)} (voice 1 is free for "
            f"the player's shots); the notes hold voice 3 for {n} frames (design: 30)")

        # sfx-wave-clear: the last explosion ends (monitor: enemy 17 one frame from the end of its explosion) in
        # a frame the player fires
        to_fight()
        quiet()
        last_explosion()
        sc0 = score()
        frame(BITS["fire"])
        r0, c0, ph0, sc1 = req(), list(calls), phase(), score()
        frame(0)
        k1 = cur()
        for _ in range(12):
            frame(0)
        frame(BITS["fire"])
        r2 = req()
        frame(0)
        k2 = cur()
        n = 14 + held(2)
        rep("sfx-wave-clear", r0 == (PS, 0, WC) and c0 == [WC, PS] and ph0 == (PHASE_CLEAR, 0) and sc1 == sc0 + 1000
            and k1 == (PS, 0, WC) and r2 == (PS, 0, 0) and k2 == (PS, 0, WC),
            f"Clear's frame 0 (the last explosion ends, + {sc1 - sc0}), fire pressed in the same frame: sfx_play "
            f"calls {nm(c0)} (formation_update, then player_update), sfx_request {nm(r0)}, then sfx_cur {nm(k1)}: "
            f"wave clear on voice 3 and the player's shot on voice 1, not silenced; a second shot 14 frames into "
            f"the notes: sfx_cur {nm(k2)}; the notes hold voice 3 for {n} frames (design: 40)")

        # sfx-title, sfx-start: no sound is asked for at the title; the press asks for the start note; the new game
        # 6 frames later asks for wave start
        safe(False)
        quiet()
        to_title()
        bad = [(f, req(), list(calls)) for f in range(70) if (frame(0), req() != (0, 0, 0) or calls)[1]]
        k0 = cur()
        frame(BITS["fire"])
        r0, c0, g0 = req(), list(calls), gstate()[0]
        frame(0)
        k1 = cur()
        seq = []
        for f in range(2, 7):
            frame(0)
            seq.append((req(), list(calls)))
        g6, ph6 = gstate()[0], phase()
        n = 0
        while cur()[0] == ST and n < 100:
            frame(0)
            n += 1
        rep("sfx-start", not bad and k0 == (0, 0, 0) and r0 == (ST, 0, 0) and c0 == [ST] and g0 == GS_TITLE and k1 == (ST, 0, 0)
            and all(x == ((0, 0, 0), []) for x in seq[:4]) and seq[4] == ((0, 0, WS), [WS]) and g6 == GS_PLAY
            and ph6 == (PHASE_INTRO, 0) and 6 + n <= NEW_GAME_COOLDOWN + 6,
            f"70 title frames (the blink, the shapes swapping): sfx_play never called ({len(bad)} frames otherwise), "
            f"nothing playing {nm(k0)}; the press: sfx_play called once, with {nm(c0)}, sfx_request {nm(r0)}, then "
            f"sfx_cur {nm(k1)}: the start note on voice 1; no request in the 4 erase frames after it; the new game's "
            f"frame (press + 6) asks for {nm(seq[4][0])}; the start note is over {6 + n} frames after the press, "
            f"before the ship can fire (press + 6 + 25)")

        # sfx-game-over: the last life. Nothing is asked for in PlayerDying's frames 1-99; GameOver's frame 0
        launcher(False)
        to_fight()
        poke("zp_lives", [1])
        quiet()
        hit_player()
        r0, bad = req(), []
        for f in range(1, 100):
            frame(0)
            if req() != (0, 0, 0) or calls:
                bad.append((f, req(), list(calls)))
        kb = cur()
        frame(0)
        r1, c1, g1 = req(), list(calls), gstate()
        frame(0)
        k1 = cur()
        n = held(0)
        rep("sfx-game-over", r0 == (0, HA, HB) and not bad and kb == (0, 0, 0) and r1 == (GO, 0, 0) and c1 == [GO]
            and g1 == (GS_OVER, 0) and k1 == (GO, 0, 0),
            f"the last life: the hit {nm(r0)}; no request in PlayerDying's frames 1-99 ({len(bad)} otherwise) and "
            f"the rumble over before GameOver (sfx_cur {nm(kb)} at frame 99); GameOver's frame 0: sfx_play called "
            f"once, with {nm(c1)}, sfx_request {nm(r1)}, then sfx_cur {nm(k1)}: game over on voice 1, for {n} frames "
            f"(design: 50)")

        # sfx-volume: the SID's volume register is written by sfx_init and never again
        d418 = mem(0xD418)[0]
        shadow = peek("sfx_shadow", 24) if "sfx_shadow" in sym else None
        rep("sfx-volume", vol_writes[0] == 0 and d418 == 0x0F and shadow in (None, 0x0F),
            f"through every sound case above (a store checkpoint on $D418 from sfx-idle to here: play, deaths, the "
            f"title, a new game, game over): {vol_writes[0]} writes to $D418; it reads ${d418:02X} through the monitor "
            f"(volume 15, no filter)" + (f"; sfx_shadow + 24 = ${shadow:02X}" if shadow is not None else
                                         "; no sfx_shadow in this build (release)"))
        mon.checkpoint_delete(cp_play.number)
        mon.checkpoint_delete(cp_vol.number)

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
