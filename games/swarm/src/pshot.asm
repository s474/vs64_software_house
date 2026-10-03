// Swarm: the player's shots (design.md "Entities": virtual sprites 4-5, at most 2 on screen,
// Y - 8 a frame, removed when Y < 46). A shot's whole state is its multiplexer entry: mux_y is
// MUX_OFF while the slot is free, and player_update spawns one by writing mux_y and mux_x.
// Stage 1 has nothing to hit; collisions come in stage 2.

// Free both shot slots and set their shape, colour and flags (unpinned, hires).
// In:  nothing       Out: nothing
// Uses: A, X
// Cost: init only
pshot_init:
        ldx #SPR_PSHOT_COUNT - 1
!:      lda #MUX_OFF
        sta mux_y + SPR_PSHOT,x
        lda #SHAPE_PSHOT
        sta mux_ptr + SPR_PSHOT,x
        lda colour_table + COL_PLAYER_SHOT
        sta mux_col + SPR_PSHOT,x
        dex
        bpl !-
        rts

// Move the shots in flight up by PSHOT_SPEED and free those that have left the screen
// (Y < PSHOT_KILL_Y). Runs BEFORE player_update each frame, so a shot is shown at its spawn Y
// for one frame and a slot freed this frame can be fired from in the same frame.
// In:  nothing       Out: nothing
// Uses: A
// Cost: 16 raster cycles with no shot, 42-43 with two in flight, to pshot_update_end (measured:
//       vice_profile 100 passes, make test ARGS=swarm 300 passes, max 43; budget 60, memory-map.md row 4). No DMA
pshot_update:
        .for (var i = 0; i < SPR_PSHOT_COUNT; i++) {
                lda mux_y + SPR_PSHOT + i       // 4
                cmp #MUX_OFF                    // 2
                beq !next+                      // 3 taken (free) / 2
                sec                             // 2
                sbc #PSHOT_SPEED                // 2
                cmp #PSHOT_KILL_Y               // 2
                bcs !+                          // 3 taken (still on screen) / 2
                lda #MUX_OFF                    // 2
!:              sta mux_y + SPR_PSHOT + i       // 4
!next:
        }
pshot_update_end:
        rts
.errorif PSHOT_SPAWN_Y >= MUX_OFF || PSHOT_KILL_Y < PSHOT_SPEED, "pshot_update: a live shot's Y must stay clear of MUX_OFF and of 0"
