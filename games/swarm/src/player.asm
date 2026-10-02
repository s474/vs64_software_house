// Swarm: the player's ship (design.md "Controls and rules", "Entities", "Stage 3 rules" 8-11).
// Virtual sprite 0, pinned, Y fixed at 221. Left / right move 3 pixels a frame with no inertia,
// clamped to X 24-318. Fire (held or pressed) spawns a shot at (player X, 213) when a shot slot is
// free and the cooldown is 0; the cooldown is 10 frames from each shot.
// Left and right together (impossible on a real stick) cancel: no movement.
// Stage 3: the ship can be hit (collide_update calls player_hit). It then becomes the white
// explosion, stationary, for 32 frames (the hit's frame and the 31 after: 4 shapes of 8 frames),
// and is hidden until the state machine (game.asm) calls player_respawn: back at X 171, moving
// and firing at once, invulnerable for 150 frames and drawn cyan / dark grey by that timer.
// The ship moves and fires in the states in which it is shown: Play and Respawn.

// The stick the player obeys: the joystick, or the script in the AUTOPLAY budget build
// (zp_joy itself is written only by engine/input.asm).
#if AUTOPLAY
.label player_joy = autoplay_joy
#else
.label player_joy = zp_joy
#endif

// Put the ship at its start position and set up virtual sprite 0.
// In:  nothing       Out: nothing
// Uses: A
// Cost: init only
player_init:
        lda #<PLAYER_X_START
        sta zp_player_x_lo
        sta mux_x_lo + SPR_PLAYER
        lda #>PLAYER_X_START
        sta zp_player_x_hi
        sta mux_x_hi + SPR_PLAYER
        lda #PLAYER_Y
        sta mux_y + SPR_PLAYER
        lda #SHAPE_PLAYER
        sta mux_ptr + SPR_PLAYER
        lda colour_table + COL_PLAYER
        sta mux_col + SPR_PLAYER
        lda #0
        sta zp_player_cooldown
        sta zp_player_invuln
        sta player_explode
        rts

// The ship comes back after a death: at its start position, shown, and invulnerable for
// PLAYER_INVULN_FRAMES frames counting this one (player_update counts the timer down after the
// collisions, so the collisions see it at 150 down to 1: exactly 150 frames).
// In:  nothing       Out: nothing
// Uses: A
// Cost: on entering Respawn only
player_respawn:
        jsr player_init
        lda #PLAYER_INVULN_FRAMES
        sta zp_player_invuln
        rts

// The player is hit (frame 0 of PlayerDying; design Stage 3 rule 8): lives - 1 and the markers
// redrawn (by panel_update, next frame), all enemy shots removed, the ship becomes the white
// explosion, the game state PlayerDying. player_update, later in this frame, shows the first
// explosion shape and doesn't move or fire. Player shots in flight are left alone.
// In:  nothing       Out: nothing
// Uses: A
// Cost: 60 cycles + jsr/rts (counted); at most once a frame, from collide_update
player_hit:
        // SFX (part B): the player hit, two effects started together, voices 2 and 3, priority 3
        dec zp_lives                            // 5
        lda panel_dirty                         // 4
        ora #PANEL_DIRTY_LIVES                  // 2
        sta panel_dirty                         // 4
        lda #MUX_OFF                            // 2
        .for (var i = 0; i < SPR_ESHOT_COUNT; i++) {
                sta mux_y + SPR_ESHOT + i       // 4 each
        }
        lda colour_table + COL_PLAYER_EXPLODE   // 4
        sta mux_col + SPR_PLAYER                // 4
        lda #PLAYER_EXPLOSION_FRAMES + 1        // 2   player_update counts it to 32 in this frame
        sta player_explode                      // 4
        lda #GAME_STATE_DYING                   // 2
        sta zp_game_state                       // 3
        lda #0                                  // 2
        sta zp_state_timer                      // 3
        rts

// The ship's frame. Shown (Play, Respawn): count the invulnerability timer down and set the
// flash colour, move from the stick, count the cooldown down, fire, and write the ship's X to the
// multiplexer. Not shown (PlayerDying, GameOver): the explosion's shapes, then hidden.
// Runs LAST in the frame, after the collisions: a player hit this frame doesn't move or fire, and
// a slot freed by a hit can be fired from in the same frame.
// In:  player_joy (JOY_* bits), zp_game_state
// Out: mux_x_lo/hi, mux_col, mux_ptr, mux_y + SPR_PLAYER; a shot spawned in a free slot
// Uses: A, X, Y
// Cost: to player_update_end, raster cycles, IRQs excluded, measured
//       (tests/games/swarm/stage3_costs.txt): 92-260, average 125, in the AUTOPLAY build, which
//       holds the invulnerability timer at 2 so that the flash runs in every frame (600 passes,
//       lines 43-86: the 260 met a badline and a row's sprites; 248 in make test). On the game
//       build: 72-129 in Play with no flash, 91-185 with the flash, 46 exploding, 16 hidden (33
//       in the frame it is hidden). Budget 290 (memory-map.md row 3): it runs in the display,
//       after the collisions
player_update:
        lda zp_game_state               // 3
        cmp #GAME_STATE_DYING           // 2
        bcs !gone+                      // 2 / 3   PlayerDying or GameOver: no ship
        lda zp_player_invuln            // 3
        beq !move+                      // 2 / 3
        dec zp_player_invuln            // 5   the flash: cyan or dark grey by the timer, 4 frames
        ldx zp_player_invuln            // 3   each; cyan when it reaches 0
        ldy player_flash,x              // 4
        lda colour_table,y              // 4
        sta mux_col + SPR_PLAYER        // 4
!move:  lda player_joy
        and #JOY_LEFT | JOY_RIGHT
        cmp #JOY_RIGHT
        beq !right+
        cmp #JOY_LEFT
        bne !moved+                     // neither, or both: stay
        // Left: X - 3, not below PLAYER_X_MIN. X >= 24 before, so the 9-bit result can't go negative.
        lda zp_player_x_lo
        sec
        sbc #PLAYER_SPEED
        sta zp_player_x_lo
        bcs !+
        dec zp_player_x_hi
!:      lda zp_player_x_hi
        bne !moved+
        lda zp_player_x_lo
        cmp #PLAYER_X_MIN
        bcs !moved+
        lda #PLAYER_X_MIN
        sta zp_player_x_lo
        bne !moved+                     // always
!right: // Right: X + 3, not above PLAYER_X_MAX.
        lda zp_player_x_lo
        clc
        adc #PLAYER_SPEED
        sta zp_player_x_lo
        bcc !+
        inc zp_player_x_hi
!:      lda zp_player_x_hi
        beq !moved+
        lda zp_player_x_lo
        cmp #<(PLAYER_X_MAX + 1)
        bcc !moved+
        lda #<PLAYER_X_MAX
        sta zp_player_x_lo
!moved:
        lda zp_player_cooldown          // count down; fire only at 0
        beq !ready+
        dec zp_player_cooldown
        bne !nofire+
!ready: lda player_joy
        and #JOY_FIRE
        beq !nofire+
        ldx #0                          // first free shot slot
        lda mux_y + SPR_PSHOT
        cmp #MUX_OFF
        beq !spawn+
        inx
        lda mux_y + SPR_PSHOT + 1
        cmp #MUX_OFF
        beq !spawn+                     // (otherwise both are in flight)
!nofire:
        lda zp_player_x_lo
        sta mux_x_lo + SPR_PLAYER
        lda zp_player_x_hi
        sta mux_x_hi + SPR_PLAYER
        jmp player_update_end

        // No ship: the explosion's 32 frames (player_explode 32 down to 1: explosion_shape is the
        // enemies' 16-frame table, read at half speed), then hidden.
!gone:  lda player_explode
        beq player_update_end           // hidden already
        dec player_explode
        beq !hide+
        lda player_explode
        clc
        adc #1
        lsr
        tax
        lda explosion_shape,x
        sta mux_ptr + SPR_PLAYER
        bne player_update_end           // always: a shape pointer is never 0
!hide:  lda #MUX_OFF
        sta mux_y + SPR_PLAYER
        bne player_update_end           // always

        // The longest path ends here with no jump: the shot and the ship take the same X.
!spawn: // SFX (part B): the player shot sound, voice 1, priority 1 (X is the shot's slot)
        lda #PSHOT_SPAWN_Y
        sta mux_y + SPR_PSHOT,x
        lda #PSHOT_COOLDOWN
        sta zp_player_cooldown
        lda zp_player_x_lo
        sta mux_x_lo + SPR_PSHOT,x
        sta mux_x_lo + SPR_PLAYER
        lda zp_player_x_hi
        sta mux_x_hi + SPR_PSHOT,x
        sta mux_x_hi + SPR_PLAYER
player_update_end:
        rts
.errorif PLAYER_X_MIN < PLAYER_SPEED || PLAYER_X_MIN > 255 || PLAYER_X_MAX < 256 || PLAYER_X_MAX > 511 - PLAYER_SPEED, "player_update's clamps assume X_MIN in the low page and X_MAX in the high one"
.errorif SPR_PSHOT_COUNT != 2, "player_update looks for a free slot among exactly 2"
.errorif GAME_STATE_PLAY >= GAME_STATE_DYING || GAME_STATE_RESPAWN >= GAME_STATE_DYING || GAME_STATE_GAMEOVER < GAME_STATE_DYING, "player_update: the ship is shown in the states below GAME_STATE_DYING"

// Frames of the player's explosion left, + 1 in the hit's frame before player_update has run;
// 0 = no explosion (the ship is shown, or hidden after one).
player_explode: .byte 0
