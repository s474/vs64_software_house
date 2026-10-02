// engine/sfx.asm: sound effects on the three SID voices (M4 stage 4). Design contract:
// engine/sfx.md. SID facts: docs/reference/sid.md.
//
// API
//   sfx_init     Write 0 to all 25 SID registers, then $0F to $D418; clear every voice's state and
//                request. Call once, before irq_init.
//   sfx_play     A = effect number (0 to SFX_COUNT - 1, not checked). Leaves a request for the
//                effect's voice: one byte. Main loop only. Uses A, X, Y.
//   sfx_update   The tick. Once a frame, from an IRQ handler (chain entry at line $FB:
//                `jsr sfx_update` then IrqDone()), never from the main loop. Takes the requests,
//                applies the priority rule, steps every playing effect by one frame, writes the
//                SID. Uses A, X, Y (the IRQ framework has saved them). No zero page, no zp_tmp.
//   SfxBegin() / SfxEffect(...) / SfxStep(...) / SfxEnd() / SfxHz(hz)
//                The game's effect data, written after this file is imported: see "Effect data".
//
// Voices: module voice 0, 1, 2 = SID voice 1, 2, 3 (registers from $D400, $D407, $D40E).
// Priorities 1-3, higher wins; a new effect replaces the one playing on its voice if its
// priority is equal or higher, otherwise the request is dropped. An idle voice takes anything.
// One effect per voice. Exactly what each routine does, tick by tick: engine/sfx.md.
//
// Registers owned: $D400-$D418; nothing else writes the SID. The module reads no SID register
// (a read returns the last byte written to the chip, not the register: sid.md fact 2). After
// sfx_init it writes only the seven registers of each voice.
// Zero page: none. State: absolute RAM at the end of this file. sfx_request (3 bytes) is the
// only thing shared between the main loop and the IRQ: one byte per voice, every access atomic.
// The rest is the IRQ's. zp_sfx_ptr, reserved by the game's zp.asm, is NOT used.
// DEBUG builds: sfx_shadow (25 bytes) holds the last value written to each of $D400-$D418,
// stored by the same code, straight after each register write (4 cycles a write).
//
// Measured cost (VICE 3.10 x64sc PAL, tests/engine/sfx: make test ARGS=sfx and
// tests/engine/sfx/measure.py, 2026-10-02). Raster cycles = CPU cycles: sfx_update runs from line
// 251, sfx_play in the top border, no badline, no sprite DMA, no IRQ inside; every pass the same.
// "span" = label to its _end label (the rts itself not included); "call" = span + jsr 6 + rts 6.
//                                                DEBUG span / call     release span / call
//   sfx_update, three voices idle                    44 /  56               42 /  54
//   sfx_update, three voices on a slide tick        202 / 214              177 / 189
//   sfx_update, three starts in one tick (worst)    417 / 429              333 / 345
//   sfx_play, nothing pending on the voice           22 /  34               22 /  34
//   sfx_play, pending equal or lower: replaced       37 /  49               37 /  49
//   sfx_play, pending higher: kept                   25 /  37               25 /  37
//   sfx_play in the display (a badline inside)       span + 43 at most: measured 22-65, 37-80, 25-68
//   Per voice, counted (the macro below): idle 14; slide 67 (59 release); step change 92 (80);
//   end 63 (59); start 139 (111); a dropped request 23 on top of whatever the voice then does.
//   The DEBUG build's idle and slide ticks are 2 and 1 over three times those: a branch of
//   voice 1 and one of voice 2 cross a page there (fixed by the .align: the same everywhere).
//   A tick that ends after line 255 (three starts: line 258) costs its chain entry 8 more in
//   irq_exit (66, not 58: the framework's raster bit-8 test), measured in the spike's IRQ.
//   Size: code 586 bytes DEBUG, 490 release (budget 600); state 21; shadow 25 (DEBUG).
// Constraints:
//   - sfx_play: main loop only, never from an IRQ handler. It never disables interrupts.
//   - A request made before line 251 of a frame is started by that frame's tick.
//   - Of several requests for one voice in a frame the highest priority survives, the latest on
//     a tie. A request of lower priority than what is playing is dropped, not queued.
//   - An effect ends when its data ends or another replaces it; it can't be stopped early.
//   - The code is page-aligned (up to 255 bytes of padding before it), so that its branches
//     cross the same page boundaries in every program: the figures above are the same everywhere.
//   - SID behaviour the data must allow for (measured in VICE, docs/reference/sid.md fact 15): a
//     start can be up to 33 ms late, the voice holding the level it had, when the envelope was
//     last stepping at a slow rate. Effects with every rate 0 are never late.

.const SFX_SID = $d400                  // 25 registers; voice v's seven start at SFX_SID + 7 * v
.const SFX_FREQ_LO = 0                  // offsets inside a voice
.const SFX_FREQ_HI = 1
.const SFX_PW_HI   = 3                  // (pulse width low, offset 2, stays 0 after sfx_init)
.const SFX_CTRL    = 4
.const SFX_AD      = 5
.const SFX_SR      = 6
.const SFX_VOLUME  = $18                // $D418: volume in the low nibble

// ------------------------------------------------------------------------------------------
// Effect data. The game writes, after importing this file:
//
//         SfxBegin()
// .label SFX_PLAYER_SHOT = SfxEffect(0, 1, $00, $a0, 8)   // voice 0-2, priority 1-3, attack/decay,
//                                                         // sustain/release, pulse width 0-15
//         SfxStep(8, $41, $2800, -$0180)   // frames 1-255, control, start frequency, slide a frame
// .label SFX_WAVE_START  = SfxEffect(2, 2, $09, $00, 8)
//         SfxStep(9, $41, SfxHz(523.25), 0)    // a note
//         SfxStep(1, $40, SfxHz(523.25), 0)    // gate off for a frame
//         ...
//         SfxEnd()                         // emits the tables where it stands
//
// SfxEffect is a function: it returns the effect's number (0, 1, 2, ... in the order written), so
// the .label in front of it names the effect for `lda #SFX_PLAYER_SHOT / jsr sfx_play`. (A .label
// may be used before the line that defines it; a .const may not.) Each effect's end marker is
// added for it: its last step's control value with the gate clear.
// SfxEnd() emits sfx_voice, sfx_prio, sfx_ad, sfx_sr, sfx_pw, sfx_first (one byte an effect) and
// sfx_s_frames, sfx_s_ctrl, sfx_s_flo, sfx_s_fhi, sfx_s_slo, sfx_s_shi (one byte a step, end
// markers included), each kept inside one page, and defines SFX_COUNT and SFX_STEPS.
// The build stops on: a voice outside 0-2, a priority outside 1-3, a pulse width over 15, frames
// outside 1-255, a control byte that isn't one waveform bit ($10, $20, $40, $80) with or without
// the gate ($01), an effect with no step, more than 127 effects or 255 steps.
// ------------------------------------------------------------------------------------------

.var sfx_d_voice  = List()              // one entry an effect
.var sfx_d_prio   = List()
.var sfx_d_ad     = List()
.var sfx_d_sr     = List()
.var sfx_d_pw     = List()
.var sfx_d_first  = List()
.var sfx_d_frames = List()              // one entry a step
.var sfx_d_ctrl   = List()
.var sfx_d_freq   = List()
.var sfx_d_slide  = List()
.var sfx_d_open   = false               // between SfxBegin and SfxEnd
.var sfx_d_steps  = 0                   // steps in the effect being written

// PAL frequency value for a pitch in Hz: Hz x 16,777,216 / 985,248 (sid.md fact 5).
.function SfxHz(hz) {
        .return round(hz * 16777216 / 985248)
}

.macro SfxBegin() {
        .errorif sfx_d_open || sfx_d_voice.size() != 0, "SfxBegin: only one set of effects per program"
        .eval sfx_d_open = true
}

// Close the effect being written: its end marker.
.function _SfxClose() {
        .if (sfx_d_voice.size() != 0) {
            .if (sfx_d_steps == 0) .error "SfxEffect: the effect before this one has no step"
            .eval sfx_d_frames.add(0)
            .eval sfx_d_ctrl.add(sfx_d_ctrl.get(sfx_d_ctrl.size() - 1) & $fe)
            .eval sfx_d_freq.add(0)
            .eval sfx_d_slide.add(0)
        }
        .return 0
}

// Begin an effect. Returns its number.
.function SfxEffect(voice, prio, ad, sr, pw) {
        .if (!sfx_d_open) .error "SfxEffect outside SfxBegin/SfxEnd"
        .if (voice < 0 || voice > 2) .error "SfxEffect: voice must be 0-2 (SID voice - 1)"
        .if (prio < 1 || prio > 3) .error "SfxEffect: priority must be 1-3"
        .if (ad < 0 || ad > 255 || sr < 0 || sr > 255) .error "SfxEffect: attack/decay and sustain/release are bytes"
        .if (pw < 0 || pw > 15) .error "SfxEffect: pulse width must be 0-15 (sixteenths)"
        .if (sfx_d_voice.size() >= 127) .error "SfxEffect: at most 127 effects"
        .var dummy = _SfxClose()
        .eval sfx_d_voice.add(voice)
        .eval sfx_d_prio.add(prio)
        .eval sfx_d_ad.add(ad)
        .eval sfx_d_sr.add(sr)
        .eval sfx_d_pw.add(pw)
        .eval sfx_d_first.add(sfx_d_frames.size())
        .eval sfx_d_steps = 0
        .return sfx_d_voice.size() - 1
}

// One step of the effect being written: `frames` ticks of control value `ctrl`, starting at
// frequency `freq` and adding `slide` (signed) on every tick but the first.
.macro SfxStep(frames, ctrl, freq, slide) {
        .errorif !sfx_d_open || sfx_d_voice.size() == 0, "SfxStep before the first SfxEffect"
        .errorif frames < 1 || frames > 255, "SfxStep: frames must be 1-255"
        .errorif (ctrl & $fe) != $10 && (ctrl & $fe) != $20 && (ctrl & $fe) != $40 && (ctrl & $fe) != $80, "SfxStep: control must be one waveform ($10, $20, $40, $80), with or without the gate ($01)"
        .errorif freq < 0 || freq > $ffff, "SfxStep: frequency must be 0-$FFFF"
        .errorif slide < -$8000 || slide > $7fff, "SfxStep: slide must be -$8000 to $7FFF"
        .eval sfx_d_frames.add(frames)
        .eval sfx_d_ctrl.add(ctrl)
        .eval sfx_d_freq.add(freq)
        .eval sfx_d_slide.add(slide & $ffff)
        .eval sfx_d_steps = sfx_d_steps + 1
}

// A table of n bytes read as `table,x` and as `table - 1,x`: both stay inside one page.
.macro _SfxFit(n) {
        .if ((* & $ff) == 0 || (* & $ff) + n > $100) {
            .align $100
            .byte 0
        }
}

// Emit the tables. Every indexed read of them is 4 cycles: no table crosses a page.
.macro SfxEnd() {
        .errorif !sfx_d_open, "SfxEnd without SfxBegin"
        .errorif sfx_d_voice.size() == 0, "SfxEnd: no effect"
        .var dummy = _SfxClose()
        .eval sfx_d_open = false
        .var n = sfx_d_voice.size()
        .var s = sfx_d_frames.size()
        .errorif s > 255, "SfxEnd: at most 255 steps in all, end markers included"
        .label @SFX_COUNT = n
        .label @SFX_STEPS = s
        _SfxFit(n)
@sfx_voice:     .for (var i = 0; i < n; i++) .byte sfx_d_voice.get(i)
        _SfxFit(n)
@sfx_prio:      .for (var i = 0; i < n; i++) .byte sfx_d_prio.get(i)
        _SfxFit(n)
@sfx_ad:        .for (var i = 0; i < n; i++) .byte sfx_d_ad.get(i)
        _SfxFit(n)
@sfx_sr:        .for (var i = 0; i < n; i++) .byte sfx_d_sr.get(i)
        _SfxFit(n)
@sfx_pw:        .for (var i = 0; i < n; i++) .byte sfx_d_pw.get(i)
        _SfxFit(n)
@sfx_first:     .for (var i = 0; i < n; i++) .byte sfx_d_first.get(i)
        .if ((* & $ff) + s > $100) .align $100
@sfx_s_frames:  .for (var i = 0; i < s; i++) .byte sfx_d_frames.get(i)
        .if ((* & $ff) + s > $100) .align $100
@sfx_s_ctrl:    .for (var i = 0; i < s; i++) .byte sfx_d_ctrl.get(i)
        .if ((* & $ff) + s > $100) .align $100
@sfx_s_flo:     .for (var i = 0; i < s; i++) .byte <sfx_d_freq.get(i)
        .if ((* & $ff) + s > $100) .align $100
@sfx_s_fhi:     .for (var i = 0; i < s; i++) .byte >sfx_d_freq.get(i)
        .if ((* & $ff) + s > $100) .align $100
@sfx_s_slo:     .for (var i = 0; i < s; i++) .byte <sfx_d_slide.get(i)
        .if ((* & $ff) + s > $100) .align $100
@sfx_s_shi:     .for (var i = 0; i < s; i++) .byte >sfx_d_slide.get(i)
@sfx_tables_end:
}

// ------------------------------------------------------------------------------------------
// Register writes: the SID register, and in DEBUG builds its shadow straight after it.
// ------------------------------------------------------------------------------------------
.macro _SfxSta(reg) {
        sta SFX_SID + reg               // 4
#if DEBUG
        sta sfx_shadow + reg            // 4
#endif
}

.macro _SfxSty(reg) {
        sty SFX_SID + reg               // 4
#if DEBUG
        sty sfx_shadow + reg            // 4
#endif
}

// One voice of the tick. Falls through to the next voice. Cycle counts are DEBUG's; a release
// build is 4 less for each register write ("w" below).
//   idle 14 | slide 67 | step change 92 | end 63 | start 139 | a dropped request + 23
.macro _SfxVoice(v) {
        .var r = v * 7
        ldx sfx_request + v             // 4  0, or effect + 1
        beq play                        // 2 / 3
        ldy #0                          // 2
        sty sfx_request + v             // 4  taken: from here the main loop's next request stands
        lda sfx_prio - 1,x              // 4
        cmp sfx_cur_prio + v            // 4
        bcc play                        // 2 / 3  lower than what is playing: dropped  (= 23)
        // Start: 7 writes. Attack/decay, sustain/release, pulse width, control 0 (gate off, so
        // that the gate-on below starts a new attack), then the first step.
        sta sfx_cur_prio + v            // 4
        stx sfx_cur + v                 // 4
        lda sfx_ad - 1,x                // 4
        _SfxSta(r + SFX_AD)             // 8 w
        lda sfx_sr - 1,x                // 4
        _SfxSta(r + SFX_SR)             // 8 w
        lda sfx_pw - 1,x                // 4
        _SfxSta(r + SFX_PW_HI)          // 8 w
        _SfxSty(r + SFX_CTRL)           // 8 w  Y = 0
        ldy sfx_first - 1,x             // 4  = 22 + 56 to here
        // Load step Y: frequency low, high, control. Or the end marker: control alone.
load:   lda sfx_s_frames,y              // 4
        beq end                         // 2 / 3
        sta sfx_left + v                // 4
        sty sfx_step + v                // 4
        lda sfx_s_flo,y                 // 4
        sta sfx_freq_lo + v             // 4
        _SfxSta(r + SFX_FREQ_LO)        // 8 w
        lda sfx_s_fhi,y                 // 4
        sta sfx_freq_hi + v             // 4
        _SfxSta(r + SFX_FREQ_HI)        // 8 w
        lda sfx_s_ctrl,y                // 4
        _SfxSta(r + SFX_CTRL)           // 8 w  = 58
        jmp done                        // 3    start: 78 + 58 + 3 = 139
end:    lda sfx_s_ctrl,y                // 4  the last waveform, gate clear: the release plays out
        _SfxSta(r + SFX_CTRL)           // 8 w
        lda #0                          // 2
        sta sfx_cur + v                 // 4
        sta sfx_cur_prio + v            // 4  idle
        beq done                        // 3  always
next:   ldy sfx_step + v                // 4
        iny                             // 2
        bne load                        // 3  always: a step index is at most 254
play:   lda sfx_cur_prio + v            // 4
        beq done                        // 2 / 3  idle: 4 + 3 + 4 + 3 = 14
        dec sfx_left + v                // 6
        beq next                        // 2 / 3  the step's frames are up
        // Slide: frequency + the step's slide, 16 bits, wrapping. 2 writes.
        ldy sfx_step + v                // 4
        clc                             // 2
        lda sfx_freq_lo + v             // 4
        adc sfx_s_slo,y                 // 4
        sta sfx_freq_lo + v             // 4
        _SfxSta(r + SFX_FREQ_LO)        // 8 w
        lda sfx_freq_hi + v             // 4
        adc sfx_s_shi,y                 // 4
        sta sfx_freq_hi + v             // 4
        _SfxSta(r + SFX_FREQ_HI)        // 8 w  slide: 7 + 6 + 8 + 46 = 67
done:
}

.align $100                             // fixed page crossings: the same cost in every program
sfx_start:

// The tick: advance every voice by one frame. Called from an IRQ handler, once a frame; never
// from the main loop.
// In:  nothing   Out: nothing   Uses: A, X, Y. No zero page, no zp_tmp
// Cost: profile span (sfx_update -> sfx_update_end), measured, DEBUG (release): three voices idle
//       44 (42); three slides 202 (177); three starts in one tick, the worst case, 417 (333).
//       Whole call + 12. Per voice in the macro above.
// TIMING: the worst tick is three starts, 417 cycles to sfx_update_end (budget 488), locked as
//         the whole call (429) in tests/engine/sfx/budget.json with the idle and slide ticks.
sfx_update:
        _SfxVoice(0)
        _SfxVoice(1)
        _SfxVoice(2)
sfx_update_end:
        rts                             // 6

// Ask for an effect to start at the next tick. Main loop only; never from an IRQ handler.
// In:  A = effect number, 0 to SFX_COUNT - 1 (not checked)
// Out: nothing   Uses: A, X, Y. No zero page
// Cost: profile span (sfx_play -> sfx_play_end), measured, no DMA: nothing pending 22; a pending
//       request of equal or lower priority replaced 37; a pending request of higher priority
//       kept 25. Whole call + 12: 34, 49, 37.
// TIMING: three constant paths, each locked as the whole call in tests/engine/sfx/budget.json.
// The tick may take the pending request between this routine's read and its write: the outcome
// is still right (the pending one started; the new one is the next tick's request, or was
// dropped because it was lower).
sfx_play:
        tax                             // 2  X = the effect
        ldy sfx_voice,x                 // 4  Y = its voice
        lda sfx_request,y               // 4  what is pending there: effect + 1, or 0
        beq sfx_play_set                // 2 / 3
        tay                             // 2
        lda sfx_prio,x                  // 4  the new effect's priority
        cmp sfx_prio - 1,y              // 4  against the pending effect's
        bcc sfx_play_end                // 2 / 3  lower: the pending one stays  (= 25)
        ldy sfx_voice,x                 // 4
sfx_play_set:
        inx                             // 2
        txa                             // 2
        sta sfx_request,y               // 5  one byte: atomic  (= 22 nothing pending, 37 replaced)
sfx_play_end:
        rts                             // 6

// Silence the SID and clear the module's state. Call once, before irq_init.
// In: nothing   Out: nothing   Uses: A, X
// Cost: about 420 cycles (counted; called once, not budgeted)
sfx_init:
        ldx #SFX_VOLUME
        lda #0
!:      sta SFX_SID,x                   // all 25 registers: gates off, no filter, volume 0
#if DEBUG
        sta sfx_shadow,x
#endif
        dex
        bpl !-
        ldx #sfx_state_end - sfx_state - 1
!:      sta sfx_state,x                 // every voice idle, nothing pending
        dex
        bpl !-
        lda #$0f
        _SfxSta(SFX_VOLUME)             // volume 15, no filter, voice 3 not muted
        rts
sfx_code_end:

// State. sfx_request is shared (sfx_play writes, sfx_update reads and clears); the rest is the
// IRQ's.
sfx_state:
sfx_request:    .fill 3, 0              // 0 = none, else effect + 1
sfx_cur:        .fill 3, 0              // the effect playing, + 1; 0 = idle
sfx_cur_prio:   .fill 3, 0              // its priority; 0 = idle
sfx_step:       .fill 3, 0              // index of the current step
sfx_left:       .fill 3, 0              // ticks left in it
sfx_freq_lo:    .fill 3, 0              // the frequency last written
sfx_freq_hi:    .fill 3, 0
sfx_state_end:
#if DEBUG
sfx_shadow:     .fill 25, 0             // the last value written to each of $D400-$D418
#endif
sfx_end:

// Size (measured, tests/engine/sfx/measure.py): 586 bytes of code in a DEBUG build, 490 in
// release (budget 600), + 21 of state and, in DEBUG, 25 of shadow. In DEBUG the tick's first
// branch (`beq play`) spans 127 bytes, the most a branch can: one more byte between it and
// `play` and the assembler stops with "jump distance is too far" (make it bne *+5 / jmp play,
// 2 cycles more a voice on the idle and slide ticks, and re-baseline the locks).
.const SFX_CODE_MAX = 600
.errorif (sfx_code_end - sfx_start) > SFX_CODE_MAX, "engine/sfx.asm: code is larger than SFX_CODE_MAX"
.errorif (>sfx_state) != (>(sfx_state_end - 1)), "engine/sfx.asm: state crosses a page"
