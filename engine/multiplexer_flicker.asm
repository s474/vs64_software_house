// engine/multiplexer_flicker.asm: the multiplexer's slow path (M3 stages 3-4). Imported by
// engine/multiplexer.asm where the code goes; not used on its own. Design:
// engine/README.md#overflow-fair-flicker, #pinned-sprites and #fast-path.
//
// Entered from the fast-path selection at the first sprite of a frame that doesn't fit
// (mux_slow). For the rest of the frame the walk fills mux_kept, and a sprite that doesn't fit
// may evict a younger unpinned kept sprite (fair flicker), or, if it is pinned, evict unpinned
// ones until it fits (capped by MUX_PIN_EVICT_MAX a frame). mux_build then calls mux_rebuild for
// the slots from the first change onwards.
//
// Routines: mux_slow (entry), mux_slow_loop, mux_slow_fail (unpinned: eviction or drop),
// mux_pin_fail (pinned), mux_ev_find, mux_ev_remove, mux_slow_drop, MuxAgeUp, mux_fill_kept,
// mux_rebuild, mux_mixed_d01c, mux_set_blocks.
// Uses: A, X, Y, zp_tmp0-zp_tmp3 (main loop only), mux_ev_* and mux_pin_* scratch.
// Measured cost: engine/README.md#multiplexer-costs (stages 3 and 4): slow part of a frame
// (mux_slow -> mux_sel_done), one eviction (mux_ev_remove), and mux_build with the rebuild.
// Stage 4, raster cycles in tests/engine/multiplexer (4 pinned), DMA included, min / avg / max:
//   slow frames' mux_update          4,665 / 6,711 / 12,330  (idle_breakdown.py, 20,000 frames)
//   pinned pass, once a slow frame   282 / 340 / 593         (idle_breakdown.py)
//   one pinned eviction              ~226 average            (derived: 9,031 in 7,409 frames)
//   one drop or eviction             ~430 average            (derived, stage 3)
//   mux_fill_kept, mux_rebuild, mux_mixed_d01c, mux_set_blocks: in their headers below
//     (tests/engine/multiplexer_edge/routine_costs.py, 600 frames, IRQs excluded, 2026-10-01)
// Page crossings in here (M3 review): every "mux_s_done - 1,x" read costs 5, not 4 (the operand is
// in the page before mux_s_done: see the slot arrays in multiplexer.asm), and "mux_pin_save,x" /
// ",y" reads cost 5 for index >= 4 (mux_pin_save is at page offset $FC in the M3 spikes).
// ------------------------------------------------------------------------------------------
// Slow path: the first sprite this frame that doesn't fit. For the rest of the frame the walk
// fills mux_kept (so slots can be removed), and mux_build rebuilds from the first changed slot.
// A sprite that doesn't fit may evict an unpinned one (mux_slow_fail, mux_pin_fail).
// Pinned sprites are marked for the rest of the selection by age $FF (unpinned ages saturate at
// $FE): the pinned pass below saves their real ages in mux_pin_save, and mux_rebuild, which every
// slow frame runs, restores them. So "pinned" is one compare, and the eviction scan needs no flag
// lookups.
// In: X = slot (>= base + 8), Y = virtual sprite, mux_s_y,x = its Y
// Cost (counted): ~85 + mux_fill_kept (~17 per slot so far) + the pinned pass (280 with 4 pinned)
mux_slow:
        stx mux_slow_from
        lda mux_sel_ord2 + 1            // the kept sprites so far are order[skipped ... skipped + k - 1]
        sta mux_sel_ordm + 1
        sta mux_sel_ords + 1
        jsr mux_fill_kept
        stx zp_tmp2
        sty zp_tmp0
        lda mux_back
        clc
        adc #8
        sta mux_ev_b8                   // base + 8: the first slot the zone IRQs write
        lda #0
        sta mux_pin_evict               // the pinned eviction cap counts per mux_update
        lda mux_flag_or                 // 4  any sprite flagged pinned this frame?
        bmi mux_pin_pass                // 3
        lda #MUX_MAX_PINNED             //    no: an empty list
        sta mux_pin_first
        jmp mux_pin_pass_end

// Pinned pass (engine/README.md#pinned-sprites), once per frame that overflows: the first
// MUX_MAX_PINNED sprites with bit 7 in virtual order 0-23 are pinned. Each is listed in
// mux_pin_list[mux_pin_first .. 3] (in reverse order), its age saved in mux_pin_save and set to
// $FF for the rest of the selection; mux_rebuild restores them. More than MUX_MAX_PINNED flagged:
// the rest are unpinned this frame (DEBUG: mux_pin_excess_count). Fast frames never run it: every
// sprite is shown there, so pinning has no effect.
// Cost (counted): 7 per unflagged sprite, 31 per pinned one, 9 per flagged extra, + 16:
// 280 with 4 pinned and 20 not (+ 5 + 9 per entry padded with fewer than 4)
mux_pin_pass:
        ldx #MUX_MAX_PINNED             // 2  X = list slots left; negative once more than 4 are flagged
        .for (var i = 0; i < MUX_COUNT; i++) {
            lda mux_flags + i           // 4
            bpl !+                      // 3 / 2
            dex                         // 2
            bmi !+                      // 2  beyond MUX_MAX_PINNED: treated as unpinned
            lda mux_age + i             // 4
            sta mux_pin_save + i        // 4
            lda #$ff                    // 2
            sta mux_age + i             // 4  pinned, for this selection
            lda #i                      // 2
            sta mux_pin_list,x          // 5
!:
        }
        txa                             // 2
        bpl !+                          // 3
#if DEBUG
        inc mux_pin_excess_count        // saturating
        bne !ok+
        dec mux_pin_excess_count
!ok:
#endif
        lda #0                          // all 4 list entries used
!:      sta mux_pin_first               // 4
        tax                             // 2  fewer than 4: pad entries 0 .. first - 1 with the dummy
        beq mux_pin_pass_end            // 3
        lda #MUX_COUNT
!:      sta mux_pin_list - 1,x
        dex
        bne !-
mux_pin_pass_end:
        ldx zp_tmp2
        ldy zp_tmp0
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
        cmp mux_s_done - 1,x            // 5  (page crossed)
        bcc !carry+
        adc #MUX_WRITE_LINES - 1
!ok:    sta mux_s_done,x
        tya
        sta mux_kept,x
        inx
        jmp mux_slow_loop
!carry: lda mux_s_done - 1,x            // 5  (page crossed)
        adc #MUX_WRITE_LINES
        cmp mux_s_y,x
        beq !ok-
        bcc !ok-
        // fall through: doesn't fit

// Sprite v doesn't fit at slot k (the end of the kept list, >= base + 8). Two cases
// (engine/README.md#overflow-fair-flicker and #pinned-sprites):
//
//   Unpinned v (fair flicker): w = the youngest UNPINNED of the last 8 kept (slots k-8 .. k-1; on
//   a tie, the later one), counting only those strictly younger than v. If w exists and v fits
//   once w is removed, w is evicted and v is kept; otherwise v is dropped.
//
//   Pinned v (age $FF during the selection): evict the youngest unpinned of the last 8 kept,
//   ignoring ages, and try v again at the new end of the list; repeat until v fits. Capped at
//   MUX_PIN_EVICT_MAX evictions per mux_update (mux_pin_evict); if the cap is reached or no
//   unpinned sprite is left in the last 8, v is dropped for the frame (mux_pin_drop_count).
//   Each retry re-enters mux_slow_loop at the new end, which re-tests v and comes back here if it
//   still doesn't fit, so the loop needs no state beyond mux_pin_evict.
//
// Removing slot w shifts slots w+1 .. k-1 down one. Their partner 8 places earlier (slot j-8 <
// k-9 < w) doesn't move, so their free lines don't change and their done lines can only get
// earlier: they still fit. The removal re-simulates max(w, base + 8) .. k-2 and keeps an unpinned
// v at slot k-1 (the checks below use the same model as the slow loop's fit test); a pinned v is
// tested again there by the slow loop.
// Does v fit at slot k-1 once w is removed? In order, cheapest first:
//   k-1 < base + 8: yes (mux_irq_top writes it). y - y[k-9] < MUX_GAP_MIN: no. v didn't fail on
//   the carry-on test (done[k-1] + WRITE <= y): yes, since removing w only makes done[k-2]
//   earlier than done[k-1] was. Otherwise a dry run computes done[k-2] after the removal.
// In: X = k (>= base + 8), Y = v   zp_tmp0 = v, zp_tmp1 = best age / done, zp_tmp2 = k, zp_tmp3 = w
// Cost (counted): unpinned v shown last frame (age 0) 20, then the drop ~45; otherwise the search
// ~150, the fit checks ~40 (+ ~33 per slot after w if the dry run is needed), the removal ~70 +
// ~71 per slot after w, then v's slot in mux_slow_loop ~60. Pinned v: ~30 + search + removal +
// re-test per eviction. Measured: engine/README.md#multiplexer-costs (stage 4)
mux_slow_fail:
        sty zp_tmp0                     // 3
        stx zp_tmp2                     // 3
        lda mux_age,y                   // 4
        beq mux_slow_drop               // 2  age 0 can't beat anyone (X, Y = k, v)
        cmp #$ff                        // 2
        bne !+                          // 3
        jmp mux_pin_fail                //    pinned
!:      sta zp_tmp1                     // 3  best so far: must be strictly younger than v
        dex                             // 2
        stx mux_ev_k1                   // 4  k - 1: v's slot after a removal
        cpx mux_ev_b8                   // 4
        bcc !find+                      // 2  slot k-1 < base + 8: written by mux_irq_top, always fits
        lda mux_y,y                     // 4  whichever w goes, v at k-1 needs y - y[k-9] >= GAP:
        sec                             // 2  test that before searching
        sbc mux_s_y - 8,x               // 4
        cmp #MUX_GAP_MIN                // 2
        bcc mux_ev_no                   // 2  = 44 to a drop here
        jsr mux_ev_find
mux_ev_found:                           // (a label for profiling)
        bmi mux_ev_no                   // no unpinned sprite younger than v
        ldx mux_ev_k1
        ldy zp_tmp0
        lda mux_s_done,x                // done[k-1] + WRITE <= y: v failed only on the gap, fits now
        clc
        adc #MUX_WRITE_LINES
        cmp mux_y,y
        beq !fits+
        bcc !fits+
        // Dry run: done line of slot k-2 once w is removed. From j0 = max(w, base + 8).
mux_ev_dry:
        lda zp_tmp3
        cmp mux_ev_b8
        bcs !+
        lda mux_ev_b8
!:      tax
        lda mux_s_done - 1,x            // 5  (page crossed)
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
!check: lda zp_tmp1                     // carrying on needs done[k-2] + WRITE <= y (gap checked above)
        clc
        adc #MUX_WRITE_LINES
        cmp mux_y,y
        beq !fits+
        bcs mux_ev_no
!fits:  jmp mux_ev_remove               // w is dropped; v is kept at slot k-1
!find:  jsr mux_ev_find                 // k-1 < base + 8: any w will do
        bmi mux_ev_no
        jmp mux_ev_remove
mux_ev_no:
        ldx zp_tmp2
        ldy zp_tmp0
mux_slow_drop:                          // X = slot, Y = virtual sprite (unpinned)
        MuxAgeUp()
#if DEBUG
        inc mux_drop_count
#endif
        inc mux_sel_ords + 1            // next order index, same slot
        jmp mux_slow_loop

// Pinned v doesn't fit at slot k: evict the youngest unpinned of the last 8 kept and try again.
// In: X = k, Y = v, zp_tmp0 = v, zp_tmp2 = k
mux_pin_fail:
        lda mux_pin_evict
        cmp #MUX_PIN_EVICT_MAX
        bcs !drop+                      // the cap: this frame, v is dropped
        lda #$ff                        // any unpinned age (<= $FE); pinned ($FF) never qualify
        sta zp_tmp1
        jsr mux_ev_find
        bmi !drop+                      // every one of the last 8 kept is pinned
        inc mux_pin_evict
        jmp mux_ev_remove
!drop:
#if DEBUG
        inc mux_pin_drop_count          // saturating
        bne !+
        dec mux_pin_drop_count
!:      inc mux_drop_count
#endif
        ldy zp_tmp0                     // its saved age + 1, saturating at $FE; not in mux_max_age
        lda mux_pin_save,y              // (unpinned only)  5 for Y >= 4: page crossed
        cmp #$fe
        bcs !+
        adc #1                          // C = 0
        sta mux_pin_save,y
!:      ldx zp_tmp2
        inc mux_sel_ords + 1            // next order index, same slot
        jmp mux_slow_loop

// w = the youngest sprite among slots k-8 .. k-1 whose age is below zp_tmp1 (on a tie, the later
// one). Pinned sprites have age $FF during the selection, so they never qualify. Scanning from
// k-1 back, the first age 0 found is the answer (nothing is younger, and it's the latest of its
// age), so the scan stops there: the common case in a crowd, where the sprites shown last frame
// have age 0.
// In: zp_tmp2 = k (>= base + 8), zp_tmp1 = age bound (>= 1)
// Out: zp_tmp3 = w and N = 0, or zp_tmp3 = $FF and N = 1 for none; zp_tmp1 = w's age
// Uses: A, X, Y   Cost (counted), with the jsr: 8 + 16 per slot passed (19 on a new best) +
// 23 found / 13 none; e.g. 71 for an age 0 at k-3, 155 for none (mux_kept - 8 + X stays in
// mux_kept's page)
mux_ev_zeros_lo:                        // age-0 exits for offsets 1-4 (branch range: 5-8 follow the routine)
        .for (var j = 1; j <= 4; j++) {
z:          lda #j                      // 2  age 0 at offset j
            bne mux_ev_zero             // 3  always
        }
mux_ev_zero:                            // A = offset of the age-0 sprite (mux_ev_w's tail, in branch range)
        ldy #0                          // 2
        sty zp_tmp1                     // 3
        eor #$ff                        // 2  w = k - offset
        sec                             // 2
        adc zp_tmp2                     // 3
        sta zp_tmp3                     // 3  N = 0
        rts                             // 6
mux_ev_find:
        ldx zp_tmp2                     // 3
        lda #0                          // 2
        sta zp_tmp3                     // 3  offset back from k of the best so far: 0 = none
        .for (var j = 1; j <= 8; j++) {
            ldy mux_kept - j,x          // 4
            lda mux_age,y               // 4
            .if (j <= 4) beq mux_ev_zeros_lo[j - 1].z   // 2  age 0: final
            .if (j > 4) beq mux_ev_zeros_hi[j - 5].z
            cmp zp_tmp1                 // 3
            bcs !+                      // 3  not younger than the best: the later one stays
            sta zp_tmp1                 // 3
            lda #j                      // 2
            sta zp_tmp3                 // 3
!:
        }
        lda zp_tmp3                     // 3
        beq !none+                      // 2
mux_ev_w:                               // A = offset
        eor #$ff                        // 2  w = k - offset = k + ~offset + 1
        sec                             // 2
        adc zp_tmp2                     // 3
        sta zp_tmp3                     // 3  N = 0 (w < 64)
        rts                             // 6
!none:  lda #$ff
        sta zp_tmp3
        rts
mux_ev_zeros_hi:
        .for (var j = 5; j <= 8; j++) {
z:          lda #j                      // 2  age 0 at offset j
            bne mux_ev_zero_hi          // 3  always
        }
mux_ev_zero_hi:                         // (the same as mux_ev_zero, in branch range)
        ldy #0                          // 2
        sty zp_tmp1                     // 3
        beq mux_ev_w                    // 3  always

// Evict slot w: it counts as dropped (age + 1); slots w+1 .. k-1 shift down; the end becomes
// k - 1 and max(w, base + 8) .. k-2 are re-simulated. Then v, the sprite that didn't fit, goes to
// the new end: at once if that's one of slots 0-7 (always fit) or v is unpinned (mux_slow_fail's
// checks showed it fits); a pinned v is re-tested by mux_slow_loop, which comes back to
// mux_pin_fail if it needs another eviction. In: zp_tmp3 = w, zp_tmp2 = k, zp_tmp0 = v
mux_ev_remove:
        ldx zp_tmp3
        ldy mux_kept,x                  // the evicted sprite: always unpinned
        MuxAgeUp()
#if DEBUG
        inc mux_drop_count
#endif
        cpx mux_slow_from               // rebuild from here
        bcs !+
        stx mux_slow_from
!:      dec zp_tmp2                     // the new end, k - 1
        cpx zp_tmp2                     // 3
        bcs !+                          // 2  w was the last kept: nothing to shift
!shift: lda mux_kept + 1,x              // 4
        sta mux_kept,x                  // 5
        lda mux_s_y + 1,x               // 4
        sta mux_s_y,x                   // 5
        inx                             // 2
        cpx zp_tmp2                     // 3
        bcc !shift-                     // 3  = 26 per slot
!:      ldx zp_tmp3                     // re-simulate j0 = max(w, base + 8) .. k - 2
        cpx mux_ev_b8
        bcs !+
        ldx mux_ev_b8
!:      cpx zp_tmp2
        bcs !sd+                        // nothing shifted at or after base + 8
        lda mux_s_done - 1,x            // 5  (page crossed)
        sta zp_tmp1
!sim:   lda mux_s_y - 8,x               // 4
        clc                             // 2
        adc #MUX_FREE_AFTER             // 2
        sta mux_s_free,x                // 5
        adc #MUX_IRQ_LINES              // 2  C = 0
        cmp zp_tmp1                     // 3
        bcs !+                          // 3
        lda zp_tmp1                     //    carry on
!:      clc                             // 2
        adc #MUX_WRITE_LINES            // 2
        sta mux_s_done,x                // 5
        sta zp_tmp1                     // 3
        inx                             // 2
        cpx zp_tmp2                     // 3
        bne !sim-                       // 3  = ~41 per slot
!sd:    inc mux_sel_ords + 1            // 6  one kept sprite fewer: v's order index = low byte + (k - 1)
        ldx zp_tmp2                     // 3
        ldy zp_tmp0                     // 3
        cpx mux_ev_b8                   // 4
        bcc !top+                       // 2
        lda mux_age,y                   // 4
        cmp #$ff                        // 2
        bne !place+                     // 3
        jmp mux_slow_loop               //    pinned v: test it again at slot k - 1 (it may need more)
!place: tya                             // 2  unpinned v: mux_slow_fail's checks showed it fits at k - 1,
        sta mux_kept,x                  // 5  so keep it here (the slow loop's keep path, without the tests)
        lda mux_y,y                     // 4
        sta mux_s_y,x                   // 5
        lda mux_s_y - 8,x               // 4
        clc                             // 2
        adc #MUX_FREE_AFTER             // 2
        sta mux_s_free,x                // 5
        adc #MUX_IRQ_LINES              // 2  C = 0: start, if a new IRQ
        cmp mux_s_done - 1,x            // 5  (4 + 1: page crossed)
        bcs !+                          // 3
        lda mux_s_done - 1,x            // 5  carry on in slot k-2's IRQ (page crossed)
!:      clc                             // 2
        adc #MUX_WRITE_LINES            // 2
        sta mux_s_done,x                // 5
        inx                             // 2
        jmp mux_slow_loop               // 3  = 80 from !sd by these counts, new IRQ (84 carrying on); was ~95
                                        //    through the slow loop's tests
!top:   tya                             // slots 0-7 always fit (and done[base + 7] stays 0)
        sta mux_kept,x
        lda mux_y,y
        sta mux_s_y,x
        inx                             // = base + 8
        jmp mux_slow_loop

// An unpinned sprite in the shown range wasn't shown this frame: age + 1, saturating at $FE ($FF
// marks a pinned sprite during the selection); DEBUG high-water mark (mux_max_age covers
// unpinned sprites only: pinned drops count up in mux_pin_fail). Inline in the two drop paths.
// In: Y = virtual sprite   Uses: A (X, Y kept)   Cost (counted): 13 (+ 7 DEBUG)
.macro MuxAgeUp() {
        lda mux_age,y                   // 4
        cmp #$fe                        // 2
        bcs done                        // 2  saturated
        adc #1                          // 2  C = 0
        sta mux_age,y                   // 5
#if DEBUG
        cmp mux_max_age                 // 4
        bcc done                        // 3
        sta mux_max_age
#endif
done:
}

// mux_kept[base ... X - 1] = the sprites the fast path kept: order[skipped + (j - base)].
// In: X = end slot (> base), mux_sel_ordm's operand set   Uses: A, X
// Cost: 5 + 18 per slot kept so far (counted, to the rts: 149 for 8). Measured 149 / 356 / 753 raster cycles
// min / avg / max, DMA included (tests/engine/multiplexer, 335 calls in 600 frames: once per frame
// that overflows, from mux_slow, and once per fast frame in mixed multicolour, from mux_mixed_d01c)
mux_fill_kept:
        stx zp_tmp0                     // 3
!:      dex                             // 2
mux_sel_ordm:
        lda mux_order,x                 // 4  self-modified low byte
        sta mux_kept,x                  // 5
        cpx mux_back                    // 4
        bne !-                          // 3  = 18 per slot
        ldx zp_tmp0                     // 3
        rts

// Slow frame: rebuild X, pointer, colour and cumulative $D010 from mux_slow_from to the end, from
// mux_kept, and clear the ages of the kept sprites (dropped ones were counted up as they went),
// after restoring the pinned sprites' ages.
// In: zp_tmp2 = end   Uses: A, X, Y
// Cost (counted): 60 for the ages (below), then ~70 per slot rebuilt and 17 per slot kept.
// Measured, raster cycles in tests/engine/multiplexer (4 pinned), DMA included, IRQs excluded,
// min / avg / max: 542 / 1,162 / 2,170 to the rts (276 slow frames of 600,
// tests/engine/multiplexer_edge/routine_costs.py); the age restore alone 60 / 75 / 160 there, and
// 60 / 74 / 221 over 20,000 frames (idle_breakdown.py). It is inside mux_build's budget (3,100).
mux_rebuild:
        lda mux_pin_first               // 4  the pinned sprites' real ages back (mux_slow marked them)
        cmp #MUX_MAX_PINNED             // 2
        beq !+                          // 2
        .for (var j = 0; j < MUX_MAX_PINNED; j++) {
            ldx mux_pin_list + j        // 4
            lda mux_pin_save,x          // 4  (5 for X >= 4: mux_pin_save,x crosses a page there, so
                                        //    + 1 per pinned sprite numbered 4-23 and per padded entry, X = 24)
            sta mux_age,x               // 5  = 60 in all with sprites 0-3 pinned (measured 60), up to 64
        }
!:      lda #1
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
// Cost (counted): ~36 per slot, + mux_fill_kept (18 per slot) in a fast frame. Measured 444 / 1,161
// / 1,996 raster cycles min / avg / max, DMA included, IRQs excluded (tests/engine/multiplexer with
// mux_flags bit 0 set on the odd-numbered sprites, 150 frames, routine_costs.py). Only frames that
// mix hires and multicolour sprites pay it; it is inside mux_build's budget
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
// Cost (counted): 19 + 24 x 43 - 1 = 1,050 to the rts. Measured 1,136 / 1,289 / 1,611 raster cycles
// min / avg / max, DMA included, IRQs excluded (24 calls, routine_costs.py: it runs through the
// display, so every call had DMA in it). Runs once per buffer when the frame's multicolour mode
// changes between uniform and mixed, so twice per change, in consecutive frames
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

