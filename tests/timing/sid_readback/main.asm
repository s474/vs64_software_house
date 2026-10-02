// Timing probe: what the SID registers do, as far as a program can read them back
// (docs/reference/sid.md; asked for by engine/sfx.md, "The reference doc it must write").
//
// The SID can be read back in two places only: $D41B (the top 8 bits of voice 3's waveform
// output) and $D41C (voice 3's envelope). So every test here uses voice 3, and what it shows is
// VICE's SID emulation, not the chip.
//
// How it works
//   - Interrupts stay off (sei) and the screen is off ($D011 = $0B, no sprites), so there is no
//     badline, no sprite DMA and no IRQ: every instruction takes its counted cycles, and the
//     spacing of the reads is exact. measure.py still MEASURES the spacings it relies on, by
//     stopping at the labels below and reading the raster position.
//   - The program idles in probe_idle until measure.py pokes a test's configuration (cfg_*) and
//     sets cfg_go, runs the test, clears cfg_go and passes probe_done, where the script stops it
//     and reads the result buffers. Every test starts with sid_settle (all 25 registers 0, then
//     three ticks: the envelope is at 0 and its rate counter back at rate 0, whatever the test
//     before left) and ends with all 25 registers written 0. $D418 = 0 throughout: the probe
//     is silent.
//
// Tests (cfg_test)
//   0 readback  Each of $D400-$D418: write (cfg_val eor register number), read it back 4 cycles
//               later (rb_now), all of $D400-$D41C again after two ticks (rb_later), then write
//               $5A to $D401 and read all 29 at once (rb_bus: does a read return the last byte
//               written to any register?).
//   1 osc       Voice 3: frequency cfg_flo/cfg_fhi, pulse width high register cfg_pw, the test
//               bit set (the oscillator held at 0), then control = cfg_ctrl, and 256 reads of
//               $D41B exactly 16 cycles apart into fine_buf, the first 4 cycles after the write.
//   2 env       A script of ticks. Once a frame, on raster line 251 (as the engine's sound tick):
//               read $D41C into env_buf[k], then do cfg_act[k]:
//                 0      nothing
//                 1, 2   a START as engine/sfx.asm does it, from parameter set 0 or 1 (set_ad,
//                        set_sr, set_pw, set_flo, set_fhi, set_ctrl): attack/decay,
//                        sustain/release, pulse width, control 0, frequency low, high, control.
//                        The control 0 write and the last write are 43 + 5 x cfg_gap cycles apart
//                        (cfg_gap = 4: 63, the module's DEBUG spacing; measure.py measures it)
//                 3      write cfg_actval[k] to the control register
//                 5, 6   as 1, 2 with the attack/decay written twice: with decay 0 where the
//                        module writes it, and whole again 18 cycles after the gate (a variant
//                        of the start sequence, measured for the Technical Director)
//               Before the action the tick waits 5 x cfg_phase cycles, so that a run can be
//               repeated against every phase of the envelope's rate counter.
//               for cfg_frames ticks (1-255). If k = cfg_fine_k, the action is followed by 256
//               reads of $D41C (the operand at fine_read + 1: measure.py may point it at $D41B)
//               into fine_buf, 17 + 5 x cfg_fine_delay cycles apart: for what happens inside a
//               frame (a 2 ms attack, a late attack). The ticks after that one are late.
//
// Labels for measure.py: cfg (the configuration block), probe_done, rb_written, osc_release / osc_read,
// env_ctrl0 / env_gate, fine_read, and the buffers rb_now, rb_later, rb_bus, env_buf, fine_buf.
//
// Rerun:
//   make GAME=sid_readback SRC_DIR=tests/timing/sid_readback
//   uv run --package budget-runner python tests/timing/sid_readback/measure.py \
//       | tee tests/timing/sid_readback/results.txt
//     (about three minutes. The header of measure.py lists the sections; results.txt is the
//     run behind docs/reference/sid.md.)
//
// Measured 2026-10-02, VICE 3.10 x64sc PAL, reSID emulating an 8580 (SidModel 1), in short
// (docs/reference/sid.md has it fact by fact):
//   - a program's read of $D400-$D418 returns the last byte written to any SID register; the
//     monitor's read returns each register's last written value;
//   - $D41B/$D41C do not read live under `-sounddev dummy` (the budget runner, the MCP server):
//     measure.py starts its own VICE with `-sounddev dump -soundarg /dev/null`;
//   - the oscillator adds the frequency value to a 24-bit count once a cycle (256 of 256 reads
//     fit, three frequency values); pulse width n/16 is low for exactly n/16 of the period; the
//     noise value changes every 2^20 / frequency value cycles;
//   - sustain level = nibble x 17; attack 0 reaches $FF in 2,295 cycles, attack 1 in 8,177;
//   - a control write with the gate set does not restart the attack; control 0 then the gate
//     63 cycles later does, from the level the envelope had;
//   - a start is up to 32,900 cycles (33 ms) late when the envelope was last stepping at a
//     slow rate (sections 8 and 9).
// Nothing to see: the screen is off. Zero page: none.

BasicUpstart2(start)

.const SID          = $d400
.const SID_V3_FLO   = $d40e
.const SID_V3_FHI   = $d40f
.const SID_V3_PWLO  = $d410
.const SID_V3_PWHI  = $d411
.const SID_V3_CTRL  = $d412
.const SID_V3_AD    = $d413
.const SID_V3_SR    = $d414
.const SID_OSC3     = $d41b
.const SID_ENV3     = $d41c
.const VIC_CTRL1    = $d011
.const VIC_RASTER   = $d012
.const VIC_SPR_ENA  = $d015
.const VIC_BORDER   = $d020
.const TICK_LINE    = 251               // the engine's sound tick is chain entry 1 at line $FB

* = $0810 "Probe"
start:
        sei                             // for good: no IRQ ever runs in this program
        lda #$0b
        sta VIC_CTRL1                   // screen off: no badlines from the next frame on
        lda #0
        sta VIC_SPR_ENA
        lda #DARK_GREY
        sta VIC_BORDER
        jsr wait_tick
        jsr wait_tick                   // a whole frame with the screen off has passed
        jsr sid_reset
probe_idle:
        lda cfg_go
        beq probe_idle
        jsr sid_settle                  // every test starts from the same state
        lda cfg_test
        bne !+
        jsr test_readback
        jmp probe_finish
!:      cmp #1
        bne !+
        jsr test_osc
        jmp probe_finish
!:      jsr test_env
probe_finish:
        jsr sid_reset
        lda #0
        sta cfg_go
probe_done:
        jmp probe_idle

// Write 0 to all 25 registers.
sid_reset:
        ldx #$18
        lda #0
!:      sta SID,x
        dex
        bpl !-
        rts

// All registers 0, then three ticks (at least 39,000 cycles). Gate off with release 0 does not
// act at once when the envelope's rate counter is above the new rate's period: the counter must
// first wrap at 32,768 (measured: measure.py section 8). After this the envelope is 0 and its
// rate counter is cycling at rate 0's period, whatever the last test left.
sid_settle:
        jsr sid_reset
        jsr wait_tick
        jsr wait_tick
        jsr wait_tick
        rts

// Return a few cycles into raster line 251, a different visit from the one we may be on.
wait_tick:
        lda #TICK_LINE
!:      cmp VIC_RASTER
        beq !-
!:      cmp VIC_RASTER
        bne !-
        rts

// ---------------------------------------------------------------------------------------------
// Test 0: read-back of the write-only registers.
// ---------------------------------------------------------------------------------------------
test_readback:
        .for (var r = 0; r <= $18; r++) {
            lda cfg_val
            eor #r
            sta SID + r                 // the write is this instruction's last cycle
            lda SID + r                 // the read is 4 cycles later
            sta rb_now + r
        }
rb_written:                             // measure.py stops here and reads $D400-$D418 through the monitor
        jsr wait_tick
        jsr wait_tick                   // at least one frame later
        .for (var r = 0; r <= $1c; r++) {
            lda SID + r
            sta rb_later + r
        }
        lda #$5a
        sta SID + 1
        .for (var r = 0; r <= $1c; r++) {
            lda SID + r                 // 4, 12, 20, ... cycles after the write
            sta rb_bus + r
        }
        rts

// ---------------------------------------------------------------------------------------------
// Test 1: voice 3's oscillator through $D41B.
// TIMING: the loop is 16 cycles, every pass (no DMA, no IRQ; one page: asserted below).
// ---------------------------------------------------------------------------------------------
.align $100
test_osc:
        lda cfg_flo
        sta SID_V3_FLO
        lda cfg_fhi
        sta SID_V3_FHI
        lda #0
        sta SID_V3_PWLO
        lda cfg_pw
        sta SID_V3_PWHI
        lda #$08
        sta SID_V3_CTRL                 // test bit: the oscillator is held at 0
        ldy #0
!:      dey
        bne !-                          // about 1,300 cycles with it held
        ldx #0
        lda cfg_ctrl
osc_release:
        sta SID_V3_CTRL                 // 4  the write is the last cycle
osc_read:
        lda SID_OSC3                    // 4  the read is the last cycle: first read 4 after the write
        sta fine_buf,x                  // 5
        nop                             // 2
        inx                             // 2
        bne osc_read                    // 3  = 16
        rts
osc_end:
        .errorif (>test_osc) != (>osc_end), "test_osc crosses a page"

// ---------------------------------------------------------------------------------------------
// Test 2: the envelope through $D41C, tick by tick.
// ---------------------------------------------------------------------------------------------
test_env:
        lda #0
        sta env_k
env_frame:
        jsr wait_tick
        ldx env_k
        lda SID_ENV3
        sta env_buf,x
        ldy cfg_phase                   // move the action 5 cycles a step: the envelope's rate
!:      dey                             // counter is then met in a different phase
        bne !-
        lda cfg_act,x
        beq env_acted
        cmp #3
        bne env_start
        lda cfg_actval,x
        sta SID_V3_CTRL
        jmp env_acted

// A start, with the module's order of writes and (cfg_gap = 4) its DEBUG spacing. The stores
// to probe_dummy stand for the module's shadow and state stores. Actions 5 and 6 (bit 2 set)
// are the variant measure.py section 9 tries: decay 0 in the attack/decay write, and the real
// value written again after the gate.
env_start:
        pha
        and #4
        sta env_split
        pla
        and #3
        tax
        dex                             // parameter set 0 or 1
        lda set_ad,x
        ldy env_split
        beq !+
        and #$f0
!:      sta env_ad_first
        ldy #0
        lda env_ad_first                // 4
        sta SID_V3_AD                   // 4
        sta probe_dummy                 // 4
        lda set_sr,x                    // 4
        sta SID_V3_SR                   // 4
        sta probe_dummy                 // 4
        lda set_pw,x                    // 4
        sta SID_V3_PWHI                 // 4
        sta probe_dummy                 // 4
env_ctrl0:
        sty SID_V3_CTRL                 // 4  control 0: gate off
        sty probe_dummy                 // 4
        ldy cfg_gap                     // 4
!:      dey                             // 2
        bne !-                          // 3 / 2: 5 x cfg_gap - 1
        lda set_flo,x                   // 4
        sta SID_V3_FLO                  // 4
        sta probe_dummy                 // 4
        lda set_fhi,x                   // 4
        sta probe_dummy                 // 4
        sta SID_V3_FHI                  // 4
        sta probe_dummy                 // 4
        lda set_ctrl,x                  // 4
env_gate:
        sta SID_V3_CTRL                 // 4  = 43 + 5 x cfg_gap after the control 0 write
        ldy env_split                   // 4
        beq env_acted                   // 2
        sta probe_dummy                 // 4  (the shadow store)
        lda set_ad,x                    // 4
        sta SID_V3_AD                   // 4  the real attack/decay, 18 cycles after the gate

env_acted:
        lda env_k
        cmp cfg_fine_k
        bne !+
        jsr fine_sample
!:      inc env_k
        lda env_k
        cmp cfg_frames
        beq !+
        jmp env_frame
!:      rts

// 256 reads, 17 + 5 x cfg_fine_delay cycles apart.
.align $100
fine_sample:
        ldx #0
fine_read:
        lda SID_ENV3                    // 4
        sta fine_buf,x                  // 5
        ldy cfg_fine_delay              // 4
!:      dey                             // 2
        bne !-                          // 3 / 2: 5 x cfg_fine_delay - 1
        inx                             // 2
        bne fine_read                   // 3  = 17 + 5 x cfg_fine_delay
        rts
fine_end:
        .errorif (>fine_sample) != (>fine_end), "fine_sample crosses a page"

// ---------------------------------------------------------------------------------------------
// Configuration (poked by measure.py while the machine is stopped) and results.
// ---------------------------------------------------------------------------------------------
env_k:          .byte 0
env_split:      .byte 0
env_ad_first:   .byte 0
probe_dummy:    .byte 0

cfg:
cfg_go:         .byte 0                 // 1 = run cfg_test; cleared when it has run
cfg_test:       .byte 0                 // 0 readback, 1 osc, 2 env
cfg_val:        .byte 0                 // readback: the value written (eor the register number)
cfg_flo:        .byte 0                 // osc: frequency
cfg_fhi:        .byte 0
cfg_pw:         .byte 0                 // osc: pulse width, high register
cfg_ctrl:       .byte 0                 // osc: control value
cfg_frames:     .byte 0                 // env: ticks, 1-255
cfg_gap:        .byte 4                 // env: start spacing, 43 + 5 x this (1-255)
cfg_fine_k:     .byte $ff               // env: tick whose action is followed by fine_sample
cfg_fine_delay: .byte 1                 // env: fine_sample's period, 17 + 5 x this (1-255)
cfg_phase:      .byte 1                 // env: wait 5 x this before each tick's action (1-255)
set_ad:         .byte 0, 0              // env: the two parameter sets for a start
set_sr:         .byte 0, 0
set_pw:         .byte 0, 0
set_flo:        .byte 0, 0
set_fhi:        .byte 0, 0
set_ctrl:       .byte 0, 0

.align $100
cfg_act:        .fill 256, 0            // env: the action of each tick
cfg_actval:     .fill 256, 0            // env: the control value of an action 3
env_buf:        .fill 256, 0            // env: $D41C at each tick, before its action
fine_buf:       .fill 256, 0            // osc: $D41B; env: fine_sample's reads
rb_now:         .fill 32, 0
rb_later:       .fill 32, 0
rb_bus:         .fill 32, 0
