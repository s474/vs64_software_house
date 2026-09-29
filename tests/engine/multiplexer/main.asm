// multiplexer spike (M3 stage 2): 24 virtual sprites through engine/multiplexer.asm, sorted,
// scheduled and written by zone IRQs, double buffered. No flicker or pinning yet (stages 3-4),
// so the motion is designed to keep <= 8 sprites in every scheduling window, always:
//
//   - Three groups of 8 (group g = v mod 3, member j = v / 3, so the virtual order interleaves
//     the groups and the sort has real work to do).
//   - Every group has the same 8 Y offsets, off[j] = amp * j / 8 (amp 0-24, so 0-21). amp
//     bounces; when it reaches 0 (all 8 on one row) the pattern reverses (j -> 7 - j), so the
//     order within each group flips through a tie every 48 frames.
//   - Group g's Y = b + g * D + off[j]. Because the offsets are identical, the sprite 8 places
//     earlier in Y order is always exactly D lines higher, so the scheduling window holds 8.
//   - D breathes between SPIKE_DMIN and SPIKE_DMIN + 20. SPIKE_DMIN is the scheduler's exact
//     limit for a full row of 8 under another full row (FREE_AFTER + IRQ_LINES + 8 * WRITE_LINES),
//     so at amp = 0 and D = DMIN every zone slot is kept with no slack: mux_late_count = 0
//     there is what validates the constants. b bounces between MUX_Y_MIN and the lowest base
//     that keeps group 2 at Y <= MUX_Y_MAX.
//   - X: each sprite bounces horizontally over 24-320 at 1-3 pixels a frame (X bit 8 in use).
//
// Chain: entry 0 mux_irq_top at $10, entry 1 spike_bottom at $FB (does nothing: proves a fixed
// entry coexists with the zone IRQs). Main loop: irq_wait_frame (via the idle loop), move,
// mux_update, then the idle loop counts iterations until the next frame tick.
//
// Sprites: sprites.hires.png (the virtual sprite's number in a ring) through tools/png2sprites,
// converted by make to build/multiplexer/sprites.hires.bin.
//
// DEBUG counters read by budget.json and the report: irq_late_count, mux_late_count,
// mux_max_age, spike_overrun_count, spike_idle_min, spike_drop_total (must stay 0 in stage 2:
// it proves the motion kept <= 8 per window).
//
// Build: make GAME=multiplexer SRC_DIR=tests/engine/multiplexer
// Test:  make test ARGS=multiplexer

BasicUpstart2(start)

#import "zp.asm"
#import "build/multiplexer/sprites.hires.inc"   // SPRITES_HIRES_COUNT

.const MUX_SCREEN = $0400
.const MUX_Y_MAX  = $f9

.const SPRITE_DATA = $2000                      // VIC bank 0: $1000-$1FFF is character ROM to the VIC
.const SPIKE_PTR0  = SPRITE_DATA / 64           // $80

* = $0810 "Engine"
#import "engine/irq.asm"
#import "engine/multiplexer.asm"

* = * "Chain"
        IrqChainBegin()
        IrqNormal(MUX_TOP_LINE, mux_irq_top)
        IrqNormal($fb, spike_bottom)
        IrqChainEnd()

.const SPIKE_AMP_MAX = 24                       // off[j] = amp * j / 8 <= 21
.const SPIKE_OFF_MAX = (SPIKE_AMP_MAX * 7) >> 3
.const SPIKE_DMIN    = MUX_FREE_AFTER + MUX_IRQ_LINES + 8 * MUX_WRITE_LINES
.const SPIKE_DMAX    = SPIKE_DMIN + 20
.const SPIKE_XMIN    = 24
.const SPIKE_XMAX    = 320
.const SPIKE_WARMUP  = 50                       // frames before spike_idle_min starts counting
.errorif MUX_Y_MIN + 2 * SPIKE_DMAX + SPIKE_OFF_MAX > MUX_Y_MAX, "spike motion doesn't fit the shown range"

* = * "Spike"
start:
        lda #0
        sta $d017                       // v1: no expansion
        sta $d01d
        sta $d01b
        ldx #0                          // clear the screen
        lda #$20
!:      sta MUX_SCREEN,x
        sta MUX_SCREEN + $100,x
        sta MUX_SCREEN + $200,x
        sta MUX_SCREEN + $2e8,x
        inx
        bne !-

        jsr mux_init
        ldx #MUX_COUNT - 1              // virtual sprites: pointer, colour, X, X speed
!:      txa
        clc
        adc #SPIKE_PTR0
        sta mux_ptr,x
        lda spike_colours,x
        sta mux_col,x
        lda spike_x0,x
        sta mux_x_lo,x
        lda #0
        sta mux_x_hi,x
        sta mux_flags,x
        lda spike_dx0,x
        sta spike_dx,x
        dex
        bpl !-
        jsr spike_move                  // valid Ys before the first mux_update

        jsr irq_init
        jsr irq_wait_frame

// The frame: zp_irq_frame has just ticked (mux_irq_top is running or done).
spike_main:
        lda zp_irq_frame
        sta zp_spike_frame
        jsr spike_move
        jsr mux_update
#if DEBUG
        lda mux_drop_count              // stage 2: must stay 0 (<= 8 per window by construction)
        beq !+
        clc
        adc spike_drop_total
        sta spike_drop_total
        bcc !+
        inc spike_drop_total + 1
!:
#endif
        lda zp_irq_frame                // work finished inside the frame?
        cmp zp_spike_frame
        beq spike_idle_start
        inc spike_overrun_count         // no: count it (saturating) and start the next frame now
        bne spike_main
        dec spike_overrun_count
        jmp spike_main

// Idle loop: count iterations until the next frame tick. 16 cycles per iteration (21 on the
// 1-in-256 carry into the high byte), counted, so free cycles ~= iterations x 16. IRQs and DMA
// that land in it simply reduce the count.
spike_idle_start:
        sta spike_idle_cmp + 1          // self-mod: compare with this frame's value
        lda #0
        sta zp_spike_idle_lo
        sta zp_spike_idle_hi
spike_idle:
        inc zp_spike_idle_lo            // 5
        bne !+                          // 3 (2 on carry)
        inc zp_spike_idle_hi            // 5 (1 in 256)
!:      lda zp_irq_frame                // 3
spike_idle_cmp:
        cmp #$00                        // 2
        beq spike_idle                  // 3  = 16
        // New frame. Keep the fewest iterations seen, after the warm-up.
        lda spike_warm
        beq !+
        dec spike_warm
        jmp spike_main
!:      lda zp_spike_idle_hi
        cmp spike_idle_min + 1
        bcc !new+
        bne !old+
        lda zp_spike_idle_lo
        cmp spike_idle_min
        bcs !old+
!new:   lda zp_spike_idle_lo
        sta spike_idle_min
        lda zp_spike_idle_hi
        sta spike_idle_min + 1
!old:   jmp spike_main

// Chain entry 1 at $FB: nothing to do.
spike_bottom:
        IrqDone()

// ------------------------------------------------------------------------------------------
// Move all 24 sprites (see the header for the pattern). Main loop.
// Uses: A, X, Y, zp_spike_acc
spike_move:
        // D breathes by 1 every 4 frames between DMIN and DMAX
        lda zp_spike_frame
        and #3
        bne !noD+
        lda spike_d
        clc
        adc spike_dd
        sta spike_d
        cmp #SPIKE_DMIN
        beq !flip+
        cmp #SPIKE_DMAX
        bne !noD+
!flip:  lda #0
        sec
        sbc spike_dd
        sta spike_dd
!noD:
        // b bounces between MUX_Y_MIN and MUX_Y_MAX - OFF_MAX - 2 * D
        lda spike_d
        asl
        sta zp_spike_acc
        lda #MUX_Y_MAX - SPIKE_OFF_MAX
        sec
        sbc zp_spike_acc
        sta zp_spike_acc                // bmax
        lda spike_b
        clc
        adc spike_db
        cmp zp_spike_acc
        bcc !+
        lda #$ff                        // at or past bmax: clamp, go up
        sta spike_db
        lda zp_spike_acc
!:      cmp #MUX_Y_MIN
        bcs !+
        ldx #1                          // at the top: go down
        stx spike_db
        lda #MUX_Y_MIN
!:      sta spike_b
        sta spike_base
        clc
        adc spike_d
        sta spike_base + 1
        clc
        adc spike_d
        sta spike_base + 2

        // amp bounces 0..AMP_MAX; at 0 (a full row) the pattern reverses
        lda spike_amp
        clc
        adc spike_damp
        sta spike_amp
        bne !+
        lda #1
        sta spike_damp
        lda spike_dir
        eor #1
        sta spike_dir
        jmp !offs+
!:      cmp #SPIKE_AMP_MAX
        bne !offs+
        lda #$ff
        sta spike_damp
!offs:  lda #0                          // off[j] = (amp * j) >> 3, j = 0..7 (or 7..0)
        sta zp_spike_acc
        ldx #0
!:      lda zp_spike_acc
        lsr
        lsr
        lsr
        ldy spike_dir
        beq !fwd+
        pha
        txa
        eor #7
        tay
        pla
        sta spike_off,y
        jmp !nx+
!fwd:   sta spike_off,x
!nx:    lda zp_spike_acc
        clc
        adc spike_amp
        sta zp_spike_acc
        inx
        cpx #8
        bne !-

        // Y and X for each virtual sprite
        ldx #MUX_COUNT - 1
!spr:   ldy spike_j,x
        lda spike_off,y
        ldy spike_g,x
        clc
        adc spike_base,y
        sta mux_y,x

        lda spike_dx,x
        bmi !left+
        clc
        adc mux_x_lo,x
        sta mux_x_lo,x
        bcc !+
        inc mux_x_hi,x
!:      lda mux_x_hi,x
        beq !xok+
        lda mux_x_lo,x
        cmp #SPIKE_XMAX - 256
        bcc !xok+
        bcs !neg+
!left:  clc
        adc mux_x_lo,x                  // adding a negative: carry clear = borrow
        sta mux_x_lo,x
        bcs !+
        dec mux_x_hi,x
!:      lda mux_x_hi,x
        bne !xok+
        lda mux_x_lo,x
        cmp #SPIKE_XMIN
        bcs !xok+
!neg:   lda #0
        sec
        sbc spike_dx,x
        sta spike_dx,x
!xok:   dex
        bpl !spr-
        rts

// ------------------------------------------------------------------------------------------
// Data
spike_j:        .fill MUX_COUNT, i / 3          // member within the group
spike_g:        .fill MUX_COUNT, mod(i, 3)      // group
spike_x0:       .fill MUX_COUNT, SPIKE_XMIN + i * 12
spike_dx0:      .fill MUX_COUNT, (mod(i, 2) == 0) ? (mod(i, 3) + 1) : ($100 - (mod(i, 3) + 1))
spike_colours:  .byte WHITE, YELLOW, CYAN, GREEN, LIGHT_RED, ORANGE, LIGHT_GREEN, LIGHT_GREY
                .byte PURPLE, RED, BROWN, GREY, LIGHT_BLUE, WHITE, YELLOW, CYAN
                .byte GREEN, LIGHT_RED, ORANGE, LIGHT_GREEN, LIGHT_GREY, PURPLE, RED, BROWN
spike_dx:       .fill MUX_COUNT, 0
spike_off:      .fill 8, 0
spike_base:     .fill 3, 0
spike_b:        .byte MUX_Y_MIN + 20
spike_db:       .byte 1
spike_d:        .byte SPIKE_DMIN + 10
spike_dd:       .byte 1
spike_amp:      .byte 12
spike_damp:     .byte 1
spike_dir:      .byte 0
spike_warm:     .byte SPIKE_WARMUP

spike_idle_min:         .word $ffff     // fewest idle iterations in a frame, after the warm-up
spike_overrun_count:    .byte 0         // frames whose work didn't finish before the next tick
spike_drop_total:       .word 0         // DEBUG: sprites dropped, summed (stage 2: must stay 0)

.errorif * > SPRITE_DATA, "spike code runs into the sprite data"

* = SPRITE_DATA "Sprites"
        .import binary "build/multiplexer/sprites.hires.bin"
.errorif SPRITES_HIRES_COUNT != MUX_COUNT, "sprites.hires.png must have 24 sprites"
