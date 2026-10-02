// Swarm: the AUTOPLAY script (budget build only: tests/games/swarm/main.asm defines AUTOPLAY).
// docs/games/swarm/memory-map.md#labels-the-game-must-provide: the game plays its worst case by
// itself, with no joystick. Stage 1: the "stick" sweeps right and left between the clamps with
// fire held, and the panel's in-play fields are redrawn every frame (the most panel_update can
// be asked to do in one frame of play), so make test measures the routines at their busiest.
// Nothing in this file is assembled into the game proper.

// Work out this frame's scripted stick: fire held, and right until the right clamp, then left
// until the left clamp, and so on.
// In:  zp_player_x_lo/hi   Out: autoplay_joy (JOY_* bits), panel_dirty
// Uses: A
// Cost: 35-45 cycles (counted), inside game_update
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
        rts

autoplay_joy:   .byte JOY_RIGHT | JOY_FIRE
