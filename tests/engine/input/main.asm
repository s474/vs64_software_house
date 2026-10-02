// input spike (M4 stage 1): proves engine/input.asm against its contract, engine/input.md.
//
// Screen: the five bits of zp_joy as U D L R F with '*' (pressed) or '.' under each, zp_joy and
// zp_joy_pressed in hex, a count of fire presses (edges, from zp_joy_pressed), and a white
// sprite that moves with the stick (2 pixels a frame).
//
// Chain: entry 0 only, line $10 (top border, far above the first badline at $30). The main loop
// calls input_read straight after irq_wait_frame, so it runs on lines $11-$12: no badline, no
// sprite DMA (the sprite is kept at Y >= 60), and the frame's only IRQ is already over. The
// profile check input_read -> input_read_end is therefore exact.
//
// Labels for tests: spike_fire_presses (1 byte, wraps), spike_frame_done (executed once a frame,
// after the frame's input_read and display: tests/engine/input/check.py stops there).
//
// Build:  make GAME=input SRC_DIR=tests/engine/input
// Budget: make test ARGS=input          (tests/engine/input/budget.json)
// Stick:  uv run --package budget-runner python tests/engine/input/check.py
// Screenshot: screenshots/input-spike.png

BasicUpstart2(start)

#import "zp.asm"

.const VIC_SPR0_X     = $d000
.const VIC_SPR0_Y     = $d001
.const VIC_SPR_X_MSB  = $d010
.const VIC_SPR_ENABLE = $d015
.const VIC_BORDER     = $d020
.const VIC_BACKGROUND = $d021
.const VIC_SPR0_COL   = $d027
.const SCREEN         = $0400
.const COLOUR_RAM     = $d800
.const SPRITE_PTR0    = SCREEN + $3f8
.const SPRITE_BLOCK   = 13              // $0340: the cassette buffer, unused here

.const ROW_TITLE = SCREEN + 1 * 40 + 4
.const ROW_BITS  = SCREEN + 4 * 40 + 4
.const ROW_STATE = SCREEN + 5 * 40 + 4
.const ROW_JOY   = SCREEN + 8 * 40 + 4
.const ROW_PRESS = SCREEN + 9 * 40 + 4
.const ROW_FIRE  = SCREEN + 10 * 40 + 4

.const SPIKE_X_MIN = 24                 // sprite limits: on screen, X below 256
.const SPIKE_X_MAX = 254
.const SPIKE_Y_MIN = 60                 // well below the lines input_read runs on
.const SPIKE_Y_MAX = 228

.encoding "screencode_upper"

.macro SpikeText(addr, text) {
        ldx #text.size() - 1
!:      lda data,x
        sta addr,x
        dex
        bpl !-
        jmp done
data:   .text text
done:
}

.macro SpikeHex(value, addr) {
        lda value
        lsr
        lsr
        lsr
        lsr
        tax
        lda spike_hex_chars,x
        sta addr
        lda value
        and #$0f
        tax
        lda spike_hex_chars,x
        sta addr + 1
}

* = $0810 "Engine"
#import "engine/irq.asm"
#import "engine/input.asm"

* = * "Chain"
        IrqChainBegin()
        IrqNormal($10, spike_h0)
        IrqChainEnd()

* = * "Spike"
start:
        lda #BLACK
        sta VIC_BORDER
        sta VIC_BACKGROUND
        ldx #0
!:      lda #' '
        sta SCREEN,x
        sta SCREEN + $100,x
        sta SCREEN + $200,x
        sta SCREEN + $2e8,x
        lda #LIGHT_GREY
        sta COLOUR_RAM,x
        sta COLOUR_RAM + $100,x
        sta COLOUR_RAM + $200,x
        sta COLOUR_RAM + $2e8,x
        inx
        bne !-
        SpikeText(ROW_TITLE, "ENGINE/INPUT.ASM  JOYSTICK PORT 2")
        SpikeText(ROW_BITS,  "U   D   L   R   F")
        SpikeText(ROW_JOY,   "ZP JOY          $")
        SpikeText(ROW_PRESS, "ZP JOY PRESSED  $")
        SpikeText(ROW_FIRE,  "FIRE PRESSES    $")

        ldx #62
        lda #$ff
!:      sta SPRITE_BLOCK * 64,x         // a solid 24 x 21 block
        dex
        bpl !-
        lda #SPRITE_BLOCK
        sta SPRITE_PTR0
        lda #WHITE
        sta VIC_SPR0_COL
        lda #0
        sta VIC_SPR_X_MSB
        lda #$01
        sta VIC_SPR_ENABLE

        jsr input_init
        jsr irq_init                    // $01 = $35, CIA interrupts off: the KERNAL's scan has stopped

spike_main:
        jsr irq_wait_frame
        jsr input_read                  // first thing in the frame: lines $11-$12, no DMA

        lda zp_joy_pressed
        and #JOY_FIRE
        beq !+
        inc spike_fire_presses
!:
        // Move the sprite, 2 pixels a frame, clamped.
        lda zp_joy
        and #JOY_UP
        beq !+
        lda spike_y
        cmp #SPIKE_Y_MIN + 2
        bcc !+
        sbc #2
        sta spike_y
!:      lda zp_joy
        and #JOY_DOWN
        beq !+
        lda spike_y
        cmp #SPIKE_Y_MAX - 1
        bcs !+
        adc #2
        sta spike_y
!:      lda zp_joy
        and #JOY_LEFT
        beq !+
        lda spike_x
        cmp #SPIKE_X_MIN + 2
        bcc !+
        sbc #2
        sta spike_x
!:      lda zp_joy
        and #JOY_RIGHT
        beq !+
        lda spike_x
        cmp #SPIKE_X_MAX - 1
        bcs !+
        adc #2
        sta spike_x
!:      lda spike_x
        sta VIC_SPR0_X
        lda spike_y
        sta VIC_SPR0_Y

        // The five bits, bit 0 (up) first.
        lda zp_joy
        sta zp_tmp0
        ldx #0
!loop:  ldy spike_bit_col,x
        lda #'.'
        lsr zp_tmp0
        bcc !+
        lda #'*'
!:      sta ROW_STATE,y
        inx
        cpx #5
        bne !loop-

        SpikeHex(zp_joy, ROW_JOY + 17)
        SpikeHex(zp_joy_pressed, ROW_PRESS + 17)
        SpikeHex(spike_fire_presses, ROW_FIRE + 17)
spike_frame_done:
        jmp spike_main

spike_h0:
        IrqDone()

spike_fire_presses:
        .byte 0
spike_x:
        .byte 172
spike_y:
        .byte 150
spike_bit_col:
        .byte 0, 4, 8, 12, 16
spike_hex_chars:
        .text "0123456789ABCDEF"
