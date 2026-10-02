// Swarm: the enemies' shots (design.md "Entities", "Firing"; memory-map.md row 7). Virtual
// sprites 1-3, pinned, at most 3 in flight. A shot's state is its multiplexer entry (mux_y is
// MUX_OFF while the slot is free) and one byte, eshot_dx: its sideways step, fixed when fired.
// Each frame Y + 2 (+ 3 from loop 2) and X + dx; X is clamped to 0-344 (both off screen: the
// design's clamp, not a removal); the shot is removed when Y > 221.
// eshot_update runs with pshot_update, BEFORE the divers (memory-map.md "Order of the frame"), so a
// shot fired by diver_update is shown at its spawn position for one frame before it moves.

// Free the three slots and set their shape and colour.
// In:  nothing       Out: nothing
// Uses: A, X
// Cost: init and new game only
eshot_init:
        ldx #SPR_ESHOT_COUNT - 1
!:      lda #MUX_OFF
        sta mux_y + SPR_ESHOT,x
        lda #SHAPE_ESHOT
        sta mux_ptr + SPR_ESHOT,x
        lda colour_table + COL_ENEMY_SHOT
        sta mux_col + SPR_ESHOT,x
        lda #0
        sta eshot_dx,x
        dex
        bpl !-
        rts

// Move the shots in flight and free those that have passed the player's line (Y > 221).
// In:  zp_loop (the shots' dy)   Out: nothing
// Uses: A, X, zp_tmp0
// Cost: to eshot_update_end, CPU cycles counted: 10 + 9 a free slot, 34 a shot falling straight,
//       47 one moving left, 52 one moving right: 166 at most. Budget 200 (row 7), in the top
//       border: no badline; the only sprite DMA there is a wrapped diver's (Y 30-50).
//       Measured: 38-169 raster cycles in the AUTOPLAY build, 600 passes, on lines 29-33
//       (tests/games/swarm/stage3_costs.txt; 162 in make test ARGS=swarm)
eshot_update:
        ldx zp_loop                             // 3
        lda eshot_dy,x                          // 4
        sta zp_tmp0                             // 3
        .for (var i = 0; i < SPR_ESHOT_COUNT; i++) {
                lda mux_y + SPR_ESHOT + i       // 4
                cmp #MUX_OFF                    // 2
                beq !next+                      // 3 taken (free) / 2
                clc                             // 2
                adc zp_tmp0                     // 3
                cmp #MUX_Y_MAX + 1              // 2
                bcc !keep+                      // 3 / 2
                lda #MUX_OFF                    // 2   Y > 221: gone
                sta mux_y + SPR_ESHOT + i       // 4
                bne !next+                      // 3   always
!keep:          sta mux_y + SPR_ESHOT + i       // 4
                lda eshot_dx + i                // 4
                beq !next+                      // 3 / 2   falling straight
                bmi !left+                      // 3 / 2
                lda mux_x_lo + SPR_ESHOT + i    // 4   right: not past DIVER_X_MAX
                cmp #<DIVER_X_MAX               // 2
                bne !go+                        // 3 / 2
                lda mux_x_hi + SPR_ESHOT + i    // 4
                bne !next+                      // 3   at 344: stays
!go:            inc mux_x_lo + SPR_ESHOT + i    // 6
                bne !next+                      // 3 / 2
                inc mux_x_hi + SPR_ESHOT + i    // 6
                bne !next+                      // 3   always: it became 1
!left:          lda mux_x_lo + SPR_ESHOT + i    // 4   left: not below 0
                bne !dec+                       // 3 / 2
                lda mux_x_hi + SPR_ESHOT + i    // 4
                beq !next+                      // 3   at 0: stays
                dec mux_x_hi + SPR_ESHOT + i    // 6
!dec:           dec mux_x_lo + SPR_ESHOT + i    // 6
!next:
        }
eshot_update_end:
        rts
.errorif DIVER_X_MIN != 0 || DIVER_X_MAX < 256, "eshot_update's clamps: 0 on the left, a value above 255 on the right"

// Fire a shot from enemy X if the design's three conditions hold: the game state is Play, the
// diver's X is 24-320, and a shot slot is free (lowest first). The shot starts at the diver's
// position; its dx is fixed here from d = player X - shot X: 0 if |d| <= 15, else + 1 if d > 0,
// - 1 if d < 0. If it can't fire, nothing happens: the caller's fire step is lost.
// In:  X = enemy index 0-17 (a diver)     Out: X preserved
// Uses: A, Y, zp_tmp0
// Cost: about 110 cycles when it fires (counted); only at a fire step
eshot_spawn:
        lda zp_game_state
        bne !none+                      // not in Play: no diver fires (Stage 3 rule 8)
        lda mux_x_hi + SPR_ENEMY,x
        bne !high+
        lda mux_x_lo + SPR_ENEMY,x
        cmp #ESHOT_FIRE_X_MIN
        bcc !none+
        bcs !slot+                      // always
!high:  lda mux_x_lo + SPR_ENEMY,x
        cmp #<(ESHOT_FIRE_X_MAX + 1)
        bcs !none+
!slot:  ldy #0                          // the lowest free slot
        lda mux_y + SPR_ESHOT
        cmp #MUX_OFF
        beq !got+
        iny
        lda mux_y + SPR_ESHOT + 1
        cmp #MUX_OFF
        beq !got+
        iny
        lda mux_y + SPR_ESHOT + 2
        cmp #MUX_OFF
        bne !none+                      // all three in flight
!got:   lda mux_y + SPR_ENEMY,x
        sta mux_y + SPR_ESHOT,y
        lda mux_x_hi + SPR_ENEMY,x
        sta mux_x_hi + SPR_ESHOT,y
        lda mux_x_lo + SPR_ENEMY,x
        sta mux_x_lo + SPR_ESHOT,y
        sec                             // d = player X - shot X, 9 bits and a sign
        lda zp_player_x_lo
        sbc mux_x_lo + SPR_ENEMY,x
        sta zp_tmp0
        lda zp_player_x_hi
        sbc mux_x_hi + SPR_ENEMY,x
        bmi !neg+
        bne !right+                     // d >= 256
        lda zp_tmp0
        cmp #ESHOT_AIM_DEAD + 1
        bcc !zero+                      // 0 <= d <= 15
!right: lda #1
        bne !set+                       // always
!neg:   cmp #$ff
        bne !left+                      // d < -256
        lda zp_tmp0
        cmp #256 - ESHOT_AIM_DEAD
        bcs !zero+                      // -15 <= d <= -1
!left:  lda #$ff
        bne !set+                       // always
!zero:  lda #0
!set:   sta eshot_dx,y
!none:  rts
.errorif SPR_ESHOT_COUNT != 3, "eshot_spawn looks for a free slot among exactly 3"
.errorif ESHOT_FIRE_X_MIN > 255 || ESHOT_FIRE_X_MAX < 256, "eshot_spawn's X test assumes 24 in the low page and 320 in the high one"

// Each shot's sideways step a frame: 0, 1 or $FF (- 1). Fixed when the shot is fired.
eshot_dx:       .fill SPR_ESHOT_COUNT, 0
