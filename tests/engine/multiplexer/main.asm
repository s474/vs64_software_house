// multiplexer spike (M3 stage 4): 24 virtual sprites through engine/multiplexer.asm, sorted,
// scheduled and written by zone IRQs, double buffered, with fair flicker and pinned sprites. The
// motion alternates between frames that keep <= 8 sprites in every scheduling window (the fast
// path) and frames that overload them (flicker):
//
//   - Three groups of 8 (group g = v mod 3, member j = v / 3, so the virtual order interleaves
//     the groups and the sort has real work to do).
//   - Every group has the same 8 Y offsets, off[j] = amp * j / 8 (amp 0-24, so 0-21). amp
//     bounces; when it reaches 0 (all 8 on one row) the pattern reverses (j -> 7 - j), so the
//     order within each group flips through a tie every 48 frames.
//   - Group g's Y = b + g * D + off[j]. Because the offsets are identical, the sprite 8 places
//     earlier in Y order is always exactly D lines higher, so the scheduling window holds 8.
//   - D breathes between SPIKE_DLO = SPIKE_DMIN - SPIKE_OVERLOAD and SPIKE_DMIN + 20. While
//     D >= SPIKE_DMIN the formation keeps <= 8 in every window; below it the rows crowd each
//     other and the multiplexer has to flicker. SPIKE_DMIN is the scheduler's exact limit for a
//     full row of 8 under another full row (FREE_AFTER + IRQ_LINES + 8 * WRITE_LINES). b bounces
//     between MUX_Y_MIN and the lowest base that keeps group 2 at Y <= MUX_Y_MAX.
//   - X: each sprite bounces horizontally over 24-320 at 1-3 pixels a frame (X bit 8 in use).
//   - Pinned (stage 4, engine/README.md#pinned-sprites): sprites 0-3 have mux_flags bit 7, the
//     maximum, so capacity is tested at its worst. Sprite 0, the "player", leaves the formation
//     and sweeps the whole shown range, MUX_Y_MIN to MUX_Y_MAX and back, 1 line a frame, through
//     every crowd. Sprite 1 tracks sprite 0's Y (at its own X) on the way down, and mirrors it
//     (MUX_Y_MIN + MUX_Y_MAX - y0) on the way up, so two pinned sprites share a row inside a crowd
//     for half of every sweep. Sprites 2 and 3 stay in the formation. 4-23 are unpinned. With
//     sprites 0 and 1 in the formation's windows, frames with D >= SPIKE_DMIN can overflow too.
//
// Chain: entry 0 mux_irq_top at $10, entry 1 spike_bottom at $FB (does nothing: proves a fixed
// entry coexists with the zone IRQs). Main loop: irq_wait_frame (via the idle loop), move,
// mux_update, then the idle loop counts iterations until the next frame tick.
//
// Sprites: sprites.hires.png (the virtual sprite's number in a ring) through tools/png2sprites,
// converted by make to build/multiplexer/sprites.hires.bin.
//
// DEBUG counters read by budget.json and the report: irq_late_count, mux_late_count,
// mux_max_age (unpinned), mux_pin_drop_count, mux_pin_excess_count, spike_overrun_count,
// spike_idle_min_normal and spike_idle_min_stress (engine/README.md#multiplexer-spike-free-cpu-labels;
// both in zero page, see zp.asm); reported: spike_drop_total (sprites dropped or evicted, summed) and
// spike_flicker_frames (frames with at least one).
//
// Build: make GAME=multiplexer SRC_DIR=tests/engine/multiplexer
// Test:  make test ARGS=multiplexer

BasicUpstart2(start)

#import "zp.asm"
#import "build/multiplexer/sprites.hires.inc"   // SPRITES_HIRES_COUNT

.const MUX_SCREEN = $0400
.const MUX_Y_MAX  = $f9

.const SPRITE_DATA = $2800                      // VIC bank 0: $1000-$1FFF is character ROM to the VIC (was $2000 until stage 4)
.const SPIKE_PTR0  = SPRITE_DATA / 64           // $A0

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
.const SPIKE_OVERLOAD = 30                      // how far D goes below the no-overflow limit (stage 3)
.const SPIKE_DLO     = SPIKE_DMIN - SPIKE_OVERLOAD
.const SPIKE_XMIN    = 24
.const SPIKE_XMAX    = 320
.const SPIKE_WARMUP  = 50                       // frames before the spike_idle_min_* pair starts counting
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

        lda #$ff                        // free-CPU minima: $FFFF each (zero page, so set here)
        ldx #3
!:      sta zp_spike_idle_min,x
        dex
        bpl !-

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
        lda spike_flags0,x              // 0-3 pinned
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
        lda mux_drop_count              // dropped or evicted this frame
        beq !+
        inc spike_flicker_frames
        bne !nc+
        inc spike_flicker_frames + 1
!nc:    clc
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
        // New frame. Keep the fewest iterations seen in this frame's class, after the warm-up.
        // Class (engine/README.md#multiplexer-spike-free-cpu-labels): stress = spike_move left
        // spike_damp = 1 and spike_amp = 2..5; X = 0 (normal) or 2 (stress) indexes the pair.
        // TIMING: the classification adds 9 cycles (spike_damp negative) or 16 (positive) to the
        // old single-minimum code, limit 16. The minima are in zero page so that the indexed
        // compares and stores cost what the old absolute ones did (4 each).
        lda spike_warm
        beq !+
        dec spike_warm
        jmp spike_main
!:      ldx #0                          // 2  normal
        lda spike_damp                  // 4
        bmi !cls+                       // 3 taken = 9 / 2
        ldy spike_amp                   // 4
        ldx spike_class,y               // 4  = 16 (no page crossing: asserted at the table)
!cls:   lda zp_spike_idle_hi            // 3
        cmp zp_spike_idle_min + 1,x     // 4
        bcc !new+
        bne !old+
        lda zp_spike_idle_lo
        cmp zp_spike_idle_min,x         // 4
        bcs !old+
!new:   lda zp_spike_idle_lo
        sta zp_spike_idle_min,x         // 4
        lda zp_spike_idle_hi
        sta zp_spike_idle_min + 1,x     // 4
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
        cmp #SPIKE_DLO
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

        // Pinned sprites 0 and 1 leave the formation. Sprite 0 sweeps MUX_Y_MIN..MUX_Y_MAX and back.
        lda spike_py
        clc
        adc spike_pdy
        cmp #MUX_Y_MAX
        bcc !+
        ldx #$ff                        // reached the bottom: go up
        stx spike_pdy
        lda #MUX_Y_MAX
!:      cmp #MUX_Y_MIN + 1
        bcs !+
        ldx #1                          // reached the top: go down
        stx spike_pdy
        lda #MUX_Y_MIN
!:      sta spike_py
        sta mux_y + 0
        ldx spike_pdy                   // sprite 1: the same Y on the way down, mirrored on the way up
        bpl !+
        eor #$ff                        // MUX_Y_MIN + MUX_Y_MAX - y0 = (MUX_Y_MIN + MUX_Y_MAX + 1) + ~y0,
        clc                             // mod 256 (the result is in MUX_Y_MIN..MUX_Y_MAX)
        adc #(MUX_Y_MIN + MUX_Y_MAX + 1) & $ff
!:      sta mux_y + 1
        rts

// ------------------------------------------------------------------------------------------
// Data
spike_j:        .fill MUX_COUNT, i / 3          // member within the group
spike_g:        .fill MUX_COUNT, mod(i, 3)      // group
spike_x0:       .fill MUX_COUNT, SPIKE_XMIN + i * 12
spike_dx0:      .fill MUX_COUNT, (mod(i, 2) == 0) ? (mod(i, 3) + 1) : ($100 - (mod(i, 3) + 1))
spike_flags0:   .fill MUX_COUNT, (i < 4) ? $80 : 0     // mux_flags: 0-3 pinned, all hires
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
spike_py:       .byte MUX_Y_MIN         // sprite 0's Y (the sweep)
spike_pdy:      .byte 1                 // +1 down, -1 up
spike_warm:     .byte SPIKE_WARMUP

// Frame class by spike_amp when spike_damp = 1: 2 (the stress minimum's offset) for amp 2-5, else 0.
spike_class:    .fill SPIKE_AMP_MAX + 1, (i >= 2 && i <= 5) ? 2 : 0
.errorif (>spike_class) != (>(spike_class + SPIKE_AMP_MAX)), "spike_class crosses a page (ldx abs,y would cost a cycle)"

spike_overrun_count:    .byte 0         // frames whose work didn't finish before the next tick
spike_drop_total:       .word 0         // DEBUG: sprites dropped or evicted, summed
spike_flicker_frames:   .word 0         // DEBUG: frames with at least one sprite dropped

.errorif * > SPRITE_DATA, "spike code runs into the sprite data"

* = SPRITE_DATA "Sprites"
        .import binary "build/multiplexer/sprites.hires.bin"
.errorif SPRITES_HIRES_COUNT != MUX_COUNT, "sprites.hires.png must have 24 sprites"
