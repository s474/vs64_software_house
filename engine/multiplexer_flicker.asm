// engine/multiplexer_flicker.asm: the multiplexer's slow path (M3 stage 3). Imported by
// engine/multiplexer.asm where the code goes; not used on its own. Design:
// engine/README.md#overflow-fair-flicker and engine/README.md#fast-path.
//
// Entered from the fast-path selection at the first sprite of a frame that doesn't fit
// (mux_slow). For the rest of the frame the walk fills mux_kept, and a sprite that doesn't fit
// may evict a younger kept sprite (fair flicker; pinning is stage 4). mux_build then calls
// mux_rebuild for the slots from the first change onwards.
//
// Routines: mux_slow (entry), mux_slow_loop, mux_slow_fail (eviction), mux_slow_drop,
// mux_age_up, mux_fill_kept, mux_rebuild, mux_mixed_d01c, mux_set_blocks.
// Uses: A, X, Y, zp_tmp0-zp_tmp3 (main loop only), mux_ev_* scratch.
// Measured cost: engine/README.md#multiplexer-costs (stage 3): slow part of a frame (mux_slow ->
// mux_sel_done) and mux_build with the rebuild.
// ------------------------------------------------------------------------------------------
// Slow path: the first sprite this frame that doesn't fit. For the rest of the frame the walk
// fills mux_kept (so slots can be removed), and mux_build rebuilds from the first changed slot.
// A sprite that doesn't fit may evict a younger one (fair flicker, mux_slow_fail).
// In: X = slot (>= base + 8), Y = virtual sprite, mux_s_y,x = its Y
mux_slow:
        stx mux_slow_from
        lda mux_sel_ord2 + 1            // the kept sprites so far are order[skipped ... skipped + k - 1]
        sta mux_sel_ordm + 1
        sta mux_sel_ords + 1
        jsr mux_fill_kept
        lda mux_back
        clc
        adc #8
        sta mux_ev_b8                   // base + 8: the first slot the zone IRQs write
        jmp mux_slow_fail

mux_slow_loop:
mux_sel_ords:
        lda mux_order,x                 // self-modified low byte: + 1 per sprite dropped
        tay
        lda mux_y,y
        cmp #MUX_Y_MAX + 1
        bcc !+
        jmp mux_sel_done
!:      sta mux_s_y,x
        sec
        sbc mux_s_y - 8,x
        cmp #MUX_GAP_MIN
        bcc mux_slow_fail
        lda mux_s_y - 8,x
        adc #MUX_FREE_AFTER - 1
        sta mux_s_free,x
        adc #MUX_IRQ_LINES
        cmp mux_s_done - 1,x
        bcc !carry+
        adc #MUX_WRITE_LINES - 1
!ok:    sta mux_s_done,x
        tya
        sta mux_kept,x
        inx
        jmp mux_slow_loop
!carry: lda mux_s_done - 1,x
        adc #MUX_WRITE_LINES
        cmp mux_s_y,x
        beq !ok-
        bcc !ok-
        // fall through: doesn't fit

// Fair flicker (engine/README.md#overflow-fair-flicker; pinning is stage 4). Sprite v doesn't fit
// at slot k. w = the youngest of the last 8 kept (slots k-8 .. k-1; on a tie, the later one),
// counting only those strictly younger than v. If w exists and v fits once w is removed, w is
// evicted (it counts as dropped) and v takes slot k-1; otherwise v is dropped.
// Removing slot w shifts slots w+1 .. k-1 down one. Their partner 8 places earlier (slot j-8 <
// k-9 < w) doesn't move, so their free lines don't change and their done lines can only get
// earlier: they still fit, and only v needs checking. A dry run computes the done line of slot
// k-2 after the removal; the commit shifts mux_kept / mux_s_y and re-simulates w .. k-1.
// In: X = k (>= base + 8), Y = v   zp_tmp0 = v, zp_tmp1 = best age / done, zp_tmp2 = k, zp_tmp3 = w
// Cost (counted): v shown last frame (age 0) ~20 then drop; otherwise search ~190, and an eviction
// ~250-900 depending on how far back w is
mux_slow_fail:
        lda mux_age,y
        bne !+
        jmp mux_slow_drop               // age 0 can't beat anyone
!:      sty zp_tmp0
        stx zp_tmp2
        sta zp_tmp1                     // best so far: must be strictly younger than v
        lda #$ff
        sta zp_tmp3                     // w: none yet
        txa
        sec
        sbc #8
        sta mux_ev_lo                   // k - 8 (>= base)
!scan:  dex                             // 2  j = k-1 down to k-8
        ldy mux_kept,x                  // 4
        lda mux_age,y                   // 4
        cmp zp_tmp1                     // 3
        bcs !older+                     // 3  not younger than the best: the later one stays
        sta zp_tmp1                     // 3
        stx zp_tmp3                     // 3
!older: cpx mux_ev_lo                   // 4
        bne !scan-                      // 3  = ~22-28 per slot
        lda zp_tmp3
        bpl !+
        jmp mux_ev_no                   // nothing younger than v
!:      // Dry run: done line of slot k-2 once w is removed. From j0 = max(w, base + 8).
        ldx zp_tmp2
        dex
        stx mux_ev_k1                   // k - 1: v's slot after the removal
        cpx mux_ev_b8
        bcc !fits+                      // slot k-1 < base + 8: written by mux_irq_top, always fits
        lda zp_tmp3
        cmp mux_ev_b8
        bcs !+
        lda mux_ev_b8
!:      sta mux_ev_j0
        tax
        lda mux_s_done - 1,x
        sta zp_tmp1                     // d = done[j0 - 1] (0 for base + 7)
!dry:   cpx mux_ev_k1                   // 4
        bcs !check+                     // 2
        lda mux_s_y - 8,x               // 4  partner: unshifted
        clc                             // 2
        adc #MUX_FREE_AFTER + MUX_IRQ_LINES   // 2  start, if a new IRQ
        cmp zp_tmp1                     // 3
        bcs !+                          // 3
        lda zp_tmp1                     //    carry on
!:      clc                             // 2
        adc #MUX_WRITE_LINES            // 2
        sta zp_tmp1                     // 3
        inx                             // 2
        jmp !dry-                       // 3  = ~33 per slot
!check: ldy zp_tmp0                     // X = k - 1
        lda mux_y,y
        sec
        sbc mux_s_y - 8,x               // y - y[k-9]
        cmp #MUX_GAP_MIN
        bcc !no+
        lda zp_tmp1                     // carrying on needs done[k-2] + WRITE <= y
        clc
        adc #MUX_WRITE_LINES
        cmp mux_y,y
        beq !fits+
        bcs !no+
!fits:  // Commit: w is dropped; shift w+1 .. k-1 down; v into slot k-1; re-simulate j0 .. k-1.
        ldx zp_tmp3
        ldy mux_kept,x                  // the evicted sprite
        jsr mux_age_up
#if DEBUG
        inc mux_drop_count
#endif
        cpx mux_slow_from               // rebuild from here
        bcs !shift+
        stx mux_slow_from
!shift: cpx mux_ev_k1
        bcs !+
        lda mux_kept + 1,x
        sta mux_kept,x
        lda mux_s_y + 1,x
        sta mux_s_y,x
        inx
        jmp !shift-
!:      ldy zp_tmp0                     // X = k - 1
        tya
        sta mux_kept,x
        lda mux_y,y
        sta mux_s_y,x
        cpx mux_ev_b8
        bcc !done+                      // slots 0-7: no simulation (and done[base+7] stays 0)
        ldx mux_ev_j0                   // set by the dry run (which ran, since k - 1 >= base + 8)
        lda mux_s_done - 1,x
        sta zp_tmp1
!sim:   lda mux_s_y - 8,x
        clc
        adc #MUX_FREE_AFTER
        sta mux_s_free,x
        adc #MUX_IRQ_LINES              // C = 0
        cmp zp_tmp1
        bcs !+
        lda zp_tmp1
!:      clc
        adc #MUX_WRITE_LINES
        sta mux_s_done,x
        sta zp_tmp1
        inx
        cpx zp_tmp2                     // through k - 1
        bne !sim-
!done:  ldx zp_tmp2                     // same slot k next; v used up an order index
        inc mux_sel_ords + 1
        jmp mux_slow_loop
mux_ev_no:
!no:    ldx zp_tmp2
        ldy zp_tmp0
mux_slow_drop:                          // X = slot, Y = virtual sprite
        jsr mux_age_up
#if DEBUG
        inc mux_drop_count
#endif
        inc mux_sel_ords + 1            // next order index, same slot
        jmp mux_slow_loop

// A sprite in the shown range wasn't shown this frame: age + 1, saturating; DEBUG high-water mark.
// In: Y = virtual sprite   Uses: A (X, Y kept)
mux_age_up:
        lda mux_age,y
        clc
        adc #1
        bcs !+                          // saturate at 255
        sta mux_age,y
#if DEBUG
        cmp mux_max_age
        bcc !+
        sta mux_max_age
#endif
!:      rts

// mux_kept[base ... X - 1] = the sprites the fast path kept: order[skipped + (j - base)].
// In: X = end slot (> base), mux_sel_ordm's operand set   Uses: A, X
mux_fill_kept:
        stx zp_tmp0
!:      dex
mux_sel_ordm:
        lda mux_order,x                 // self-modified low byte
        sta mux_kept,x
        cpx mux_back
        bne !-
        ldx zp_tmp0
        rts

// Slow frame: rebuild X, pointer, colour and cumulative $D010 from mux_slow_from to the end, from
// mux_kept, and clear the ages of the kept sprites (dropped ones were counted up as they went).
// In: zp_tmp2 = end   Uses: A, X, Y
mux_rebuild:
        lda #1
        sta mux_dirty
        ldx mux_slow_from
        cpx zp_tmp2
        beq !ages+
!loop:  ldy mux_kept,x                  // 4
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
        bne !st+                        // 3
!clr:   lda mux_s_d010 - 1,x            // 4
        and mux_t_nbit,x                // 4
!st:    sta mux_s_d010,x                // 5
        inx                             // 2
        cpx zp_tmp2                     // 3
        bne !loop-                      // 3  = ~70 per slot
!ages:  ldx mux_back
        cpx zp_tmp2
        beq !done+
        lda #0
!:      ldy mux_kept,x                  // 4
        sta mux_age,y                   // 5
        inx                             // 2
        cpx zp_tmp2                     // 3
        bne !-                          // 3  = 17 per slot
!done:  rts

// Mixed multicolour: cumulative $D01C for every slot, from mux_kept (filled in first in a fast
// frame). In: zp_tmp2 = end   Uses: A, X, Y
mux_mixed_d01c:
        lda mux_slow_from
        bpl !+                          // slow frame: mux_kept is complete
        lda mux_sel_ord2 + 1
        sta mux_sel_ordm + 1
        ldx zp_tmp2
        cpx mux_back
        beq !done+
        jsr mux_fill_kept
!:      ldx mux_back
        cpx zp_tmp2
        beq !done+
!loop:  ldy mux_kept,x                  // 4
        lda mux_flags,y                 // 4
        lsr                             // 2  C = multicolour
        lda mux_s_d01c - 1,x            // 4
        bcc !clr+                       // 2/3
        ora mux_t_bit,x                 // 4
        bcs !st+                        // 3
!clr:   and mux_t_nbit,x                // 4
!st:    sta mux_s_d01c,x                // 5
        inx                             // 2
        cpx zp_tmp2                     // 3
        bne !loop-                      // 3  = ~36 per slot
!done:  rts

// Point the back buffer's 24 zone-block entries at the uniform (A = 0) or mixed (A = 1) set.
// In: A = mode, Y = buffer number, X = base   Uses: A, X, Y, zp_tmp0, zp_tmp1
mux_set_blocks:
        sta mux_blk_mode,y
        asl
        asl
        asl
        sta zp_tmp0                     // template offset: 0 or 8
        lda #0
        sta zp_tmp1                     // j
!:      lda zp_tmp1
        and #7
        ora zp_tmp0
        tay
        lda mux_tpl_lo,y
        sta mux_t_blk_lo,x
        lda mux_tpl_hi,y
        sta mux_t_blk_hi,x
        inx
        inc zp_tmp1
        lda zp_tmp1
        cmp #MUX_COUNT
        bne !-
        rts

