// Timing probe: how much raster time does a fixed block of CPU work take?
// block_start..block_end is 63 NOPs = exactly 126 CPU cycles. Profiling it with
// vice_profile gives 126 when nothing is stolen; the excess on other passes is what the
// VIC-II stole (badlines, sprite DMA). Interrupts are off so nothing else interferes.
//
//   make GAME=badline SRC_DIR=tests/timing/badline
//   vice_start build/badline/badline.prg, then vice_profile block_start block_end
//   Sprites: poke $d015 (enable) and the Y registers via vice_write_memory, profile again.

BasicUpstart2(start)

start:
        sei
        lda #$7f
        sta $dc0d               // no CIA1 interrupts
        lda $dc0d
loop:
block_start:
        .fill 63, NOP           // 63 x 2 = 126 cycles
block_end:
        jmp loop
