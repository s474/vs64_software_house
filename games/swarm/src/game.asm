// Swarm: the two state machines (design.md "Game flow", "Stage 3 rules" 8-13, "Stage 4 rules").
//
// THE GAME STATE (zp_game_state, zp_state_timer): what the player is doing.
//   Play ----------- the player is hit (collide_update -> player_hit) ----------> PlayerDying
//   PlayerDying ---- first frame, 100 or later, with no diver out, lives left --> Respawn
//   PlayerDying ---- frame 100, no lives left, whatever is diving --------------> GameOver
//   Respawn -------- 50 frames (READY, if the phase was Fight in its frame 0) --> Play
//   GameOver ------- 200 frames, or a NEW press of fire from its frame 50 ------> Title
//   Title ---------- a NEW press of fire from its frame 8 (title.asm) ----------> Play (game_new)
// zp_state_timer is the number of frames the state has run: 0 in the frame the state is entered,
// + 1 at the top of every later frame (game_state_update), stopping at 255. It isn't counted in
// Play. The player's hit happens in collide_update, so frame 0 of PlayerDying is the hit's frame;
// Respawn and GameOver are entered here, at the top of a frame, which is their frame 0.
//
// THE WAVE PHASE (zp_wave_phase, zp_wave_timer): what the formation is doing, beside the state.
//   Intro ---------- 50 frames: WAVE nn on row 9 for 49, enemy k appears in frame 2k ---> Fight
//   Fight ---------- the last explosion ends (formation_update -> enemy_kill) ----------> Clear
//   Clear ---------- + 1,000 in its frame 0; 75 frames of empty sky; then the next wave -> Intro
// zp_wave_timer is the number of frames the phase has run, 0 in its first frame. It counts in
// every frame in which lives > 0, whatever the game state, and stands still with the last life
// gone (Stage 4 rule 1). It isn't counted in Fight.
// The three wave stores (zp_wave BCD and sticking at 99, zp_pattern cycling 0-2, zp_loop sticking
// at 3) change only in the frame after Clear's 75th and in game_new (Stage 4 rule 5); everything
// a loop or a pattern changes is read from them where it is used.
//
// What the other files do with them: diver_update counts the launch timer and launches only in
// Play and Fight together; eshot_spawn fires only in Play; collide_update tests the player only
// in Play with zp_player_invuln 0; player_update moves and fires in Play and Respawn (the states
// in which the ship is shown).
//
// ROW 9 HOLDS ONE MESSAGE AT A TIME (Stage 4 rule 6): WAVE nn in Intro's frames 0-48; READY in
// Respawn, written only if the phase is Fight in Respawn's frame 0 and erased only if written
// (game_ready); GAME OVER over whatever is there.

// Start a game (design, Stage 4 rule 10), all in one frame, which is Intro's frame 0 of wave 1:
// score 0, lives 3, the wave stores at 01 / 0 / 0, no shot of either kind, the ship at X 171,
// shown, no invulnerability, the fire cooldown at 25, state Play, all four panel fields redrawn;
// then the wave's Intro (the formation reset, every diver slot free, WAVE 01, enemy 0). The high
// score is kept. Called by the title (title.asm) in the frame after its last text is erased, and
// at power-on in the budget build, which has no title.
// In:  nothing       Out: nothing
// Uses: A, X, Y, zp_tmp4-5
// Cost: about 950 cycles (counted: game_wave_intro's 720 and the other inits). Measured as
//       game_update for the frame it runs in, from the title, with the sound (stage 4 part B, the
//       build as tuned): 2,293-2,294 raster cycles, to line 59-60, formation_update 369 on lines
//       48-54, 14,432 cycles idle (a one-off frame: limits 4,000, 750 and 5,000 idle;
//       tests/games/swarm/stage4_costs.txt, item 4). Part A: 2,190, to line 58
game_new:
        ldx #TEXT_GAME_OVER             // row 9: the widest message's cells
        jsr game_text_erase
        lda #0
        sta game_score
        sta game_score + 1
        sta game_score + 2
        sta zp_state_timer
        sta game_ready
        lda #PLAYER_LIVES
        sta zp_lives
        lda #NEW_GAME_WAVE              // 01 / 0 / 0 (the budget build: wave 12's stores)
        sta zp_wave
        lda #NEW_GAME_PATTERN
        sta zp_pattern
        lda #NEW_GAME_LOOP
        sta zp_loop
        lda #PANEL_DIRTY_ALL            // all four fields, drawn at the top of the next frame: the
        sta panel_dirty                 // third place that sets PANEL_DIRTY_HI (memory-map.md)
        jsr eshot_init
        jsr pshot_init
        jsr player_init
        lda #NEW_GAME_COOLDOWN + 1      // player_update, later in this frame, counts it once: 25 at
        sta zp_player_cooldown          // the frame's end, and no shot in this frame or the 24 after
        lda #LAUNCH_TIMER_START
        sta zp_launch_timer
        lda #GAME_STATE_PLAY
        sta zp_game_state
        // falls through: the first wave's Intro, without advancing the stores

// Intro's frame 0 (design, Stage 4 rule 2): the formation reset with all 18 Waiting and 18 alive,
// every diver slot free, WAVE nn on row 9, the panel's wave redrawn, and enemy 0 Parked.
// In:  zp_wave, zp_loop      Out: zp_wave_phase = Intro, zp_wave_timer = 0
// Uses: A, X, Y, zp_tmp4-5
// Cost: about 720 cycles + jsr/rts (counted: formation_reset 430, diver_init 40, the text 150,
//       enemy_park 86); a one-off frame. Measured for a later wave's Intro frame 0, with the
//       wave-start request (stage 4 part B, as tuned): game_update 1,952-1,953, formation_update
//       326 on lines 44-49, 14,752 idle (stage4_costs.txt, item 2). Part A: 1,892, lines 43-48
game_wave_intro:
        lda #WAVE_PHASE_INTRO
        sta zp_wave_phase
        lda #0
        sta zp_wave_timer
        jsr formation_reset             // after the stores: the drift's period depends on zp_loop
        jsr diver_init                  // divers active 0 and every slot free (Stage 4 rule 4)
        ldx #TEXT_WAVE
        jsr game_text_draw              // "WAVE 00", then the shown wave's two digits
        lda zp_wave
        lsr
        lsr
        lsr
        lsr
        ora #GLYPH_ZERO
        sta MSG_WAVE_DIGITS
        lda zp_wave
        and #$0f
        ora #GLYPH_ZERO
        sta MSG_WAVE_DIGITS + 1
        lda panel_dirty
        ora #PANEL_DIRTY_WAVE
        sta panel_dirty
        lda #SFX_WAVE_START             // the wave start sound (voice 3, priority 2), in the
        jsr sfx_play                    // border: 36 cycles
        ldx #0                          // enemy k appears in frame 2k: enemy 0 now
        jmp enemy_park

// The wave is cleared: called by enemy_kill (inside formation_update) in the frame the last
// explosion ends, whatever the game state. + 1,000 (the score stops at 999,990), the panel's score
// marked for redraw, and the Clear phase starts: this is its frame 0.
// In:  nothing       Out: X preserved
// Uses: A, Y, zp_tmp0 (X kept in it across sfx_play)
// Cost: 104 cycles + rts, 120 when the score stops (counted: 62 / 78 + the sound request's 42
//       with X kept); inside formation_update's row. Measured: formation_update 692-712 in Clear's
//       first frame with 3 explosions ending on a turn-and-swap frame, ending on lines 38-39 (limit
//       750, above line 49; it was 650-670 without the sound; tests/games/swarm/stage4_costs.txt,
//       item 1)
game_wave_clear:
        lda #WAVE_PHASE_CLEAR           // 2
        sta zp_wave_phase               // 3
        lda #0                          // 2
        sta zp_wave_timer               // 3
        sed                             // 2   decimal mode is allowed (memory-map.md (c) 2)
        clc                             // 2
        lda game_score + 1              // 4
        adc #WAVE_BONUS_MID             // 2
        sta game_score + 1              // 4
        lda game_score                  // 4
        adc #0                          // 2
        sta game_score                  // 4
        cld                             // 2
        bcc !+                          // 3 / 2
        lda #$99                        // past 999,990: stop there
        sta game_score
        sta game_score + 1
        lda #$90
        sta game_score + 2
!:      lda panel_dirty                 // 4
        ora #PANEL_DIRTY_SCORE          // 2
        sta panel_dirty                 // 4
        stx zp_tmp0                     // 3   sfx_play uses A, X, Y and no zero page
        lda #SFX_WAVE_CLEAR             // 2   the wave clear sound (voice 3, priority 2)
        jsr sfx_play                    // 34  nothing pending on voice 3: no dive starts with
        ldx zp_tmp0                     // 3   the last enemy exploding
        rts

// The wave phase's frame, for Intro and Clear (Fight has nothing to count).
// In:  A = zp_wave_phase (Intro or Clear), lives > 0
// Out: enemies parked, WAVE nn erased, Fight entered; or the next wave's Intro
// Uses: A, X, Y, zp_tmp4-5
// Cost: about 25 cycles in an ordinary frame; 105 in a frame an enemy appears (enemy_park), 110
//       when WAVE nn is erased, about 790 when the next wave starts (counted). Measured over a
//       whole Intro with the ship firing: formation_update ends on line 37 at the latest
//       (stage4_costs.txt, item 3)
game_wave_step:
        inc zp_wave_timer
        ldx zp_wave_timer
        cmp #WAVE_PHASE_CLEAR
        beq !clear+
        cpx #INTRO_FRAMES               // Intro
        bcs !fight+
        cpx #INTRO_MSG_FRAMES
        beq !erase+
        cpx #2 * ENEMY_COUNT
        bcs !out+                       // all 18 have appeared (the last in frame 34)
        txa
        lsr
        bcs !out+                       // an odd frame
        tax
        jmp enemy_park                  // enemy k appears in frame 2k, Parked at its home
!erase: ldx #TEXT_WAVE
        jmp game_text_erase
!fight: lda #WAVE_PHASE_FIGHT           // the frame after Intro's last (frame 49)
        sta zp_wave_phase
        lda #FIGHT_LAUNCH_TIMER         // 10 once diver_update has counted this frame (consts.asm)
        sta zp_launch_timer
!out:   rts
!clear: cpx #WAVE_CLEAR_PAUSE
        bcc !out-
        // The frame after Clear's 75th: the three stores advance, here and nowhere else in a game
        // (Stage 4 rule 5), then Intro's frame 0 with the new numbers.
        lda zp_wave
        cmp #WAVE_MAX
        beq !+                          // the shown wave stops at 99
        sed
        clc
        adc #1
        cld
        sta zp_wave
!:      ldx zp_pattern
        inx
        cpx #PATTERN_COUNT
        bcc !+
        ldx #0                          // the pattern wraps: the next loop, up to 3
        lda zp_loop
        cmp #GAME_LOOP_MAX
        bcs !+
        inc zp_loop
!:      stx zp_pattern
        jmp game_wave_intro

// The frame's timers and state changes: the wave phase, then the game state. Called after the
// shots have moved and before formation_update (memory-map.md "Order of the frame").
// In:  zp_game_state, zp_state_timer, zp_wave_phase, zp_wave_timer, zp_lives, zp_joy_pressed
// Out: both machines stepped: texts on row 9, the ship (Respawn), the high score (GameOver), a
//      new wave, the title
// Uses: A, X, Y, zp_tmp4-5
// Cost: 22 cycles in Play and Fight (counted: the usual frame); up to about 60 in the other
//       states' ordinary frames; a state change up to about 300; the wave phase's frames as
//       game_wave_step; a new game about 950. Inside game_update's figure (memory-map.md row 1)
game_state_update:
        lda zp_lives                    // 3   the wave timer stands still with the last life gone
        beq !state+                     // 2
        lda zp_wave_phase               // 3
        beq !state+                     // 3   Fight: nothing to count
        jsr game_wave_step
!state: ldx zp_game_state               // 3
        beq !out+                       // 3   Play: nothing to count
        inc zp_state_timer
        bne !+
        dec zp_state_timer              // stays at 255
!:      lda zp_state_timer
        cpx #GAME_STATE_DYING
        beq !dying+
        bcc !respawn+
        jmp game_over_step

!respawn:
        // Respawn: 50 frames (READY, if it was written), then Play.
        cmp #RESPAWN_FRAMES
        bcc !out+
        lda game_ready
        beq !+                          // erased only if it was written
        ldx #TEXT_READY
        jsr game_text_erase
        lda #0
        sta game_ready
!:      lda #LAUNCH_TIMER_START
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
        lda zp_wave_phase               // READY only if the phase is Fight in Respawn's frame 0:
        bne !+                          // in a Clear or an Intro row 9 is WAVE nn's (Stage 4 rule 6)
        ldx #TEXT_READY
        jsr game_text_draw
        lda #1
        sta game_ready
!:      lda #GAME_STATE_RESPAWN
        bne !enter+                     // always

!gameover:
        lda game_score                  // the high score is compared and copied here, once, and
        cmp game_hiscore                // nowhere else (Stage 4 rule 14)
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
        lda panel_dirty                 // one of the three places that ask for the high score's
        ora #PANEL_DIRTY_HI             // redraw (memory-map.md "The panel's budget")
        sta panel_dirty
!text:  ldx #TEXT_GAME_OVER             // over whatever is there: its cells cover the other two
        jsr game_text_draw
        lda #SFX_GAME_OVER              // the game over sound (voice 1, priority 3): this is
        jsr sfx_play                    // GameOver's frame 0. In the border: 36 cycles
        lda #GAME_STATE_GAMEOVER
!enter: sta zp_game_state
        lda #0
        sta zp_state_timer
        beq game_state_update_end       // always

game_state_update_end:
        rts

// GameOver's frames after its first: 200 frames; from frame 50 a new press of fire ends it.
// In:  A = zp_state_timer (1 or more)     Out: the title when it ends
// Uses: A, X, Y, zp_tmp4-5
// Cost: about 20 cycles a frame (counted)
game_over_step:
        cmp #GAMEOVER_FRAMES
        bcs !new+
        cmp #GAMEOVER_SKIP_FRAME
        bcc !out+
        lda zp_joy_pressed              // a NEW press: held fire doesn't skip the screen the
        and #JOY_FIRE                   // player died holding it on
        beq !out+
        lda #GAMEOVER_FRAMES - 1        // this is GameOver's last frame
        sta zp_state_timer
!out:   rts
!new:   jmp title_enter                 // not a new game: the title (Stage 4 rule 13). main.asm
                                        // then skips the rest of this frame's play routines

// Write text X (a TEXT_* index: tables.asm) to its cells in the play area. Screen codes only: the
// play area's colour RAM has been the message colour since screen_init and no star is in a text's
// cells (the band rule).
// In:  X = text index        Out: nothing
// Uses: A, X, Y, zp_tmp4-5
// Cost: 47 + 17 a character + rts (counted): 132 for READY, 387 for the longest (20 cells).
//       Only on a state change; the title draws one text a frame
game_text_draw:
        lda text_scr_lo,x               // 4
        sta zp_tmp4                     // 3
        lda text_scr_hi,x               // 4
        sta zp_tmp5                     // 3
        ldy text_len1,x                 // 4
        lda text_last,x                 // 4
        tax                             // 2
!:      lda text_data,x                 // 4
        sta (zp_tmp4),y                 // 6
        dex                             // 2
        dey                             // 2
        bpl !-                          // 3
        rts

// Erase text X's cells: spaces. Erasing GAME OVER's cells erases any message on row 9.
// In:  X = text index        Out: nothing
// Uses: A, Y, zp_tmp4-5. X preserved
// Cost: 27 + 11 a character + rts (counted): 126 for GAME OVER's 9 cells
game_text_erase:
        lda text_scr_lo,x
        sta zp_tmp4
        lda text_scr_hi,x
        sta zp_tmp5
        ldy text_len1,x
        lda #GLYPH_SPACE
!:      sta (zp_tmp4),y
        dey
        bpl !-
        rts

game_ready:     .byte 0         // 1 while READY is on row 9: it is erased at Respawn's end only if written
