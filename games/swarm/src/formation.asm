// Swarm: the formation and the per-enemy data (design.md "The formation", "Enemy behaviour",
// "Sprite shapes"). 18 enemies, 3 rows of 6, on virtual sprites 6-23: enemy e = row * 6 + column
// is sprite SPR_ENEMY + e. Home position: X = 34 + fx + 36 * column, Y = 56 / 96 / 136 by row.
// The drift: fx runs 0 -> 96 -> 0, one pixel every 2 frames (every frame from loop 2), starting
// at 48 moving right. Each row is one type (A, B, C): its colour and its two shapes, which swap
// every 16 frames, all 18 together.
// Stage 2 part A: every enemy is Parked. No hits, explosions or dives yet.
//
// PER-ENEMY DATA LAYOUT (for part B's hits and stage 3's divers). Parallel arrays indexed by the
// enemy index e (0-17), all absolute:
//   enemy_state,e   ENEMY_* below, the design's state machine. Bit 7 clear (DEAD, PARKED): the
//                   formation owns the sprite's X. Bit 7 set (WINDUP, DIVE, RETURN, EXPLODING):
//                   the state's own code owns it and formation_update leaves mux_x alone. So
//                   "scores the diving value" is bit 7 set, and "can be hit" is every state but
//                   DEAD (hidden: mux_y = MUX_OFF, which the collision module never reports) and
//                   EXPLODING (the highest value: one cmp).
//   enemy_timer,e   frames left in a timed state (WindUp, Exploding). Unused while Parked.
//   enemy_row,e / enemy_col,e   constants (tables.asm): the row is the type, so it indexes the
//                   colour (colour_table + COL_ENEMY_A), the shapes, the score and the dive path.
//   formation_home_x_lo/hi,column   this frame's home X, written by formation_update every frame
//                   for all six columns, whatever is alive: where Return is heading and where
//                   WindUp wobbles around. Home Y is formation_row_y,row.
//   The position itself is the multiplexer's entry (mux_x_lo/hi, mux_y + SPR_ENEMY + e): there
//   is no second copy. A diver's path data (segment, steps left, mirror, shots) belongs to the
//   3 diver slots of stage 3, not to all 18 enemies.
// THE RULES THAT GO WITH IT:
//   1. formation_update writes mux_x_lo of every enemy whose state has bit 7 clear, every frame,
//      and mux_x_hi only in the columns that can pass X 255 (4 and 5). mux_y, mux_col and the
//      other columns' mux_x_hi (always 0 at home) are written when an enemy is parked, by
//      enemy_park: call it to put an enemy (back) in its place (wave start, the end of Return).
//   2. A dead enemy is state ENEMY_DEAD with mux_y = MUX_OFF. formation_update still writes its
//      X and shape: harmless, the sprite is hidden.
//   3. The animation swap writes mux_ptr of ALL 18 without looking at their states (it is the
//      cheapest way). So explosion code must write an exploding enemy's mux_ptr every frame,
//      AFTER the swap (in formation_update's tail, or in a routine called after it).
//   4. Whoever takes an enemy out of Parked sets bit 7 in its state in the same frame it starts
//      writing mux_x; whoever kills one keeps zp_enemies_alive.

.const ENEMY_DEAD      = $00    // slot hidden
.const ENEMY_PARKED    = $01
.const ENEMY_OWN_X     = $80    // bit 7: not the formation's to place
.const ENEMY_WINDUP    = $80    // stage 3
.const ENEMY_DIVE      = $81    // stage 3
.const ENEMY_RETURN    = $82    // stage 3
.const ENEMY_EXPLODING = $83    // part B

// The first column whose home X can pass 255: formation_update writes mux_x_hi from here on.
.const FORM_HI_COL = floor((255 - FORM_FX_MAX - FORM_X0) / FORM_COL_DX) + 1    // 4
.errorif FORM_X0 + FORM_FX_MAX + FORM_COL_DX * (FORM_COLS - 1) > 511, "home X is 9 bits"

// Start a wave's formation: fx = 48 moving right, animation frame 0, all 18 enemies Parked at
// their home positions in their type's colour and first shape.
// (The design's wave start, one enemy appearing every 2 frames, is the wave stage's.)
// In:  zp_loop (the drift's speed)   Out: zp_enemies_alive = 18
// Uses: A, X, Y
// Cost: init only
formation_init:
        lda #FORM_FX_START
        sta zp_fx
        lda #1
        sta zp_drift_dir                // moving right
        ldx zp_loop
        lda formation_drift_period,x
        sta zp_drift_timer              // fx stays at 48 for one whole period first
        lda #ENEMY_ANIM_FRAMES
        sta zp_anim_timer
        lda #0
        sta zp_anim_frame
        ldx #FORM_COLS - 1              // home X of each column for the starting fx
!col:   lda formation_col_x,x
        clc
        adc zp_fx
        sta formation_home_x_lo,x
        lda #0
        rol
        sta formation_home_x_hi,x
        dex
        bpl !col-
        ldx #ENEMY_COUNT - 1
!enemy: lda #0
        sta enemy_timer,x
        jsr enemy_park
        dex
        bpl !enemy-
        lda #ENEMY_COUNT
        sta zp_enemies_alive
        rts

// Put enemy X in its place in the formation: state Parked, at this frame's home position, in
// its type's colour and the current animation shape. For the wave start and, from stage 3, the
// end of Return. If it is called after formation_update in a frame, the position is that frame's.
// In:  X = enemy index 0-17      Out: X preserved
// Uses: A, Y
// Cost: 74 cycles + jsr/rts (counted); not a per-frame routine
enemy_park:
        lda #ENEMY_PARKED
        sta enemy_state,x
        ldy enemy_col,x
        lda formation_home_x_lo,y
        sta mux_x_lo + SPR_ENEMY,x
        lda formation_home_x_hi,y
        sta mux_x_hi + SPR_ENEMY,x
        ldy enemy_row,x
        lda formation_row_y,y
        sta mux_y + SPR_ENEMY,x
        lda colour_table + COL_ENEMY_A,y
        sta mux_col + SPR_ENEMY,x
        tya                             // shape = SHAPE_ENEMY + row * 2 + animation frame
        asl
        ora zp_anim_frame
        clc
        adc #SHAPE_ENEMY
        sta mux_ptr + SPR_ENEMY,x
        rts

// The formation's frame: step the drift, work out the six columns' home X and write it to every
// enemy the formation places (state bit 7 clear), and every 16 frames swap the animation shape
// of all 18. Unrolled by column. Runs after pshot_update and before the collisions and the player.
// In:  nothing       Out: formation_home_x_lo/hi, mux_x_lo/hi and mux_ptr of the enemies
// Uses: A, X
// Cost: to formation_update_end, CPU cycles counted: 298 in a frame with no drift step and no
//       swap, + 27 on a drift step (+ 34 on a turn), + 105 on a swap frame: 437 at most.
//       Measured, raster cycles: 296-437 in the game (vice_profile, 400 passes, loop 0); 323-437,
//       average 331, in the AUTOPLAY build, which drifts every frame (600 passes:
//       tests/games/swarm/stage2a_costs.py, results beside it). Budget 750 (memory-map.md row 5,
//       which also has to hold stage 3's wind-up wobble and explosion timers).
//       NO DMA IN THESE FIGURES: it runs on lines 29-36, above the first badline and the first
//       enemy row. Once the collisions run before it, expect about x 1.27: 555
formation_update:
        dec zp_drift_timer              // 5
        bne !placed+                    // 3 / 2
        ldx zp_loop                     // 3
        lda formation_drift_period,x    // 4
        sta zp_drift_timer              // 3
        lda zp_fx                       // 3
        clc                             // 2
        adc zp_drift_dir                // 3   + 1 or - 1
        sta zp_fx                       // 3
        beq !turn+                      // 2 / 3   reached 0 ...
        cmp #FORM_FX_MAX                // 2
        bne !placed+                    // 3 / 2   ... or 96: turn round
!turn:  lda zp_drift_dir                // 3
        eor #$fe                        // 2   1 <-> $FF
        sta zp_drift_dir                // 3
!placed:
        // Per column: 9-22 cycles for the home X, then 14 an enemy placed (10 one left alone).
        .var carry_known_clear = false
        .for (var c = 0; c < FORM_COLS; c++) {
                lda zp_fx                               // 3
                .if (!carry_known_clear) {
                        clc                             // 2   (not needed after a column that can't carry)
                }
                adc #FORM_X0 + FORM_COL_DX * c          // 2
                sta formation_home_x_lo + c             // 4
                .if (c >= FORM_HI_COL) {
                        ldx #0                          // 2
                        bcc !nc+                        // 3 / 2
                        inx                             // 2
!nc:                    stx formation_home_x_hi + c     // 4
                }
                .for (var r = 0; r < FORM_ROWS; r++) {
                        .var e = r * FORM_COLS + c
                        bit enemy_state + e             // 4
                        bmi !skip+                      // 2 / 3   not the formation's to place
                        sta mux_x_lo + SPR_ENEMY + e    // 4
                        .if (c >= FORM_HI_COL) {
                                stx mux_x_hi + SPR_ENEMY + e    // 4
                        }
!skip:
                }
                .eval carry_known_clear = (c < FORM_HI_COL)
        }
        // The animation: every ENEMY_ANIM_FRAMES frames, the other shape, all 18 together.
        dec zp_anim_timer               // 5
        bne !done+                      // 3 / 2
        lda #ENEMY_ANIM_FRAMES          // 2
        sta zp_anim_timer               // 3
        lda zp_anim_frame               // 3
        eor #1                          // 2
        sta zp_anim_frame               // 3
        .for (var r = 0; r < FORM_ROWS; r++) {
                lda zp_anim_frame                       // 3
                clc                                     // 2
                adc #SHAPE_ENEMY + r * 2                // 2   the row's first shape + 0 or 1
                .for (var c = 0; c < FORM_COLS; c++) {
                        sta mux_ptr + SPR_ENEMY + r * FORM_COLS + c     // 4
                }
        }
!done:
formation_update_end:
        rts

// Per-enemy variables, indexed by enemy index 0-17 (the layout is described at the top).
enemy_state:            .fill ENEMY_COUNT, ENEMY_DEAD
enemy_timer:            .fill ENEMY_COUNT, 0
// This frame's home X of each column, 9 bits (hi is 0 or 1). Columns 0-3 never pass 255.
formation_home_x_lo:    .fill FORM_COLS, 0
formation_home_x_hi:    .fill FORM_COLS, 0
