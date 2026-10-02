// Swarm: collisions (design.md "Hit boxes", "Scoring", "Enemy behaviour"; memory-map.md "The
// collision budget" and its five rules). Bounding boxes through engine/collision.asm, which reads
// the multiplexer's arrays; the boxes are col_pairs (tables.asm), from consts.asm's BOX_*.
// Stage 2 part B: each player shot in flight against the 18 enemies. A hit removes the shot,
// scores the enemy's value, and starts its explosion (formation.asm: enemy_explode).
// STAGE 3 adds, in collide_update where marked: the player against the 3 enemy shots (pair
// COL_PAIR_PLAYER_ESHOT, a collision_range over SPR_ESHOT..SPR_ESHOT + 2) and against the
// diving enemies (pair COL_PAIR_PLAYER_ENEMY, collision_one each), both guarded by Y first
// (PLAYER_HIT_ESHOT_Y, PLAYER_HIT_ENEMY_Y: consts.asm), and at most 1 player hit a frame.
//
// The rules kept here (memory-map.md):
//   1. Called once a frame, after every mover (pshot_update, formation_update) and before
//      player_update: a test sees the positions the next frame shows, and a slot freed by a hit
//      can be fired from in the same frame.
//   2. A free shot slot is skipped by the test below (9 cycles), never by collision_begin (95).
//   4. A shot is ONE collision_range over all 18 enemies. A Dead enemy is hidden and is never
//      reported; an Exploding one is reported (the module knows positions, not states) and is
//      passed over with collision_next; anything else is the hit and the scan stops.
//   5. At most 2 enemy hits a frame (there are 2 shots, and a shot stops at its first hit). The
//      panel is never drawn from here: PANEL_DIRTY_SCORE is set and panel_update draws it at the
//      top of the next frame, the frame in which the explosion is first shown.
// AUTOPLAY (the budget build): a hit is detected, scored and the shot removed, but the enemy
// stays (memory-map.md "Labels the game must provide"), so the formation stays full and the two
// scans keep their worst case. The explosion's start (enemy_explode, about 100 cycles a hit) is
// therefore NOT in the budget build's figure: it is measured in the game build by
// tests/games/swarm/stage2b_costs.py.
// Sound (the design's enemy-explosion effect) is the sound stage's: engine/sfx.asm isn't built.

// Test every player shot in flight against the enemies and answer the hits.
// In:  nothing       Out: shots removed, enemies exploding, game_score, panel_dirty
// Uses: A, X, Y
// Cost: to collide_update_end, raster cycles, IRQs excluded, measured (2026-10-02, VICE 3.10 x64sc
//       PAL, DEBUG; tests/games/swarm/stage2b_costs.py, results beside it):
//         18              no shot in flight
//         18-1,192, average 685   the AUTOPLAY budget build, 600 passes, full formation, 2 shots
//                         in flight (max 1,189 in make test ARGS=swarm, another 600)
//         1,245           the game, two hits in one frame, each at the far end of its scan
//                         (enemy 0 after 12 rejects and 6 full tests, enemy 12 after 6 full
//                         tests), with both scores and both explosion starts
//       Budget 2,825 (row 8); part B's trigger for the grid fallback is 2,050: not reached.
//       ALMOST NO DMA IN THESE FIGURES: it starts on lines 30-37 and ends by line 55, so it runs
//       in the top border and the first lines of the display (first badline 51, first enemy
//       sprite line 57). Stage 3's movers push it down the frame: expect up to x 1.35
collide_update:
        .for (var i = 0; i < SPR_PSHOT_COUNT; i++) {
                lda mux_y + SPR_PSHOT + i               // 4
                cmp #MUX_OFF                            // 2
                beq !next+                              // 3   a free slot: nothing to test (rule 2)
                ldx #SPR_PSHOT + i                      // 2
                ldy #COL_PAIR_PSHOT_ENEMY               // 2
                jsr collision_begin                     // 95  the shot has moved this frame
                ldx #SPR_ENEMY + ENEMY_COUNT - 1        // 2
                lda #SPR_ENEMY                          // 2
                jsr collision_range                     // 22 + 17 a reject + 39 a full test
!test:          bcc !next+                              // nothing (more) under the shot
                lda enemy_state - SPR_ENEMY,x           // X = the enemy's virtual sprite
                cmp #ENEMY_EXPLODING
                bne !hit+
                jsr collision_next                      // an explosion can't be hit: carry on below it
                jmp !test-
!hit:           lda #MUX_OFF                            // the shot is gone: its slot is free for
                sta mux_y + SPR_PSHOT + i               // player_update, later in this frame
                jsr collide_enemy_hit
!next:
        }
        // (b) and (c): the player against the enemy shots, then against the diving enemies
        // (design Stage 3 rules, step 6). Only in Play with the invulnerability timer at 0; the
        // budget build tests in every frame.
#if !AUTOPLAY
        lda zp_game_state               // 3
        ora zp_player_invuln            // 3
        beq !+                          // 3 / 2
        jmp collide_update_end          // dying, respawning, game over or invulnerable
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
        jmp collide_update_end          // 3   no diver low enough: the usual frame
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
collide_update_end:
        rts

// A player shot has hit the enemy on virtual sprite X: add its value to the score (the row's
// parked value, or its diving value when the state has bit 7 set: WindUp, Dive, Return), ask
// for the panel's score to be redrawn, and start the explosion. The score stops at 999,990.
// The high score is not touched: it is updated when the game ends (design "Title and game-over
// screens"; PANEL_DIRTY_HI is never set by a play-state routine).
// In:  X = the enemy's virtual sprite (SPR_ENEMY + e), its state not Dead or Exploding
// Out: nothing       Uses: A, X, Y
// Cost: 85 cycles + jsr/rts in AUTOPLAY, + enemy_explode's 73-100 in the game (counted)
collide_enemy_hit:
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
