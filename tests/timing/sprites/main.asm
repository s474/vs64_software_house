// Timing probe: sprite DMA, on its own and on the same lines as a badline.
//
// `spr_enable` (a RAM byte) is copied to $D015 every frame, so the sprite set is chosen by
// poking it with vice_write_memory; nothing else changes between configurations. Sprite data
// and X positions don't matter: DMA happens for every enabled sprite on its lines.
// Default YSCROLL = 3 (badlines on $33, $3B, ...), no X/Y expansion, interrupts off.
//
// Each frame the sprites are placed twice (Y is rewritten after the first set has finished):
//   1. Y = $10: DMA on lines 17-37, all in the top border (no badlines there).
//      spr_blk -> spr_blk_end: 20 NOPs = 40 CPU cycles, started on line $18 at 17 different
//      offsets (PhaseDelay/PhaseDelayHi). 40 cycles + one DMA slot is under 63, so a pass sees at
//      most ONE line's sprite fetches: max - 40 = the per-line steal, min should be 40.
//   2. Y = $28: DMA on lines 41-61, which covers badline $33 (51).
//      spr_long -> spr_long_end: 63 NOPs (126) from line $2A: sprites only (lines < 48 are
//      never badlines).
//      bls_blk -> bls_blk_end: 63 NOPs (126) from line $32: sprites + badline $33.
//
// Rerun:
//   make GAME=sprites SRC_DIR=tests/timing/sprites
//   vice_start build/sprites/sprites.prg
//   vice_write_memory spr_enable <mask>         e.g. 00, 01, 03, 05, 09, ff
//   vice_run_frames 2                            (let the new mask take effect)
//   vice_profile spr_blk spr_blk_end samples=96    per-line sprite steal = max - 40
//   vice_profile spr_long spr_long_end samples=64  steal = result - 126
//   vice_profile bls_blk bls_blk_end samples=64    steal = result - 126
//   With spr_enable = 00, spr_blk must give 40 and bls_blk 126 + 43 (badline alone).
//   CPU cycles left ON the badline (line 51), per sprite mask, by instruction trace:
//   cd mcp/vice && uv run python ../../tests/timing/sprites/trace_badline.py ff 32 -q
//
// Measured 2026-09-29, VICE 3.10 x64sc PAL (spr_blk max - 40 / spr_long - 126 / bls_blk - 126):
//   mask 00: 0 / 0 / 43      01: 5 / 10 / 58      03: 7      05: 9      09: 10 (min 5: one group)
//   mask f8: 13 / - / 82     ff: 19 / 57 / 119
//   Trace, CPU cycles on line 51: 00 -> 20, 01 -> 15, 07 -> 10-12, f8 -> 6-8, ff -> 0-2
// Zero page: $fb (phase) only, a free user location.

BasicUpstart2(start)

.const phase = $fb

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

// Delay of 0-15 extra cycles, chosen by the low 4 bits of `phase`.
.macro PhaseDelay() {
        lda phase
        and #$0f
        lsr
        bcs !+                  // +1
!:      lsr
        bcc !+                  // +2
        bit $ea
!:      lsr
        bcc !+                  // +4
        nop
        bit $ea
!:      lsr
        bcc !+                  // +8
        nop
        nop
        nop
        bit $ea
!:
}

.macro SetSpriteY(y) {
        lda #y
        .for (var i = 0; i < 8; i++) {
            sta $d001 + i * 2
        }
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
        sta $d017               // no Y expansion
        sta $d01d               // no X expansion
        sta $d010
        lda #$80
        .for (var i = 0; i < 8; i++) {
            sta $d000 + i * 2   // X = 128 (irrelevant to DMA)
        }

loop:
        WaitFrameStart()
        inc phase
        lda spr_enable
        sta $d015
        SetSpriteY($10)         // DMA on lines 17-37

        // --- Sprites only, top border: at most one DMA slot per pass --------------------
        PhaseDelay()
        WaitLine($18)
        PhaseDelayHi()
spr_blk:
        .fill 20, NOP           // 40
spr_blk_end:
        nop                     // end marker: a label on a busy-wait loop would stop the profiler every poll

        WaitLine($27)           // first set finished on line 37
        SetSpriteY($28)         // DMA on lines 41-61

        // --- Sprites only, 126-cycle window (lines $2A..) ---------------------------------
        PhaseDelay()
        WaitLine($2a)
        PhaseDelayHi()
spr_long:
        .fill 63, NOP           // 126
spr_long_end:
        nop                     // end marker: a label on a busy-wait loop would stop the profiler every poll

        // --- Sprites + badline $33 ----------------------------------------------------------
        PhaseDelay()
        WaitLine($32)
        PhaseDelayHi()
bls_blk:
        .fill 63, NOP           // 126
bls_blk_end:
        nop                     // end marker: a label on a busy-wait loop would stop the profiler every poll
        jmp loop

spr_enable:
        .byte $00
