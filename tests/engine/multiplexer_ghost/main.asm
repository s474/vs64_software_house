// multiplexer_ghost probe (M3 stage 3.5): regression probe for the wrap ghosts.
//
// The VIC-II compares sprite Y with raster bits 0-7 only. On PAL (lines 0-311) a hardware
// sprite still enabled with Y <= 55 after its last slot matches again on line 256 + Y and is
// displayed a second time, across the frame wrap, into the top border of the next frame (up to
// line 20 for Y = 55). The DMA lands in the lower border and inside mux_irq_top. The ghost
// can't be seen with normal borders, so this probe opens the top and bottom borders (RSEL = 0
// on line 249, back to 1 on line 252): screenshots with area="full" then show every sprite
// the VIC displays outside the 320 x 200 window.
//
// Phases (PROBE_FRAMES frames each, cycling; write probe_lock = 0-4 to hold one, $FF cycles):
//   0  8 sprites at Y 48-55, nothing below: <= 8 slots, all 8 hardware sprites end at Y <= 55
//      (engine: mux_irq_top re-arms mux_irq_park)
//   1  8 at Y 30-51 + 4 at Y 120: 12 slots; hardware sprites 4-7 end at Y <= 55. The zone IRQ
//      chain ends on line ~52-60 (engine: re-arm mux_irq_park at MUX_PARK_LINE)
//   2  8 at Y 48-55 + 8 at Y 120: 16 slots, every hardware sprite ends at Y 120. Control: no ghost
//   3  8 at Y 30-37 + 1 at Y 55: slot 8 (a zone slot on hardware sprite 0) itself at Y = 55
//   4  8 at Y 52-55 + 4 at Y 100: hardware sprites 4-7 end at Y 55 and the zone chain ends on
//      or after MUX_PARK_LINE (engine: mux_zone_done parks at once)
//
// DEBUG counters (budget.json): probe_ghost_frames = frames in which, on line 249, some enabled
// hardware sprite has Y <= 55 (each of those frames displays a ghost); probe_ghost_mask = the
// $D015 bits of the last such frame. Plus irq_late_count and mux_late_count.
//
// Build: make GAME=multiplexer_ghost SRC_DIR=tests/engine/multiplexer_ghost
// Test:  make test ARGS=multiplexer_ghost

BasicUpstart2(start)

#import "zp.asm"
#import "build/multiplexer_ghost/sprites.hires.inc"   // SPRITES_HIRES_COUNT

.const MUX_SCREEN = $0400
.const MUX_Y_MAX  = $c0                         // fixed entries from $C2: the border opener is at $F9

.const SPRITE_DATA  = $2800                    // was $2000 until the stage 4 engine outgrew it
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

// Write the phase's 16 sprites (the rest stay hidden). Main loop. Uses A, X, Y.
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
!ph:    asl                             // phase * 16
        asl
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
        cpx #16
        bne !-
        rts

// Chain entry 1, line 249: open the top/bottom border, and count frames that will ghost.
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
        sta probe_ghost_mask
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
// Data: per phase, Y of virtual sprites 0-15 (MUX_OFF = hidden)
.const OFF = MUX_OFF
probe_y:
        .byte 48, 49, 50, 51, 52, 53, 54, 55, OFF, OFF, OFF, OFF, OFF, OFF, OFF, OFF     // 0
        .byte 30, 33, 36, 39, 42, 45, 48, 51, 120, 120, 120, 120, OFF, OFF, OFF, OFF     // 1
        .byte 48, 49, 50, 51, 52, 53, 54, 55, 120, 120, 120, 120, 120, 120, 120, 120     // 2
        .byte 30, 31, 32, 33, 34, 35, 36, 37, 55, OFF, OFF, OFF, OFF, OFF, OFF, OFF      // 3
        .byte 52, 53, 54, 55, 55, 55, 55, 55, 100, 100, 100, 100, OFF, OFF, OFF, OFF     // 4
probe_x:        .fill 8, 32 + i * 28                   // all < 256: X bit 8 stays 0
                .fill 8, 46 + i * 28
probe_colours:  .byte WHITE, YELLOW, CYAN, GREEN, LIGHT_RED, ORANGE, LIGHT_GREEN, LIGHT_GREY
                .byte PURPLE, RED, BROWN, GREY, LIGHT_BLUE, WHITE, YELLOW, CYAN
                .byte GREEN, LIGHT_RED, ORANGE, LIGHT_GREEN, LIGHT_GREY, PURPLE, RED, BROWN
probe_lock:     .byte $ff                       // $FF: cycle the phases; 0-4: hold that phase
probe_phase:    .byte 0
probe_count:    .byte PROBE_FRAMES
probe_ghost_frames: .byte 0                     // DEBUG: frames with a ghost pending (saturating)
probe_ghost_mask:   .byte 0                     // DEBUG: $D015 bits of the last one

.errorif * > SPRITE_DATA, "probe code runs into the sprite data"

* = SPRITE_DATA "Sprites"
        .import binary "build/multiplexer_ghost/sprites.hires.bin"
.errorif SPRITES_HIRES_COUNT != MUX_COUNT, "sprites.hires.png must have 24 sprites"
