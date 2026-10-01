// Timing probe: when does the VIC-II use each sprite register? (engine/README.md#slot-write-deadline,
// estimates #7 and #8.) One hardware sprite, one register write per frame at a swept raster cycle,
// and VICE's frame buffer says which display lines show the old value and which the new one.
//
// How it works
//   - engine/irq.asm runs two chain entries: probe_top (line 20) copies the whole sprite
//     configuration from RAM (cfg_*) to the VIC-II, so every frame starts from the same "old" state;
//     probe_stable is a STABLE entry on line PROBE_LINE (102): it starts on cycle 6 of that line
//     (IRQ_STABLE_CYCLE, measured again here by sweep.py at every sample).
//   - probe_stable waits cfg_coarse x 5 cycles (a dex/bne loop, for the writes 22 lines later in
//     the FREE test), then cfg_delay cycles (0-255, one-cycle steps, see ProbeDelay), then runs
//     `lda cfg_val / sta <target>`. sweep.py pokes the target address into the sta's operand
//     (probe_write + 1) and steps over the sta, so the cycle of the write is MEASURED for every
//     sample, never computed: it is the raster position after the instruction, minus one (the
//     write is the last cycle of `sta abs`). With cfg_coarse = 0 and nothing stolen it is cycle
//     64 + cfg_delay counted from the start of line 102 (handler at cycle 6, + 7 + 4 + 40 + 4 + 3).
//   - The screen is on (sprites are hidden by the border when DEN is off), and the probed lines sit
//     between two badlines (99 and 107, YSCROLL = 3): the stable entry's lines 100-102, the
//     sprite's Y line 103 and its first display line 104 have no badline, so the only DMA near the
//     write is the probed sprite's own. (engine/README.md asked for "screen off, borders open";
//     this gives the same thing, a badline-free window, with the sprite visible.)
//   - Main loop: `jmp *`.
//
// Configuration (RAM, poked by sweep.py while the machine is stopped):
//   cfg_d015, cfg_d010, cfg_d01c   register values at the top of the frame
//   cfg_xy[16]                     $D000-$D00F: X low and Y of sprites 0-7
//   cfg_col[8], cfg_ptr[8]         $D027-$D02E and the pointers at $07F8
//   cfg_coarse, cfg_delay, cfg_val the write: delay (5-cycle steps, then 1-cycle steps), value
//   probe_write + 1 / + 2          the write's target address (default cfg_dummy: no write)
// Sprite data: pointer PTR_SOLID (24 x 21 solid) and PTR_STRIPE ($AA bytes: every other pixel in
// hires, solid in multicolour, so the $D01C bit shows).
//
// Rerun:
//   make GAME=sprite_latch SRC_DIR=tests/timing/sprite_latch
//   uv run python tests/timing/sprite_latch/sweep.py | tee tests/timing/sprite_latch/results.txt
//     (about a minute; `sweep.py --quick` does sprite 0 only. The header of sweep.py describes
//     the tests and the output; results.txt is the run behind the figures below.)
//   By hand: vice_start build/sprite_latch/sprite_latch.prg; vice_run_until probe_stable -> line
//     102, cycle 6 every frame; vice_screenshot shows the configured sprite.
//
// Measured 2026-10-01, VICE 3.10 x64sc PAL (sweep.py, 13,590 samples; probe_stable on line 102
// cycle 6 in every one). Last write cycle at which the sprite's first display line (Y + 1) shows
// the new value, as "line:cycle" relative to the sprite's Y line:
//   Y and the $D015 bit    Y:53 (sprite 0), Y:54 (sprites 2, 3, 7)
//   pointer                Y:54 (sprite 0), Y:58 (2), Y:60 (3), Y+1:05 (7)
//   X low, $D010 bit, colour, $D01C bit    Y+1:15 for a sprite at X = 24 (cycle 12 + X / 8)
//   Rewriting a hardware sprite: nothing written on line Y_old + 22 or later marks the old sprite.
// Details: RESULTS in sweep.py's header, results.txt (the run's full output) and
// docs/reference/vic-ii-timing.md#sprite-register-write-deadlines.
// Zero page: zp_irq_idx, zp_irq_frame (engine/irq.asm), in zp.asm.

BasicUpstart2(start)

#import "zp.asm"

.const PROBE_TOP_LINE = 20              // top border: configuration -> VIC-II
.const PROBE_LINE     = 102             // the stable entry: 100-102 are not badlines (99 and 107 are)
.const SCREEN         = $0400
.const VIC_SPR        = $d000
.const VIC_XMSB       = $d010
.const VIC_ENABLE     = $d015
.const VIC_YEXP       = $d017
.const VIC_PRIO       = $d01b
.const VIC_MCOLOR     = $d01c
.const VIC_XEXP       = $d01d
.const VIC_BORDER     = $d020
.const VIC_BG         = $d021
.const VIC_SPR_MC1    = $d025
.const VIC_SPR_MC2    = $d026
.const VIC_SPR_COL    = $d027

* = $0810 "Engine"
#import "engine/irq.asm"

* = * "Chain"
        IrqChainBegin()
        IrqNormal(PROBE_TOP_LINE, probe_top)
        IrqStable(PROBE_LINE, probe_stable)
        IrqChainEnd()

* = * "Probe"
start:
        lda #0
        sta VIC_ENABLE
        sta VIC_YEXP
        sta VIC_XEXP
        sta VIC_PRIO
        sta VIC_BG                      // black background: sprite pixels are anything else
        lda #11
        sta VIC_BORDER                  // dark grey border
        lda #5
        sta VIC_SPR_MC1
        lda #13
        sta VIC_SPR_MC2
        ldx #0
!:      lda #$20                        // clear the screen: only the sprite shows
        sta SCREEN,x
        sta SCREEN + $100,x
        sta SCREEN + $200,x
        sta SCREEN + $2e8,x
        inx
        bne !-
        jsr irq_init
probe_main:
        jmp probe_main

// Chain entry 0, line 20: the frame's starting configuration. Not timing-critical: it only has to
// finish well before the probed lines (it takes about 6 lines).
probe_top:
        lda cfg_d015
        sta VIC_ENABLE
        lda cfg_d010
        sta VIC_XMSB
        lda cfg_d01c
        sta VIC_MCOLOR
        ldx #7
!:      lda cfg_col,x
        sta VIC_SPR_COL,x
        lda cfg_ptr,x
        sta SCREEN + $3f8,x
        dex
        bpl !-
        ldx #15
!:      lda cfg_xy,x
        sta VIC_SPR,x
        dex
        bpl !-
        IrqDone()

// Wait A cycles more than the fixed 40: bit k of A adds 2^k cycles (a taken bcc is 3; not taken
// it is 2 + a body of 2^k + 1 cycles). Uses A. No branch may cross a page (checked below).
.macro ProbeDelay() {
        lsr                             // 2
        bcc !+                          // 3 / 2
        nop                             // 2      + 1
!:      lsr
        bcc !+
        bit $ea                         // 3      + 2
!:      lsr
        bcc !+
        nop
        bit $ea                         // 5      + 4
!:      lsr
        bcc !+
        .fill 3, NOP
        bit $ea                         // 9      + 8
!:      lsr
        bcc !+
        .fill 7, NOP
        bit $ea                         // 17     + 16
!:      lsr
        bcc !+
        .fill 15, NOP
        bit $ea                         // 33     + 32
!:      lsr
        bcc !+
        .fill 31, NOP
        bit $ea                         // 65     + 64
!:      lsr
        bcc !+
        .fill 63, NOP
        bit $ea                         // 129    + 128
!:
}

        .align $100                     // the delay's branches stay inside one page
// TIMING: stable entry, starts on line PROBE_LINE at cycle IRQ_STABLE_CYCLE (6). With cfg_coarse
// = 0 the write lands 58 + cfg_delay cycles later (7 + 4 + 40 + cfg_delay + 4 + 3) when nothing is
// stolen in between, i.e. on cycle 64 + cfg_delay counted from the start of line 102; each
// cfg_coarse = c > 0 adds 5c - 2. sweep.py measures it at every sample (0, 0: line 103, cycle 1).
probe_stable:
        ldx cfg_coarse                  // 4
        beq fine                        // 3 (cfg_coarse = 0) / 2
coarse: dex                             // 2
        bne coarse                      // 3 / 2: 5 per step
fine:   lda cfg_delay                   // 4
        ProbeDelay()                    // 40 + cfg_delay
        lda cfg_val                     // 4
probe_write:
        sta cfg_dummy                   // 4  the write is its last cycle; operand poked by sweep.py
probe_after:
        IrqDone()
probe_stable_end:
        .errorif (probe_stable >> 8) != ((probe_stable_end - 1) >> 8), "probe_stable crosses a page"

// --- configuration (poked by sweep.py) ---------------------------------------------------------
cfg_d015:   .byte $01
cfg_d010:   .byte $00
cfg_d01c:   .byte $00
cfg_xy:     .byte 24, 103, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
cfg_col:    .fill 8, 1
cfg_ptr:    .fill 8, PTR_SOLID
cfg_coarse: .byte 0
cfg_delay:  .byte 0
cfg_val:    .byte 0
cfg_dummy:  .byte 0

        .align 64
sprite_solid:
        .fill 63, $ff                   // 24 x 21 solid
        .byte 0
sprite_stripe:
        .fill 63, $aa                   // hires: every other pixel; multicolour: all pairs %10 = sprite colour
        .byte 0
sprite_end:
        .errorif sprite_end > $1000, "sprite data must stay below $1000 (the VIC sees the character ROM there)"
.label PTR_SOLID  = sprite_solid / 64
.label PTR_STRIPE = sprite_stripe / 64
