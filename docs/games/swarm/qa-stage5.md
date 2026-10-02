# Swarm: QA report, M4 stage 5 (ship)

QA tester, 2026-10-02, on commit `0cf34d3` (game build `2d6cf3f`; `make test` 113/113). DEBUG build
`build/swarm/swarm.prg`, release build `build/swarm-release/swarm.prg`, disk `dist/swarm/swarm.d64`.
Deliverable 6 of the M4 brief and measurement F3 carried in from M3.

## Verdict: PASS (no blocker, major or minor bug found)

Every check passed in both builds. The release build plays the same game as DEBUG (state and
every sprite identical in 1,500 frames; five screenshots pixel-identical), the multiplexer's
register writes were right in every one of 231,586 slot checks (natural play) plus 512,794
(hostile layouts), and no counter moved in about 310,000 soak frames. One design observation is
recorded below (the right-hand screen edge is almost safe to stand at); it is not a code bug and
does not block release.

## What was run

All scripts are in `tests/games/swarm/` (headers say how to run each), outputs in
`tests/games/swarm/qa_results/` and the two `qa_*_results.txt` beside the scripts. Every script
steps the game one frame at a time (a stop at `game_update_end`), as `check.py` does, and drives
the stick through the monitor's joyport 2.

| Script | Does |
|---|---|
| `qa_lib.py` | Shared: one VICE stepped by frame, labels, stick, a stick-driven bot (chases the lowest enemy, fires, sidesteps shots), a PNG writer |
| `qa_play.py` | Item 1: whole games by bot, title to GameOver to title to next game, every frame checked against the rules |
| `qa_positions.py` (+ `qa_positions_all.sh`, `qa_hostile_all.sh`) | Item 2 (F3): the engine's `positions.Checker` (unedited) and `--slack` on the game, DEBUG and release; `--hostile` overwrites the 24 virtual sprites with the engine's own worst-case layouts |
| `qa_soak.py` (+ `qa_soak_all.sh`) | Item 3: wave 3 / 12 flicker, thinned formations, the wrap, death with three divers, GameOver cycles, 130 Clear/Intro cycles past wave 99 and 999,990, the fifth explosion, a random-stick fuzz |
| `qa_release.py` | Item 4: release against DEBUG, frame by frame, screenshots, `$D020/$D021` store watch |
| `qa_edge.py` | Item 5: the edge cases |
| `qa_camp.py` | A tester's probe: is any ship position safer than another |
| MCP session (`vice_start`, `vice_joystick`, `vice_run_frames`, `vice_read_memory`, `vice_screenshot`) | Item 1 by hand on DEBUG, item 4 on the `.d64` |

Also rerun as a regression: `check.py` on both builds, **122/122 PASS each**
(`qa_results/check_debug_rerun.txt`, `check_release_rerun.txt`).

## Results

### 1. Playthrough (DEBUG)

By hand through the MCP (about 2,300 frames): title, press, Intro `WAVE 01`, play with shots,
a dive, the ship at the right edge, death, `READY`, game over, title with the score left on the
panel, a second game started with fire still held. By bot, six full games (8,940 frames, 179 kills of
which 39 diving, 7 wave clears, 18 deaths): **0 rule violations** (`qa_play_results.txt`).

| Rule (design.md) | Result |
|---|---|
| Score 50 / 80 / 150 parked, doubled diving, every frame's change equals the kills that frame | PASS, 179 kills, every frame |
| Wave clear + 1,000 in the frame the last explosion ends | PASS, 7 clears (and 130 in item 3) |
| 3 lives, one lost per hit, never rises, no hit while `zp_player_invuln` > 0 | PASS, 18 deaths |
| Dying lasts at least 100 frames, longer while a diver is out (100, 142, 144, 176 seen) | PASS |
| Respawn exactly 50 frames, ship at X 171 (the bot may already have moved it 3 pixels), `READY` on row 9 when it began in Fight | PASS |
| `WAVE nn` on row 9 through Intro frames 1-47; `GAME OVER` on row 9 in GameOver | PASS |
| High score compared once at GameOver; title panel shows the score and `HI` (checked in all six) | PASS: 5,000 kept, then 6,230 and 6,850 carried |
| 25-frame fire hold at a new game (fire held from the press) | PASS: first shot 25 frames after the game's first frame, 6 of 6 games |
| First wind-up 60 frames into the wave | PASS: 60, 6 of 6 games |
| New game 6 frames after the press; lives 3, score 0; high score kept | PASS |

Screenshots, all looked at (no glitch, wrong colour, stray character, text over stars or panel
corruption seen): [title](../../../screenshots/swarm-qa-title.png),
[Intro WAVE 01](../../../screenshots/swarm-qa-intro-wave01.png),
[shots](../../../screenshots/swarm-qa-fight-shots.png), [dive](../../../screenshots/swarm-qa-dive-1.png),
[ship at the right edge](../../../screenshots/swarm-qa-edge-right.png),
[after a death](../../../screenshots/swarm-qa-after-death.png),
[waiting for the divers](../../../screenshots/swarm-qa-dying-wait.png),
[READY](../../../screenshots/swarm-qa-respawn-ready.png),
[GAME OVER](../../../screenshots/swarm-qa-gameover.png),
[title after a game](../../../screenshots/swarm-qa-title-after-game.png) (taken 2 frames into the
title's own 8-frame redraw, as designed: only `150 PTS` drawn yet),
[title again](../../../screenshots/swarm-qa-title-2nd.png),
[second game](../../../screenshots/swarm-qa-second-game-intro.png) (50 points already: fire was held, first
shot 31 frames after the press),
[title after 3,000 frames](../../../screenshots/swarm-qa-title-after-3000-frames.png).

### 2. Positions and write timing on the game (F3)

`qa_positions.py` reuses the engine's `Checker` for every comparison; only the driver is new (see
"What I changed from the engine's tool"). The game is started from the title, played by a bot with
5% random stick, and restarted when it ends, so one run covers Title, Intro, Fight, Clear, Dying,
Respawn and GameOver, in the game's extended colour mode with its panel and sound tick running.
Four runs a build and mode of 3,000 game frames each, with the wave placed at 1, 3, 12 and 20.

| Run | Game frames | Slot checks (X, X bit 8, Y, pointer, colour, mc, enable: all 7) | Sprites with X > 255 | Mismatches | Late counters |
|---|---|---|---|---|---|
| DEBUG, natural play | 12,000 | 117,642 | 19,660 | **0** | `mux_late_count` 0, `irq_late_count` 0 |
| release, natural play | 12,000 | 113,944 | 19,189 | **0** | (no counters) |
| DEBUG, hostile layouts | 12,000 | 255,959 | 68,837 | **0** | 0, 0 |
| release, hostile layouts | 12,000 | 256,835 | 69,136 | **0** | (no counters) |

Also all PASS in every run: `$D015` at the top entry, park mask, "previous occupant free
(`MUX_FREE_AFTER`) before the write", every slot written once, all six writes before line Y cycle
55. Natural play flickers little (21 and 14 flicker builds of 11,996); hostile layouts flicker in 11.5%.

**Slack** (`--slack`, one stop per zone slot: cycles from the slot's last write to line Y, cycle 55;
the engine's 17 and 39 are margins to cycle 54, the same measure to within the one cycle the
`inx` itself takes). 12,000 frames per build and mode:

| Build | Mode | Zone slots | Finished on line Y | Latest cycle on line Y | **Least slack** | Engine's measured margin |
|---|---|---|---|---|---|---|
| DEBUG | natural play | 34,708 | 0 | none | **115** (762 in three of four runs) | 17 (uniform, worst found) |
| DEBUG | hostile | 167,251 | 5,447 | 28 | **27** | 17 |
| release | natural play | 33,388 | 0 | none | **275** (812 in two) | 39 (uniform, worst found) |
| release | hostile | 167,251 | 221 | 13 | **42** | 39 |

The game never gets near the engine's thin figures in play: its sprites are 40 lines apart, and in
natural play over 99.9% of slots end 6 or more lines before their line Y. Only the engine's own hostile
layouts (`edge.py` staircases of 2 to 6 lines, three rows of 8, base lines to put slot Y on badlines;
and dense random layouts) reach it, and then **27 against 17 (DEBUG) and 42 against 39 (release)**:
**extended colour mode and the game's other IRQs cost the margin nothing**. Caveat, as the README says of
its own figures: a search result, not a proof of the worst case.

What I changed from the engine's tool (copy, not an edit): `qa_positions.py` imports `Checker`,
`DMA_CYCLE` from `tests/engine/multiplexer/positions.py` and `staircase` from
`tests/engine/multiplexer_edge/edge.py`, and replaces the driver. (a) The spike's HIRES / MC /
MIXED phases (random colours, pointers, multicolour bits written into the arrays) are dropped:
the game owns those arrays. (b) The game is driven by stick from the title, with the wave placed
by the monitor as `check.py` does. (c) Zone block layout per build, found from labels and checked by
opcode: DEBUG block 81 bytes, `inx` at +45; **release 66 bytes, `inx` at +30** (the README gives only the DEBUG
figures). (d) Late counters only in DEBUG. (e) `--hostile`: at `game_update_end` (after the game's
update, before `mux_update`) the 24 virtual sprites' X, Y, pointer and colour are overwritten with a hostile
layout (new one every 20 frames), and the game's own values are put back at `mux_build_end`, so the
game's logic isn't disturbed. (f) `--slack` also stops at `game_update_end` (to drive the stick).

### 3. Soak of the states the budget build doesn't reach (DEBUG)

Counters read every 500 frames and at the end. After every run: `irq_late_count`, `mux_late_count`,
`game_overrun_count`, `mux_pin_drop_count`, `mux_pin_excess_count` all **0**, `mux_max_age` **1** at most.
Also checked every frame: lives, divers and alive in range, BCD wave and score valid and never above
999,990, sprite Y 30-221 or hidden, X bit 8, enemy states valid, loop <= 3, pattern <= 2.

| Scenario | Frames | Result |
|---|---|---|
| Wave 3 held, ship kept alive, bot **dodging only** (formation stays full, divers keep coming: the model's worst case) | 12,000 | PASS. **8.32%** of frames dropped a sprite (998). By divers out: 1 = 12.80% (969 frames), 2 = 7.18%, 3 = 9.10% |
| Wave 3, bot chasing and firing | 12,000 | PASS. **0.02%** (2 frames) |
| Wave 12 held, dodging only | 12,000 | PASS. **6.47%** (776). 2 divers 5.08%, 3 divers 7.24% |
| Wave 12, chasing and firing | 12,000 | PASS. **0.08%** (10) |
| Thinned formation: wave 12 and wave 30 held, thinned to 1-4 alive at Fight's start, ship alive; 4 seeds each (3 alive with 3 divers out in 4 of the 8 runs) | 8 x 6,000 | PASS, 0 dropped sprites, wraps to Y 30 seen 48-152 a run |
| Death with three divers out (20 placed shots on the ship, waves 12) | 12,141 | PASS: 20 deaths |
| GameOver / title / new game, 40 cycles (10 skipped by a press from frame 60, 20 waited out, 10 with fire held through GameOver and the title: nothing started) | 14,792 | PASS |
| Clear and Intro, 130 waves by the monitor (a short Fight each, then the last explosion), score started at 999,000 | 29,206 | PASS: wave shows 12, 13, 14 ... 98, 99, then **stays 99**; pattern keeps cycling, loop sticks at 3; score **stays 999,990** through the bonuses and kills, the panel shows `SCORE 999990`, GameOver at the cap makes `HI 999990` |
| Fifth explosion: 4 running + a shot on a 5th; 3 running + two shots in one frame | 2 cases | PASS: the 5th dies at once (hidden, +50, no explosion); of two simultaneous hits one explodes and one dies unseen, +100, explosions 4 |
| Random-stick fuzz (random directions and fire every 1-25 frames, games restarted, a random jump every 400-900 frames: wave 1-99, thinned, score near the cap, ship X, lives), 4 seeds | 4 x 40,200 | PASS |

Model (design.md) against measured: wave 3 **11.6%** model, **8.32%** measured with the full
formation and three divers coming (12.80% in the 969 frames with exactly one diver out); wave 12 **9.0%**
model (9.0-9.6% in the budget build's AUTOPLAY), **6.47%** measured. Never above the model over a whole
run. No pinned sprite was ever dropped (`mux_pin_drop_count` 0), no sprite missed two frames running
(`mux_max_age` 1).

**Lowest idle** (`game_idle_min`, 16 cycles an iteration, floor 45 cycles):
**417 iterations = 6,672 cycles** in fuzz seed 23 at frame 8,670, wave 3, Play/Fight, 18 alive, 2 divers.
Other minima: 483 (7,728 cycles) wave 12 dodging-only, 3 divers; 490 (7,840) wave 3 dodging-only, 3 divers;
417 to 889 in every other run (the thinned-formation runs are the highest, 837-889). Only the hostile layouts go lower: 127 (2,032 cycles), still 45 times the floor.

### 4. Release build

`make test-release GAME=swarm`: `release-check: swarm OK: raw 18859 B, crunched 6630 B, 27 blocks on disk;
title at frame 1156 from the d64`. By MCP: `dist/swarm/swarm.d64` loaded, title
([screenshot](../../../screenshots/swarm-qa-release-title.png)), a short game
([Intro](../../../screenshots/swarm-qa-release-intro.png), [play, ship exploding](../../../screenshots/swarm-qa-release-play.png)),
state read with the release labels (`zp_game_state` 4 at the title, `game_score` 000410 while the panel read
`SCORE 000410`, `zp_lives` 2), back to the title after game over. `$D020/$D021` read 0 / 0 after boot.

`qa_release.py` (`qa_results/release_vs_debug.txt`): both builds driven by the same stick script for
1,500 frames: **state per frame identical** (state, lives, score, ship X, alive, phase, all 24 sprites'
X and Y), ending in the same state; screenshots of title, Intro, play, READY, GAME OVER
([debug](../../../screenshots/swarm-qa-debug-gameover.png) and
[release](../../../screenshots/swarm-qa-release-gameover.png), also
[READY](../../../screenshots/swarm-qa-release-ready.png)) **differ in 0 pixels**. A store checkpoint on
`$D020`/`$D021` over 3,000 frames of play: **0 stores in release and in DEBUG** (positive control: 3,101
and 3,116 stores to `$D015` seen in the same runs), so no debug border colours.

### 5. Edge cases (`qa_edge.py`, 24 of 24 PASS, `qa_edge_results.txt`)

| Case | Result |
|---|---|
| Left / right held with fire against the edges, 160 frames | X stays 24 / 318, shots leave from there; left + right + fire: no move |
| Fire held from the press through a whole life cycle (Intro, Fight, deaths, Respawn, GameOver, title) | nothing starts from the title while held (150 more frames), no stuck state |
| Title left alone 3,000 frames | `PRESS FIRE` blinks 32 on / 32 off without a slip across the 256 wrap; texts and 48 stars intact, none in the text cells |
| Both player shots in flight when the last explosion ends | one + 1,000, shots fly on and are removed, next wave 02, no diver |
| Ship shot in the frame the wave clears (lives left) | `Dying` and `Clear` together: +1,000 and one life lost; the Intro runs under `Dying`; Respawn without `READY` over `WAVE 02`; play goes on |
| The same on the last life | `GAME OVER` at +100 over an empty sky, wave timer stands still, + 1,000 in the high score (0 to 1,000 with the high score zeroed first) |
| Last enemy shot while diving (row 0 / 1 / 2) | +300 / +160 / +100, diver slot freed in the hit's frame, Clear exactly 16 frames later, +1,000, next Intro with no diver |
| Last enemy rams the ship | ship dies, enemy scores +100, state consistent |
| Last life lost in the frame a shot reaches an enemy | the +50 scores; GameOver follows |

## Bugs

**None found** (blocker 0, major 0, minor 0, cosmetic 0).

### Observation (not a defect): the right-hand edge is almost safe

`qa_camp.py X`: the ship walks to X and stands still with fire held, vulnerable, 5,000 frames per wave
(`qa_results/camp_*.txt`). Hits per 1,000 frames of Play, waves 1 / 3 / 12:

| X | 24 | 60 | 120 | 171 (centre) | 220 | 280 | **318** |
|---|---|---|---|---|---|---|---|
| wave 1 | 0.21 | 0.43 | 0.43 | 4.66 | 1.58 | 0.00 | **0.00** |
| wave 3 | 1.50 | 0.43 | 2.82 | 3.61 | 0.43 | 0.43 | **0.43** |
| wave 12 | 1.22 | 0.43 | 3.91 | 4.99 | 3.88 | 1.22 | **0.21** |

A ship parked at X 318 took 1 hit in 4,836 frames of wave 12; at the centre, 12 in 2,404. This is the
consequence of divers leaving by the side and the Sweep and Plunge paths (the v1 limit Simon already
named). It is not a way to score: at X 318 the ship can only reach column 5 when the drift is at its far
right, so the wave rarely clears. Owner if anyone wants to act: game-designer (a path or aim that reaches
the corners). Not for M4.

## Not covered

- **Real hardware.** Simon's runs on the C64 Ultimate are the only evidence. VICE x64sc only; sprite
  deadlines for hardware sprites 1 and 4-6 and X < 24 were never probed by the engine either.
- **Sound by ear**, and `$D400-$D418` on release beyond `check.py`'s checks. I did not read the SID in
  release.
- **NTSC**, joystick port 1, the keyboard, RESTORE/NMI inside a zone IRQ, an `I` flag held by the main loop.
- **`make test-long`** (Simon's terminal) and anything beyond about 310,000 soak frames.
- **A human-skill game past wave 3**: the bot dies in wave 2-3. Waves 12, 30, 99 and beyond were reached by
  placed state (the game's own Clear/Intro path), with the bot shooting and dodging inside them.
- Worst-case layouts that the engine's search did not find. The hostile run uses the engine's families only.
- The hostile runs reached `mux_max_age` 2 once (`hostile_slack_debug_2.txt`: dense random layouts of 12-24
  sprites in 30-120 lines with the 4 pins among them). The game cannot make such a layout; noted, not a game bug.

## Process notes

1. **`check.py` is 3,200 lines whose helpers are closures inside `main()`**, so none could be reused for the
   new cases; I wrote `qa_lib.py` (stepping, state, stick, bot) instead. Moving them to a module would let the next
   game's QA start from them.
2. **The engine's slack figures (17 and 39) are worst cases found by search, so a run of natural play can't
   be "compared" with them: the game's own numbers are 115 and 275 and say nothing about the margin.** The
   comparison only means something with hostile layouts, so `--hostile` (not in the engine's tool) is the
   piece worth keeping; the engine README gives only the DEBUG zone block size and `inx` offset (81, 45), the
   release ones (66, 30) had to be found.
3. Killing a script with `pkill` leaves its VICE running (two strays after I killed two soak runs; `pgrep x64sc`
   found them and I killed them). The budget runner's `Vice.close()` only runs in a `finally`.
4. `game_idle_min` is a minimum without a place: to say where the lowest idle came from I had to read it every frame.
   A DEBUG "frame and state of the minimum" store would answer it for free.

## Files

`tests/games/swarm/`: `qa_lib.py`, `qa_play.py`, `qa_positions.py`, `qa_positions_all.sh`, `qa_hostile_all.sh`,
`qa_soak.py`, `qa_soak_all.sh`, `qa_release.py`, `qa_edge.py`, `qa_camp.py`, `qa_play_results.txt`,
`qa_edge_results.txt`, `qa_results/` (positions, slack, hostile, soak, camp, release, check reruns).
