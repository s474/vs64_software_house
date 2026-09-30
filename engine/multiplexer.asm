// engine/multiplexer.asm: sprite multiplexer v1 (M3 stage 3). Design contract:
// engine/README.md#sprite-multiplexer-v1-enginemultiplexerasm
//
// STAGE 3 SCOPE: sort, fast-path select (the build merged into the keep path), slow path with
// rebuild, zone IRQs, double buffer, constant $D01C when every sprite has the same multicolour
// bit. NOT YET: pinned sprites (stage 4): mux_flags bit 7 is ignored.
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
// MUX_Y_MAX (largest Y shown, $50-$F9: >= 80 so mux_irq_park on lines 77-79 is in the zone region).
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
// Wrap ghosts (stage 3.5, engine/README.md#wrap-ghosts): hardware sprites whose last slot is at
// Y <= 55 are disabled on line 77 or later (mux_irq_park, or mux_zone_park at the end of the zone
// chain), so they don't match again on line 256 + Y. MUX_Y_MAX must be >= 80 for that.
//
// Fast path (engine/README.md#fast-path): while every sprite fits, the selection writes each
// kept sprite's slot (Y, X, pointer, colour, cumulative $D010, free line, done line) as it goes,
// and never writes mux_kept or mux_age. The first sprite that doesn't fit switches the rest of
// the frame to the slow path (mux_sel_fail): mux_kept is filled in, and at the end the slots from
// the first change onwards are rebuilt from mux_kept.
//
// Measured cost (VICE 3.10 x64sc PAL, DEBUG, raster cycles in tests/engine/multiplexer, DMA
// included, profile_excl_irq via the budget runner, 600 passes; engine/README.md#multiplexer-costs):
//                          stage 2 min/avg/max      stage 3 fast path (spike <= 8 per window)
//   mux_sort               479 / 705 / 3,315        455 / 703 / 3,315
//   mux_select             2,364 / 2,832 / 3,295    2,771 / 3,455 / 3,933   (now includes the build)
//   mux_build              2,349 / 2,767 / 3,272    142 / 186 / 283         (now the per-buffer tail)
//   mux_update             5,263 / 6,240 / 8,595    3,526 / 4,264 / 6,896   (target avg <= 5,000)
//   mux_irq_top -> rti     378                      378 (stage 3.5: see below)
//   mux_irq_zone -> rti    744 / 968 / 1,482        631 / 897 / 1,484 (1,000 IRQs)
//   zone slot, back to back 78 (DEBUG)              62 (DEBUG, uniform multicolour; 53 release, counted)
// Stage 3.5 (wrap-ghost fix, 2026-09-30; tests/engine/multiplexer and multiplexer_ghost, constant
// paths, DEBUG and release alike): mux_irq_top -> rti 378 (> 8 slots) / 381 (<= 8, ghosts to park)
// / 393 (<= 8, none); mux_irq_park -> rti 80; mux_zone_done -> rti 94 (parks at once) / 89
// (re-arms mux_irq_park); mux_build + 43 counted for the ghost scan.
// Overflow frames (fair flicker) and the overloaded spike: engine/README.md#multiplexer-costs.
//
// Constraints:
//   - Slot k >= 8 is kept only if the scheduling simulation (MUX_FREE_AFTER, MUX_IRQ_LINES,
//     MUX_WRITE_LINES) says the zone IRQ can write it before its Y line. mux_late_count (DEBUG)
//     counts slots the IRQ reached on or after their Y line: must stay 0.
//   - No fixed chain entry between MUX_TOP_LINE and MUX_Y_MAX + 2.
//   - A zone IRQ's raster span includes DMA (badlines, sprites); see engine/README.md#dma-inside-an-irq.
//   - Self-modifying: the selection loops' mux_order operands (code must be in RAM, as it is).

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
.const MUX_FREE_AFTER  = 22             // display on Y+1 .. Y+21 measured (README #6: tests/timing/sprite_wrap,
                                        // docs/reference/vic-ii-timing.md); that a rewrite on Y_old + 22 never
                                        // marks the old occupant's last line is still estimate #8
.const MUX_IRQ_LINES   = 1              // measured: first write 0-1 lines after the free line in 1,999 of
                                        // 2,000 zone IRQs, 2 once (README #9); the slack in WRITE_LINES covers it
.const MUX_WRITE_LINES = 2              // measured: 1 gave mux_late_count 139 in 3,000 frames (a slot takes
                                        // 78 cycles with no DMA, up to ~2 lines with it); 2 gives 0, with
                                        // >= 7 lines of margin on full rows (README #9)
.const MUX_GAP_MIN     = MUX_FREE_AFTER + MUX_IRQ_LINES + MUX_WRITE_LINES   // 25: y[k] - y[k-8] at least
.const MUX_BUF         = 32             // buffer 1's base index in the slot arrays
// Wrap ghosts (engine/README.md#wrap-ghosts): the VIC compares sprite Y with raster bits 0-7, so on
// PAL a sprite left enabled at Y <= MUX_WRAP_Y matches again on line 256 + Y and is displayed a
// second time across the frame wrap. A hardware sprite whose last slot of the frame has such a Y
// is disabled once that slot has been displayed, on or after MUX_PARK_LINE (Y + 21 <= 76 done).
.const MUX_WRAP_Y      = 311 - 256      // 55: largest Y with a second matching line (PAL, 312 lines)
.const MUX_PARK_LINE   = MUX_WRAP_Y + 22   // 77: every slot at Y <= 55 has finished displaying
.errorif MUX_Y_MAX < MUX_PARK_LINE + 3, "MUX_Y_MAX must be >= 80: mux_irq_park runs on lines 77-79, before any fixed entry"

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

// Slot arrays: 64 bytes each, in aligned pages, so no indexed read crosses a page.
// mux_s_y sits at page offset $40 so the selection's mux_s_y - 8 + x (x >= 8) stays in the page;
// mux_s_d010 and mux_s_d01c sit at $40 / $80 so their "previous slot" reads (- 1 + x, x >= 0)
// stay in the page too (they read mux_s_free + 63 / mux_s_d010 + 63 at x = 0: never written).
.align $100
mux_s_xlo:      .fill 64, 0             // X bits 0-7
mux_s_y:        .fill 64, 0             // Y
mux_s_ptr:      .fill 64, 0             // sprite pointer
mux_s_col:      .fill 64, 0             // colour
mux_s_free:     .fill 64, 0             // line on which slot k's hardware sprite is free (k >= 8); $FF after the last
mux_s_d010:     .fill 64, 0             // cumulative $D010 after this slot is written
mux_s_d01c:     .fill 64, 0             // cumulative $D01C after this slot is written (mixed multicolour only)
mux_kept:       .fill 64, 0             // virtual sprite in this slot (slow path and mixed multicolour only)
mux_s_done:     .fill 64, 0             // simulated line on which the zone IRQ has written slot k (main loop only)

// Per-buffer values at index base + 24 (never a slot; mux_s_free + 24 is the $FF sentinel of a full buffer)
.label mux_b_end  = mux_s_col  + MUX_SPARE   // end index (base + count)
.label mux_b_d015 = mux_s_ptr  + MUX_SPARE   // $D015 for the frame
.label mux_b_d010 = mux_s_d010 + MUX_SPARE   // $D010 after slots 0-7
.label mux_b_d01c = mux_s_d01c + MUX_SPARE   // $D01C after slots 0-7
.label mux_b_park = mux_s_xlo  + MUX_SPARE   // $D015 bits to clear after the frame's slots (wrap ghosts)

.function mux_zone_blk(j, mixed) {
        .if (mixed) {
            .if (j == 0) .return mux_zone_m0
            .if (j == 1) .return mux_zone_m1
            .if (j == 2) .return mux_zone_m2
            .if (j == 3) .return mux_zone_m3
            .if (j == 4) .return mux_zone_m4
            .if (j == 5) .return mux_zone_m5
            .if (j == 6) .return mux_zone_m6
            .return mux_zone_m7
        }
        .if (j == 0) .return mux_zone_0
        .if (j == 1) .return mux_zone_1
        .if (j == 2) .return mux_zone_2
        .if (j == 3) .return mux_zone_3
        .if (j == 4) .return mux_zone_4
        .if (j == 5) .return mux_zone_5
        .if (j == 6) .return mux_zone_6
        .return mux_zone_7
}

// Zone block per slot index (either buffer): hardware sprite k & 7, from the uniform set (no
// $D01C write) or the mixed set. mux_update rewrites a buffer's 24 entries when its multicolour
// mode changes (mux_blk_mode); the IRQ only reads the front buffer's, so there's no race.
.align $100
mux_t_blk_lo:   .for (var i = 0; i < 64; i++) .byte <mux_zone_blk(i & 7, false)
mux_t_blk_hi:   .for (var i = 0; i < 64; i++) .byte >mux_zone_blk(i & 7, false)
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
mux_age:        .fill MUX_COUNT, 0      // frames since last shown (saturating); see mux_dirty
mux_t_d015:     .byte $00, $01, $03, $07, $0f, $1f, $3f, $7f, $ff
mux_tpl_lo:     .for (var i = 0; i < 16; i++) .byte <mux_zone_blk(i & 7, i >= 8)
mux_tpl_hi:     .for (var i = 0; i < 16; i++) .byte >mux_zone_blk(i & 7, i >= 8)
mux_back:       .byte 0                 // back buffer base during mux_update
mux_mc_mode:    .byte 0                 // this frame: 0 all hires, 1 all multicolour, 2 mixed
mux_blk_mode:   .byte 0, 0              // per buffer: 0 uniform zone blocks in mux_t_blk, 1 mixed
mux_slow_from:  .byte 0                 // $FF: fast frame; else the first slot to rebuild
mux_dirty:      .byte 0                 // 1: some mux_age may be non-zero (a sprite was dropped)
mux_vars_end:
        .errorif (mux_x_lo >> 8) != ((mux_vars_end - 1) >> 8), "multiplexer variables cross a page"
        // The selection indexes mux_order with the slot index (base 0 or 32) from a self-modified
        // low byte: mux_order + skipped - base + x must stay in this page for any base.
        .errorif (mux_order & $ff) < MUX_BUF, "mux_order must be at page offset >= MUX_BUF"

// Slow-path scratch (eviction)
mux_ev_b8:      .byte 0                 // base + 8
mux_ev_lo:      .byte 0                 // k - 8
mux_ev_k1:      .byte 0                 // k - 1
mux_ev_j0:      .byte 0                 // max(w, base + 8)

#if DEBUG
mux_late_count: .byte 0                // slots the zone IRQ reached on or after their Y line (saturating)
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
        sta mux_b_park
        sta mux_dirty
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

// Fast-path selection: walk the sorted list and give each shown sprite its slot, writing the
// slot arrays directly (the build is merged into the keep path).
//   Setup: multicolour mode (unrolled over the 24 flags), skip the sprites above MUX_Y_MIN
//   (sorted first), point both loops' mux_order operand at order index = skipped + (x - base).
//   Loop 1, slots 0-7 (written by mux_irq_top on line 16): always fit.
//   Loop 2, slots 8+: simulate the zone IRQs. With free = y[k-8] + MUX_FREE_AFTER,
//     start = max(free + MUX_IRQ_LINES, done[k-1]); done = start + MUX_WRITE_LINES; fits: done <= y.
//     A new IRQ fits exactly when y - y[k-8] >= MUX_GAP_MIN, which is checked first (and bounds
//     every sum below 256); carrying on in slot k-1's IRQ also needs done[k-1] + WRITE <= y.
//   The first sprite that doesn't fit leaves for the slow path (mux_sel_fail), for the rest of
//   the frame.
// X = slot index (base + k), Y = virtual sprite, zp_tmp3 = base + 8
// Cost (counted): setup ~150; loop 1 68-70 per slot; loop 2 108 (new IRQ) / 124 (carry on) per slot
mux_select:
        lda mux_flags + 0               // multicolour mode: OR of bit 0 over all 24 = 0 -> all hires
        .for (var i = 1; i < MUX_COUNT; i++) ora mux_flags + i
        and #1
        beq !mode+                      // mode 0
        lda mux_flags + 0               // AND of bit 0 = 1 -> all multicolour
        .for (var i = 1; i < MUX_COUNT; i++) and mux_flags + i
        and #1
        bne !mode+                      // mode 1
        lda #2                          // mixed
!mode:  sta mux_mc_mode

        ldy #0                          // skip sprites above MUX_Y_MIN: they sort first
!:      ldx mux_order,y                 // 4
        lda mux_y,x                     // 4
        cmp #MUX_Y_MIN                  // 2
        bcs !+                          // 2  (the sentinel's $FF stops it)
        iny                             // 2
        bne !-                          // 3  always
!:      tya                             // order operand = mux_order + skipped - base
        clc
        adc #<mux_order
        sec
        sbc mux_back
        sta mux_sel_ord1 + 1
        sta mux_sel_ord2 + 1
        ldx mux_back
        txa
        clc
        adc #8
        sta zp_tmp3
        lda #$ff
        sta mux_slow_from               // fast frame so far
        lda #0
        sta mux_s_done + 7,x            // done[base + 7] = 0: slot 8's IRQ is always new
#if DEBUG
        sta mux_drop_count
#endif

mux_sel_l1:                             // slots 0-7
mux_sel_ord1:
        lda mux_order,x                 // 4  self-modified low byte
        tay                             // 2
        lda mux_y,y                     // 4
        cmp #MUX_Y_MAX + 1              // 2
        bcs !end1+                      // 2  sorted: the rest are below the range, hidden, or the sentinel
        sta mux_s_y,x                   // 5
        lda mux_x_lo,y                  // 4
        sta mux_s_xlo,x                 // 5
        lda mux_ptr,y                   // 4
        sta mux_s_ptr,x                 // 5
        lda mux_col,y                   // 4
        sta mux_s_col,x                 // 5
        lda mux_x_hi,y                  // 4  cumulative $D010: this slot's bit from X bit 8
        beq !clr+                       // 2/3
        lda mux_s_d010 - 1,x            // 4
        ora mux_t_bit,x                 // 4
        bne !st+                        // 3  always
!clr:   lda mux_s_d010 - 1,x            // 4
        and mux_t_nbit,x                // 4
!st:    sta mux_s_d010,x                // 5
        inx                             // 2
        cpx zp_tmp3                     // 3
        bne mux_sel_l1                  // 3  = 68-70 per slot
        beq mux_sel_l2                  // 3  always (Z = 1): once per frame
!end1:  jmp mux_sel_done                // (branch range)

mux_sel_l2:                            // slots 8+
mux_sel_ord2:
        lda mux_order,x                 // 4  self-modified low byte
        tay                             // 2
        lda mux_y,y                     // 4
        cmp #MUX_Y_MAX + 1              // 2
        bcs mux_sel_done                // 2
        sta mux_s_y,x                   // 5  speculative: a sprite that doesn't fit leaves the frame's fast path
        sec                             // 2
        sbc mux_s_y - 8,x               // 4  y - y[k-8] (sorted: 0-219)
        cmp #MUX_GAP_MIN                // 2
        bcc mux_sel_fail                // 2  too close to the sprite 8 places earlier
        lda mux_s_y - 8,x               // 4
        adc #MUX_FREE_AFTER - 1         // 2  C = 1: free = y[k-8] + FREE_AFTER (<= 227: no overflow)
        sta mux_s_free,x                // 5
        adc #MUX_IRQ_LINES              // 2  C = 0: start, if a new IRQ
        cmp mux_s_done - 1,x            // 4
        bcc !carry+                     // 2  slot k-1's IRQ is still writing: carry on in it
        adc #MUX_WRITE_LINES - 1        // 2  C = 1: done = start + WRITE (fits: the gap check)
!ok:    sta mux_s_done,x                // 5  = 55 to here (new IRQ)
        lda mux_x_lo,y                  // 4
        sta mux_s_xlo,x                 // 5
        lda mux_ptr,y                   // 4
        sta mux_s_ptr,x                 // 5
        lda mux_col,y                   // 4
        sta mux_s_col,x                 // 5
        lda mux_x_hi,y                  // 4
        beq !clr+                       // 2/3
        lda mux_s_d010 - 1,x            // 4
        ora mux_t_bit,x                 // 4
        bne !st+                        // 3  always
!clr:   lda mux_s_d010 - 1,x            // 4
        and mux_t_nbit,x                // 4
!st:    sta mux_s_d010,x                // 5
        inx                             // 2
        jmp mux_sel_l2                  // 3  = 108 per slot (new IRQ)
!carry: lda mux_s_done - 1,x            // 4  C = 0
        adc #MUX_WRITE_LINES            // 2  done = done[k-1] + WRITE
        cmp mux_s_y,x                   // 4  done - y
        beq !ok-                        // 3/2
        bcc !ok-                        // 3  = 124 per slot (carry on)
mux_sel_fail:
        jmp mux_slow                    // X = slot, Y = virtual sprite, mux_s_y,x = its Y

mux_sel_done:                           // X = end index
mux_select_end:

// Per-buffer values and anything the slow path, the mixed multicolour mode or the ages need.
// In: X = end index (base + count)
// Cost (counted): fast frame, uniform multicolour, ~110; the slow path adds the rebuild
// (~70 per slot from the first change) and the age pass (~17 per slot); mixed multicolour adds
// ~40 per slot
mux_build:
        lda #$ff                        // sentinel: the zone IRQ's "next slot free?" check fails after the last
        sta mux_s_free,x
        stx zp_tmp2                     // zp_tmp2 = end
        txa
        ldx mux_back
        sta mux_b_end,x
        lda mux_slow_from
        bmi !fast+
        jsr mux_rebuild                 // slow frame: slots from mux_slow_from, and the ages
        jmp !mc+
!fast:  lda mux_dirty                   // fast frame: every shown sprite was shown, so clear the ages
        beq !mc+                        // once after a frame that dropped some (engine/README.md#fast-path)
        lda #0
        sta mux_dirty
        .for (var i = 0; i < MUX_COUNT; i++) sta mux_age + i
!mc:    lda mux_mc_mode
        cmp #2
        bne !+
        jsr mux_mixed_d01c              // mixed multicolour: cumulative $D01C per slot
!:
// Slots 0-7 are what mux_irq_top writes: $D015 for min(count, 8), and the cumulative values after
// the last of them.
        ldx mux_back
        lda zp_tmp2
        sec
        sbc mux_back                    // count
        cmp #9
        bcc !+
        lda #8
!:      tay                             // min(count, 8)
        lda mux_t_d015,y
        sta mux_b_d015,x
// Wrap ghosts: the last min(count, 8) slots are each one hardware sprite's last slot of the frame.
// They're in Y order, so those at Y <= MUX_WRAP_Y are a prefix of them: collect their $D015 bits
// in mux_b_park (mux_irq_park / mux_zone_done clear them after line MUX_PARK_LINE).
// Cost (counted): 43 when the first of them is below MUX_WRAP_Y (the usual case); + 28 per ghost
        sty zp_tmp1                     // 3  min(count, 8)
        lda zp_tmp2                     // 3
        sec                             // 2
        sbc zp_tmp1                     // 3
        tay                             // 2  first of the last min(count, 8) slots
        lda #0                          // 2
        sta zp_tmp0                     // 3  mask
!gh:    cpy zp_tmp2                     // 3
        bcs !gd+                        // 2
        lda mux_s_y,y                   // 4
        cmp #MUX_WRAP_Y + 1             // 2
        bcs !gd+                        // 3
        lda zp_tmp0                     //    ghost: add hardware sprite (slot & 7)
        ora mux_t_bit,y
        sta zp_tmp0
        iny
        bne !gh-                        //    always
!gd:    lda zp_tmp0                     // 3
        sta mux_b_park,x                // 5
        ldy zp_tmp1                     // 3  = 43 with no ghost
        lda mux_mc_mode                 // uniform: $D01C is 0 or $FF for the whole frame
        beq !+
        lda #$ff
!:      sta mux_b_d01c,x
        dey                             // slot min(count, 8) - 1: its cumulative values
        bmi !none+
        tya
        clc
        adc mux_back
        tay
        lda mux_s_d010,y
        sta mux_b_d010,x
        lda mux_mc_mode
        cmp #2
        bne !blk+
        lda mux_s_d01c,y
        sta mux_b_d01c,x
        jmp !blk+
!none:  lda #0
        sta mux_b_d010,x
// Zone blocks for this buffer: the uniform set (no $D01C write) or the mixed set.
!blk:   lda mux_mc_mode
        cmp #2
        lda #0
        rol                             // C from cmp: 1 = mixed
        ldy #0
        cpx #0
        beq !+
        iny                             // Y = buffer number
!:      cmp mux_blk_mode,y
        beq !+
        jsr mux_set_blocks              // rare: only when the mode changes
!:
mux_build_end:
        lda #1                          // 2
        sta zp_mux_ready                // 3
        bit mux_slow_from               // 4  N = 0: a slow frame
        bpl mux_update_end              // 2
// Reached only in fast frames (no drop, no eviction), at its own address: budget.json profiles
// mux_update -> mux_update_fast to get the fast path on its own in a spike that overloads rows.
mux_update_fast:
        nop                             // 2  (gives the label an address of its own)
mux_update_end:
        clc                             // 2
        rts

// ------------------------------------------------------------------------------------------
// Slow path, fair flicker, rebuild and the rarely used helpers: engine/multiplexer_flicker.asm
#import "engine/multiplexer_flicker.asm"

// ------------------------------------------------------------------------------------------
// TIMING: chain entry 0, line MUX_TOP_LINE (16, top border: no badlines, no sprites yet).
// Swap in the back buffer if one is ready, write $D015/$D010/$D01C and slots 0-7, re-arm at
// slot 8's free line; with <= 8 slots, re-arm mux_irq_park at line 77 if there are wrap ghosts,
// else end the entry. Budget 393 (a lock, measured: the worst of the three paths; the 393 path runs
// every pass in tests/engine/multiplexer_top, the 381 path in tests/engine/multiplexer_ghost).
// Cost: measured from mux_irq_top to irq_exit_rti, every pass (constant paths, top border, no DMA;
// + 32 framework before it): 378 (> 8 slots), 381 (<= 8, ghosts to park), 393 (<= 8, none)
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
!done:  lda mux_b_park - 8,x            // 4  <= 8 slots (X = base + 8): any wrap ghosts to park?
        bne !park+                      // 2
        IrqDone()
!park:  lda #MUX_PARK_LINE              // 2  far below line 16: no race with the late check
        IrqRearm(mux_irq_park)

// ------------------------------------------------------------------------------------------
.align $100                             // the zone code's page: see MUX_ZONE_OFFSET
// TIMING: zone IRQ, re-armed at slot zp_mux_slot's free line. Budget: see budget.json (raster
// span, DMA included). Dispatches to the block for hardware sprite (slot & 7): 22 cycles.
mux_irq_zone:
        ldx zp_mux_slot                 // 3
        lda mux_t_blk_lo,x              // 4
        sta mux_zone_jmp + 1            // 4
        lda mux_t_blk_hi,x              // 4
        sta mux_zone_jmp + 2            // 4
mux_zone_jmp:
        jmp mux_zone_jmp                // 3  = 22 (operand written above)

// End of the frame's slots: advance the chain, parking the wrap ghosts first if there are any
// (mux_zone_park, after the blocks). Cost: 10 more than IrqDone alone with nothing to park (counted;
// the zone IRQ minimum measured 154 -> 164). With ghosts, measured to irq_exit_rti: 94 parking at
// once, 89 re-arming mux_irq_park (tests/engine/multiplexer_ghost phases 4 and 1)
mux_zone_done:
        ldx zp_mux_front                // 3
        lda mux_b_park,x                // 4
        beq !+                          // 3
        jmp mux_zone_park
!:      IrqDone()

// The next slot's sprite frees 3 or more lines from now: re-arm at its free line.
// (3 lines of margin, so irq_rearm's own late check can't see the line even if a badline
// with 8 sprites lands in between.)
mux_zone_rearm:
        stx zp_mux_slot                 // 3
        lda mux_s_free,x                // 4
        IrqRearm(mux_irq_zone)          // 7 + irq_rearm

// Block j writes slot X on hardware sprite j, then moves on to slot X+1 (block j+1 & 7):
// straight in if its sprite is already free, after a wait if it frees within 2 lines, or
// through a re-arm. After the last slot, mux_s_free is $FF, so the "free already" test fails
// and the end test runs only off the fast path. In: X = slot index (base included).
// Cost per slot, block to block, next slot free already (counted): uniform 53 (release) /
// 62 (DEBUG: + 9 late check); mixed + 8 for $D01C. Stage 2 was 67 / 78.
// A taken branch that crosses a page costs 1 more cycle (6502-timing.md), so every branch in a
// block is checked at assembly time: 'next' is the address after the branch, 'target' its target.
.function mux_crosses(next, target) { .return (>next) != (>target) }

.macro MuxZoneBlock(j, mixed) {
        lda mux_s_y,x                   // 4
        sta MUX_VIC_SPR + 1 + j * 2     // 4
#if DEBUG
        cmp MUX_VIC_RASTER              // 4  Y - raster: late if the raster is already on or past Y
        beq late                        // 2
n1:     bcs ok                          // 3
late:   inc mux_late_count
        bne ok
n3:     dec mux_late_count
ok:
        .errorif mux_crosses(n1, late) || mux_crosses(late, ok) || mux_crosses(n3, ok), "mux zone block: a late-check branch crosses a page"
#endif
        lda mux_s_xlo,x                 // 4
        sta MUX_VIC_SPR + j * 2         // 4
        lda mux_s_ptr,x                 // 4
        sta MUX_PTRS + j                // 4
        lda mux_s_col,x                 // 4
        sta MUX_VIC_COLOR + j           // 4
        lda mux_s_d010,x                // 4
        sta MUX_VIC_XMSB                // 4  = 40 writes (uniform)
        .if (mixed) {
            lda mux_s_d01c,x            // 4
            sta MUX_VIC_MCOLOR          // 4
        }
        inx                             // 2
        lda mux_s_free,x                // 4  next slot's free line ($FF after the last slot)
        cmp MUX_VIC_RASTER              // 4
        bcc next                        // 3  free < raster: go   (= 13 from inx)
n4:     cpx zp_mux_end                  // 3
        bne more                        // 3
n5:     jmp mux_zone_done
more:   sbc #2                          // 2  C = 0 (X < end): A = free - 3
        cmp MUX_VIC_RASTER              // 4
        bcc wait                        // 2  free - 3 < raster: frees within 2 lines
n6:     jmp mux_zone_rearm
wait:   lda mux_s_free,x                // 4
w:      cmp MUX_VIC_RASTER              // 4
        beq next                        // 2
n7:     bcs w                           // 3  free > raster: wait
next:
        .errorif mux_crosses(n4, next) || mux_crosses(n5, more) || mux_crosses(n6, wait) || mux_crosses(n7, next) || mux_crosses(next, w), "mux zone block: a branch crosses a page"
}

// The blocks start at a fixed page offset, chosen (by counting the block layout, and enforced by
// the .errorif in the macro) so that every page boundary inside them falls on straight-line code,
// never inside a branch's span: DEBUG blocks are 81 / 87 bytes and fit at offsets 57-72, release
// ones 66 / 72 at 88-92. mux_irq_zone, mux_zone_done and mux_zone_rearm fill the gap before them.
#if DEBUG
.const MUX_ZONE_OFFSET = 64
#else
.const MUX_ZONE_OFFSET = 90
#endif
        .errorif (* & $ff) > MUX_ZONE_OFFSET, "zone dispatch code runs past MUX_ZONE_OFFSET"
        .fill MUX_ZONE_OFFSET - (* & $ff), 0    // never executed
mux_zone_blocks:                        // uniform multicolour: $D01C is written once, by mux_irq_top
mux_zone_0:     MuxZoneBlock(0, false)
mux_zone_1:     MuxZoneBlock(1, false)
mux_zone_2:     MuxZoneBlock(2, false)
mux_zone_3:     MuxZoneBlock(3, false)
mux_zone_4:     MuxZoneBlock(4, false)
mux_zone_5:     MuxZoneBlock(5, false)
mux_zone_6:     MuxZoneBlock(6, false)
mux_zone_7:     MuxZoneBlock(7, false)
        jmp mux_zone_0
mux_zone_m0:    MuxZoneBlock(0, true)   // mixed multicolour: cumulative $D01C per slot
mux_zone_m1:    MuxZoneBlock(1, true)
mux_zone_m2:    MuxZoneBlock(2, true)
mux_zone_m3:    MuxZoneBlock(3, true)
mux_zone_m4:    MuxZoneBlock(4, true)
mux_zone_m5:    MuxZoneBlock(5, true)
mux_zone_m6:    MuxZoneBlock(6, true)
mux_zone_m7:    MuxZoneBlock(7, true)
        jmp mux_zone_m0
mux_zone_blocks_end:

// ------------------------------------------------------------------------------------------
// Wrap ghosts, from mux_zone_done: park now if every ghost slot has finished displaying, else
// re-arm mux_irq_park.
mux_zone_park:                          // A = mask, X = front base
        ldy MUX_VIC_RASTER              // 4  (the last slot is at Y <= MUX_Y_MAX: raster bit 8 is 0)
        cpy #MUX_PARK_LINE              // 2
        bcs mux_park_now                // 3  every ghost slot has finished displaying: clear now
        tya                             //    else re-arm at max(MUX_PARK_LINE, raster + 3): 3 lines
        adc #3                          //    of margin for irq_rearm's late check (C = 0)
        cmp #MUX_PARK_LINE
        bcs !+
        lda #MUX_PARK_LINE
!:      IrqRearm(mux_irq_park)

// TIMING: re-armed IRQ on line MUX_PARK_LINE (77) to 79, only in frames with wrap ghosts: clear
// the $D015 bits of the hardware sprites whose last slot is at Y <= MUX_WRAP_Y, so they don't
// match again on line 256 + Y. Their slots finished displaying by line Y + 21 <= 76. No budget of
// its own: counted in all IRQ time per frame. Cost: measured 80 to irq_exit_rti, every pass (1,921
// of 1,921, starts on line 77 cycle 26-28; tests/engine/multiplexer_ghost budget.json locks it)
mux_irq_park:
        ldx zp_mux_front                // 3
        lda mux_b_park,x                // 4
mux_park_now:                           // A = mask, X = front base
        eor #$ff                        // 2
        and mux_b_d015,x                // 4  $D015 as mux_irq_top wrote it (zone IRQs don't write it)
        sta MUX_VIC_ENABLE              // 4
        IrqDone()                       // 3  = 20 to irq_exit

