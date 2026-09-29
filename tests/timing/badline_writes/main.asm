// Timing probe: what a badline steals when the CPU is running write cycles.
//
// The VIC-II pulls BA low 3 cycles before a badline's fetches; the CPU only stops at its next
// READ cycle, so write cycles in progress keep running. This probe runs three streams across
// the badline on raster line $33 (51), $3B (59) and $43 (67) (default YSCROLL = 3):
//
//   Label pair                   Stream                           CPU cycles
//   nop_bl   -> nop_bl_end       63 x NOP          (reads only)    126
//   inc_bl   -> inc_bl_end       21 x INC abs      (2 writes/6)    126
//   jsr_bl   -> jsr_bl_end       10 x JSR + RTS    (2 writes/12)   120
//
// Each block starts on the line before its badline and spans exactly one badline. The start
// is varied by the frame counter (PhaseDelay before the poll, PhaseDelayHi after it), so over
// many passes the badline lands on every cycle of the stream. Stolen = raster time - CPU cycles.
//
// Controls in the top border (line $10: no badlines, no sprites) prove the CPU counts:
//   nop_ctrl -> inc_ctrl = 126, inc_ctrl -> jsr_ctrl = 126, jsr_ctrl -> ctrl_end = 120.
//
// Rerun:
//   make GAME=badline_writes SRC_DIR=tests/timing/badline_writes
//   vice_start build/badline_writes/badline_writes.prg
//   vice_profile nop_ctrl inc_ctrl samples=32         (control: expect min = max = 126)
//   vice_profile nop_bl nop_bl_end samples=128         steal = result - 126
//   vice_profile inc_bl inc_bl_end samples=128         steal = result - 126
//   vice_profile jsr_bl jsr_bl_end samples=128         steal = result - 120
// Interrupts are off and no sprites are enabled, so the badline is the only thing stealing.
//
// Measured 2026-09-29, VICE 3.10 x64sc PAL, 128 passes each (steal min / avg / max):
//   controls 126 / 126 / 120 exact;  NOP 43 / 43.0 / 43;  INC abs 41 / 42.3 / 43;
//   JSR 41 / 42.8 / 43. (A delay placed only after the poll gave JSR 43 on every pass:
//   the poll's exit grid cancelled it. Hence PhaseDelay before the poll.)
// Zero page: $fb (phase) only, a free user location.

BasicUpstart2(start)

.const phase = $fb

// Wait for the start of a new frame: line >= 256, then back to line 0.
.macro WaitFrameStart() {
!:      bit $d011
        bpl !-
!:      bit $d011
        bmi !-
}

// Busy-wait for a raster line below 256 (call in ascending order after WaitFrameStart).
.macro WaitLine(line) {
!:      lda $d012
        cmp #line
        bne !-
}

// Delay of 0-15 extra cycles, chosen by the low 4 bits of `phase`.
// Each branch skips to code whose cost differs by 1, 2, 4 or 8 cycles.
.macro PhaseDelay() {
        lda phase               // 3
        and #$0f                // 2
        lsr                     // 2
        bcs !+                  // bit 0: taken 3 / not taken 2 -> +1
!:      lsr
        bcc !+                  // bit 1: 3 / 2+3 -> +2
        bit $ea
!:      lsr
        bcc !+                  // bit 2: 3 / 2+2+3 -> +4
        nop
        bit $ea
!:      lsr
        bcc !+                  // bit 3: 3 / 2+2+2+2+3 -> +8
        nop
        nop
        nop
        bit $ea
!:
}

// Extra 0 or +8 cycles after the poll, from bit 4 of `phase`. PhaseDelay goes BEFORE the
// poll (it moves the poll's 9-cycle exit grid through all 9 offsets); a delay placed only
// after the poll is cancelled by that grid, so the start offset would barely change.
.macro PhaseDelayHi() {
        lda phase
        and #$10
        beq !+                  // 3 / 2+2+2+2+3 -> +8
        nop
        nop
        nop
        bit $ea
!:
}

start:
        sei
        lda #$7f
        sta $dc0d               // no CIA1 interrupts
        lda $dc0d
        lda #0
        sta $d015               // no sprites

loop:
        WaitFrameStart()
        inc phase

        // --- Controls: top border, no DMA --------------------------------------------
        WaitLine($10)
nop_ctrl:
        .fill 63, NOP           // 126
inc_ctrl:
        .for (var i = 0; i < 21; i++) {
            inc scratch         // 6 x 21 = 126
        }
jsr_ctrl:
        .for (var i = 0; i < 10; i++) {
            jsr do_rts          // (6 + 6) x 10 = 120
        }
ctrl_end:
        nop                     // end marker: a label on a busy-wait loop would stop the profiler every poll

        // --- NOP stream across badline $33 --------------------------------------------
        PhaseDelay()
        WaitLine($32)
        PhaseDelayHi()
nop_bl:
        .fill 63, NOP           // 126
nop_bl_end:
        nop                     // end marker: a label on a busy-wait loop would stop the profiler every poll

        // --- INC abs stream across badline $3B ----------------------------------------
        PhaseDelay()
        WaitLine($3a)
        PhaseDelayHi()
inc_bl:
        .for (var i = 0; i < 21; i++) {
            inc scratch         // 126
        }
inc_bl_end:
        nop                     // end marker: a label on a busy-wait loop would stop the profiler every poll

        // --- JSR/RTS stream across badline $43 ----------------------------------------
        PhaseDelay()
        WaitLine($42)
        PhaseDelayHi()
jsr_bl:
        .for (var i = 0; i < 10; i++) {
            jsr do_rts          // 120
        }
jsr_bl_end:
        nop                     // end marker: a label on a busy-wait loop would stop the profiler every poll
        jmp loop

do_rts:
        rts

scratch:
        .byte 0
