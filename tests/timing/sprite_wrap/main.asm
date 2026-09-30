// Timing probe: sprite Y and the PAL frame wrap. Raw VIC-II registers, interrupts off, no engine.
//
// Question: the VIC-II compares a sprite's Y register with raster bits 0-7 only. On PAL (lines
// 0-311), does a sprite at Y <= 55 start a second time on line 256 + Y, run 21 lines across the
// 311 -> 0 wrap, and cost DMA there? What happens at Y = 55 / 56?
//
// Configuration lives in RAM and is poked with vice_write_memory; the probe copies it to the
// VIC-II once a frame on line $FC (after the bottom-border code), so every register is constant
// from there to line $FC of the next frame and nothing is written while the probed lines run:
//   spr_enable ($D015), spr_yexp ($D017), spr_x[8] / spr_y[8] (sprite 0-7 X and Y, $D010 = 0),
//   d011_val ($D011 at the top of the frame: $1B = screen on, $0B = DEN off, no badlines).
//
// Each frame (interrupts off):
//   1. WaitFrameStart (line 0). If probe_hi = 0: probe on line probe_lo (1-240; line 0 can't be
//      reached in time after WaitFrameStart: the poll would catch line 256 or start on line 1).
//   2. Line $F9: clear RSEL; line $FC: set it again. This opens the top and bottom border, so a
//      sprite in them is visible (the area shows $D021, idle-graphics byte $3FFF = 0).
//   3. Line $FC: copy the configuration to the VIC-II.
//   4. If probe_hi = 1: probe on line 256 + probe_lo (256-311), or with probe_lo = $38 on line 0
//      of the next frame (waits for the wrap instead of polling $D012; skips a frame).
// Probe: PhaseDelay (0-15 cycles, before the poll), poll for the line, PhaseDelayHi (0/+8), then
// wrap_blk -> wrap_blk_end (probe_hi = 0) or wrap_blk_hi -> wrap_blk_hi_end (probe_hi = 1),
// each 31 NOPs = 62 CPU cycles. A pass that starts on line L at cycle 11-36 spans the whole
// end-of-line DMA slot of line L (sprites 0-2, CPU halted from cycle 55: tests/timing/sprites)
// and the start-of-line slot of L + 1 (sprites 3-7, to cycle 10), and ends (62 + up to 19) before
// L + 1's own end slot. Both slots fetch data for DISPLAY line L + 1, and nothing else, so
// raster time - 62 = the DMA that feeds display line L + 1. Passes that start later (up to ~cycle
// 57 where a poll exits at once) can also catch line L + 1's slot: sweep.py discards them, using
// the start (line, cycle) of every pass.
//
// Rerun:
//   make GAME=sprite_wrap SRC_DIR=tests/timing/sprite_wrap
//   Full sweep (DMA per line + displayed rows from VICE's frame buffer, several configurations):
//     cd mcp/vice && uv run python ../../tests/timing/sprite_wrap/sweep.py
//   By hand, one line:
//     vice_start build/sprite_wrap/sprite_wrap.prg
//     vice_write_memory spr_y 37          sprite 0 Y = $37 = 55 (default config: sprite 0 only)
//     vice_write_memory probe_hi 01 ; vice_write_memory probe_lo 37     line 256 + 55 = 311
//     vice_run_frames 2 ; vice_profile wrap_blk_hi wrap_blk_hi_end samples=32  -> 62 + DMA
//     (probe_hi 00: lines 0-240, profile wrap_blk wrap_blk_end instead)
//   Screenshot with the borders open: vice_screenshot area=full (sweep.py takes them too).
//
// Measured 2026-09-30, VICE 3.10 x64sc PAL (sweep.py, 32 passes a line; DMA by start line L):
//   Y=55: DMA 55-75 and 311, 0-19, 5 cycles every pass (sprite 0); shown 56-76 and 0-20.
//   Y=56: DMA 56-76 only, nothing on 256-311 or 0-55: the wrap stops at Y = 55 = 311 - 256.
//   Y=0 / 10 / 35: second DMA run 256-276 / 266-286 / 291-311. Y-expanded Y=55: 42 + 42 lines.
//   Sprites 0-7 at Y=55: 19 a line on 311 and 0-19. Default config: wrap_blk_hi 67 (62 + 5).
// Details: sweep.py's header and docs/reference/vic-ii-timing.md#sprite-y-and-the-frame-wrap.
// Zero page: $fb (phase) only, a free user location.

BasicUpstart2(start)

.const phase    = $fb
.const SPR_PTR  = sprite_data / 64          // bank 0, screen $0400: pointers at $07F8

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

// Delay of 0-15 extra cycles, chosen by the low 4 bits of `phase` (as tests/timing/sprites).
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

// Extra 0 or +8 cycles after the poll, from bit 4 of `phase`.
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

// Poll for the low byte of the probed line (the caller has already got into the right half
// of the frame), then run the measured block.
.macro Probe() {
        PhaseDelay()
!:      lda $d012
        cmp probe_lo
        bne !-
        PhaseDelayHi()
}

start:
        sei
        lda #$7f
        sta $dc0d               // no CIA1 interrupts
        lda $dc0d
        lda #0
        sta $d01d               // no X expansion
        sta $d010
        sta $d01c               // hires sprites
        sta $3fff               // idle graphics blank in the opened border
        lda #11
        sta $d020               // border dark grey
        lda #6
        sta $d021               // background blue (also the opened border area)
        ldx #0
!:      lda #$20                // clear the screen: only the sprites show
        sta $0400,x
        sta $0500,x
        sta $0600,x
        sta $06e8,x
        inx
        bne !-
        ldx #7
!:      lda #SPR_PTR
        sta $07f8,x
        lda spr_col,x
        sta $d027,x
        dex
        bpl !-

loop:
        WaitFrameStart()
        lda probe_hi
        bne !+
        Probe()
wrap_blk:
        .fill 31, NOP           // 62
wrap_blk_end:
        nop                     // end marker: a label on a busy-wait loop would stop the profiler every poll
!:      inc phase               // after the probe, so line 1 is reached early enough
        lda d011_val
        sta $d011               // DEN from the configuration (takes effect from the next line $30), RSEL = 1
        // --- open the top/bottom border -----------------------------------------------------
        WaitLine($f9)
        lda $d011
        and #$77                // RSEL = 0 (24 rows) on line 249: the bottom border never starts
        sta $d011
        WaitLine($fc)
        lda $d011
        and #$7f
        ora #$08                // RSEL = 1 again for the next frame's top-border compare
        sta $d011

        // --- configuration -> VIC-II (line $FC, done before line 256) ---------------------------
        lda spr_enable
        sta $d015
        lda spr_yexp
        sta $d017
        .for (var i = 0; i < 8; i++) {
            lda spr_x + i
            sta $d000 + i * 2
            lda spr_y + i
            sta $d001 + i * 2
        }

        lda probe_hi
        bne !+
        jmp loop_end
!:      PhaseDelay()            // shifts the exit of the bit-8 wait: what line 256 sees
!:      bit $d011               // wait for line 256 (raster bit 8): 7-cycle exit grid
        bpl !-
        lda probe_lo
        beq hi_go               // line 256: already on it (a $D012 poll would exit late)
        cmp #312 - 256
        bne hi_poll
        PhaseDelay()            // probe_lo = $38: line 312, i.e. line 0 of the next frame
!:      bit $d011               // wait for the wrap: 7-cycle exit grid, shifted by PhaseDelay
        bmi !-
        jmp hi_go
hi_poll:
        PhaseDelay()
!:      lda $d012
        cmp probe_lo
        bne !-
hi_go:
        PhaseDelayHi()
wrap_blk_hi:
        .fill 31, NOP           // 62
wrap_blk_hi_end:
        nop
loop_end:
        jmp loop

// --- configuration (poked by sweep.py / vice_write_memory) ----------------------------------
probe_hi:   .byte 1             // 0: probe line probe_lo; 1: probe line 256 + probe_lo
probe_lo:   .byte $37           // default: line 311
d011_val:   .byte $1b           // $1B screen on, $0B DEN off (no badlines from the next frame)
spr_enable: .byte $01
spr_yexp:   .byte $00
spr_x:      .byte 100, 140, 180, 220, 60, 80, 120, 160
spr_y:      .byte 55, 10, 30, 56, 55, 55, 55, 55
spr_col:    .byte 1, 7, 13, 10, 3, 4, 5, 8

        .align 64
sprite_data:
        .fill 63, $ff           // solid 24x21 block: every displayed line is visible
        .byte 0
