// Swarm (M4 training game), stage 2: the player's ship moves and fires, the star field twinkles,
// the status panel is drawn, the formation of 18 enemies drifts and animates, and the player's
// shots hit the enemies: they explode and score. When all 18 are gone the formation comes back
// after the design's 75-frame pause (no bonus and no wave count yet: stage 4's). No dives, enemy
// shots, lives logic, title screen or sound yet.
//
// Design (the source of truth for behaviour): docs/games/swarm/design.md
// Memory, zero page, raster timeline, budgets: docs/games/swarm/memory-map.md
//
// Files (one per subsystem, all imported here):
//   zp.asm        zero page            consts.asm   hardware, layout and design constants
//   tables.asm    colour table, star table, custom glyphs, strings ($3800)
//   screen.asm    charset and screen set-up (init only)
//   stars.asm     star field and twinkle        panel.asm   status panel, score variables
//   player.asm    the ship                      pshot.asm   the player's shots
//   formation.asm the 18 enemies: per-enemy state, the drift, the animation, the explosions
//   collide.asm   player shots against the enemies, the score (engine/collision.asm)
//   autoplay.asm  the scripted stick of the AUTOPLAY budget build (tests/games/swarm/main.asm)
//
// Chain: entry 0 mux_irq_top at line 16, entry 1 game_irq_bottom at line 251 (nothing to do
// until the sound stage). Main loop: irq_wait_frame, input_read, panel_update (first, so it is
// always in the top border: memory-map.md "The panel's budget"), the update routines, mux_update.
//
// Rules this code keeps (engine v1, memory-map.md "(c) The four conditions"): after irq_init
// there is no sei, no write to $01, $DC00 or $DC02; $D011 is written once (screen_init); $D017
// and $D01D stay 0; sprites are written through the mux_* arrays only.
//
// Build:  make GAME=swarm            Run: make run GAME=swarm
// Budget: make test ARGS=swarm       (tests/games/swarm/budget.json, the AUTOPLAY build)
// Stick:  uv run --package budget-runner python tests/games/swarm/check.py
//
// Measured costs (VICE 3.10 x64sc PAL, DEBUG, 2026-10-02): in each routine's header. Where
// game_update runs in the frame (measured) is in its own header below.

BasicUpstart2(start)

#import "zp.asm"
#import "consts.asm"

// The sprite sheet (sprites.hires.png, beside this file) is converted by make into the build
// directory of the program being built, which is on the include path: build/swarm for the game,
// build/swarm_budget for the AUTOPLAY budget build (whose budget.json names this directory as
// its "asset_dir", so make converts the same PNG for it). No build-specific path here.
#import "sprites.hires.inc"             // SPRITES_HIRES_COUNT
.const SPRITE_BIN = "sprites.hires.bin"

// ------------------------------------------------------------------------------------------
* = ENGINE_START "Engine"
#import "engine/irq.asm"
#import "engine/multiplexer.asm"
#import "engine/input.asm"
#import "engine/rng.asm"
#import "engine/collision.asm"          // after the multiplexer: it reads its arrays. Needs col_pairs

* = * "Chain"
        IrqChainBegin()
        IrqNormal(MUX_TOP_LINE, mux_irq_top)    // entry 0, line 16: frame tick, sprites
        IrqNormal($fb, game_irq_bottom)         // entry 1, line 251: the sound tick (stage 4)
        IrqChainEnd()
.errorif * > CHARSET, "the engine block runs into the charset ($2800)"

// ------------------------------------------------------------------------------------------
* = CHARSET "Charset"
        .fill CHARSET_SIZE, 0           // built by screen_charset_init: ROM glyphs 0-63, 27-29 patched
                                        // $2A00-$2FFF: unused, kept empty

* = SPRITE_DATA "Sprites"
        .var sprite_bin = LoadBinary(SPRITE_BIN)
        .fill sprite_bin.getSize(), sprite_bin.get(i)
.errorif SPRITES_HIRES_COUNT != SHAPE_COUNT, "sprites.hires.png must have 13 shapes (games/swarm/art/README.md)"
.errorif * > GAME_TABLES, "the sprite shapes run into the game tables ($3800)"

* = GAME_TABLES "Game tables"
#import "tables.asm"
.errorif * > GAME_CODE, "the game tables run into the game code ($4000)"

// ------------------------------------------------------------------------------------------
* = GAME_CODE "Game code"

// Entry from BASIC. Everything that needs I set or a write to $01 happens here, before irq_init.
start:
        jsr screen_charset_init         // sei; $01 = $33 and back. I stays set until irq_init
        jsr screen_init
        jsr mux_init                    // before irq_init: entry 0 may fire straight away
        jsr game_sprites_init
        jsr stars_init
        jsr panel_init
        jsr player_init
        jsr pshot_init
#if AUTOPLAY
        lda #GAME_LOOP_MAX              // the budget build plays the hardest loop: the formation
#else                                   // drifts every frame (memory-map.md, AUTOPLAY)
        lda #0                          // loop 0 until the wave stage counts it
#endif
        sta zp_loop
        jsr formation_init              // after zp_loop: the drift's period depends on it
        jsr input_init                  // $DC02: before irq_init, and never written again
        lda #<GAME_RNG_SEED             // stage 1 draws no random numbers; a game start will seed
        ldx #>GAME_RNG_SEED             // from zp_irq_frame and $D012 (engine/rng.md), AUTOPLAY
        jsr rng_seed                    // with this constant
        lda #GAME_STATE_PLAY
        sta zp_game_state
        lda #0
        sta zp_state_timer
        sta zp_state_timer + 1
#if DEBUG
        sta game_overrun_count
        sta game_flicker_frames
        sta game_flicker_frames + 1
        lda #$ff
        sta game_idle_min
        sta game_idle_min + 1
        lda #GAME_IDLE_WARMUP
        sta game_idle_warm
#endif
        jsr irq_init                    // $01 = $35, chain running, interrupts on

// The frame. irq_wait_frame returns just after the tick at line 16, in the top border.
main:   jsr irq_wait_frame              // A = frame number
main_frame:
        sta zp_game_frame
// game_update .. game_update_end: everything the main loop does in a frame except mux_update.
// Cost: 576-764 raster cycles in the game (measured, vice_profile, 400 passes, moving and firing);
//       841-1,007 in the AUTOPLAY build, which redraws three panel fields and steps the drift
//       every frame (tests/games/swarm/stage2a_costs.py, 600 passes; max 1,020 in make test
//       ARGS=swarm, another 600). Budget 5,765.
//       It runs from line 23 to lines 36-39 (measured, the same script): still in the top
//       border, above the first badline (51) and the first enemy row (57), so no DMA yet
game_update:
        jsr input_read                  // exactly once a frame, straight after the tick
#if AUTOPLAY
        jsr autoplay_update
#endif
        jsr panel_update                // straight after the input: always in the top border. It
                                        // draws what the previous frame's updates made dirty
        jsr pshot_update                // before player_update: see pshot_update's header
        // Stand-in for stage 4's wave clear: when the last explosion has ended (enemy_kill starts
        // the timer) wait WAVE_CLEAR_PAUSE frames, then the same 18 again. No bonus, no wave + 1.
        lda zp_state_timer              // 3
        beq !+                          // 3: no pause running, the usual frame
        dec zp_state_timer
        bne !+
        jsr formation_init              // a frame with no enemy and nothing to hit: time to spare
!:      jsr formation_update            // every mover has moved before the collisions ...
        jsr collide_update
        jsr player_update               // ... and the player moves and fires after them
        jsr stars_update
game_update_end:
        jsr mux_update

#if DEBUG
        lda mux_drop_count              // did the multiplexer drop or evict a sprite this frame?
        beq !+
        inc game_flicker_frames         // 16 bits, saturating
        bne !+
        inc game_flicker_frames + 1
        bne !+
        dec game_flicker_frames
        dec game_flicker_frames + 1
!:      lda zp_irq_frame                // did the work finish inside the frame?
        cmp zp_game_frame
        beq game_idle_start
        inc game_overrun_count          // no: count it (saturating) and wait for the next tick,
        bne main                        // as the release build does
        dec game_overrun_count
        jmp main

// Idle loop: count iterations until the next frame tick. 16 cycles an iteration (21 on the
// 1-in-256 carry), as the multiplexer spike's (tests/engine/multiplexer/main.asm, spike_idle):
// budget.json multiplies game_idle_min by 16. IRQs and DMA that land in it reduce the count.
game_idle_start:
        sta game_idle_cmp + 1           // self-modified: compare with this frame's number
        lda #0
        sta zp_idle_lo
        sta zp_idle_hi
game_idle:
        inc zp_idle_lo                  // 5
        bne !+                          // 3 (2 on the carry)
        inc zp_idle_hi                  // 5 (1 in 256)
!:      lda zp_irq_frame                // 3
game_idle_cmp:
        cmp #$00                        // 2
        beq game_idle                   // 3  = 16
game_idle_done:
        // The tick has happened. Keep the fewest iterations seen after the warm-up, then start
        // the frame without going through irq_wait_frame (which would wait for another tick).
        lda game_idle_warm
        beq !+
        dec game_idle_warm
        bne !next+                      // always: the warm-up ends on the frame that makes it 0,
        beq !next+                      // and counting starts with the frame after
!:      lda zp_idle_hi
        cmp game_idle_min + 1
        bcc !new+
        bne !next+
        lda zp_idle_lo
        cmp game_idle_min
        bcs !next+
!new:   lda zp_idle_lo
        sta game_idle_min
        lda zp_idle_hi
        sta game_idle_min + 1
!next:  lda zp_irq_frame
        jmp main_frame
.errorif (>game_idle) != (>game_idle_done), "the idle loop crosses a page: its branches would cost a cycle more than the 16 counted"
#else
        jmp main
#endif

// Chain entry 1, line 251 (lower border, no DMA). Nothing to do until the sound stage, when it
// calls sfx_update. IRQ context: no zp_tmp*, no zp_joy_pressed.
// Cost: 93 cycles of framework, no work (engine/README.md#irq-framework-costs)
game_irq_bottom:
        IrqDone()

// Set the multiplexer's per-sprite flags, once, all 24: virtual sprites 0-3 (player, enemy
// shots) pinned, every sprite hires. Never written again. Call after mux_init (which hides
// every sprite).
// In:  nothing       Out: nothing
// Uses: A, X
// Cost: init only
game_sprites_init:
        ldx #MUX_COUNT - 1
!loop:  lda #0
        cpx #SPR_PINNED
        bcs !+
        lda #MUX_FLAG_PINNED
!:      sta mux_flags,x
        dex
        bpl !loop-
        rts


#if DEBUG
game_overrun_count:     .byte 0         // frames whose game_update + mux_update finished after the next tick (saturating)
game_flicker_frames:    .word 0         // frames in which mux_drop_count was not 0 after mux_update (saturating)
game_idle_warm:         .byte 0         // frames left before game_idle_min starts counting
#endif

#import "screen.asm"
#import "stars.asm"
#import "panel.asm"
#import "pshot.asm"
#import "player.asm"
#import "formation.asm"
#import "collide.asm"                   // after formation.asm: it uses the ENEMY_* states
#if AUTOPLAY
#import "autoplay.asm"
#endif
.errorif * > GAME_CODE_END, "game code and variables run past $5FFF"
