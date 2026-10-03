// Swarm: the formation and the per-enemy data (design.md "The formation", "Enemy behaviour",
// "Sprite shapes"). 18 enemies, 3 rows of 6, on virtual sprites 6-23: enemy e = row * 6 + column
// is sprite SPR_ENEMY + e. Home position: X = 34 + fx + 36 * column, Y = 56 / 96 / 136 by row.
// The drift: fx runs 0 -> 96 -> 0, one pixel every 2 frames (every frame from loop 2), starting
// at 48 moving right. Each row is one type (A, B, C): its colour and its two shapes, which swap
// every 16 frames, all 18 together.
// An enemy is Parked, Exploding (16 frames, 4 shapes of 4 frames, orange, stationary, in the
// enemy's own sprite), Dead (hidden), or a diver (WindUp, Dive, Return: diver.asm, stage 3).
//
// PER-ENEMY DATA LAYOUT (for part B's hits and stage 3's divers). Parallel arrays indexed by the
// enemy index e (0-17), all absolute:
//   enemy_state,e   ENEMY_* below, the design's state machine. Bit 7 clear (DEAD, PARKED): the
//                   formation owns the sprite's X. Bit 7 set (WINDUP, DIVE, RETURN, EXPLODING):
//                   the state's own code owns it and formation_update leaves mux_x alone. So
//                   "scores the diving value" is bit 7 set, and "can be hit" is every state but
//                   DEAD (hidden: mux_y = MUX_OFF, which the collision module never reports) and
//                   EXPLODING (the highest value: one cmp). WAITING (stage 4) is hidden like DEAD.
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
//      enemy_park: call it to put an enemy (back) in its place (the wave's Intro, the end of Return).
//   2. A dead enemy is state ENEMY_DEAD with mux_y = MUX_OFF. formation_update still writes its
//      X and shape: harmless, the sprite is hidden.
//   3. The animation swap writes mux_ptr of ALL 18 without looking at their states (it is the
//      cheapest way). So explosion code must write an exploding enemy's mux_ptr every frame,
//      AFTER the swap (in formation_update's tail, or in a routine called after it).
//   4. Whoever takes an enemy out of Parked sets bit 7 in its state in the same frame it starts
//      writing mux_x; whoever kills one keeps zp_enemies_alive.
// EXPLOSIONS (part B). A hit calls enemy_explode: state ENEMY_EXPLODING, enemy_timer = 16, the
// first explosion shape, orange, and the enemy's index goes in one of the EXPLOSION_SLOTS entries
// of explosion_enemy. formation_update's tail walks those entries (not the 18 states) after the
// animation swap: it counts the timer down, writes the shape for the frames left, and when the
// timer reaches 0 calls enemy_kill: Dead, hidden, zp_enemies_alive - 1, and at 0 alive the wave
// is cleared (the bonus and the Clear phase: game_wave_clear, game.asm). So zp_enemies_alive counts every
// enemy that isn't Dead, an exploding one included: it reaches 0 when the last explosion ends
// (design: "all 18 dead and exploded").
// The sprite is shown exploding for exactly 16 frames: the hit's frame and the 15 after it.
// Why 4 slots: shots spawn at least 10 frames apart and a shot lives at most 21, so no more than
// 4 hits can fall inside any 16 frames (3 while every target is parked: flights of 8, 13 or 18
// frames). If the slots were ever all taken, enemy_explode kills the enemy at once (no explosion).

.const ENEMY_DEAD      = $00    // slot hidden
.const ENEMY_PARKED    = $01
.const ENEMY_WAITING   = $02    // stage 4: hidden until its turn to appear in the wave's Intro. Not
                                // Parked (can't be hit or launched), not Dead (it counts as alive)
.const ENEMY_OWN_X     = $80    // bit 7: not the formation's to place
.const ENEMY_WINDUP    = $80    // stage 3
.const ENEMY_DIVE      = $81    // stage 3
.const ENEMY_RETURN    = $82    // stage 3
.const ENEMY_EXPLODING = $83    // part B
.const EXPLOSION_SLOTS = 4      // explosions animating at once
.const EXPLOSION_FREE  = $ff    // explosion_enemy entry: no explosion (any value with bit 7 set)

// The first column whose home X can pass 255: formation_update writes mux_x_hi from here on.
.const FORM_HI_COL = floor((255 - FORM_FX_MAX - FORM_X0) / FORM_COL_DX) + 1    // 4
.errorif FORM_X0 + FORM_FX_MAX + FORM_COL_DX * (FORM_COLS - 1) > 511, "home X is 9 bits"

// Reset the formation for a wave's Intro (design, Stage 4 rule 2; memory-map.md "Stage 4" (b):
// formation_init split in two, this is the reset): fx = 48 moving right, the drift and animation
// timers, animation frame 0, no explosion, the six home X, and all 18 enemies Waiting: hidden,
// not Parked, counted as alive. Nothing is parked here: game.asm's wave phase parks enemy k in
// Intro's frame 2k (enemy_park), one every 2 frames.
// In:  zp_loop (the drift's speed)   Out: zp_enemies_alive = 18, no explosion running
// Uses: A, X
// Cost: about 420 cycles + jsr/rts (counted: 30 the slots, 30 the timers, 108 the home X, 18 x
//       14 the enemies); only in a wave's first frame (a one-off frame)
formation_reset:
        ldx #EXPLOSION_SLOTS - 1
        lda #EXPLOSION_FREE
!:      sta explosion_enemy,x
        dex
        bpl !-
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
!enemy: lda #ENEMY_WAITING              // 2
        sta enemy_state,x               // 5
        lda #MUX_OFF                    // 2
        sta mux_y + SPR_ENEMY,x         // 5
        dex                             // 2
        bpl !enemy-                     // 3
        lda #ENEMY_COUNT
        sta zp_enemies_alive            // 18 from Intro's frame 0: the wave can't read as cleared
        rts                             // while it is still arriving

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

// Start enemy's explosion (a hit): state Exploding for EXPLOSION_FRAMES frames, the first
// explosion shape, the explosion's colour, where it is now (bit 7 of the state stops the
// formation placing it). formation_update animates it from the next frame and ends it.
// In:  X = the enemy's VIRTUAL SPRITE, SPR_ENEMY + e (what collision_range returns)
// Out: nothing       Uses: A, X, Y
// Cost: 61-88 cycles + jsr/rts by the slot found (counted); only on a hit
enemy_explode:
        lda #ENEMY_EXPLODING            // 2
        sta enemy_state - SPR_ENEMY,x   // 5
        lda #EXPLOSION_FRAMES           // 2
        sta enemy_timer - SPR_ENEMY,x   // 5
        lda #SHAPE_EXPLOSION            // 2
        sta mux_ptr,x                   // 5
        lda colour_table + COL_ENEMY_EXPLODE    // 4
        sta mux_col,x                   // 5
        txa                             // 2
        sec                             // 2
        sbc #SPR_ENEMY                  // 2
        tax                             // 2  X = enemy index
        ldy #EXPLOSION_SLOTS - 1        // 2
!find:  lda explosion_enemy,y           // 4
        bmi !free+                      // 2 / 3
        dey                             // 2
        bpl !find-                      // 3
        jmp enemy_kill                  // every slot taken (can't happen: see the top): no explosion
!free:  txa                             // 2
        sta explosion_enemy,y           // 5
        rts

// Enemy X is dead: hide its sprite, count it, and when it was the last one the wave is cleared:
// game_wave_clear (game.asm) pays the bonus and starts the Clear phase in this same frame.
// In:  X = enemy index 0-17      Out: X preserved
// Uses: A; for the last enemy of a wave also Y and zp_tmp0 (game_wave_clear's sound request)
// Cost: 28 cycles + jsr/rts (counted); + game_wave_clear's 104-120 for the last enemy of a wave.
//       Only when an explosion ends
enemy_kill:
        lda #ENEMY_DEAD
        sta enemy_state,x
        lda #MUX_OFF
        sta mux_y + SPR_ENEMY,x
        dec zp_enemies_alive
        bne !+
        jmp game_wave_clear             // X preserved
!:      rts

// The formation's frame: step the drift, work out the six columns' home X and write it to every
// enemy the formation places (state bit 7 clear), every 16 frames swap the animation shape
// of all 18, then (after the swap, which writes all 18) animate the explosions and end those
// whose 16 frames are up. Unrolled by column. Runs after pshot_update and before the collisions
// and the player.
// In:  nothing       Out: formation_home_x_lo/hi, mux_x_lo/hi and mux_ptr of the enemies
// Uses: A, X, Y
// Cost: to formation_update_end, CPU cycles counted: 298 in a frame with no drift step and no
//       swap, + 27 on a drift step (+ 34 on a turn), + 105 on a swap frame: 437 at most.
//       Measured, raster cycles: 296-437 in the game (vice_profile, 400 passes, loop 0); 323-437,
//       average 331, in the AUTOPLAY build, which drifts every frame (600 passes:
//       tests/games/swarm/stage2a_costs.py, results beside it). Budget 750 (memory-map.md row 5).
//       Part B, with the explosion slots (stage2b_costs.py, results beside it): 352-466, average
//       359, in the AUTOPLAY build, where nothing explodes (4 free slots: + 28); 431-538 in the
//       game with all 4 slots animating for 15 frames and ending together in the 16th, drifting
//       every frame. Counted worst: 437 + 2 ending (53 each) + 2 animating (31 each) = 605.
//       Stage 3 (stage3_costs.py): 339-495 in the AUTOPLAY build, on lines 31-41 (after
//       eshot_update and the state step; wrapped divers' sprites at Y 30-50 can be on those
//       lines); 616-620 in the game with 3 explosions ending and 1 animating on a turn-and-swap
//       frame (counted 627). It must end above line 51 (the first badline): it does in every
//       frame but the one-off frames in which a wave's set-up runs before it (main.asm).
//       Stage 4 (stage4_costs.py): the wave-clear bonus is paid inside it, in enemy_kill, in the
//       frame the last explosion ends: figures in tests/games/swarm/stage4_costs.txt
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
        // The explosions: 7 cycles a free slot, 31 one that is animating, 53 one that ends.
        .for (var i = 0; i < EXPLOSION_SLOTS; i++) {
                ldx explosion_enemy + i                 // 4
                bmi !next+                              // 3 / 2   free
                dec enemy_timer,x                       // 7
                beq !over+                              // 2 / 3
                ldy enemy_timer,x                       // 4   frames left, 15-1
                lda explosion_shape,y                   // 4
                sta mux_ptr + SPR_ENEMY,x               // 5
                bne !next+                              // 3   always: a shape pointer is never 0
!over:          lda #EXPLOSION_FREE                     // 2
                sta explosion_enemy + i                 // 4
                jsr enemy_kill                          // 6 + 28 + 6
!next:
        }
formation_update_end:
        rts
.errorif SHAPE_EXPLOSION == 0, "formation_update: the explosion loop's bne assumes a non-zero shape pointer"

// Per-enemy variables, indexed by enemy index 0-17 (the layout is described at the top).
enemy_state:            .fill ENEMY_COUNT, ENEMY_DEAD
enemy_timer:            .fill ENEMY_COUNT, 0
// The enemies that are exploding, by enemy index 0-17; EXPLOSION_FREE = none in this entry.
explosion_enemy:        .fill EXPLOSION_SLOTS, EXPLOSION_FREE
// This frame's home X of each column, 9 bits (hi is 0 or 1). Columns 0-3 never pass 255.
formation_home_x_lo:    .fill FORM_COLS, 0
formation_home_x_hi:    .fill FORM_COLS, 0
