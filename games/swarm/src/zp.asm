// Swarm: zero page. Every zero-page byte the game and the engine use is declared here, to the
// allocation in docs/games/swarm/memory-map.md#zero-page. $40-$FF are free.

// $02-$09: scratch, main loop only. mux_update uses zp_tmp0-3. Never held across a jsr, never
// used in an IRQ handler.
.label zp_tmp0 = $02
.label zp_tmp1 = $03
.label zp_tmp2 = $04
.label zp_tmp3 = $05
.label zp_tmp4 = $06
.label zp_tmp5 = $07
.label zp_tmp6 = $08
.label zp_tmp7 = $09

// $0A-$17: engine (engine/README.md#zero-page)
.label zp_irq_idx     = $0a     // IRQ: current chain entry
.label zp_irq_frame   = $0b     // shared: IRQ +1 at entry 0, main loop reads (one byte: atomic)
.label zp_mux_front   = $0c     // shared: IRQ writes on the swap. Game code doesn't touch it
.label zp_mux_ready   = $0d     // shared: main sets, IRQ clears. Game code doesn't touch it
.label zp_mux_slot    = $0e     // IRQ: next slot the zone IRQ writes
.label zp_mux_end     = $0f     // IRQ: end of the front buffer
.label zp_joy         = $10     // main loop (input.asm): the stick this frame
.label zp_joy_pressed = $11     // main loop (input.asm): newly pressed this frame. Never read in an IRQ
.label zp_rng_lo      = $12     // main loop (rng.asm): generator state
.label zp_rng_hi      = $13
.label zp_sfx_ptr     = $14     // 2 bytes, IRQ only (sfx.asm, stage 4). Unused until then
                                // $16-$17 reserved for the engine

// $18-$1F: game core (main.asm)
.label zp_game_frame  = $18     // the value irq_wait_frame returned for the frame being worked on
.label zp_game_state  = $19     // GAME_STATE_* (stage 1: always GAME_STATE_PLAY)
.label zp_state_timer = $1a     // 2 bytes: frames left in the current state (unused in stage 1)
.label zp_idle_lo     = $1c     // DEBUG: idle-loop iterations this frame
.label zp_idle_hi     = $1d
.label game_idle_min  = $1e     // 2 bytes, DEBUG, little-endian: fewest idle iterations in a frame
                                // after GAME_IDLE_WARMUP frames (budget.json reads it by this name)

// $20-$2F: player, shots, formation
.label zp_player_x_lo     = $20 // player X, sprite coordinates, 24-318 (9 bits)
.label zp_player_x_hi     = $21 // bit 8 of X in bit 0
.label zp_player_cooldown = $22 // frames until the player may fire again (0 = may fire)
.label zp_player_invuln   = $23 // frames of invulnerability left after a respawn (stage 3)
.label zp_lives           = $24 // lives, the ship in play included (3 at the start of a game)
.label zp_fx              = $25 // formation drift offset 0-96
.label zp_drift_dir       = $26 // formation drift direction: 1 = right, $FF = left (added to zp_fx)
.label zp_launch_timer    = $27 // frames until the next dive launch (stage 3)
.label zp_divers_active   = $28 // enemies in WindUp, Dive or Return (stage 3)
.label zp_enemies_alive   = $29 // enemies not dead (stage 2)
.label zp_wave            = $2a // wave number as shown, BCD 01-99
.label zp_loop            = $2b // difficulty loop 0-3 (counted from stage 4; 0 until then)
.label zp_drift_timer     = $2c // frames until the drift's next 1-pixel step
.label zp_anim_timer      = $2d // frames until the enemies' next animation swap
.label zp_anim_frame      = $2e // the enemies' animation frame, 0 or 1
                                // $2f free

// $30-$3F: pointers and per-call scratch for game routines
.label zp_star_ptr  = $30       // 2 bytes: colour RAM cell of the star being twinkled
.label zp_star_idx  = $32       // the star twinkled last frame, 0-47
                                // $33-$3f free
