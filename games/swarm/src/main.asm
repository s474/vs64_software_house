// Swarm (M4 training game), stage 3: the player's ship moves and fires, the star field twinkles,
// the status panel is drawn, the formation of 18 enemies drifts and animates, the player's shots
// hit the enemies, and now the enemies dive (wind-up, three paths, return), shoot aimed shots and
// ram; the player has lives, dies, comes back behind READY, and the game ends with GAME OVER and
// starts again. Every formation is pattern 3 at loop 0 (design "Stage 3 rules", rule 1). No waves,
// wave-clear bonus, title screen or sound yet: stage 4.
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
//   eshot.asm     the enemies' shots            game.asm    the game states, a new game
//   formation.asm the 18 enemies: per-enemy state, the drift, the animation, the explosions
//   diver.asm     the launcher and the divers: wind-up, dive paths, firing, return
//   collide.asm   player shots against the enemies (grid lookup + box test), the player against
//                 enemy shots and divers, the score (engine/collision.asm)
//   autoplay.asm  the scripted stick of the AUTOPLAY budget build (tests/games/swarm/main.asm)
//
// Chain: entry 0 mux_irq_top at line 16, entry 1 game_irq_bottom at line 251 (nothing to do
// until the sound stage). Main loop: irq_wait_frame, input_read, panel_update and stars_update
// (first, so they are always in the top border: memory-map.md "The panel's budget", "Order of the
// frame"), pshot_update, eshot_update, game_state_update, formation_update, diver_update,
// collide_update, player_update, then mux_update. That order is memory-map.md's and is behaviour:
// shots move before the divers fire, every mover before the collisions, the player last.
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
        jsr input_init                  // $DC02: before irq_init, and never written again
        lda #<GAME_RNG_SEED             // a fixed seed until stage 4's title seeds from zp_irq_frame
        ldx #>GAME_RNG_SEED             // and $D012 at the press of fire (engine/rng.md); AUTOPLAY
        jsr rng_seed                    // keeps this constant
        jsr game_new                    // score 0, lives 3, wave 1's Intro frame 0, the ship, state Play
        dec zp_wave_timer               // game_new ran Intro's frame 0 outside a frame: the first frame
                                        // of the main loop counts the timer back to 0 and is frame 0
        lda #0
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
// Cost (stage 3, measured: tests/games/swarm/stage3_costs.py, results beside it; raster cycles,
//       IRQs excluded): 1,421-3,448, average 2,066, in the AUTOPLAY build (wave 12, 3 divers,
//       600 passes), from line 23 to lines 45-86. Budget 6,075. One-off frames: 2,875 when a
//       cleared formation comes back, 3,713 when a new game starts (formation_init: those frames
//       run formation_update below line 51, with nothing diving and nothing to hit).
//       Idle in the worst AUTOPLAY frame: 6,288 cycles (required 625)
game_update:
        jsr input_read                  // exactly once a frame, straight after the tick
#if AUTOPLAY
        jsr autoplay_update
#endif
        jsr panel_update                // straight after the input: always in the top border. It
                                        // draws what the previous frame's updates made dirty
        jsr stars_update                // in the border too (memory-map.md "Order of the frame"):
                                        // no badline, no sprite DMA, so its cost is its CPU count
        jsr pshot_update                // the shots move first, in the border ...
        jsr eshot_update                // ... so a shot fired this frame stays at its spawn position
        jsr game_state_update           // the state's timer and changes; the formation's return
        jsr formation_update            // this frame's home X, the animation, the explosions
        jsr diver_update                // the launcher, wind-up, dive paths (and their shots), return
        jsr collide_update              // every mover has moved before the collisions ...
        jsr player_update               // ... and the player moves and fires after them
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
#import "eshot.asm"
#import "player.asm"
#import "formation.asm"
#import "diver.asm"                     // after formation.asm: it uses the ENEMY_* states
#import "game.asm"
#import "collide.asm"                   // after formation.asm: it uses the ENEMY_* states
#if AUTOPLAY
#import "autoplay.asm"
#endif
.errorif * > GAME_CODE_END, "game code and variables run past $5FFF"
