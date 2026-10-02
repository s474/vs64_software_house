// Swarm: the player's ship (design.md "Controls and rules", "Entities"). Virtual sprite 0,
// pinned, Y fixed at 221. Left / right move 3 pixels a frame with no inertia, clamped to X
// 24-318. Fire (held or pressed) spawns a shot at (player X, 213) when a shot slot is free and
// the cooldown is 0; the cooldown is 10 frames from each shot.
// Left and right together (impossible on a real stick) cancel: no movement.
// Stage 1: no hit, no explosion, no respawn flash yet.

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
        rts

// Move the ship from the stick, count the cooldown down, fire, and write the ship's X to the
// multiplexer. Runs after pshot_update.
// In:  player_joy (JOY_* bits)   Out: mux_x_lo/hi + SPR_PLAYER; a shot spawned in a free slot
// Uses: A, X
// Cost: 56-122 raster cycles to player_update_end: 56 idle, 122 moving and firing in one frame
//       (measured: vice_profile 100 passes with right + fire held, make test ARGS=swarm 300
//       passes of the AUTOPLAY sweep, max 122; budget 200). Runs in the top border: no DMA
player_update:
        lda player_joy
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
        bne !nofire+                    // both in flight
!spawn: lda #PSHOT_SPAWN_Y
        sta mux_y + SPR_PSHOT,x
        lda zp_player_x_lo
        sta mux_x_lo + SPR_PSHOT,x
        lda zp_player_x_hi
        sta mux_x_hi + SPR_PSHOT,x
        lda #PSHOT_COOLDOWN
        sta zp_player_cooldown
!nofire:
        lda zp_player_x_lo
        sta mux_x_lo + SPR_PLAYER
        lda zp_player_x_hi
        sta mux_x_hi + SPR_PLAYER
player_update_end:
        rts
.errorif PLAYER_X_MIN < PLAYER_SPEED || PLAYER_X_MIN > 255 || PLAYER_X_MAX < 256 || PLAYER_X_MAX > 511 - PLAYER_SPEED, "player_update's clamps assume X_MIN in the low page and X_MAX in the high one"
.errorif SPR_PSHOT_COUNT != 2, "player_update looks for a free slot among exactly 2"
