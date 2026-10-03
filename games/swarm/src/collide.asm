// Swarm: collisions (design.md "Hit boxes", "Scoring", "Enemy behaviour"; memory-map.md "The
// collision budget" and its five rules). Bounding boxes through engine/collision.asm, which reads
// the multiplexer's arrays; the boxes are col_pairs (tables.asm), from consts.asm's BOX_*.
// Each frame, in the design's order (Stage 3 rules, step 6):
//   (a) each player shot in flight against the enemies. A hit removes the shot, scores the
//       enemy's value (its diving value in WindUp, Dive or Return), frees a diver's slot and
//       starts the explosion (formation.asm: enemy_explode);
//   (b) the player against the 3 enemy shots (pair COL_PAIR_PLAYER_ESHOT, one collision_range);
//   (c) the player against the divers (pair COL_PAIR_PLAYER_ENEMY, collision_one each): a ram
//       kills both. (b) and (c) run only in Play with the invulnerability timer at 0, each behind
//       its Y guard (PLAYER_HIT_ESHOT_Y 207, PLAYER_HIT_ENEMY_Y 210); at most one player hit a
//       frame: if (b) hits, (c) is skipped.
// (a) IS THE GRID LOOKUP (memory-map.md "The collision budget", the fallback; switched to in stage
// 3 when the box scan of all 18 measured 2,833-2,836 against 2,825 in the placed worst frame:
// tests/games/swarm/stage3_costs_boxscan.txt). Parked enemies stand on a grid, so a shot has at
// most one Parked candidate, found from its Y (the row) and its X less this frame's fx (the
// column: grid_col, tables.asm), with the same pixel-exact box as the module's (GRID_* in
// consts.asm are built from the same BOX_* numbers). Enemies that aren't at home (the divers in
// the 3 diver slots: WindUp, Dive, Return) go through the module's box test, and only when
// they are in the shot's Y band. The highest virtual sprite hit wins, as the scan from sprite 23
// down chose it. Dead and Exploding enemies are neither Parked nor in a diver slot, so a shot
// passes through them.
//
// The rules kept here (memory-map.md):
//   1. Called once a frame, after every mover (the shots, formation_update, diver_update) and
//      before player_update: a slot freed by a hit can be fired from in the same frame. The
//      ship's own position is last frame's (it moves after this).
//   2. A free shot slot is skipped by a test here, never by collision_begin (95).
//   3. The player's scans are guarded by Y: no collision_begin unless a target is low enough.
//   5. At most 2 shot hits and 1 player hit a frame (a ram adds a third enemy explosion). The
//      panel is never drawn from here: the dirty bits are set and panel_update draws next frame.
// AUTOPLAY (the budget build): an enemy hit is detected, scored and the shot removed, but the
// enemy stays (a diver carries on); a hit on the player is counted in autoplay_player_hits and
// not answered, (b) and (c) run in every frame whatever the invulnerability timer, and (c) runs
// after a hit in (b) too. So nothing dies there: the answers are measured on the game build.
// SOUND (memory-map.md "Stage 4 part B", requests 7 and 8): the enemy explosion is asked for ONCE
// a frame, at the routine's end, if an enemy was hit (collide_hit, set by collide_enemy_hit) AND the
// player wasn't: the two paths that call player_hit (which asks for the hit's two effects) go
// straight to collide_update_end, every other path goes through !sfx. In the hit's frame the
// explosion would lose voice 2 to the hit anyway (priority 3 against 2).

// The frame's collisions: (a), (b), (c) above.
// In:  zp_fx (this frame's), zp_game_state, zp_player_invuln
// Out: shots removed, enemies exploding, game_score, panel_dirty, the player hit, the sounds asked for
// Uses: A, X, Y
// Cost: to collide_update_end, raster cycles, IRQs excluded, measured (2026-10-02, VICE 3.10 x64sc
//       PAL, DEBUG; tests/games/swarm/stage3_costs.py, results beside it):
//         95-1,399, average 434   the AUTOPLAY build, 600 passes: 2 shots, 3 divers, both of the
//                         player's scans when a target is low enough (max 1,489 in make test)
//         1,846           the game, the placed worst frame: both shots hit, the shot scan with 3
//                         full tests, the diver scan with 3 collision_one and a ram: 3 explosions
//                         started, 3 scores, the player's hit. Lines 40-69
//         1,033           the game, both shots hit with 3 divers in a shot's band
//         311 / 690       the player's hit alone: by a shot / by a ram
//       Tuned (stage 5), with the sound requests: the placed worst frames A / B / C 2,010 / 2,554 /
//       2,612, lines 40-41 to 73 / 95 / 95 (stage3_collide_worst.py, run by make test); 1,506-1,673
//       max in the AUTOPLAY build (1,506 in make test, 1,673 over 6,000 passes:
//       tuning_long_look.txt). Stage 4 part B (stage4b_collide_worst.txt): 2,013 / 2,553 / 2,571
//       (1,863 / 2,446 / 2,471 without sound). Budget 2,750 (row 8, since the long run: 2,612 + 5%). The box scan it replaced: 2,004-2,209 in AUTOPLAY, 2,833-2,836 in
//       the same placed worst frame (stage3_costs_boxscan.txt, commit 039ad26)
collide_update:
        lda zp_fx                               // 3   what the grid lookup subtracts from a shot's X
        clc                                     // 2
        adc #GRID_X0                            // 2
        sta collide_fx                          // 4
        lda #0                                  // 2
        sta collide_hit                         // 4   no enemy hit yet this frame
        // (a) Each player shot in flight against the enemies.
        .for (var i = 0; i < SPR_PSHOT_COUNT; i++) {
                lda mux_y + SPR_PSHOT + i               // 4
                cmp #MUX_OFF                            // 2
                bne !+                                  // 3
                jmp !next+                              //     a free slot: nothing to test (rule 2)
!:              clc                                     // 2
                adc #GRID_Y_OFF                         // 2   the shot's Y as the band tests want it
                sta collide_y                           // 4
                // The Parked candidate, by the grid: the row whose band the shot is in ...
                sec                                     // 2
                sbc #FORM_ROW_Y0                        // 2
                cmp #GRID_BAND                          // 2
                bcc !row0+                              // 2 / 3
                sbc #FORM_ROW_DY                        // 2   (C is set)
                cmp #GRID_BAND                          // 2
                bcc !row1+                              // 2 / 3
                sbc #FORM_ROW_DY                        // 2
                cmp #GRID_BAND                          // 2
                bcs !nocand+                            // 2 / 3   between the rows, above or below them
                lda #SPR_ENEMY + 2 * FORM_COLS          // 2
                bne !row+                               // 3   always
!row1:          lda #SPR_ENEMY + FORM_COLS
                bne !row+                               //     always
!row0:          lda #SPR_ENEMY
!row:           sta collide_best                        // 4   the row's first sprite, for now
                lda mux_x_lo + SPR_PSHOT + i            // 4   ... and the column under it
                sec                                     // 2
                sbc collide_fx                          // 4
                tax                                     // 2
                lda mux_x_hi + SPR_PSHOT + i            // 4
                sbc #0                                  // 2
                bne !nocand+                            // 2 / 3   left of column 0's box, or far right
                lda grid_col,x                          // 4
                bmi !nocand+                            // 2 / 3   between two columns' boxes
                clc                                     // 2
                adc collide_best                        // 4
                tax                                     // 2   the candidate's virtual sprite
                lda enemy_state - SPR_ENEMY,x           // 4
                cmp #ENEMY_PARKED                       // 2
                beq !cand+                              // 3 / 2   (Dead, Exploding, or a diver away from home)
!nocand:        ldx #0                                  // 2   0 = no enemy (sprite 0 is the ship)
!cand:          stx collide_best                        // 4
                // The divers (WindUp, Dive, Return): the box test, for those in the shot's Y band.
                lda zp_divers_active                    // 3
                beq !answer+                            // 3 / 2
                .for (var s = 0; s < DIVER_SLOTS; s++) {
                        ldx diver_enemy + s             // 4
                        bmi !no+                        // 2 / 3
                        lda collide_y                   // 4
                        sec                             // 2
                        sbc mux_y + SPR_ENEMY,x         // 4
                        cmp #GRID_BAND                  // 2
                        bcc !box+                       // 2 / 3
!no:
                }
                jmp !answer+                            // 3   no diver in the shot's band
!box:           ldx #SPR_PSHOT + i                      // 2
                ldy #COL_PAIR_PSHOT_ENEMY               // 2
                jsr collision_begin                     // 95  the shot has moved this frame
                .for (var s = 0; s < DIVER_SLOTS; s++) {
                        ldx diver_enemy + s             // 4
                        bmi !no+                        // 2 / 3
                        txa                             // 2
                        clc                             // 2
                        adc #SPR_ENEMY                  // 2
                        tax                             // 2
                        jsr collision_one               // up to 52. X preserved
                        bcc !no+                        // 3 / 2
                        cpx collide_best                // 4   the highest sprite wins, as a scan from
                        bcc !no+                        // 2 / 3   sprite 23 down would have found it
                        stx collide_best                // 4
!no:
                }
!answer:        ldx collide_best                        // 4
                beq !next+                              // 3 / 2   nothing under the shot
                lda #MUX_OFF                            // the shot is gone: its slot is free for
                sta mux_y + SPR_PSHOT + i               // player_update, later in this frame
                jsr collide_enemy_hit                   // X = the enemy's virtual sprite
!next:
        }
        // (b) and (c): the player against the enemy shots, then against the diving enemies
        // (design Stage 3 rules, step 6). Only in Play with the invulnerability timer at 0; the
        // budget build tests in every frame.
#if !AUTOPLAY
        lda zp_game_state               // 3
        ora zp_player_invuln            // 3
        beq !+                          // 3 / 2
        jmp !sfx+                       // dying, respawning, game over or invulnerable
!:
#endif
        // (b) The Y guard (memory-map.md "The collision budget", rule 3): a shot can touch the
        // ship only at Y >= 207. MUX_OFF passes the first compare, so the second excludes it.
        .for (var i = 0; i < SPR_ESHOT_COUNT; i++) {
                lda mux_y + SPR_ESHOT + i       // 4
                cmp #PLAYER_HIT_ESHOT_Y         // 2
                bcc !no+                        // 3 / 2   too high
                cmp #MUX_OFF                    // 2
                bne !scan+                      // 2 / 3   in flight at the ship's height
!no:
        }
        jmp !divers+                    // 3   no shot low enough: the usual frame
!scan:  ldx #SPR_PLAYER
        ldy #COL_PAIR_PLAYER_ESHOT
        jsr collision_begin             // the ship's position: last frame's, it moves after this
        ldx #SPR_ESHOT + SPR_ESHOT_COUNT - 1
        lda #SPR_ESHOT
        jsr collision_range
        bcc !divers+
#if AUTOPLAY
        jsr autoplay_count_hit          // counted, not answered: the shot is left alone, and (c)
#else                                   // still runs (the longer frame)
        jsr player_hit                  // at most one player hit a frame: (c) is skipped
        jmp collide_update_end
#endif
        // (c) The same guard for the divers: an enemy can touch the ship only at Y >= 210, and
        // only a diver gets there. (A diver is never hidden; the MUX_OFF test is the rule's.)
!divers:
        .for (var s = 0; s < DIVER_SLOTS; s++) {
                ldx diver_enemy + s             // 4
                bmi !no+                        // 3 / 2   free slot
                lda mux_y + SPR_ENEMY,x         // 4
                cmp #PLAYER_HIT_ENEMY_Y         // 2
                bcc !no+                        // 3 / 2
                cmp #MUX_OFF                    // 2
                bne !ram+                       // 2 / 3
!no:
        }
        jmp !sfx+                       // 3   no diver low enough: the usual frame
!ram:   ldx #SPR_PLAYER
        ldy #COL_PAIR_PLAYER_ENEMY
        jsr collision_begin
        .for (var s = 0; s < DIVER_SLOTS; s++) {
                ldx diver_enemy + s
                bmi !no+
                lda mux_y + SPR_ENEMY,x
                cmp #PLAYER_HIT_ENEMY_Y
                bcc !no+
                txa
                clc
                adc #SPR_ENEMY
                tax                             // the diver's virtual sprite
                jsr collision_one               // never with X = the player: X is 6-23
                bcc !no+
#if AUTOPLAY
                jsr autoplay_count_hit          // counted; the diver flies on
#else
                jsr collide_enemy_hit           // a ram: the enemy is hit (its diving value, the
                jsr player_hit                  // explosion, its diver slot freed) and so is the
                jmp collide_update_end          // player. One player hit a frame
#endif
!no:
        }
        // The enemy explosion sound (voice 2, priority 2), once a frame. Every path on which the
        // player wasn't hit passes through here.
!sfx:   lda collide_hit                 // 4
        beq collide_update_end          // 3 / 2
        lda #SFX_ENEMY_EXPLOSION        // 2
        jsr sfx_play                    // 34  nothing else asks for voice 2 but the hit
collide_update_end:
        rts

// A player shot has hit the enemy on virtual sprite X: add its value to the score (the row's
// parked value, or its diving value when the state has bit 7 set: WindUp, Dive, Return), ask
// for the panel's score to be redrawn, and start the explosion. The score stops at 999,990.
// The high score is not touched: it is updated when the game ends (design "Title and game-over
// screens"; PANEL_DIRTY_HI is never set by a play-state routine).
// In:  X = the enemy's virtual sprite (SPR_ENEMY + e), its state not Dead or Exploding
// Out: collide_hit = 1 (collide_update asks for the explosion sound at its end)
// Uses: A, X, Y
// Cost: 91 cycles + jsr/rts in AUTOPLAY, + enemy_explode's 73-100 in the game (counted)
collide_enemy_hit:
        lda #1                          // 2
        sta collide_hit                 // 4
        ldy enemy_row - SPR_ENEMY,x     // 4  the type: 0-2
        lda enemy_state - SPR_ENEMY,x   // 4
        bpl !parked+                    // 3 / 2
        iny                             // diving: the values at row + SCORE_DIVING
        iny
        iny
!parked:
        sed                             // decimal mode is allowed (memory-map.md (c) 2); the IRQ
        clc                             // framework clears D for its handlers
        lda game_score + 2
        adc score_lo,y
        sta game_score + 2
        lda game_score + 1
        adc score_hi,y
        sta game_score + 1
        lda game_score
        adc #0
        sta game_score
        cld
        bcc !+
        lda #$99                        // past 999,990: stop there
        sta game_score
        sta game_score + 1
        lda #$90
        sta game_score + 2
!:      lda panel_dirty
        ora #PANEL_DIRTY_SCORE
        sta panel_dirty
#if AUTOPLAY
        rts                             // the enemy stays (a diver carries on): the formation is always full
#else
        lda enemy_state - SPR_ENEMY,x
        bpl !+                          // Parked
        txa                             // a diver (WindUp, Dive or Return): divers active - 1 in
        sec                             // the hit's frame, its slot free at once (Stage 3 rule 5)
        sbc #SPR_ENEMY
        jsr diver_free                  // X preserved
!:      jmp enemy_explode               // X = the virtual sprite. It explodes where it is
#endif
.errorif SCORE_DIVING != 3, "collide_enemy_hit steps to the diving values with three iny"

// collide_update's variables (absolute: they are held across the collision module's calls).
collide_fx:     .byte 0         // fx + GRID_X0, this frame
collide_y:      .byte 0         // the shot's Y + GRID_Y_OFF
collide_best:   .byte 0         // the virtual sprite of the enemy the shot hits; 0 = none
collide_hit:    .byte 0         // 1 when an enemy was hit this frame (by a shot or a ram)
