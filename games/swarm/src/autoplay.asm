// Swarm: the AUTOPLAY script (budget build only: tests/games/swarm/main.asm defines AUTOPLAY).
// docs/games/swarm/memory-map.md#labels-the-game-must-provide: the game plays its worst case by
// itself, with no joystick: the "stick" sweeps right and left between the clamps with fire held,
// the panel's in-play fields are redrawn every frame (the most panel_update can be asked to do in
// one frame of play: set here for the next frame's panel_update), and from stage 3 the respawn flash runs every frame and hits on the player
// are counted, not answered (collide.asm), at wave 12 (pattern 3, loop 3: game.asm, game_new).
// Nothing in this file is assembled into the game proper.

// Work out this frame's scripted stick: fire held, and right until the right clamp, then left
// until the left clamp, and so on.
// Called in game_update straight after stars_update (main.asm), not before panel_update: so the
// border routines start on the lines they start on in the game, which has no autoplay_update
// (memory-map.md "The long run"). What it sets is read later: autoplay_joy and zp_player_invuln
// by player_update in this frame (collide_update doesn't read the timer in this build), the three
// sound requests by the tick, and panel_dirty (overwritten with the in-play fields, which other
// routines may add to) by the NEXT frame's panel_update.
// In:  zp_player_x_lo/hi, zp_game_frame   Out: autoplay_joy (JOY_* bits), panel_dirty
// Uses: A; X and Y too in the frames it asks for the three effects
// Cost: 50-60 cycles (counted), + 125 every 64th frame; inside game_update
.const AUTOPLAY_SFX_PERIOD = 64         // frames between the three-effect requests (a power of 2)
autoplay_update:
        lda autoplay_joy
        and #JOY_RIGHT
        beq !left+
        lda zp_player_x_hi              // going right: turn at PLAYER_X_MAX
        beq !done+
        lda zp_player_x_lo
        cmp #<PLAYER_X_MAX
        bcc !done+
        lda #JOY_LEFT | JOY_FIRE
        sta autoplay_joy
        bne !done+                      // always
!left:  lda zp_player_x_hi              // going left: turn at PLAYER_X_MIN
        bne !done+
        lda zp_player_x_lo
        cmp #PLAYER_X_MIN + 1
        bcs !done+
        lda #JOY_RIGHT | JOY_FIRE
        sta autoplay_joy
!done:  lda #PANEL_DIRTY_PLAY
        sta panel_dirty
        lda #2                          // the respawn flash runs in every frame: player_update
        sta zp_player_invuln            // counts this to 1 (memory-map.md "What AUTOPLAY cannot
                                        // measure", change 2). collide_update ignores it here
        // Every 64 frames: three priority-3 effects, one a voice, so that the sound tick's worst
        // case (three effects starting in one tick) is in every run (memory-map.md "Stage 4" (e)).
        // In the border, nothing pending: 3 x 36 cycles.
        lda zp_game_frame
        and #AUTOPLAY_SFX_PERIOD - 1
        bne !out+
        lda #SFX_GAME_OVER              // voice 1
        jsr sfx_play
        lda #SFX_PLAYER_HIT_A           // voice 2
        jsr sfx_play
        lda #SFX_PLAYER_HIT_B           // voice 3
        jsr sfx_play
        inc autoplay_sfx_triples
        bne !out+
        inc autoplay_sfx_triples + 1
        bne !out+
        dec autoplay_sfx_triples        // saturate at $FFFF
        dec autoplay_sfx_triples + 1
!out:   rts

// A hit on the player that collide_update's scans reported: counted, not answered (the player
// can't be hit in the budget build; budget.json requires the count to be 1 or more, which shows
// that the scans were inside collide_update's figure).
// In:  nothing       Out: autoplay_player_hits + 1, stopping at $FFFF
// Uses: nothing (A, X, Y and the flags' users are unaffected: only inc / dec)
// Cost: 12 cycles + jsr/rts
autoplay_count_hit:
        inc autoplay_player_hits
        bne !+
        inc autoplay_player_hits + 1
        bne !+
        dec autoplay_player_hits        // saturate at $FFFF
        dec autoplay_player_hits + 1
!:      rts

autoplay_joy:   .byte JOY_RIGHT | JOY_FIRE
autoplay_player_hits:   .word 0         // little-endian, saturating at $FFFF
autoplay_sfx_triples:   .word 0         // frames in which the three effects were asked for; the same
                                        // (budget.json requires 1 or more)
