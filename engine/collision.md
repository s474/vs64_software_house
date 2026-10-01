# Sprite collisions: `engine/collision.asm`

Design contract for M4 (Technical Director, 2026-10-01). Status: **not implemented**. The
raster-engineer builds it in M4 stage 2 with the spike below. Conventions are
[engine/README.md](README.md)'s.

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
// Cost: estimate 78 CPU cycles + jsr/rts 12
collision_begin:

// Test A against every virtual sprite from X down to the first one, stopping at the first hit.
// In:  X = last target (highest index), A = first target (lowest index); first <= last
// Out: C = 1 and X = the target hit; C = 0 if none (X undefined)
// Uses: A, X, Y
// Cost: estimate 19 CPU cycles per target rejected on Y, 42 per target tested on X, + jsr/rts 12
collision_range:

// Carry on below the last hit (same A, same pair, same first target).
// In:  X = the target collision_range or collision_next last returned
// Out: as collision_range
collision_next:

// Test A against one target.
// In:  X = target   Out: C = 1 hit, C = 0 miss; X preserved   Uses: A, Y
// Cost: estimate 42 CPU cycles + jsr/rts 12
collision_one:
```

Rules:

- **Main loop only**, after the game has written this frame's positions and before or after
  `mux_update` (which doesn't change the arrays). Not re-entrant: one `collision_begin` at a time.
- The setup is kept in **self-modified operands**, so the module needs no zero page and the
  loop compares against immediates.
- **A hidden target never hits.** A sprite with `mux_y` = `MUX_OFF` must fail the Y check: either by
  the arithmetic (then an `.errorif` proves it for the ranges allowed), or by an explicit test.
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

All *estimates*, counted from the intended inner loop:

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
