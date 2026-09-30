// multiplexer_top spike (M3 stage 3.5): holds mux_irq_top on its worst path every frame.
//
// mux_irq_top has three constant paths (engine/multiplexer.asm, measured to irq_exit_rti):
//   378  > 8 slots: re-arms mux_irq_zone at slot 8's free line
//   381  <= 8 slots with wrap ghosts (a slot at Y <= 55): re-arms mux_irq_park
//   393  <= 8 slots, no ghosts (mux_b_park = 0): IrqDone
// The multiplexer spike takes the 393 path in only ~1.8% of frames, and multiplexer_ghost only the
// other two, so neither exercises the 393 lock in a short make test window. Every frame here has
// <= 8 slots, all at Y >= 56 (MUX_WRAP_Y + 1), so every pass of mux_irq_top is the 393 path.
// The paths above assume a swap (mux_update ran since the last frame, as it does here every frame);
// re-showing the same frame (!keep) is 21 cycles shorter.
//
// Phases (PROBE_FRAMES frames each, cycling; write probe_lock = 0-4 to hold one, $FF cycles):
//   0  8 sprites at Y 56: the boundary (Y = 56 has no second matching line on PAL)
//   1  8 at Y 56-140, staggered: a row of 8 like a game's
//   2  8 at Y 150-192 (MUX_Y_MAX): the bottom of the shown range
//   3  1 sprite at Y 100: one slot
//   4  none shown (all hidden): zero slots, the same path
// The top and bottom borders are opened as in multiplexer_ghost (RSEL = 0 on line 249, 1 on 252),
// so a screenshot with area="full" would show any ghost; probe_ghost_frames counts frames with an
// enabled hardware sprite at Y <= 55 on line 249 (must stay 0).
//
// Build: make GAME=multiplexer_top SRC_DIR=tests/engine/multiplexer_top
// Test:  make test ARGS=multiplexer_top

BasicUpstart2(start)

#import "zp.asm"
#import "build/multiplexer_top/sprites.hires.inc"   // SPRITES_HIRES_COUNT

.const MUX_SCREEN = $0400
.const MUX_Y_MAX  = $c0                         // fixed entries from $C2: the border opener is at $F9

.const SPRITE_DATA  = $2000
.const PROBE_PTR0   = SPRITE_DATA / 64
.const PROBE_WRAP_Y = 311 - 256                 // largest Y that matches a second line on PAL
.const PROBE_PHASES = 5
.const PROBE_FRAMES = 32
.const VIC_CTRL1    = $d011

* = $0810 "Engine"
#import "engine/irq.asm"
#import "engine/multiplexer.asm"

* = * "Chain"
        IrqChainBegin()
        IrqNormal(MUX_TOP_LINE, mux_irq_top)
        IrqNormal($f9, probe_open)
        IrqNormal($fc, probe_close)
        IrqChainEnd()

* = * "Probe"
start:
        lda #0
        sta $d017
        sta $d01d
        sta $d01b
        sta $3fff                       // idle fetch in the open border: blank
        ldx #0
        lda #$20
!:      sta MUX_SCREEN,x
        sta MUX_SCREEN + $100,x
        sta MUX_SCREEN + $200,x
        sta MUX_SCREEN + $2e8,x
        inx
        bne !-
        jsr mux_init
        ldx #MUX_COUNT - 1
!:      txa
        clc
        adc #PROBE_PTR0
        sta mux_ptr,x
        lda probe_colours,x
        sta mux_col,x
        lda #0
        sta mux_x_hi,x
        sta mux_flags,x
        dex
        bpl !-
        jsr probe_set
        jsr irq_init

probe_main:
        jsr irq_wait_frame
        jsr probe_set
        jsr mux_update
        jmp probe_main

// Write the phase's 8 sprites (the rest stay hidden). Main loop. Uses A, X, Y.
probe_set:
        lda probe_lock
        bpl !ph+
        dec probe_count
        bne !+
        lda #PROBE_FRAMES
        sta probe_count
        ldx probe_phase
        inx
        cpx #PROBE_PHASES
        bne !nx+
        ldx #0
!nx:    stx probe_phase
!:      lda probe_phase
!ph:    asl                             // phase * 8
        asl
        asl
        tay
        ldx #0
!:      lda probe_y,y
        sta mux_y,x
        lda probe_x,x
        sta mux_x_lo,x
        iny
        inx
        cpx #8
        bne !-
        rts

// Chain entry 1, line 249: open the top/bottom border, and count frames that would ghost.
probe_open:
        lda VIC_CTRL1
        and #$77                        // RSEL = 0 (bit 3) before line 251; bit 7 stays clear
        sta VIC_CTRL1
#if DEBUG
        lda #0                          // bit j = 1: hardware sprite j has Y > PROBE_WRAP_Y
        .for (var j = 7; j >= 0; j--) {
            ldx $d001 + j * 2
            cpx #PROBE_WRAP_Y + 1
            rol
        }
        eor #$ff
        and $d015                       // enabled and Y <= 55: displayed again from line 256 + Y
        beq !+
        inc probe_ghost_frames
        bne !+
        dec probe_ghost_frames
!:
#endif
        IrqDone()

// Chain entry 2, line 252: RSEL back to 1 (the line-251 compare has been missed).
probe_close:
        lda VIC_CTRL1
        and #$7f
        ora #$08
        sta VIC_CTRL1
        IrqDone()

// ------------------------------------------------------------------------------------------
// Data: per phase, Y of virtual sprites 0-7 (MUX_OFF = hidden). Every Y shown is >= 56.
.const OFF = MUX_OFF
probe_y:
        .byte 56, 56, 56, 56, 56, 56, 56, 56                    // 0
        .byte 56, 68, 80, 92, 104, 116, 128, 140                // 1
        .byte 150, 156, 162, 168, 174, 180, 186, MUX_Y_MAX      // 2
        .byte 100, OFF, OFF, OFF, OFF, OFF, OFF, OFF            // 3
        .byte OFF, OFF, OFF, OFF, OFF, OFF, OFF, OFF            // 4
        .errorif (* - probe_y) != PROBE_PHASES * 8, "probe_y: 8 bytes per phase"
probe_x:        .fill 8, 32 + i * 28                   // 32-228, all < 256: X bit 8 stays 0
probe_colours:  .byte WHITE, YELLOW, CYAN, GREEN, LIGHT_RED, ORANGE, LIGHT_GREEN, LIGHT_GREY
                .byte PURPLE, RED, BROWN, GREY, LIGHT_BLUE, WHITE, YELLOW, CYAN
                .byte GREEN, LIGHT_RED, ORANGE, LIGHT_GREEN, LIGHT_GREY, PURPLE, RED, BROWN
probe_lock:     .byte $ff                       // $FF: cycle the phases; 0-4: hold that phase
probe_phase:    .byte 0
probe_count:    .byte PROBE_FRAMES
probe_ghost_frames: .byte 0                     // DEBUG: frames with a ghost pending (saturating)

.errorif * > SPRITE_DATA, "probe code runs into the sprite data"

* = SPRITE_DATA "Sprites"
        .import binary "build/multiplexer_top/sprites.hires.bin"
.errorif SPRITES_HIRES_COUNT != MUX_COUNT, "sprites.hires.png must have 24 sprites"
