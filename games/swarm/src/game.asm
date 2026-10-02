// Swarm: the game state machine (design.md "Game flow" and "Stage 3 rules" 8-13). Stage 3 has
// four states; the title, the wave intro and the wave clear are stage 4's.
//
//   Play ----------- the player is hit (collide_update -> player_hit) ----------> PlayerDying
//   PlayerDying ---- first frame, 100 or later, with no diver out, lives left --> Respawn
//   PlayerDying ---- frame 100, no lives left, whatever is diving --------------> GameOver
//   Respawn -------- 50 frames of READY ----------------------------------------> Play
//   GameOver ------- 200 frames, or a NEW press of fire from its frame 50 ------> a new game (Play)
//                    (stage 4: the title)
//
// zp_state_timer is the number of frames the state has run: 0 in the frame the state is entered,
// + 1 at the top of every later frame (game_state_update), stopping at 255. It isn't counted in
// Play. The player's hit happens in collide_update, so frame 0 of PlayerDying is the hit's frame;
// Respawn and GameOver are entered here, at the top of a frame, which is their frame 0.
// The formation's return after a clear (Stage 2 rule 3) runs on its own timer, zp_clear_timer,
// in every state (Stage 3 rule 12).
// What the other files do with the state: diver_update counts the launch timer and launches only
// in Play; eshot_spawn fires only in Play; collide_update tests the player only in Play with
// zp_player_invuln 0; player_update moves and fires in Play and Respawn (the states in which the
// ship is shown).
// Stage 3 stand-in for waves (Stage 3 rule 1): every game is pattern 3 at loop 0, set in the
// pattern and loop stores by game_new and read from them everywhere, so a test can set them.

// Start a game: score 0, lives 3, the formation as at power-on (all 18 Parked, fx 48, no diver,
// shot or explosion), the ship at X 171 with no invulnerability, the launch timer at 50, state
// Play. The high score is kept. Also called once at power-on (after panel_init, before irq_init).
// In:  nothing       Out: nothing
// Uses: A, X, Y
// Cost: about 2,400 cycles (counted: formation_init's 2,000 and the other inits); the frame it
//       runs in has no collisions to speak of. Measured as game_update for that frame:
//       tests/games/swarm/stage3_costs.txt
game_new:
        jsr game_text_clear
        lda #0
        sta game_score
        sta game_score + 1
        sta game_score + 2
        sta zp_state_timer
        sta zp_clear_timer
        lda #PLAYER_LIVES
        sta zp_lives
        lda panel_dirty
        ora #PANEL_DIRTY_SCORE | PANEL_DIRTY_LIVES
        sta panel_dirty
        lda #STAGE3_PATTERN             // the stand-in for waves: pattern 3 ...
        sta zp_pattern
#if AUTOPLAY
        lda #GAME_LOOP_MAX              // the budget build plays wave 12: pattern 3, loop 3
#else                                   // (memory-map.md "Labels the game must provide")
        lda #0                          // ... at loop 0
#endif
        sta zp_loop
        jsr formation_init              // after zp_loop: the drift's period depends on it
        jsr diver_init                  // no diver: formation_init has parked them all
        jsr eshot_init
        jsr pshot_init
        jsr player_init
        lda #LAUNCH_TIMER_START
        sta zp_launch_timer
        lda #GAME_STATE_PLAY
        sta zp_game_state
        rts

// The frame's timers and state changes. Called after the shots have moved and before
// formation_update (memory-map.md "Order of the frame").
// In:  zp_game_state, zp_state_timer, zp_clear_timer, zp_joy_pressed
// Out: the state, texts on row 12, the ship (Respawn), the high score (GameOver), a new game
// Uses: A, X, Y
// Cost: 12 cycles in Play with no pause running (counted: the usual frame); up to about 60 in the
//       other states' ordinary frames; a state change up to about 150; the formation's return
//       about 2,000 and a new game about 2,400 (formation_init: frames with nothing to hit).
//       Inside game_update's figure (memory-map.md row 1)
game_state_update:
        lda zp_clear_timer              // 3   the pause after a cleared formation
        beq !state+                     // 3
        dec zp_clear_timer
        bne !state+
        jsr formation_init              // the same 18 again (stage 4: the next wave's intro)
        lda #LAUNCH_TIMER_START
        sta zp_launch_timer
!state: ldx zp_game_state               // 3
        beq !out+                       // 3   Play: nothing to count
        inc zp_state_timer
        bne !+
        dec zp_state_timer              // stays at 255
!:      lda zp_state_timer
        cpx #GAME_STATE_DYING
        beq !dying+
        bcs !over+

        // Respawn: READY for 50 frames, then Play.
        cmp #RESPAWN_FRAMES
        bcc !out+
        jsr game_text_clear
        lda #LAUNCH_TIMER_START
        sta zp_launch_timer
        lda #GAME_STATE_PLAY
        sta zp_game_state
!out:   rts

        // PlayerDying: at least 100 frames; then GameOver with no lives left, or Respawn as
        // soon as nothing is diving.
!dying: cmp #DYING_MIN_FRAMES
        bcc game_state_update_end
        lda zp_lives
        beq !gameover+
        lda zp_divers_active
        bne game_state_update_end
        jsr player_respawn              // X 171, shown, invulnerable for 150 frames from this one
        ldx #TEXT_READY_LEN - 1
!:      lda text_ready,x
        sta MSG + TEXT_READY_COL,x
        dex
        bpl !-
        lda #GAME_STATE_RESPAWN
        bne !enter+                     // always

!gameover:
        lda game_score                  // the high score changes here and nowhere else
        cmp game_hiscore
        bcc !text+
        bne !higher+
        lda game_score + 1
        cmp game_hiscore + 1
        bcc !text+
        bne !higher+
        lda game_score + 2
        cmp game_hiscore + 2
        bcc !text+
        beq !text+
!higher:
        lda game_score
        sta game_hiscore
        lda game_score + 1
        sta game_hiscore + 1
        lda game_score + 2
        sta game_hiscore + 2
        lda panel_dirty                 // the only place but panel_init that asks for the
        ora #PANEL_DIRTY_HI             // high score's redraw (memory-map.md "The panel's budget")
        sta panel_dirty
!text:  ldx #TEXT_GAME_OVER_LEN - 1
!:      lda text_game_over,x
        sta MSG + TEXT_GAME_OVER_COL,x
        dex
        bpl !-
        lda #GAME_STATE_GAMEOVER
!enter: sta zp_game_state
        lda #0
        sta zp_state_timer
        beq game_state_update_end       // always

        // GameOver: 200 frames; from frame 50 a new press of fire ends it. The new game starts
        // in the next frame.
!over:  cmp #GAMEOVER_FRAMES
        bcs !new+
        cmp #GAMEOVER_SKIP_FRAME
        bcc game_state_update_end
        lda zp_joy_pressed              // a NEW press: held fire doesn't skip the screen the
        and #JOY_FIRE                   // player died holding it on
        beq game_state_update_end
        lda #GAMEOVER_FRAMES - 1        // this is GameOver's last frame
        sta zp_state_timer
        bne game_state_update_end       // always
!new:   jsr game_new
game_state_update_end:
        rts

// Erase the message on row 12 (READY or GAME OVER): spaces over the longest text's cells. No star
// is ever in these cells (the band rule), so nothing is looked up.
// In:  nothing       Out: nothing
// Uses: A, X
// Cost: about 110 cycles (counted); only on a state change
game_text_clear:
        lda #GLYPH_SPACE
        ldx #TEXT_GAME_OVER_LEN - 1
!:      sta MSG + TEXT_GAME_OVER_COL,x
        dex
        bpl !-
        rts
.errorif TEXT_READY_COL < TEXT_GAME_OVER_COL || TEXT_READY_COL + TEXT_READY_LEN > TEXT_GAME_OVER_COL + TEXT_GAME_OVER_LEN, "game_text_clear erases GAME OVER's cells: READY must be inside them"
