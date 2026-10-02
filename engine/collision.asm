// engine/collision.asm: sprite against sprite, bounding boxes (M4 stage 2). Design contract:
// engine/collision.md
//
// API
//   collision_begin   In: X = virtual sprite A (0-23), Y = pair index (row of col_pairs).
//                     Sets up the tests' constants from A's position. Uses A; X, Y preserved.
//   collision_range   In: X = last target (highest index), A = first target (lowest); first <= last.
//                     Out: C = 1 and X = the first target hit, counting down from X; C = 0 if none
//                     (X undefined). Uses A, X, Y. A itself is skipped.
//   collision_next    In: X = the target collision_range / collision_next last returned.
//                     Out: as collision_range, for the targets below X.
//   collision_one     In: X = target. Out: C = 1 hit, C = 0 miss; X preserved. Uses A, Y.
//   ColPair(ax0, ax1, ay0, ay1, bx0, bx1, by0, by1)   macro: one 4-byte row of the game's
//                     col_pairs table. A's box and B's box in sprite pixels inside the 24 x 21
//                     cell, inclusive.
//
// The game provides the label col_pairs (ColPair rows, at most 64) and imports this file after
// engine/multiplexer.asm (it reads mux_x_lo, mux_x_hi, mux_y and uses MUX_OFF, MUX_Y_MIN,
// MUX_Y_MAX).
//
// The test (pixel-exact; Y first, 8 bits; then X, 9 bits):
//   Y: (Ay + ay1 - by0 - By) mod 256 < range_y        range_y = (ay1 - ay0) + (by1 - by0) + 1
//   X: D = Ax + (ax0 - bx1) + 255 - Bx, 16 bits; hit when the high byte of D is 0 and the low
//      byte is >= 256 - range_x                        range_x = (ax1 - ax0) + (bx1 - bx0) + 1
//      (D <= 255 says A's left edge is not right of B's right edge; D >= 256 - range_x says
//      A's right edge is not left of B's left edge. The same test as the contract's
//      0 <= Ax - Bx + off_x < range_x, shifted by 256 - range_x so that a hit leaves C = 1.)
//   A's side of both is worked out once, in collision_begin, and kept in the operands of the
//   loop's immediates (self-modified): no zero page, and zp_tmp0-7 are not used.
//   col_pairs row: (ax0 - bx1) & $FF, 256 - range_x, (ay1 - by0) & $FF, range_y.
//
// Hidden sprites (mux_y = MUX_OFF):
//   - A hidden TARGET never hits, by the arithmetic: ColPair's .errorif proves it for every Y of
//     A in MUX_Y_MIN-MUX_Y_MAX (it needs MUX_Y_MAX + ay1 - by0 < 255).
//   - A hidden A never hits anything: collision_begin tests for it and sets range_y to 0.
//
// Zero page: none. Main loop only, not re-entrant: one collision_begin at a time.
//
// Measured (VICE 3.10 x64sc PAL, tests/engine/collision, 2026-10-02: make test ARGS=collision and
// tests/engine/collision/measure.py; DEBUG and release alike, there is no #if in this file).
// Raster cycles. "Border" = lower border, no DMA and no IRQ inside, the same in every pass:
//   collision_begin -> collision_begin_end (its rts)   83 border; 95 with the jsr and the rts
//                                                      (83-183 in the display, DMA included)
//   a target rejected on Y                             17
//   a target that passes Y and misses on X             39 (35 when the X high bytes differ)
//   collision_range, the whole call                    18 rejects: 327; 18 full misses: 723
//                                                      (= jsr 6 + 10 + the targets - 1 + rts 6)
//   collision_one, a hit                               40; 52 with the jsr and the rts
//   Swarm's worst frame, 42 tests (21 full, 21 rejects, 4 hits, as the spike calls them)
//                                                      1,813 border; 2,227-2,335 through the
//                                                      display with 24 sprites shown
//   Size                                               148 bytes, in one page
// Constraints:
//   - Y of A and of every shown target is in MUX_Y_MIN-MUX_Y_MAX; a target at any other Y but
//     MUX_OFF is not supported (the 8-bit Y test is only exact inside that range).
//   - mux_x_hi holds bit 8 in bit 0 and zeros above it (the multiplexer's rule).
//   - collision_one on A itself is not skipped: it reports whether the pair's two boxes overlap
//     at one position. Don't ask.
//   - collision_one overwrites nothing collision_range set up, so a collision_next after it
//     still carries on with the range.
//   - The positions are read when called: collision_begin copies A's, the tests read B's.
//     Moving A after collision_begin has no effect until the next collision_begin.

.const COLLISION_SIZE = 150             // bytes reserved in one page (148 used), checked at the end

// One row of col_pairs: A's box against B's box (columns x0-x1, rows y0-y1, inclusive).
.macro ColPair(ax0, ax1, ay0, ay1, bx0, bx1, by0, by1) {
        .var rx = (ax1 - ax0) + (bx1 - bx0) + 1
        .var ry = (ay1 - ay0) + (by1 - by0) + 1
        .var oy = ay1 - by0
        .errorif ax0 < 0 || ax1 > 23 || ax0 > ax1, "ColPair: A's columns must be 0-23, x0 <= x1"
        .errorif bx0 < 0 || bx1 > 23 || bx0 > bx1, "ColPair: B's columns must be 0-23, x0 <= x1"
        .errorif ay0 < 0 || ay1 > 20 || ay0 > ay1, "ColPair: A's rows must be 0-20, y0 <= y1"
        .errorif by0 < 0 || by1 > 20 || by0 > by1, "ColPair: B's rows must be 0-20, y0 <= y1"
        .errorif ry > 64, "ColPair: range_y must be <= 64"
        // Shown against shown, 8 bits: the true difference d = Ay - By + oy must not reach
        // [0, range_y) by wrapping round 256.
        .errorif (MUX_Y_MAX - MUX_Y_MIN) + oy > 255, "ColPair: Y difference wraps (too high)"
        .errorif (MUX_Y_MIN - MUX_Y_MAX) + oy + 256 < ry, "ColPair: Y difference wraps (too low)"
        // A hidden target (By = MUX_OFF = 255) against a shown A: the loop computes
        // (Ay + oy + 1) mod 256, which must be >= range_y for every Ay in MUX_Y_MIN-MUX_Y_MAX.
        .errorif MUX_OFF != $ff, "ColPair: the hidden-target proof assumes MUX_OFF = $FF"
        .errorif MUX_Y_MAX + oy + 1 > 255, "ColPair: a hidden target could hit: needs MUX_Y_MAX + ay1 - by0 < 255"
        .errorif MUX_Y_MIN + oy + 1 < ry, "ColPair: a hidden target could hit: needs MUX_Y_MIN >= by1 - ay0"
        .byte (ax0 - bx1) & $ff, 256 - rx, oy & $ff, ry
}

// The module's branches are cycle-counted: keep it inside one page.
.if (((* & $ff) + COLLISION_SIZE) > $100) .align $100
collision_start:

// Choose the object to test and the pair of kinds. Sets up the tests' constants from A's position.
// In:  X = virtual sprite A (0-23), Y = pair index (row of col_pairs, 0-63)
// Out: nothing   Uses: A (X, Y preserved)
// Cost: 83 raster cycles to collision_begin_end (measured, every border pass: tests/engine/collision,
//       no DMA, no IRQ inside) + rts 6 + the caller's jsr 6 = 95. A hidden A takes 6 fewer (counted).
// TIMING: constant path for a shown A (the sign branch is balanced, 7 cycles either way): 83,
//         locked as the whole call (95) in tests/engine/collision/budget.json.
collision_begin:
        stx col_self + 1                // 4  A is skipped in a range
        sty col_begin_y + 1             // 4
        tya                             // 2
        asl                             // 2
        asl                             // 2
        tay                             // 2  Y = pair * 4
        lda col_pairs + 1,y             // 4  256 - range_x
        sta col_rx + 1                  // 4
        lda mux_y,x                     // 4
        cmp #MUX_OFF                    // 2  C = 1 only if equal
        beq col_begin_off               // 2  a hidden A hits nothing
        adc col_pairs + 2,y             // 4  Ay + (ay1 - by0), 8 bits (C = 0)
        sta col_ky + 1                  // 4
        lda col_pairs + 3,y             // 4  range_y
col_begin_ry:
        sta col_ry + 1                  // 4
        lda col_pairs,y                 // 4  ax0 - bx1, two's complement
        clc                             // 2
        adc mux_x_lo,x                  // 4
        sta col_kxl + 1                 // 4  low byte of Ax + (ax0 - bx1) + 256
        lda col_pairs,y                 // 4  N = its sign; C (the carry of the low byte) is kept
        bmi col_begin_neg               // 2 / 3
        lda #1                          // 2  positive: the + 256 is a 1 in the high byte
        bne col_begin_hi                // 3       = 7
col_begin_neg:
        lda #0                          // 2  negative: the byte was (ax0 - bx1) + 256 already
        nop                             // 2       = 7
col_begin_hi:
        adc mux_x_hi,x                  // 4
        sta col_kxh + 1                 // 4
col_begin_y:
        ldy #0                          // 2  = 83
collision_begin_end:
        rts                             // 6
col_begin_off:
        lda #0                          // range_y = 0: the Y test passes nothing
        beq col_begin_ry

// Test A against every virtual sprite from X down to the first one, stopping at the first hit.
// In:  X = last target (highest index), A = first target (lowest index); first <= last
// Out: C = 1 and X = the target hit; C = 0 if none (X undefined)
// Uses: A, X, Y
// Cost: 10 + 17 a target rejected on Y + 39 a target that passes Y and misses on X (35 if the X
//       high bytes differ) - 1 at the end, + rts 6 + the caller's jsr 6. Measured, border, whole
//       call: 327 for 18 rejects, 723 for 18 full misses. A hit ends it 20 after the Y test.
// TIMING: 17 cycles a rejected target. Locked in tests/engine/collision/budget.json
//         (spike_reject 327, spike_full 723).
collision_range:
        clc                             // 2
        adc #1                          // 2
        sta col_step + 1                // 4  first + 1
        sec                             // 2  = 10
col_test:
col_ky: lda #0                          // 2  (Ay + ay1 - by0) & $FF   C = 1 here, always
        sbc mux_y,x                     // 4
col_ry: cmp #0                          // 2  range_y
        bcc col_xtest                   // 2 / 3
// Carry on below the last hit (same A, same pair, same first target).
// In:  X = the target collision_range or collision_next last returned
// Out: as collision_range   Uses: A, X, Y
// Cost: as collision_range without its first 10 cycles
collision_next:
col_step:
        cpx #0                          // 2  C = 1 while X > first
        dex                             // 2
        bcs col_test                    // 3  = 17 a target rejected on Y
        rts                             // none: C = 0
col_xtest:
col_kxl: lda #0                         // 2  C = 0 here: the subtraction takes 1 more
        sbc mux_x_lo,x                  // 4
        tay                             // 2
col_kxh: lda #0                         // 2
        sbc mux_x_hi,x                  // 4
        bne col_step                    // 2 / 3  further apart than 255
col_rx: cpy #0                          // 2  256 - range_x
        bcc col_step                    // 2 / 3  = 11 + 21 + 7 = 39 a target tested on X
col_self:
        cpx #0                          // 2  A itself?
        beq col_step                    // 2
        sec                             // 2
        rts                             // hit: C = 1, X = target

// Test A against one target.
// In:  X = target   Out: C = 1 hit, C = 0 miss; X preserved   Uses: A, Y
// Cost: a hit 40 raster cycles (measured, border: 52 with rts 6 and the caller's jsr 6, every
//       pass); a miss on Y 19 + rts, a miss on X 39 or 37 + rts
// TIMING: constant path for a hit: 40. Locked as the whole call (52) in
//         tests/engine/collision/budget.json (spike_one).
collision_one:
        sec                             // 2
        lda col_ky + 1                  // 4  the loop's operands, read as data
        sbc mux_y,x                     // 4
        cmp col_ry + 1                  // 4
        bcs col_one_miss                // 2 / 3
        lda col_kxl + 1                 // 4  C = 0
        sbc mux_x_lo,x                  // 4
        tay                             // 2
        lda col_kxh + 1                 // 4
        sbc mux_x_hi,x                  // 4
        bne col_one_miss                // 2 / 3
        cpy col_rx + 1                  // 4  C = 1: hit   = 40
        rts
col_one_miss:
        clc
        rts
collision_end:

.errorif (collision_end - collision_start) > COLLISION_SIZE, "collision.asm is larger than COLLISION_SIZE"
.errorif (>collision_start) != (>(collision_end - 1)), "collision.asm crosses a page"
