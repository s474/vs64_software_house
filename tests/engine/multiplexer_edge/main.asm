// multiplexer_edge probe (M3 follow-up): the multiplexer at the scheduler's limit, with slot Y
// lines on badlines. Specified in engine/README.md#slot-write-deadline (probe 2).
//
// Question: the engine keeps a zone slot when its simulated `done` line is <= Y, and its DEBUG
// check only covers the Y write. Can a slot's later writes (X, pointer, colour, $D010, $D01C)
// land after the VIC-II needs them, when Y is a badline and other sprites are being displayed?
// The deadlines are the ones tests/timing/sprite_latch measured.
//
// Static layouts, EDGE_FRAMES frames each, cycling. Each is built so zone slots sit exactly at the
// selection's limit (done = Y). yB is the Y of the first limit slot (slot 8), 96 + r for r = 2, 3
// and 4: 99 is a badline (YSCROLL = 3: lines 51 + 8n), 98 and 100 are the lines either side.
//   type 0 "rows":    three full rows 39 lines apart (yB - 39, yB, yB + 39): MUX_FREE_AFTER +
//                     MUX_IRQ_LINES + 8 x MUX_WRITE_LINES, a full row directly under a full row.
//                     One zone IRQ writes 8 slots; the last one's done line = its Y.
//   type 1 "reuse":   one hardware sprite reused at the 25-line limit (yB - 25, then yB) while
//                     the other 7 sprites (Y = yB - 16 .. yB - 4) are displayed across line yB.
//   type 2 "stairs":  three staircases of 8, each sprite 2 lines below the one before, the
//                     staircases 25 lines apart (Y = yB - 25 + 25 x row + 2 x i): EVERY zone slot
//                     has done = Y, each is written by its own zone IRQ (or after a wait in the
//                     previous one), and 6-7 other sprites are displayed while it is written.
//                     Its slots' Y lines cover every residue mod 8, badlines included.
// Phase = type x 6 + (r - 2) x 2 + mixed; mixed = 1 sets the multicolour bit on the middle row
// (virtual sprites 8-15), so the mixed zone blocks (which also write $D01C) run.
// Consecutive occupants of a hardware sprite always differ in X, colour, pointer (rows alternate
// a solid block and a half-width block) and, in mixed phases, the multicolour bit: a late write
// of any of them shows on the sprite's first line. No two sprites overlap, so edge.py can compare
// the whole frame buffer with the picture the virtual sprites should make.
//
// edge_lock (poke with vice_write_memory): $FF cycle the phases (default), 0-17 hold a phase,
//   $80 manual: the probe leaves the virtual arrays alone and edge.py writes its own layouts
//   (sweeps of the same three types over every line offset, and random dense layouts).
// The idle loop is the irq_chain spike's jitter generator (36 or 43 cycles a pass here, chosen by an
// LFSR), so the zone IRQs arrive on every phase of the main loop.
//
// DEBUG counters for budget.json: edge_drop_total (every layout must fit: 0), edge_overrun_count
// (0), edge_cycles (full passes through the 18 phases), plus mux_late_count and irq_late_count.
//
// Build:  make GAME=multiplexer_edge SRC_DIR=tests/engine/multiplexer_edge
// Test:   make test ARGS=multiplexer_edge        (the counters)
// Probe:  uv run python tests/engine/multiplexer_edge/edge.py     (every slot's write times and
//         the displayed picture, from outside; its header has the options and the results)
// Screenshots: screenshots/multiplexer-edge-*.png

BasicUpstart2(start)

#import "zp.asm"

.const MUX_SCREEN = $0400
.const MUX_Y_MAX  = $f9

.const SPRITE_DATA  = $2800
.const EDGE_PTR     = SPRITE_DATA / 64          // + 0: solid block, + 1: half-width block
.const EDGE_TYPES   = 3
.const EDGE_PHASES  = EDGE_TYPES * 6
.const EDGE_FRAMES  = 16
.const EDGE_MANUAL  = $80
.const EDGE_YB      = 96                        // + r: 99 is a badline

* = $0810 "Engine"
#import "engine/irq.asm"
#import "engine/multiplexer.asm"

* = * "Chain"
        IrqChainBegin()
        IrqNormal(MUX_TOP_LINE, mux_irq_top)
        IrqNormal($fb, edge_bottom)             // a fixed entry below the zone region, as a game has
        IrqChainEnd()

* = * "Probe"
start:
        lda #0
        sta $d017
        sta $d01d
        sta $d01b
        sta $d021                       // black background
        lda #11
        sta $d020
        lda #5
        sta $d025                       // sprite multicolour 1 (%01)
        lda #2
        sta $d026                       // sprite multicolour 2 (%11)
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
!:      lda edge_x_lo,x
        sta mux_x_lo,x
        lda edge_x_hi,x
        sta mux_x_hi,x
        lda edge_ptrs,x
        sta mux_ptr,x
        lda edge_cols,x
        sta mux_col,x
        dex
        bpl !-
        lda #$01
        sta zp_edge_lfsr                // any non-zero seed
        jsr edge_layout
        jsr irq_init
        jsr irq_wait_frame              // start the first pass on a frame tick, like every other:
                                        // without this the tick can land inside it (a false overrun)
edge_main:
        lda zp_irq_frame
        sta zp_edge_frame
        jsr edge_layout
        jsr mux_update
#if DEBUG
        lda mux_drop_count              // dropped or evicted this frame: every layout must fit
        clc
        adc edge_drop_total
        sta edge_drop_total
        bcc !+
        inc edge_drop_total + 1
!:
#endif
        lda zp_irq_frame                // work finished inside the frame?
        cmp zp_edge_frame
        beq edge_idle
        inc edge_overrun_count          // no: count it (saturating) and start the next frame now
        bne edge_main
        dec edge_overrun_count
        jmp edge_main

// Idle until the next frame tick, as a jitter generator (tests/engine/irq_chain): 7-cycle
// instructions mixed with short ones, 36 or 43 cycles a pass chosen by an LFSR, so IRQs land on
// every phase.
edge_idle:
        ldx #0
!loop:  inc edge_scratch,x              // 7
        asl zp_edge_lfsr                // 5  Galois LFSR, x^8+x^4+x^3+x^2+1: period 255
        bcc !+                          // 3 / 2
        lda zp_edge_lfsr                // 3
        eor #$1d                        // 2
        sta zp_edge_lfsr                // 3
!:      inc edge_scratch,x              // 7
        bit zp_edge_jit                 // 3
        inx                             // 2
        lda zp_irq_frame                // 3
        cmp zp_edge_frame               // 3
        beq !loop-                      // 3
        jmp edge_main

// Chain entry 1 at $FB: nothing to do.
edge_bottom:
        IrqDone()

// Write this frame's layout into the virtual arrays (Y and the multicolour flag; X, pointer and
// colour are fixed per virtual sprite). Main loop. Uses A, X.
edge_layout:
        lda edge_lock
        cmp #EDGE_MANUAL
        beq !done+                      // manual: edge.py owns the arrays
        cmp #$ff
        bne !hold+
        dec edge_count
        bne !+
        lda #EDGE_FRAMES
        sta edge_count
        ldx edge_phase
        inx
        cpx #EDGE_PHASES
        bne !nx+
        inc edge_cycles                 // a full pass through the phases (saturating)
        bne !z+
        dec edge_cycles
!z:     ldx #0
!nx:    stx edge_phase
!:      lda edge_phase
!hold:  tax
        stx edge_phase
        lda edge_row_lo,x
        sta edge_rd + 1
        lda edge_row_hi,x
        sta edge_rd + 2
        txa
        and #1                          // odd phases: mixed multicolour
        sta edge_mixed
        ldx #MUX_COUNT - 1
edge_rd:
        lda edge_y,x                    // operand = this phase's row of 24
        sta mux_y,x
        lda edge_mid,x                  // 1 for the middle row
        and edge_mixed
        sta mux_flags,x
        dex
        bpl edge_rd
!done:  rts

// ------------------------------------------------------------------------------------------
// Data. Virtual sprite v = row x 8 + i (row 0-2, i 0-7).
.function edge_yv(type, r, v) {
        .var yb = EDGE_YB + r
        .var row = floor(v / 8)
        .var i = mod(v, 8)
        .if (type == 0) .return yb - 39 + 39 * row
        .if (type == 2) .return yb - 25 + 25 * row + 2 * i
        .if (row == 0 && i == 0) .return yb - 25        // type 1: the reused sprite's first slot
        .if (row == 0) .return yb - 18 + 2 * i          //   the 7 displayed across line yb
        .if (row == 1 && i == 0) .return yb             //   the reuse, at the 25-line limit
        .return MUX_OFF
}
edge_y:
        .for (var t = 0; t < EDGE_TYPES; t++) {
            .for (var r = 2; r <= 4; r++) {
                .for (var m = 0; m < 2; m++) {
                    .for (var v = 0; v < MUX_COUNT; v++) .byte edge_yv(t, r, v)
                }
            }
        }
edge_row_lo:    .fill EDGE_PHASES, <(edge_y + i * MUX_COUNT)
edge_row_hi:    .fill EDGE_PHASES, >(edge_y + i * MUX_COUNT)
// X = 24 + 37 x i + 3 x row: columns never overlap, rows differ in X; column 7 has X bit 8 set
edge_x_lo:      .fill MUX_COUNT, <(24 + 37 * mod(i, 8) + 3 * floor(i / 8))
edge_x_hi:      .fill MUX_COUNT, >(24 + 37 * mod(i, 8) + 3 * floor(i / 8))
edge_ptrs:      .fill MUX_COUNT, EDGE_PTR + (floor(i / 8) & 1)
edge_cols:      .fill MUX_COUNT, 1 + mod(mod(i, 8) + 5 * floor(i / 8), 15)
edge_mid:       .fill MUX_COUNT, (floor(i / 8) == 1) ? 1 : 0
edge_lock:      .byte $ff               // $FF cycle, 0-17 hold a phase, $80 manual
edge_phase:     .byte 0
edge_count:     .byte EDGE_FRAMES
edge_mixed:     .byte 0
edge_cycles:    .byte 0                 // full passes through the phases (saturating)
edge_overrun_count: .byte 0             // frames whose work didn't finish before the next tick
edge_drop_total:    .word 0             // DEBUG: sprites dropped or evicted, summed (must stay 0)
edge_scratch:   .fill 256, 0

.errorif * > SPRITE_DATA, "probe code runs into the sprite data"

* = SPRITE_DATA "Sprites"
        .fill 63, $ff                   // solid 24 x 21 (multicolour: 12 double pixels of colour %11)
        .byte 0
        .for (var k = 0; k < 21; k++) .byte $ff, $f0, $00       // left 12 pixels
        .byte 0
