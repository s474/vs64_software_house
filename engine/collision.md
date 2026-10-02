# Sprite collisions: `engine/collision.asm`

Design contract for M4 (Technical Director, 2026-10-01). Status: **implemented, measured and
accepted** (raster-engineer, M4 stage 2, 2026-10-02; reviewed by the Technical Director the same
day): `engine/collision.asm`, 148 bytes, no zero page; spike `tests/engine/collision/`, **13 checks
in `make test`, all passing, none pending**. The single paths are at or under their estimates
except `collision_begin` (83 against 78, limit 90). The contract's own count for Swarm's worst
frame was wrong, not the module: 1,641 CPU cycles counted, **1,813 measured**, so 2,227–2,335
through the display against the 2,100 first budgeted. **Decided:** the requirement is now the
measured figure + 5% = **2,450**, and Swarm's budget rose to match
([memory-map.md](../docs/games/swarm/memory-map.md#the-collision-budget)); the 2,100 is withdrawn.
Cost a frame of calls with [the formula below](#what-a-frame-of-calls-costs), which counts whole
calls. Conventions are [engine/README.md](README.md)'s.

## Purpose

Tell the game whether two **virtual sprites** overlap, by bounding boxes that differ per kind of
object, exact to the pixel. It reads positions straight from the multiplexer's arrays (`mux_x_lo`,
`mux_x_hi`, `mux_y`), so there is no second copy of the positions to keep in step.

It is software only. The VIC-II's collision registers (`$D01E`, `$D01F`) are useless under a
multiplexer (they report hardware sprites, and only what was displayed), and nothing reads them.

Swarm's worst frame is **42 tests**: 2 player shots against 18 enemies, and the player against 3
enemy shots and 3 divers ([design](../docs/games/swarm/design.md#worst-case-per-frame)).

Out of scope for M4: sprite against background, pixel-exact masks, a broad phase (sorting or
grids), expanded sprites, more than one box per sprite.

## The test

Object A has box `ax0..ax1`, `ay0..ay1` inside its sprite cell (inclusive, as in the design's
hit-box table), target B `bx0..bx1`, `by0..by1`. With sprite positions (Ax, Ay) and (Bx, By) they
overlap exactly when both of these hold:

```
0 <= (Ax - Bx) + off_x < range_x      off_x = ax1 - bx0    range_x = (ax1 - ax0 + 1) + (bx1 - bx0 + 1) - 1
0 <= (Ay - By) + off_y < range_y      off_y = ay1 - by0    range_y = (ay1 - ay0 + 1) + (by1 - by0 + 1) - 1
```

Each is one subtraction and one unsigned compare. Y is 8 bits; X is 9 bits (`mux_x_hi` bit 0), so
its subtraction is 16-bit and the high byte must come out 0. Y is tested first: most targets fail
there. Example, Swarm's player shot (x 11–12, y 0–7) against an enemy (x 4–19, y 3–17):
`off_x` 8, `range_x` 17, `off_y` 4, `range_y` 22.

The four numbers depend only on the **pair of kinds**, so they are assembly-time constants in a
table the game provides.

## API

```
// Choose the object to test and the pair of kinds. Sets up the loop's constants from A's position.
// In:  X = virtual sprite A (0-23), Y = pair index (row of col_pairs)
// Out: nothing   Uses: A (X, Y preserved)
// Cost: measured 83 raster cycles (no DMA) in the profile span, 95 for the whole call (estimate was 78 + 12)
collision_begin:

// Test A against every virtual sprite from X down to the first one, stopping at the first hit.
// In:  X = last target (highest index), A = first target (lowest index); first <= last
// Out: C = 1 and X = the target hit; C = 0 if none (X undefined)
// Uses: A, X, Y
// Cost: measured 17 per target rejected on Y, 39 per target tested on X (35 if the X high bytes
//       differ), + 10 + jsr/rts 12 (estimates were 19 and 42)
collision_range:

// Carry on below the last hit (same A, same pair, same first target).
// In:  X = the target collision_range or collision_next last returned
// Out: as collision_range
collision_next:

// Test A against one target.
// In:  X = target   Out: C = 1 hit, C = 0 miss; X preserved   Uses: A, Y
// Cost: measured 40 for a hit, 52 for the whole call (estimate was 42 + 12)
collision_one:
```

Rules:

- **Main loop only**, after the game has written this frame's positions and before or after
  `mux_update` (which doesn't change the arrays). Not re-entrant: one `collision_begin` at a time.
- The setup is kept in **self-modified operands**, so the module needs no zero page and the
  loop compares against immediates.
- **A hidden target never hits.** A sprite with `mux_y` = `MUX_OFF` must fail the Y check: either by
  the arithmetic (then an `.errorif` proves it for the ranges allowed), or by an explicit test.
  **As built it is the arithmetic, and that is a constraint on the game: every pair needs
  `MUX_Y_MAX + ay1 − by0 < 255`** (and `MUX_Y_MIN ≥ by1 − ay0`). `ColPair` stops the build
  otherwise. Any boxes pass when `MUX_Y_MAX` ≤ 234 (Swarm: 221, largest `ay1 − by0` 17); a game
  with `MUX_Y_MAX` 235–249 is limited to pairs with `ay1 − by0` < 255 − `MUX_Y_MAX`, or the module
  needs the explicit test (about 4 cycles a target, not built). A hidden **A** hits nothing either:
  `collision_begin` tests for it.
- **`collision_begin` copies A's position when it is called.** Move A first; moving it afterwards
  has no effect until the next `collision_begin`. Targets are read when tested.
- **`collision_one` does not skip A.** Called with X = A it reports whether the pair's two boxes
  overlap at one position, which means nothing. Don't.
- **A itself is skipped** if it lies inside the range.
- The module knows nothing about kinds or states beyond the pair index. A target that shouldn't
  collide though it's on screen (Swarm: an exploding enemy) is the game's to ignore: call
  `collision_next` and carry on.
- 8-bit Y arithmetic is exact as long as every `range_y` is ≤ 64 and Y stays in
  `MUX_Y_MIN`–`MUX_Y_MAX`; the `ColPair` macro checks the first with `.errorif`.

## Data the game provides

```
col_pairs:                              // 4 bytes a pair: off_x, range_x, off_y, range_y
        ColPair(11,12, 0,7,   4,19, 3,17)       // pair 0: player shot against enemy
        ColPair(6,17, 6,20,   11,12, 14,20)     // pair 1: player against enemy shot
        ColPair(6,17, 6,20,   4,19, 3,17)       // pair 2: player against enemy
```

`ColPair(ax0, ax1, ay0, ay1, bx0, bx1, by0, by1)` is the module's macro; `col_pairs` is the game's
label (at most 64 pairs, so the index × 4 fits a byte). The box numbers are the design's hit-box
table, typed once.

## Zero page

None of its own, and it doesn't use `zp_tmp0–7`.

## Cycle budget

The design's estimates, counted from the intended inner loop, kept for the record; what was built
and **measured** follows them, and [the formula](#what-a-frame-of-calls-costs) is the one to use:

```
!loop:  lda #ay_plus_off        // 2   self-modified by collision_begin
        sec                     // 2
        sbc mux_y,x             // 4
        cmp #range_y            // 2
        bcc !x_test+            // 2   (3 taken)
!next:  dex                     // 2
        cpx #first              // 2   (or a bpl when first = 0)
        bcs !loop-              // 3          = 19 a target rejected on Y, 17 with the bpl form
```

and the X test adds `lda # / sec / sbc mux_x_lo,x / tay / lda # / sbc mux_x_hi,x / bne / cpy # /
bcs`: 22, so 42 for a target that passes Y (the taken `bcc` is 1 more than the reject path's).

| Path | Budget (raster cycles, in the spike's border run: no DMA) | Basis |
|---|---|---|
| `collision_begin` → `collision_begin_end` | **90** | estimate |
| `collision_range`, 18 targets, all rejected on Y | **360** (12 + 18 × 19 + exit) | estimate |
| `collision_range`, 18 targets, all pass Y and miss on X | **780** (12 + 18 × 42 + exit) | estimate |
| `collision_one`, a hit | **55** | estimate |
| Swarm's worst frame through the display: 2 × (`collision_begin` + 18 targets, 9 and 6 of them passing Y), then the player against 3 + 3 | **2,100** raster with 24 sprites displayed (1,641 CPU × 1.27, [memory-map.md](../docs/games/swarm/memory-map.md#frame-budget)) | estimate |
| Size | 300 bytes | estimate |

The first four become locks once measured (constant paths, no DMA); the last is a max over 600
passes + 5%, as the README's multiplexer budgets are.

**Measured** (raster-engineer, 2026-10-02; the loop as built is 17 / 39, not 19 / 42: the `sec` is
not needed in either test, and the end test is `cpx # / dex / bcs`):

| Path | Estimate / limit above | **Measured** | In `budget.json` |
|---|---|---|---|
| `collision_begin` → `collision_begin_end` | 78 / 90 | **83** in every border call (95 with `jsr` and `rts`); 83–183 in the display | lock 95 on the border call |
| `collision_range`, 18 rejects, whole call | 360 | **327** | lock |
| `collision_range`, 18 full misses, whole call | 780 | **723** | lock |
| `collision_one`, a hit, whole call | 55 | **52** | lock |
| Swarm's worst frame, no DMA | 1,641 CPU (counted) | **1,813** | lock (added) |
| Swarm's worst frame through the display | 2,100, withdrawn | **2,227–2,335** | max **2,450** (2,335 + 5%): the requirement now |
| Size | 300 bytes | **148** | `.errorif` in the module |

### What a frame of calls costs

The first count in this contract (1,641 for Swarm) added up tests and set-ups and left out the
calls. Count **whole calls** (`jsr` and `rts` included; CPU cycles, **measured**, no DMA):

```
  95 x collision_begin calls
+ 22 x collision_range calls  + 17 x targets rejected on Y  + 39 x targets tested on X
+ 52 x collision_one calls    (a hit; a miss is less)
+ the caller: about 6 a call (loading X, Y, A; the branch on C)
+ about 22 a hit (the hit exit, recording it, collision_next), before the game's own response
```

then × 1.27 for code that runs through the display (**measured** here: × 1.23–1.29; up to about
× 1.35 by count if the whole run sits in rows of 8 sprites). `collision_range` is exactly
21 + 17 × rejects + 39 × full tests when it runs to the end with no hit (327 and 723 for 18); a
target whose X high byte differs from A's costs 35, not 39.

Swarm's worst frame: 4 × 95 + 3 × 22 + 21 × 17 + 18 × 39 + 3 × 52 = 1,661, + about 60 for the
caller and about 90 for the 4 hits = **1,813 measured** (`spike_mix`).

Which call site each lock in `budget.json` measures (all in the lower border, from the `jsr` to
the instruction after it):

| Check | Labels | The call | Lock |
|---|---|---|---|
| `collision_begin`, the whole call | `spike_begin` → `spike_begin_end` | `jsr collision_begin`, A shown (a hidden A takes 6 fewer, *counted*) | 95 |
| 18 targets, all rejected on Y | `spike_reject` → `spike_reject_end` | `jsr collision_range`, 18 targets, none passes Y | 327 |
| 18 targets, all tested on X | `spike_full` → `spike_full_end` | `jsr collision_range`, 18 targets pass Y and miss on X by the longest path | 723 |
| `collision_one`, hit | `spike_one` → `spike_one_end` | `jsr collision_one`, a hit | 52 |
| Swarm's worst frame, no DMA | `spike_mix` → `spike_mix_end` | The whole frame's calls as a game makes them: 4 `collision_begin`, 3 `collision_range`, 3 `collision_one`, the loads between them, 4 hits recorded | 1,813 |

The sixth cost check, `spike_collide` → `spike_collide_end`, is the same macro as `spike_mix`
called in the display (lines 39–113), IRQ time excluded: a maximum (2,450), not a lock.

## Spike: `tests/engine/collision/`

The multiplexer with 24 sprites laid out as Swarm's worst case and moving: 18 "enemies" in three
rows of 6 at the design's positions with the drift, 2 "shots" climbing through the rows, 3
"divers" crossing a row, a "player" and 3 "enemy shots" at the bottom. Sprites that are hit change
colour for that frame, so a screenshot shows the tests working. Chain: `mux_irq_top` and one fixed
entry at `$FB`, as the other multiplexer spikes.

It must demonstrate:

1. **Correctness against a reference.** A script (`tests/engine/collision/check.py`) reads the
   positions each frame, computes every overlap from the box table in Python, and compares it with
   what the module reported (`spike_hits`, a bit per target), over at least 2,000 frames: no
   false hit, no missed hit.
2. **The edges.** A static phase steps one object pixel by pixel around another, so each of the
   four box edges is crossed in both directions: touching by exactly one pixel hits, one pixel
   apart doesn't. X positions on both sides of 255 are included (the 9-bit case), and Y near
   `MUX_Y_MIN` and `MUX_Y_MAX`.
3. Hidden targets (`MUX_OFF`) and A inside its own range are never reported.
4. `collision_next` finds the second and third overlapping target.
5. The measured cost of each path in the table, in the routine headers and here.

`tests/engine/collision/budget.json`:

| Check | Kind | Labels | Limit | Basis |
|---|---|---|---|---|
| `collision_begin` | `profile` | `collision_begin` → `collision_begin_end` | 90 | estimate |
| 18 targets, all rejected on Y (border) | `profile` | `spike_reject` → `spike_reject_end` | 360 | estimate |
| 18 targets, all tested on X (border) | `profile` | `spike_full` → `spike_full_end` | 780 | estimate |
| `collision_one`, hit (border) | `profile` | `spike_one` → `spike_one_end` | 55 | estimate |
| Swarm's worst frame, 42 tests, through the display | `profile_excl_irq`, 600 samples | `spike_collide` → `spike_collide_end` | 2,100 | estimate |
| nothing missed, nothing false | `memory` | `spike_mismatch_count` (the spike's own 6502 reference test of the same pairs, slow and simple) | equals 0 after 2,000 frames | requirement |
| no late entries, no late slots, no overrun | `memory` ×3 | `irq_late_count`, `mux_late_count`, `spike_overrun_count` | equals 0 | requirement |

The three border checks run their passes in the lower border (after the fixed entry at `$FB`),
where no badline or sprite DMA can land on them.

## Results (raster-engineer, 2026-10-02)

Built as specified: the four routines and `ColPair` have the API above, the module reads
`mux_x_lo` / `mux_x_hi` / `mux_y`, keeps its set-up in self-modified operands and uses no zero
page. VICE 3.10 x64sc PAL. Everything below is reproduced by three commands (build first:
`make GAME=collision SRC_DIR=tests/engine/collision`):

```
make test ARGS=collision                                                        # 13 checks, 20 s
uv run --package budget-runner python tests/engine/collision/check.py           # model check, 8 s
uv run --package budget-runner python tests/engine/collision/measure.py --frames 6144   # costs by phase, about a minute
```

Their output is committed beside them: `check_results.txt`, `measure_results.txt` (DEBUG, 6,144
frames) and `measure_results_release.txt` (release, 768 frames).

### Correctness

`check.py` compares the 6502 routines with a Python model that is the plain definition (two boxes
overlap when neither is wholly left of, right of, above or below the other; a hidden sprite
overlaps nothing). **All parts pass in the DEBUG and the release build**, with the same counts:

| Part | What | Counts |
|---|---|---|
| D demo (spike item 1) | The spike's own frames, stopped at `spike_frame_done`: positions and hit arrays read, all 42 pairs of the frame compared | 2,000 frames, 84,000 pairs, 1,532 overlaps in 772 frames: no false hit, no missed hit. `spike_mismatch_count` 0 (the spike's 6502 reference test), `spike_overrun_count` 0 |
| E edges (item 2) | For each of the 3 pairs and 15 positions of A, B at every offset from 3 pixels outside the overlap rectangle on one side to 3 outside on the other, in X and Y | 1,272 scenes, 28,836 positions: 17,982 overlap, 10,854 don't. Touching by one pixel (must hit): left 906, right 906, top 727, bottom 660. One pixel apart (must miss): 906, 906, 714, 660. A and B on opposite sides of X 255/256 in 72 (pair, offset) cases; Y at `MUX_Y_MIN` and `MUX_Y_MAX` |
| X far | A and B at 21 X values over 0–511, every combination | 2,646 pairs: no hit from 9-bit wrap-round |
| H hidden (item 3) | B hidden at an X that would hit, A at every Y 30–221; A hidden, B at every Y and hidden | 627 scenes: nothing reported |
| N next (items 3, 4) | 2–9 overlapping targets in the range, hidden ones among them, A inside its own range in half | 120 scenes, 400 hits returned by `collision_range` + `collision_next`, all in order (70 scenes with 3 or more) |
| R random | Seed 20261002: random pair, A, range and positions | 400 scenes, 9,200 pairs: 1,202 overlap, 7,998 don't |

Each scene also checks that `collision_begin` preserves X and Y and `collision_one` preserves X.
The script was tried against four deliberate faults in the module (range_x off by one, range_y off
by one, the hidden-A test removed, A's index not stored so that the self test is wrong): it failed
on each.

Item 2 is met by the script's scenes, not by a static phase of the spike's own motion: the script
writes the positions and the C64 runs the module on them (`spike_scene`).

### How it differs from the sketch above

1. **Table bytes.** A `col_pairs` row is `(ax0 − bx1) & $FF, 256 − range_x, (ay1 − by0) & $FF,
   range_y`: the X test is the same comparison shifted by `256 − range_x`, so that a hit leaves
   C = 1 with no `sec` in `collision_one`. Games type `ColPair(...)` and never see the bytes.
2. **A hidden target** is rejected by the arithmetic, and `ColPair` proves it with `.errorif`. The
   condition is **`MUX_Y_MAX + ay1 − by0 < 255`**: true for any boxes when `MUX_Y_MAX` ≤ 234
   (Swarm: 221), but a game with `MUX_Y_MAX` up to 249 could only use pairs with `ay1 − by0` ≤ 5,
   and would need an explicit test in the loop (4 cycles a target). Not built: no game needs it.
3. **A hidden A** (not in the contract) hits nothing: `collision_begin` tests for it (2 cycles).
4. **A itself** is skipped by a test on the hit path only (4 cycles a hit, none a miss).
   `collision_one` on A itself is not skipped.
5. `collision_one` reads the loop's operands as data and writes nothing, so a `collision_next`
   after it still continues the range.

### Costs

Raster cycles. Border = from line 252, no badline, no sprite DMA, no IRQ inside: the same figure
in every pass (32 in `make test`, 384 in `measure.py`).

| Path | Span | Estimate | **Measured** |
|---|---|---|---|
| `collision_begin` | to `collision_begin_end` (its `rts`) | 78 | **83** border (1,920 calls); **95** whole call. 83–183 for the calls in the display |
| A target rejected on Y | in the loop | 19 | **17** |
| A target that passes Y, misses on X | in the loop | 42 | **39** (35 when the X high bytes differ) |
| `collision_range`, 18 rejects | whole call | 360 | **327** = 6 + 10 + 18 × 17 − 1 + 6 |
| `collision_range`, 18 full misses | whole call | 780 | **723** = 6 + 10 + 18 × 39 − 1 + 6 |
| `collision_one`, a hit | whole call | 54 | **52** = 6 + 40 + 6 |
| 42 tests, the worst mix, no DMA | `spike_mix` → `spike_mix_end` | 1,641 | **1,813** |
| 42 tests, the worst mix, in the display | `spike_collide` → `spike_collide_end`, IRQs excluded, lines 39–89 | 2,100 | **2,227–2,335** (384 passes): × 1.23–1.29 |
| 42 tests, moving (typical) | the same, lines 47–113 | about 1,650 (1,300 × 1.27) | **1,639–2,279**, average 1,885 (5,376 passes) |

**The worst frame is over its budget: 2,335 against 2,100.** Not because a test costs more than
estimated (17 and 39 against 19 and 42) but because the count of 1,641 left out what goes round
the tests. For the worst mix (21 full tests, 21 rejects, 4 hits):

| | CPU cycles |
|---|---|
| 21 × 39 + 21 × 17 | 1,176 |
| 4 × `collision_begin`, whole call (95; the count had 90) | 380 |
| 3 × `collision_range`'s own 10 + `jsr` + `rts` | 66 |
| 3 × `collision_one` instead of a loop pass (52 − 39) | 39 |
| The caller: loading X, Y and A for 4 + 3 + 3 calls, the `bcc` after each | about 60 |
| 4 hits: the hit exit, two stores to record it, `collision_next` | about 90 |
| **Total** | **1,813 measured** |

The DMA factor measured 1.23–1.29, as the 1.27 assumed. In the game `collide_update` runs later in
the frame than the spike's (which starts on line 39–51), inside the rows' sprites, so the game's
own measurement decides; the memory map's row 8 (2,100 + 375) needs **about 2,350 + 375** on these
figures, 250 of the 935 headroom.

**Technical Director's decision (2026-10-02):** accepted as measured. Row 8 is now **2,450 + 375 =
2,825** and Swarm's headroom 585
([memory-map.md](../docs/games/swarm/memory-map.md#the-collision-budget), with the trigger for
the grid fallback). `budget.json`: the display check's limit is **2,450** (2,335 + 5% = 2,452; the
raster-engineer had rounded up to 2,500), the same figure as the game's budget for the tests; the
PENDING check against 2,100 is removed, because an estimate a measurement has replaced isn't a
target; the five border locks stand. On "later in the frame": Swarm's frame order puts
`collide_update` on about line 37 in stage 2 and no later than about line 62 in stage 3, so the
spike's lines 39–89 are close to the game's, and the + 5% is the allowance for the difference.

Cheaper for the game, without touching the module: the player's two scans cost 2 × 95 for 6
tests; and the fallback in the memory map (a player shot finds its one parked candidate by row and
column) removes most of the 36.

### The spike as built

Swarm's 24 sprites, each drawn as its hit box; a sprite that hits or is hit is white in the next
frame and the border is red. Three phases in a 256-frame cycle: **M** moving (224 frames), **W**
the worst mix held static (16), **B** the same layout with no tests (16), in which the five border
passes run. Phase B exists because a frame with the tests, `mux_update` and the reference test
ends on line 236–318 in DEBUG (the tick is at 328), which leaves no room for border passes after it.

Two checks differ from the table above, and one is added:

- **`collision_begin` is locked as the border call** (`spike_begin` → `spike_begin_end`, 95), not on
  `collision_begin` → `collision_begin_end`: the spike also calls it four times a frame in the
  display, and a profile check on the module's labels takes those passes too (83–183).
- **The 2,100 row** is one check with the measured limit, 2,450 (it was two until the Technical
  Director's decision above: the measured limit and the 2,100 held PENDING).
- **`spike_mix`** (1,813, a lock) is the worst mix with no DMA: the CPU count behind the display figure.

Screenshots: `screenshots/collision-spike.png` (phase W: four hits, red border) and
`screenshots/collision-spike-moving.png`.

Not covered: Y values outside `MUX_Y_MIN`–`MUX_Y_MAX` other than `MUX_OFF` (not supported);
`mux_x_hi` with bits above bit 0 set; more than 3 pairs in the table (the index × 4 is two `asl`s).
