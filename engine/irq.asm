// engine/irq.asm: raster IRQ framework (M3). Design contract: engine/README.md#irq-framework-engineirqasm
//
// API
//   IrqChainBegin() / IrqNormal(line, handler) / IrqStable(line, handler) / IrqChainEnd()
//       Declare the chain: 1-16 entries, ascending lines 0-255, run in order every frame.
//       Entry 0 is the frame entry (zp_irq_frame += 1 just before its handler).
//       IrqChainEnd() emits the tables and stubs where it is placed.
//   irq_init        Machine setup ($01=$35, CIAs off, NMI -> rti, raster IRQ on), start the chain.
//   irq_wait_frame  Wait for the next frame tick. Out: A = new zp_irq_frame.
//   IrqDone()       End a handler: advance to the next entry, ack, restore, rti.
//   IrqRearm(h)     End a handler with A = line: fire h at that line without advancing the chain.
//
// Handlers: A, X, Y free (saved by the framework), D clear, I set (never cli), $01 = $35,
// $D019 not yet acknowledged (don't touch it). Stack free; the IRQ uses 3 bytes (6 in a stable entry).
//
// Registers owned (nothing else writes them): $FFFE/$FFFF, $FFFA/$FFFB, $D012, $D019, $D01A,
// $DC0D, $DD0D, $D011 bit 7. Every other $D011 write keeps bit 7 clear.
// Zero page (defined by the game's zp.asm): zp_irq_idx (IRQ only), zp_irq_frame (IRQ writes,
// main reads). Register saves are self-modified operands, not zero page.
//
// Measured cost (VICE 3.10 x64sc PAL, tests/engine/irq_chain/measure.py, 1,000 frames, 2026-09-29;
// engine/README.md#irq-framework-costs). Raster cycles, no DMA on the lines involved:
//   IRQ sequence starts                        cycle 2 of the trigger line at the earliest
//   Jitter (instruction in progress)           0-7 cycles with the spike's worst-case main loop
//   irq_dispatch -> handler                    17 (+8 on entry 0: the frame tick)
//   Normal handler's first instruction         cycle 26-33 of its line (entry 0: 34-41)
//   irq_exit -> irq_exit_rti                   60 (58 on the wrap to entry 0)
//   irq_rearm -> irq_exit_rti                  35 (counted, not yet exercised: M3 stage 2)
//   rti                                        6
//   Whole normal entry, excluding its work     7 + 17 + 3 (jmp irq_exit) + 60 + 6 = 93 (+8 entry 0)
//   Stable: irq_stable_begin -> handler        99-106; handler starts at IRQ_STABLE_CYCLE, every frame
//   Whole stable entry, excluding its work     192-199
// Constraints:
//   - $01 must stay $35 whenever interrupts are enabled; the handlers don't save it.
//   - Stable entries: lines line-2 .. line must not be badlines and must have the same sprite
//     DMA every frame. Stage 1 must start by about cycle 40 of line-2 (counted; measured 26-33),
//     or its fallback runs the handler unstable and counts a late run.
//   - irq_exit runs into the line after a handler's line; if that's a badline it costs 43 more.
//   - The late check can't catch a last entry that runs past line 311.
//   - A BRK goes through $FFFE like an IRQ and puts the chain out of step (v1 limit).

.errorif zp_irq_idx > $ff, "zp_irq_idx must be in zero page"
.errorif zp_irq_frame > $ff, "zp_irq_frame must be in zero page"

.const IRQ_MAX_ENTRIES = 16

// The stable handler's first instruction runs on its line at this raster cycle (VICE CYC),
// every frame. MEASURED: tests/engine/irq_chain spike_h2 (line 177), cycle 6 in 1,000 of 1,000
// frames, with stage 1 arriving on 8 different cycles and stage 2 on 2.
.const IRQ_STABLE_CYCLE = 6

// Stage 2's wait: X loop count and extra cycles, set so that `cmp $d012` reads on the last
// cycle of line-1 for the early arrival and the first cycle of `line` for the late one.
// Found by measurement (tests/engine/irq_chain/measure.py), not by counting: don't change one
// without re-measuring spike_h2's spread.
.const IRQ_STABLE_DELAY = 3             // dex/bne loop count: 5 * n - 1 cycles
.const IRQ_STABLE_PAD   = 3             // 0, 2, 3, 4 or 5 extra cycles

.const IRQ_VIC_CTRL1  = $d011
.const IRQ_VIC_RASTER = $d012
.const IRQ_VIC_ISR    = $d019
.const IRQ_VIC_IMR    = $d01a
.const IRQ_CIA1_ICR   = $dc0d
.const IRQ_CIA2_ICR   = $dd0d
.const IRQ_VEC_NMI    = $fffa
.const IRQ_VEC_IRQ    = $fffe

// ------------------------------------------------------------------------------------------
// Chain declaration. Entry data is kept in assembly-time lists (lines, kinds) and in one
// root-scope label per entry for the handler address: labels resolve across passes, list
// entries holding a forward reference don't.
// ------------------------------------------------------------------------------------------

.var irq_chain_lines  = List()          // requested line (the handler's line)
.var irq_chain_stable = List()          // true for IrqStable entries
.var irq_chain_open   = false

.macro IrqChainBegin() {
        .errorif irq_chain_open, "IrqChainBegin: chain already open"
        .errorif irq_chain_lines.size() != 0, "IrqChainBegin: only one chain per program"
        .eval irq_chain_open = true
}

.macro IrqNormal(line, handler) {
        _IrqAdd(line, handler, false)
}

.macro IrqStable(line, handler) {
        .errorif line < 2, "IrqStable: line must be at least 2 (it triggers at line - 2)"
        _IrqAdd(line, handler, true)
}

.macro _IrqAdd(line, handler, stable) {
        .errorif !irq_chain_open, "IrqNormal/IrqStable outside IrqChainBegin/IrqChainEnd"
        .errorif line < 0 || line > 255, "IRQ chain line must be 0-255"
        .var n = irq_chain_lines.size()
        .errorif n >= IRQ_MAX_ENTRIES, "IRQ chain: at most 16 entries"
        .eval irq_chain_lines.add(line)
        .eval irq_chain_stable.add(stable)
        _IrqSetHandler(n, handler)
}

.macro _IrqSetHandler(i, h) {
        .if (i == 0)  { .label @irq_chain_h0  = h }
        .if (i == 1)  { .label @irq_chain_h1  = h }
        .if (i == 2)  { .label @irq_chain_h2  = h }
        .if (i == 3)  { .label @irq_chain_h3  = h }
        .if (i == 4)  { .label @irq_chain_h4  = h }
        .if (i == 5)  { .label @irq_chain_h5  = h }
        .if (i == 6)  { .label @irq_chain_h6  = h }
        .if (i == 7)  { .label @irq_chain_h7  = h }
        .if (i == 8)  { .label @irq_chain_h8  = h }
        .if (i == 9)  { .label @irq_chain_h9  = h }
        .if (i == 10) { .label @irq_chain_h10 = h }
        .if (i == 11) { .label @irq_chain_h11 = h }
        .if (i == 12) { .label @irq_chain_h12 = h }
        .if (i == 13) { .label @irq_chain_h13 = h }
        .if (i == 14) { .label @irq_chain_h14 = h }
        .if (i == 15) { .label @irq_chain_h15 = h }
}

.function _IrqHandler(i) {
        .if (i == 0)  .return irq_chain_h0
        .if (i == 1)  .return irq_chain_h1
        .if (i == 2)  .return irq_chain_h2
        .if (i == 3)  .return irq_chain_h3
        .if (i == 4)  .return irq_chain_h4
        .if (i == 5)  .return irq_chain_h5
        .if (i == 6)  .return irq_chain_h6
        .if (i == 7)  .return irq_chain_h7
        .if (i == 8)  .return irq_chain_h8
        .if (i == 9)  .return irq_chain_h9
        .if (i == 10) .return irq_chain_h10
        .if (i == 11) .return irq_chain_h11
        .if (i == 12) .return irq_chain_h12
        .if (i == 13) .return irq_chain_h13
        .if (i == 14) .return irq_chain_h14
        .return irq_chain_h15
}

// The line the raster IRQ is programmed with: stable entries trigger 2 lines early.
.function _IrqTriggerLine(i) {
        .if (irq_chain_stable.get(i)) .return irq_chain_lines.get(i) - 2
        .return irq_chain_lines.get(i)
}

// One byte of the dispatch target: entry 0 goes through the tick stub, stable entries through
// stage 1. The list lookup is resolved by .if before any forward label is used (an expression
// mixing the two fails across passes).
.macro _IrqTargetByte(i, hi) {
        .if (i == 0) {
            .byte hi ? >irq_tick : <irq_tick
        } else .if (irq_chain_stable.get(i)) {
            .byte hi ? >irq_stable_begin : <irq_stable_begin
        } else {
            .byte hi ? >_IrqHandler(i) : <_IrqHandler(i)
        }
}

// Emits the tables (6 bytes per entry, all in one page so indexed reads never cross) and the
// entry-0 tick stub.
//   irq_lines       trigger line per entry (RAM: the main loop may move an entry, one byte, atomic;
//                   for a stable entry write line - 2)
//   irq_next        index of the entry after this one (wraps to 0)
//   irq_target_lo/hi  what irq_dispatch jumps to
//   irq_handler_lo/hi the handler itself (read by the stable stage 2)
.macro IrqChainEnd() {
        .errorif !irq_chain_open, "IrqChainEnd without IrqChainBegin"
        .eval irq_chain_open = false
        .var n = irq_chain_lines.size()
        .errorif n < 1, "IRQ chain: at least 1 entry"
        .for (var i = 1; i < n; i++) {
            .errorif _IrqTriggerLine(i) <= _IrqTriggerLine(i - 1), "IRQ chain: trigger lines must ascend (a stable entry triggers at line - 2): entry " + i
        }
        .label @IRQ_COUNT = n
        .if (((* & $ff) + 6 * n) > $100) .align $100
@irq_lines:
        .for (var i = 0; i < n; i++) .byte _IrqTriggerLine(i)
@irq_next:
        .for (var i = 0; i < n; i++) .byte mod(i + 1, n)
@irq_target_lo:
        .for (var i = 0; i < n; i++) _IrqTargetByte(i, false)
@irq_target_hi:
        .for (var i = 0; i < n; i++) _IrqTargetByte(i, true)
@irq_handler_lo:
        .for (var i = 0; i < n; i++) .byte <_IrqHandler(i)
@irq_handler_hi:
        .for (var i = 0; i < n; i++) .byte >_IrqHandler(i)
@irq_tables_end:
        .errorif (irq_lines >> 8) != ((irq_tables_end - 1) >> 8), "irq tables cross a page"

// Entry 0's dispatch target: the frame tick, then the entry's real target. 8 cycles.
@irq_tick:
        inc zp_irq_frame                // 5
        .if (irq_chain_stable.get(0)) {
            jmp irq_stable_begin        // 3
        } else {
            jmp irq_chain_h0            // 3
        }
}

// End a handler: advance the chain. (jmp: 3 cycles)
.macro IrqDone() {
        jmp irq_exit
}

// End a handler with A = line: fire `handler` at that line, without advancing the chain.
.macro IrqRearm(handler) {
        ldx #<handler
        ldy #>handler
        jmp irq_rearm
}

// ------------------------------------------------------------------------------------------
// Hot block: irq_dispatch and the stable stage 2 share a page (stage 1 and stage 2 swap only
// the low byte of $FFFE), and stage 2's branches must not cross a page (they'd add a cycle).
// ------------------------------------------------------------------------------------------
.const IRQ_HOT_SIZE = 64
.if (((* & $ff) + IRQ_HOT_SIZE) > $100) .align $100
irq_hot_start:

// TIMING: every IRQ enters here. 17 cycles to the handler (24 after the IRQ is taken).
// In: IRQ taken (I set)   Out: jumps to the current entry's target with A, X, Y saved, D clear
irq_dispatch:
        sta irq_save_a + 1              // 4
        stx irq_save_x + 1              // 4
        sty irq_save_y + 1              // 4
        cld                             // 2  the main loop may use decimal mode
irq_jmp:
        jmp irq_dispatch                // 3  operand = target, written by irq_exit / irq_rearm / irq_init
                                        // total 17

// TIMING: stable stage 2. Arrives on line-1 at cycle c or c+1 (IRQ during stage 1's NOP slide).
// Ends at the handler on `line`, cycle IRQ_STABLE_CYCLE, every frame. Must not be a badline.
irq_stable_stage2:
        txs                             // 2  drop stage 2's own 3-byte frame (X = SP from stage 1)
        lda #<irq_dispatch              // 2
        sta IRQ_VEC_IRQ                 // 4  $FFFE back to the dispatcher (same page: low byte only)
        ldx zp_irq_idx                  // 3
        lda irq_handler_lo,x            // 4  tables never cross a page (asserted)
        sta irq_stable_jmp + 1          // 4
        lda irq_handler_hi,x            // 4
        sta irq_stable_jmp + 2          // 4  = 27
        ldx #IRQ_STABLE_DELAY           // 2
!:      dex                             // 2
        bne !-                          // 3 / 2: loop 5n - 1
        .if (IRQ_STABLE_PAD == 2) { nop }
        .if (IRQ_STABLE_PAD == 3) { bit $00 }
        .if (IRQ_STABLE_PAD == 4) { nop
                                    nop }
        .if (IRQ_STABLE_PAD == 5) { nop
                                    bit $00 }
        lda IRQ_VIC_RASTER              // 4  on line-1 in both cases
        cmp IRQ_VIC_RASTER              // 4  reads on the line change: equal only for the early arrival
        beq !+                          // 3 early (still line-1) / 2 late (line): removes the last cycle
!:
irq_stable_jmp:
        jmp irq_stable_jmp              // 3  operand = handler, written above
irq_hot_end:
        .errorif (irq_dispatch >> 8) != (irq_stable_stage2 >> 8), "irq_dispatch and irq_stable_stage2 must share a page"
        .errorif (irq_hot_start >> 8) != ((irq_hot_end - 1) >> 8), "irq.asm hot block crosses a page"
        .errorif irq_hot_end - irq_hot_start > IRQ_HOT_SIZE, "raise IRQ_HOT_SIZE"

// ------------------------------------------------------------------------------------------
// Exit, re-arm and late check.
// ------------------------------------------------------------------------------------------

// TIMING: 60 cycles to irq_exit_rti on the non-wrap path, 58 on the wrap (measured, tests/engine/irq_chain).
// Advance to the next entry: $D012 and the dispatch target first, then acknowledge, then the
// late check. The wrap to entry 0 is exempt from the check (it's for the next frame).
// In: from a handler (IrqDone), registers saved by irq_dispatch
irq_exit:
        ldy zp_irq_idx                  // 3
        ldx irq_next,y                  // 4
        stx zp_irq_idx                  // 3
        ldy irq_lines,x                 // 4
        sty IRQ_VIC_RASTER              // 4
        lda irq_target_lo,x             // 4
        sta irq_jmp + 1                 // 4
        lda irq_target_hi,x             // 4
        sta irq_jmp + 2                 // 4
        lda #$01                        // 2
        sta IRQ_VIC_ISR                 // 4  acknowledge
        cpy IRQ_VIC_RASTER              // 4  line - raster: C=0 below, Z=1 on it
        bcc irq_late                    // 2  raster already past the line
        beq irq_late                    // 2  raster on the line (the IRQ may have been acked away)
        bit IRQ_VIC_CTRL1               // 4  raster bit 8: lines 256-311 are past every chain line
        bmi irq_late                    // 2  (checked after the compare, so a 255 -> 256 crossing can't slip through)
irq_restore:
irq_save_a:
        lda #$00                        // 2  operands written by irq_dispatch
irq_save_x:
        ldx #$00                        // 2
irq_save_y:
        ldy #$00                        // 2  = 60
irq_exit_rti:
        rti                             // 6

// Late: the raster is already on or past the next entry's line, so its IRQ wouldn't fire
// until next frame. Acknowledge again (a latch may have happened after the first ack) and
// run the entry now, registers still saved. X = the new entry index; 0 is the wrap: exempt.
irq_late:
        txa                             // 2
        beq irq_restore                 // 3  wrap to entry 0: not late, next frame's
irq_late_now:
        lda #$01                        // 2
        sta IRQ_VIC_ISR                 // 4
#if DEBUG
        inc irq_late_count              // 6  saturating at 255
        bne !+
        dec irq_late_count
!:
#endif
        jmp irq_jmp                     // 3  the target was already written

// TIMING: 35 cycles to irq_exit_rti (counted; the irq_chain spike doesn't use it).
// Fire `handler` (X = lo, Y = hi) at line A, without advancing the chain.
// In: A = line, X/Y = handler, from a handler (IrqRearm)
irq_rearm:
        sta IRQ_VIC_RASTER              // 4
        stx irq_jmp + 1                 // 4
        sty irq_jmp + 2                 // 4
        ldx #$01                        // 2
        stx IRQ_VIC_ISR                 // 4  acknowledge
        cmp IRQ_VIC_RASTER              // 4  line - raster
        bcc irq_late_now                // 2
        beq irq_late_now                // 2
        bit IRQ_VIC_CTRL1               // 4
        bmi irq_late_now                // 2
        jmp irq_restore                 // 3  = 35

// NMI (RESTORE) with the KERNAL out: ignore it.
irq_nmi:
        rti

// ------------------------------------------------------------------------------------------
// Stable stage 1: a stable entry's dispatch target, on line-2. Points $FFFE at stage 2,
// programs the next line, acknowledges and waits in a NOP slide, so stage 2's IRQ arrives
// with at most 1 cycle of jitter.
// ------------------------------------------------------------------------------------------
irq_stable_begin:
        lda #<irq_stable_stage2         // 2
        sta IRQ_VEC_IRQ                 // 4  low byte only: same page as irq_dispatch
        inc IRQ_VIC_RASTER              // 6  compare = current line + 1 = line-1
        lda #$01                        // 2
        sta IRQ_VIC_ISR                 // 4  ack line-2 (and any latch from the RMW's dummy write)
        tsx                             // 2  for stage 2's txs
        cli                             // 2  = 22
        .fill 24, NOP                   // 48 cycles: stage 2's IRQ arrives in here
// Fallback, only if stage 2's IRQ never came (stage 1 ran too late, e.g. after a long sei):
// run the handler now, unstable, and count it as late.
        sei
#if DEBUG
        inc irq_late_count
        bne !+
        dec irq_late_count
!:
#endif
        lda #<irq_dispatch
        sta IRQ_VEC_IRQ
        ldx zp_irq_idx
        lda irq_handler_lo,x
        sta irq_stable_jmp + 1
        lda irq_handler_hi,x
        sta irq_stable_jmp + 2
        jmp irq_stable_jmp

// ------------------------------------------------------------------------------------------
// Set up the machine and start the raster chain at entry 0.
// In:  nothing (the chain is declared with IrqChainBegin/IrqChainEnd)
// Out: interrupts enabled, chain running
// Uses: A, X
// Doesn't touch the stack pointer, the VIC bank, $D018 or anything else on the screen.
irq_init:
        sei
        lda #$7f
        sta IRQ_CIA1_ICR                // CIA 1 interrupts off
        sta IRQ_CIA2_ICR                // CIA 2 NMIs off
        lda IRQ_CIA1_ICR                // clear anything pending
        lda IRQ_CIA2_ICR
        lda #$35
        sta $01                         // BASIC and KERNAL out, I/O in
        lda #<irq_nmi
        sta IRQ_VEC_NMI
        lda #>irq_nmi
        sta IRQ_VEC_NMI + 1
        lda #<irq_dispatch
        sta IRQ_VEC_IRQ
        lda #>irq_dispatch
        sta IRQ_VEC_IRQ + 1
        lda IRQ_VIC_CTRL1
        and #$7f                        // compare bit 8 = 0: chain lines are 0-255
        sta IRQ_VIC_CTRL1
        ldx #0
        stx zp_irq_idx
        lda irq_lines
        sta IRQ_VIC_RASTER
        lda irq_target_lo
        sta irq_jmp + 1
        lda irq_target_hi
        sta irq_jmp + 2
        lda #$01
        sta IRQ_VIC_IMR                 // raster IRQ only
        lda #$ff
        sta IRQ_VIC_ISR                 // acknowledge every VIC latch
        cli
        rts

// Wait for the next frame tick (entry 0 has just started).
// In: nothing   Out: A = new zp_irq_frame   Uses: A
irq_wait_frame:
        lda zp_irq_frame
!:      cmp zp_irq_frame
        beq !-
        lda zp_irq_frame
        rts

#if DEBUG
// Late runs (exit, re-arm, or a stable stage 2 that never came). Saturates at 255.
// make test requires 0 in every spike.
irq_late_count:
        .byte 0
#endif
