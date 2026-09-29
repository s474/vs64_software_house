// Timing probe: CPU cycles per raster line and per frame, measured with a CIA timer.
//
// vice_profile can't measure this: it turns VICE's raster position into cycles using 63
// cycles/line itself. So this probe times raster lines with CIA1 timer A, which counts every
// phi2 cycle whether or not the VIC-II has the bus.
//
//   res200: cycles from line $10 (16) to line $D8 (216) of the same frame = 200 lines
//   res312: cycles from line $10 to line $10 of the next frame              = 1 frame
//
// Start and stop use identical code (poll exit -> lda # -> sta $dc0e), so the fixed CIA
// start/stop latency and the code cost cancel apart from a small constant, and each result is
// the raster time +- the busy-wait loop's jitter (the loop is 9 cycles). Results are stored as
// cycles elapsed = $FFFF - timer (the timer counts down from $FFFF), in 8-entry ring buffers.
//
// Rerun:
//   make GAME=rasterline SRC_DIR=tests/timing/rasterline
//   vice_start build/rasterline/rasterline.prg, vice_run_frames 40
//   vice_read_memory res200_lo 8, res200_hi 8, res312_lo 8, res312_hi 8
//   elapsed = $FFFF - (hi * 256 + lo). Expect 200 x cycles/line and lines x cycles/line.
//
// Measured 2026-09-29, VICE 3.10 x64sc PAL, all 8 ring-buffer entries identical:
//   res200 = $3136 = 12,598 (200 x 63 = 12,600)   res312 = $4CC7 = 19,655 (312 x 63 = 19,656)
//   The -2 / -1 is the constant CIA start/stop latency plus poll phase; 64 or 65 cycles/line
//   would give 12,800 / 13,000.
// Zero page: none. Interrupts off.

BasicUpstart2(start)

.macro WaitFrameStart() {
!:      bit $d011
        bpl !-
!:      bit $d011
        bmi !-
}

.macro WaitLine(line) {
!:      lda $d012
        cmp #line
        bne !-
}

.macro StartTimer() {
        lda #%00010001          // force load latch ($FFFF), start, continuous, count phi2
        sta $dc0e
}

.macro StopTimer() {
        lda #%00000000          // stop (same cost as StartTimer)
        sta $dc0e
}

start:
        sei
        lda #$7f
        sta $dc0d               // no CIA1 interrupts
        lda $dc0d
        lda #0
        sta $dc0e               // timer A stopped
        lda #$ff
        sta $dc04               // latch = $FFFF
        sta $dc05

loop:
        // --- 200 raster lines within one frame --------------------------------------------
        WaitFrameStart()
        WaitLine($10)
        StartTimer()
        WaitLine($d8)
        StopTimer()
        ldx idx
        lda #$ff
        sec
        sbc $dc04
        sta res200_lo,x
        lda #$ff
        sbc $dc05
        sta res200_hi,x

        // --- One whole frame, line $10 to line $10 -------------------------------------
        WaitFrameStart()
        WaitLine($10)
        StartTimer()
        WaitFrameStart()
        WaitLine($10)
        StopTimer()
        ldx idx
        lda #$ff
        sec
        sbc $dc04
        sta res312_lo,x
        lda #$ff
        sbc $dc05
        sta res312_hi,x

        inx
        txa
        and #7
        sta idx
        jmp loop

idx:        .byte 0
res200_lo:  .fill 8, 0
res200_hi:  .fill 8, 0
res312_lo:  .fill 8, 0
res312_hi:  .fill 8, 0
