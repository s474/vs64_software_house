// engine/multiplexer.asm: sprite multiplexer v1 (M3 stage 2). Design contract:
// engine/README.md#sprite-multiplexer-v1-enginemultiplexerasm
//
// STAGE 2 SCOPE: sort, select (scheduling simulation, keep or drop), build, zone IRQs, double
// buffer. NOT YET: fair flicker (stage 3) and pinned sprites (stage 4). A sprite that doesn't fit
// is dropped for the frame (mux_drop_count), with no rotation; mux_flags bit 7 is ignored.
//
// API (engine/README.md#api)
//   mux_init      Hide all virtual sprites, reset. Call once, before irq_init. Uses A, X.
//   mux_update    Main loop, once per frame after writing the virtual arrays: sort, select, build
//                 the back buffer. Out: C=0 queued for the next mux_irq_top; C=1 skipped (the
//                 previous build hasn't been shown yet). Uses A, X, Y, zp_tmp0-zp_tmp3.
//   mux_irq_top   Chain entry 0: IrqNormal(MUX_TOP_LINE, mux_irq_top).
//   Virtual arrays (24 each, main loop writes): mux_x_lo, mux_x_hi (bit 0), mux_y (MUX_OFF hides),
//   mux_ptr, mux_col, mux_flags (bit 0 multicolour; bit 7 pinned: stage 4).
//
// The game defines before the import: MUX_SCREEN (screen whose +$3F8 are the sprite pointers) and
// MUX_Y_MAX (largest Y shown, <= $F9).
//
// Registers owned: $D000-$D010, $D015, $D01C, $D027-$D02E, MUX_SCREEN+$3F8..$3FF.
// $D017 and $D01D must be 0 (21-line sprites only).
// Zero page (game's zp.asm): zp_mux_front, zp_mux_ready (shared), zp_mux_slot, zp_mux_end (IRQ),
// zp_tmp0-zp_tmp3 (mux_update scratch).
//
// How a frame goes: mux_update (main loop) builds slot arrays into the back buffer (indices
// 0-23 or 32-55 of each 64-byte slot array) and sets zp_mux_ready. mux_irq_top (line 16) swaps
// it in, writes slots 0-7 and re-arms at slot 8's free line. mux_irq_zone writes slot k (on
// hardware sprite k & 7), carries on with k+1 if its sprite is free (waiting up to 2 lines),
// re-arms if it's further away, and ends the chain entry (IrqDone) after the last slot.
//
// Measured cost (VICE 3.10 x64sc PAL, DEBUG, tests/engine/multiplexer, 300 passes, 2026-09-29;
// engine/README.md#multiplexer-costs). CPU = no DMA (sprites and DEN off); raster = in the spike,
// 24 sprites, main loop running through the display:
//                          CPU min/avg/max          raster min/avg/max
//   mux_sort               436 / 598 / 2,237        479 / 695 / 2,894   (max: the spike reverses 3 x 8)
//   mux_select             2,165 / 2,183 / 2,193    2,374 / 2,774 / 3,286
//   mux_build              2,175 / 2,183 / 2,189    2,352 / 2,743 / 3,127
//   mux_update             4,826 / 4,984 / 6,639    5,647 / 6,342 / 8,603
//   mux_irq_top -> rti     378 (every pass, border)
//   mux_irq_zone -> rti    702 / 909 / 1,448        745 / 967 / 1,489   (8 slots, incl. waits)
//   zone slot, back to back 78 (DEBUG; 67 release)  78-~190 with DMA and waits
//
// Constraints:
//   - Slot k >= 8 is kept only if the scheduling simulation (MUX_FREE_AFTER, MUX_IRQ_LINES,
//     MUX_WRITE_LINES) says the zone IRQ can write it before its Y line. mux_late_count (DEBUG)
//     counts slots the IRQ reached on or after their Y line: must stay 0.
//   - No fixed chain entry between MUX_TOP_LINE and MUX_Y_MAX + 2.
//   - A zone IRQ's raster span includes DMA (badlines, sprites); see engine/README.md#dma-inside-an-irq.

.errorif zp_mux_front > $ff, "zp_mux_front must be in zero page"
.errorif zp_mux_ready > $ff, "zp_mux_ready must be in zero page"
.errorif zp_mux_slot > $ff, "zp_mux_slot must be in zero page"
.errorif zp_mux_end > $ff, "zp_mux_end must be in zero page"
.errorif zp_tmp0 > $ff || zp_tmp1 > $ff || zp_tmp2 > $ff || zp_tmp3 > $ff, "zp_tmp0-3 must be in zero page"
.errorif MUX_Y_MAX > $f9, "MUX_Y_MAX must be <= $F9"

.const MUX_COUNT       = 24
.const MUX_OFF         = $ff
.const MUX_TOP_LINE    = $10
.const MUX_Y_MIN       = $1e
.const MUX_FREE_AFTER  = 22             // estimate (README #6/#8)
.const MUX_IRQ_LINES   = 1              // measured: first write 0-1 lines after the free line in 1,999 of
                                        // 2,000 zone IRQs, 2 once (README #9); the slack in WRITE_LINES covers it
.const MUX_WRITE_LINES = 2              // measured: 1 gave mux_late_count 139 in 3,000 frames (a slot takes
                                        // 78 cycles with no DMA, up to ~2 lines with it); 2 gives 0, with
                                        // >= 7 lines of margin on full rows (README #9)
.const MUX_BUF         = 32             // buffer 1's base index in the slot arrays

// Spare indices 24-31 of each buffer hold per-buffer values (written by mux_update, read by mux_irq_top).
.const MUX_SPARE       = 24

.const MUX_VIC_SPR     = $d000
.const MUX_VIC_XMSB    = $d010
.const MUX_VIC_RASTER  = $d012
.const MUX_VIC_ENABLE  = $d015
.const MUX_VIC_MCOLOR  = $d01c
.const MUX_VIC_COLOR   = $d027
.const MUX_PTRS        = MUX_SCREEN + $3f8

// ------------------------------------------------------------------------------------------
// Data
// ------------------------------------------------------------------------------------------

// Slot arrays: 8 x 64 bytes in two aligned pages, so no indexed read crosses a page.
// mux_s_y sits at page offset $40 so the selection's mux_s_y - 8 + x (x >= 8) stays in the page.
.align $100
mux_s_xlo:      .fill 64, 0             // X bits 0-7
mux_s_y:        .fill 64, 0             // Y
mux_s_ptr:      .fill 64, 0             // sprite pointer
mux_s_col:      .fill 64, 0             // colour
mux_s_d010:     .fill 64, 0             // cumulative $D010 after this slot is written
mux_s_free:     .fill 64, 0             // line on which slot k's hardware sprite is free (k >= 8)
mux_s_d01c:     .fill 64, 0             // cumulative $D01C after this slot is written
mux_kept:       .fill 64, 0             // virtual sprite in this slot (mux_update only)

// Per-buffer values at index base + 24 (never a slot)
.label mux_b_end  = mux_s_free + MUX_SPARE   // end index (base + count)
.label mux_b_d015 = mux_s_ptr  + MUX_SPARE   // $D015 for the frame
.label mux_b_d010 = mux_s_d010 + MUX_SPARE   // $D010 after slots 0-7
.label mux_b_d01c = mux_s_d01c + MUX_SPARE   // $D01C after slots 0-7

.function mux_zone_blk(j) {
        .if (j == 0) .return mux_zone_0
        .if (j == 1) .return mux_zone_1
        .if (j == 2) .return mux_zone_2
        .if (j == 3) .return mux_zone_3
        .if (j == 4) .return mux_zone_4
        .if (j == 5) .return mux_zone_5
        .if (j == 6) .return mux_zone_6
        .return mux_zone_7
}

// Constant tables, 64 entries indexed by slot index (either buffer): hardware sprite k & 7.
.align $100
mux_t_blk_lo:   .for (var i = 0; i < 64; i++) .byte <mux_zone_blk(i & 7)
mux_t_blk_hi:   .for (var i = 0; i < 64; i++) .byte >mux_zone_blk(i & 7)
mux_t_bit:      .fill 64, 1 << (i & 7)
mux_t_nbit:     .fill 64, ($ff ^ (1 << (i & 7)))

// Virtual arrays and sort state: one page. mux_y and mux_order have a 25th entry, the sentinel
// (virtual sprite 24, Y = $FF) that ends the selection walk.
.align $100
mux_x_lo:       .fill MUX_COUNT, 0
mux_x_hi:       .fill MUX_COUNT, 0
mux_y:          .fill MUX_COUNT + 1, MUX_OFF
mux_ptr:        .fill MUX_COUNT, 0
mux_col:        .fill MUX_COUNT, 0
mux_flags:      .fill MUX_COUNT, 0
mux_order:      .fill MUX_COUNT + 1, i
mux_age:        .fill MUX_COUNT, 0      // frames since last shown (saturating)
mux_t_d015:     .byte $00, $01, $03, $07, $0f, $1f, $3f, $7f, $ff
mux_back:       .byte 0                 // back buffer base during mux_update
mux_vars_end:
        .errorif (mux_x_lo >> 8) != ((mux_vars_end - 1) >> 8), "multiplexer variables cross a page"

#if DEBUG
mux_late_count: .byte 0                 // slots the zone IRQ reached on or after their Y line (saturating)
mux_max_age:    .byte 0                 // highest mux_age ever reached
mux_drop_count: .byte 0                 // sprites dropped in the last mux_update
#endif

// ------------------------------------------------------------------------------------------
// Hide all virtual sprites and reset the multiplexer. Call once, before irq_init.
// In: nothing   Out: nothing   Uses: A, X
mux_init:
        lda #MUX_COUNT                  // the sentinel: virtual sprite 24, always hidden
        sta mux_order + MUX_COUNT
        lda #MUX_OFF
        sta mux_y + MUX_COUNT
        ldx #MUX_COUNT - 1
!:      lda #MUX_OFF
        sta mux_y,x
        txa
        sta mux_order,x
        lda #0
        sta mux_age,x
        sta mux_flags,x
        sta mux_x_hi,x
        dex
        bpl !-
        lda #0
        sta zp_mux_front
        sta zp_mux_ready
        sta zp_mux_end                  // front buffer (0) is empty
        sta mux_b_end
        sta mux_b_d015
        sta mux_b_d010
        sta mux_b_d01c
        sta MUX_VIC_ENABLE
#if DEBUG
        sta mux_late_count
        sta mux_max_age
        sta mux_drop_count
#endif
        rts

// ------------------------------------------------------------------------------------------
// Sort, select and build the next frame's sprites into the back buffer.
// In:  virtual arrays   Out: C=0 queued; C=1 skipped (previous build not shown yet)
// Uses: A, X, Y, zp_tmp0-zp_tmp3
// Cost: see mux_sort / mux_select / mux_build, measured in engine/README.md#multiplexer-costs
mux_update:
        lda zp_mux_ready
        beq !+
        sec
        rts
!:      lda zp_mux_front                // stable: the IRQ only changes it while ready = 1
        eor #MUX_BUF
        sta mux_back

// Insertion sort of mux_order (0-23) by mux_y. Nearly sorted between frames: 23 compares plus
// one shift per place a sprite moves. Equal Ys keep their order.
// zp_tmp0 = key, zp_tmp1 = sprite being inserted, zp_tmp2 = outer index, zp_tmp3 = its key
// Cost: 23 cycles per in-order pair; an insertion adds ~40 + 29 per place moved.
// Measured CPU 436-598 normal frames, 2,237 when the spike reverses three groups of 8.
mux_sort:
        ldx #0
        ldy mux_order
        lda mux_y,y                     // A = key of order[x]
!loop:  ldy mux_order + 1,x             // 4
        cmp mux_y,y                     // 4  prev - next
        beq !next+                      // 2  equal: in order, A still right
        bcs !insert+                    // 2  prev > next: out of order
        lda mux_y,y                     // 4  A = key of order[x+1]
!next:  inx                             // 2
        cpx #MUX_COUNT - 1              // 2
        bne !loop-                      // 3  = 23 per in-order pair
        jmp mux_sort_end

!insert:                                // A = prev key, Y = sprite to insert, X = its index - 1
        sta zp_tmp3
        sty zp_tmp1
        lda mux_y,y
        sta zp_tmp0
        stx zp_tmp2
!shift: lda mux_order,x                 // 4
        sta mux_order + 1,x             // 5
        dex                             // 2
        bmi !place+                     // 2
        ldy mux_order,x                 // 4
        lda mux_y,y                     // 4
        cmp zp_tmp0                     // 3
        beq !place+                     // 2  equal: stop (stable)
        bcs !shift-                     // 3  still greater: keep shifting   = 29 per place
!place: inx                             // X = -1 at the front: abs,X doesn't wrap, so index from X+1
        lda zp_tmp1
        sta mux_order,x
        ldx zp_tmp2
        lda zp_tmp3                     // order[x+1] is now the old prev: its key
        jmp !next-
mux_sort_end:

// Walk the sorted list and keep each shown sprite the zone IRQs can write in time.
// Slots 0-7 (written by mux_irq_top on line 16) always fit. Slot k >= 8 simulates the IRQs:
//   free  = y[k-8] + MUX_FREE_AFTER
//   start = max(free + MUX_IRQ_LINES, done[k-1]);  done = start + MUX_WRITE_LINES;  fits: done <= y
// Writes mux_s_y, mux_s_free, mux_kept, mux_b_end; ages (0 kept, +1 dropped).
// X = slot index (base + k), zp_tmp0 = order index, zp_tmp1 = y, zp_tmp2 = done[k-1], zp_tmp3 = base + 8
// Cost: ~55 per kept sprite in slots 0-7, ~100 in slots 8+ (counted); measured CPU 2,165-2,193
// for 24 shown sprites
mux_select:
        ldx mux_back
        txa
        clc
        adc #8
        sta zp_tmp3
        lda #0
        sta zp_tmp0
        sta zp_tmp2
#if DEBUG
        sta mux_drop_count
#endif
        beq !walk+                      // always

!skip:  inc zp_tmp0                     // above MUX_Y_MIN: not shown
!walk:  ldy zp_tmp0                     // 3
        lda mux_order,y                 // 4
        tay                             // 2  Y = virtual sprite
        lda mux_y,y                     // 4
        cmp #MUX_Y_MIN                  // 2
        bcc !skip-                      // 2
        cmp #MUX_Y_MAX + 1              // 2
        bcs !end+                       // 2  sorted: everything after is below the range, hidden, or the sentinel
        cpx zp_tmp3                     // 3
        bcs !sim+                       // 2
!keep:  sta mux_s_y,x                   // 5
        tya                             // 2
        sta mux_kept,x                  // 5
        lda #0                          // 2
        sta mux_age,y                   // 5
        inx                             // 2
        inc zp_tmp0                     // 5
        jmp !walk-                      // 3

!sim:   sta zp_tmp1                     // C = 1 here
        lda mux_s_y - 8,x               // y[k-8]
        adc #MUX_FREE_AFTER - 1         // + MUX_FREE_AFTER (C was 1)
        bcs !drop+                      // past line 255: can't fit
        sta mux_s_free,x
        adc #MUX_IRQ_LINES              // C = 0
        bcs !drop+
        cmp zp_tmp2
        bcs !+
        lda zp_tmp2                     // carry on in the IRQ that wrote slot k-1
!:      clc
        adc #MUX_WRITE_LINES
        bcs !drop+
        cmp zp_tmp1
        beq !fit+                       // done == y: fits
        bcs !drop+                      // done > y
!fit:   sta zp_tmp2
        lda zp_tmp1
        jmp !keep-

!drop:  lda mux_age,y                   // Y = virtual sprite
        clc
        adc #1
        bcs !+                          // saturate at 255
        sta mux_age,y
#if DEBUG
        cmp mux_max_age
        bcc !+
        sta mux_max_age
#endif
!:
#if DEBUG
        inc mux_drop_count
#endif
        inc zp_tmp0
        jmp !walk-

!end:   txa                             // end index = base + count
        ldx mux_back
        sta mux_b_end,x
mux_select_end:

// Copy the kept sprites into the back buffer's slot arrays, with the cumulative $D010 / $D01C
// per slot, and the per-buffer $D015 / $D010 / $D01C for mux_irq_top.
// X = slot index, Y = virtual sprite, zp_tmp0 = cumulative $D010, zp_tmp1 = $D01C, zp_tmp2 = end
// Cost: ~88 per slot (counted); measured CPU 2,175-2,189 for 24 slots
mux_build:
        lda mux_b_end,x                 // X = base (from mux_select)
        sta zp_tmp2
        lda #0
        sta zp_tmp0
        sta zp_tmp1
        cpx zp_tmp2
        beq !top+                       // nothing shown
!loop:  ldy mux_kept,x                  // 4
        lda mux_x_lo,y                  // 4
        sta mux_s_xlo,x                 // 5
        lda mux_ptr,y                   // 4
        sta mux_s_ptr,x                 // 5
        lda mux_col,y                   // 4
        sta mux_s_col,x                 // 5
        lda mux_x_hi,y                  // 4
        lsr                             // 2  C = X bit 8
        lda zp_tmp0                     // 3
        bcc !clr+                       // 2/3
        ora mux_t_bit,x                 // 4
        bcs !st+                        // 3  always
!clr:   and mux_t_nbit,x                // 4
!st:    sta zp_tmp0                     // 3
        sta mux_s_d010,x                // 5
        lda mux_flags,y                 // 4
        lsr                             // 2  C = multicolour
        lda zp_tmp1                     // 3
        bcc !clr+                       // 2/3
        ora mux_t_bit,x                 // 4
        bcs !st+                        // 3
!clr:   and mux_t_nbit,x                // 4
!st:    sta zp_tmp1                     // 3
        sta mux_s_d01c,x                // 5
        inx                             // 2
        cpx zp_tmp2                     // 3
        bne !loop-                      // 3  = ~80 per slot
// Per-buffer values: slots 0-7 are what mux_irq_top writes.
!top:   txa
        sec
        sbc mux_back                    // count
        cmp #9
        bcc !+
        lda #8
!:      tay                             // min(count, 8)
        ldx mux_back
        lda mux_t_d015,y
        sta mux_b_d015,x
        dey                             // slot min(count, 8) - 1: its cumulative values
        bmi !none+
        tya
        clc
        adc mux_back
        tay
        lda mux_s_d010,y
        sta mux_b_d010,x
        lda mux_s_d01c,y
        sta mux_b_d01c,x
        jmp !done+
!none:  lda #0
        sta mux_b_d010,x
        sta mux_b_d01c,x
!done:
mux_build_end:
        lda #1
        sta zp_mux_ready
        clc
mux_update_end:
        rts

// ------------------------------------------------------------------------------------------
// TIMING: chain entry 0, line MUX_TOP_LINE (16, top border: no badlines, no sprites yet).
// Swap in the back buffer if one is ready, write $D015/$D010/$D01C and slots 0-7, re-arm at
// slot 8's free line (or end the entry if there are <= 8 slots). Budget 600 (estimate).
// Cost: measured 378 from mux_irq_top to irq_exit_rti, every pass (constant path; + 32 framework before it)
mux_irq_top:
        lda zp_mux_ready                // 3
        beq !keep+                      // 2
        lda zp_mux_front                // 3
        eor #MUX_BUF                    // 2
        sta zp_mux_front                // 3
        tax                             // 2
        lda mux_b_end,x                 // 4
        sta zp_mux_end                  // 3
        lda #0                          // 2
        sta zp_mux_ready                // 3
        beq !go+                        // 3  always
!keep:  ldx zp_mux_front                // 3  nothing new: show the same frame again
!go:    lda mux_b_d015,x                // 4
        sta MUX_VIC_ENABLE              // 4
        lda mux_b_d010,x                // 4
        sta MUX_VIC_XMSB                // 4
        lda mux_b_d01c,x                // 4
        sta MUX_VIC_MCOLOR              // 4
        .for (var j = 0; j < 8; j++) {  // 32 per slot, 256 in all
            lda mux_s_y + j,x
            sta MUX_VIC_SPR + 1 + j * 2
            lda mux_s_xlo + j,x
            sta MUX_VIC_SPR + j * 2
            lda mux_s_ptr + j,x
            sta MUX_PTRS + j
            lda mux_s_col + j,x
            sta MUX_VIC_COLOR + j
        }
        txa                             // 2
        clc                             // 2
        adc #8                          // 2
        tax                             // 2
        cpx zp_mux_end                  // 3
        bcs !done+                      // 2  <= 8 slots: nothing for the zone IRQs
        stx zp_mux_slot                 // 3
        lda mux_s_free,x                // 4  >= 52, far below line 16: no race with the late check
        IrqRearm(mux_irq_zone)
!done:  IrqDone()

// ------------------------------------------------------------------------------------------
// TIMING: zone IRQ, re-armed at slot zp_mux_slot's free line. Budget 550 per IRQ (estimate,
// raster span, DMA included). Dispatches to the block for hardware sprite (slot & 7): 22 cycles.
mux_irq_zone:
        ldx zp_mux_slot                 // 3
        lda mux_t_blk_lo,x              // 4
        sta mux_zone_jmp + 1            // 4
        lda mux_t_blk_hi,x              // 4
        sta mux_zone_jmp + 2            // 4
mux_zone_jmp:
        jmp mux_zone_jmp                // 3  = 22 (operand written above)

// End of the frame's slots: advance the chain.
mux_zone_done:
        IrqDone()

// The next slot's sprite frees 3 or more lines from now: re-arm at its free line.
// (3 lines of margin, so irq_rearm's own late check can't see the line even if a badline
// with 8 sprites lands in between.)
mux_zone_rearm:
        stx zp_mux_slot                 // 3
        lda mux_s_free,x                // 4
        IrqRearm(mux_irq_zone)          // 7 + irq_rearm

// Block j writes slot X on hardware sprite j, then moves on to slot X+1 (block j+1 & 7):
// straight in if its sprite is already free, after a wait if it frees within 2 lines, or
// through a re-arm. In: X = slot index (base included).
// Cost per slot: 48 (writes) + 19 (next slot free already) + 11 (DEBUG late check) = 78, measured
// block to block with no DMA (67 in release).
.macro MuxZoneBlock(j) {
#if DEBUG
        lda MUX_VIC_RASTER              // 4  late: the raster has reached the slot's Y line
        cmp mux_s_y,x                   // 4
        bcc !ok+                        // 3
        inc mux_late_count
        bne !ok+
        dec mux_late_count
!ok:
#endif
        lda mux_s_y,x                   // 4
        sta MUX_VIC_SPR + 1 + j * 2     // 4
        lda mux_s_xlo,x                 // 4
        sta MUX_VIC_SPR + j * 2         // 4
        lda mux_s_ptr,x                 // 4
        sta MUX_PTRS + j                // 4
        lda mux_s_col,x                 // 4
        sta MUX_VIC_COLOR + j           // 4
        lda mux_s_d010,x                // 4
        sta MUX_VIC_XMSB                // 4
        lda mux_s_d01c,x                // 4
        sta MUX_VIC_MCOLOR              // 4  = 48
        inx                             // 2
        cpx zp_mux_end                  // 3
        bne !more+                      // 3
        jmp mux_zone_done
!more:  lda mux_s_free,x                // 4
        cmp MUX_VIC_RASTER              // 4
        bcc !next+                      // 3  free < raster: go   (= 19 from inx)
        sbc #3                          // 2  C = 1: A = free - 3
        cmp MUX_VIC_RASTER              // 4
        bcc !wait+                      // 2  free - 3 < raster: frees within 2 lines
        jmp mux_zone_rearm
!wait:  lda mux_s_free,x                // 4
!w:     cmp MUX_VIC_RASTER              // 4
        beq !next+                      // 2
        bcs !w-                         // 3  free > raster: wait
!next:
}

mux_zone_blocks:
mux_zone_0:     MuxZoneBlock(0)
mux_zone_1:     MuxZoneBlock(1)
mux_zone_2:     MuxZoneBlock(2)
mux_zone_3:     MuxZoneBlock(3)
mux_zone_4:     MuxZoneBlock(4)
mux_zone_5:     MuxZoneBlock(5)
mux_zone_6:     MuxZoneBlock(6)
mux_zone_7:     MuxZoneBlock(7)
        jmp mux_zone_0
mux_zone_blocks_end:
