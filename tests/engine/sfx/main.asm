// sfx spike (M4 stage 4): proves engine/sfx.asm against its contract, engine/sfx.md, and is the
// player Simon judges the effects with.
//
// HEAR IT:  make run GAME=sfx SRC_DIR=tests/engine/sfx     (joystick in port 2; VICE: sound on)
//   It starts in PHASES mode, a test pattern that repeats every 80 frames (three soft probe
//   tones, then two shots and the start note). Move the stick or press fire once: STICK mode.
//   Up/down (or left/right) choose an effect from the list on screen, fire plays it. Entry 13
//   plays both halves of the player hit together, as the game does. Tap fire quickly to hear an
//   effect cut itself off; pick another and fire to hear priorities (the PLAYING line shows the
//   effect number on each voice). The same PRG runs on the C64 Ultimate.
//   Release build: make BUILD=release GAME=sfx SRC_DIR=tests/engine/sfx (no shadow, 4 cycles
//   less a register write; it sounds the same).
//
// Effects: Swarm's ten (swarm_sfx.asm, numbers 0-9), then three probe effects, one a voice: a
// single step of 40 frames with a slide (numbers 10-12).
//
// Chain: entry 0 at line $10 (the frame tick), entry 1 at line $FB: spike_bottom, which calls
// sfx_update. No multiplexer, no sprites. The main loop does its sfx_play calls straight after
// irq_wait_frame, in the top border (lines 16-25, no badline before line 51), so their spans
// are exact.
//
// spike_mode (1 at start):
//   1 PHASES   the fixed 80-frame cycle below. What make test measures.
//   0 SCRIPT   set by check.py through the monitor. Each frame, for each of the 4 bytes of
//              spike_cmd in order: if not 0, sfx_play with it - 1, then clear it.
//   2 STICK    entered from PHASES by any stick movement or fire. For Simon.
//   3 DISPLAY  set by measure.py. Each frame, in the display (lines 100-110, a badline at
//              107): sfx_play by each of its three paths, at a start line and cycle that
//              change every frame. Call sites spike_disp_take / _replace / _keep (+ _end).
//
// One call site per path (whole calls: from the jsr to the label after it):
//   spike_tick_idle    jsr sfx_update   nothing playing, nothing asked for      phases 41-49, 57, 69-79
//   spike_tick_slide   jsr sfx_update   three probe effects on a slide tick     phases 1-39
//   spike_tick_start3  jsr sfx_update   three effects start, one a voice        phase 0
//   spike_tick_other   jsr sfx_update   any other tick; every tick in modes 0, 2, 3
//   spike_play_take    jsr sfx_play     nothing pending on the voice            phases 0 (x 3), 50, 58
//   spike_play_replace jsr sfx_play     a request of equal priority pending     phase 50
//   spike_play_keep    jsr sfx_play     a request of higher priority pending    phase 58
// spike_bottom picks the tick's call site from spike_site, which the main loop sets each frame
// from spike_site_tab (the phases are a fixed script). The choice costs 7 (idle), 11 (slide),
// 13 (start3) or 12 (other) cycles before the jsr: that is what the spike's IRQ has over a game's.
//
// The phase cycle (spike_phase 0-79):
//    0      the three probes asked for (take x 3): the tick starts all three; spike_triple_count + 1
//    1-39   the three probes slide
//   40      the three probes end (other)
//   41-49   idle
//   50      player shot (take), enemy shot (replace: equal priority): the tick starts the enemy shot
//   51-55   it plays (other); 56 it ends (other); 57 idle
//   58      start note (take), player shot (keep: lower priority): the tick starts the start note
//   59-67   it plays (other); 68 it ends (other); 69-79 idle
//
// Labels for tests: spike_frame (the first instruction after irq_wait_frame: check.py stops
// there once a frame), spike_mode, spike_cmd (4), spike_site, spike_phase, spike_triple_count
// (2 bytes, saturating), and the call sites above.
//
// Build:   make GAME=sfx SRC_DIR=tests/engine/sfx
// Budget:  make test ARGS=sfx                       (tests/engine/sfx/budget.json)
// Model:   uv run --package budget-runner python tests/engine/sfx/check.py
// Costs:   uv run --package budget-runner python tests/engine/sfx/measure.py
// Screenshot: screenshots/sfx-spike.png

BasicUpstart2(start)

#import "zp.asm"

.const VIC_RASTER     = $d012
.const VIC_BORDER     = $d020
.const VIC_BACKGROUND = $d021
.const SCREEN         = $0400
.const COLOUR_RAM     = $d800

.const MODE_SCRIPT  = 0
.const MODE_PHASES  = 1
.const MODE_STICK   = 2
.const MODE_DISPLAY = 3

.const SITE_IDLE   = 0
.const SITE_SLIDE  = 1
.const SITE_START3 = 2
.const SITE_OTHER  = 3

.const PHASE_COUNT   = 80
.const PHASE_TRIPLE  = 0
.const PHASE_REPLACE = 50
.const PHASE_KEEP    = 58

.const SPIKE_ENTRIES   = 14             // list entries: 13 effects + the player hit's pair
.const SPIKE_ENTRY_HIT = 13
.const ROW_MODE    = 3
.const ROW_LIST    = 6
.const ROW_PLAYING = 21
.const ROW_TRIPLE  = 23
.const SPIKE_DISP_LINE = 100            // mode 3: the first of the 8 lines its calls start on

.encoding "screencode_upper"

* = $0810 "Engine"
#import "engine/irq.asm"
#import "engine/input.asm"
#import "engine/sfx.asm"

* = * "Chain"
        IrqChainBegin()
        IrqNormal($10, spike_h0)
        IrqNormal($fb, spike_bottom)
        IrqChainEnd()

* = * "Effects"
        SfxBegin()
#import "swarm_sfx.asm"
// The probes: one a voice, a single step of 40 frames with a non-zero slide. Soft triangles.
.label SFX_PROBE_0 = SfxEffect(0, 1, $00, $40, 8)
        SfxStep(40, $11, $1000, $0010)
.label SFX_PROBE_1 = SfxEffect(1, 1, $00, $40, 8)
        SfxStep(40, $11, $1400, $0010)
.label SFX_PROBE_2 = SfxEffect(2, 1, $00, $40, 8)
        SfxStep(40, $11, $1800, $0010)
        SfxEnd()

// One entry of spike_texts: where on the screen, how long, the text.
.macro SpikeText(row, col, text) {
        .word SCREEN + row * 40 + col
        .byte text.size()
        .text text
}

.function SpikePad(text, width) {
        .var t = text
        .for (var i = text.size(); i < width; i++) .eval t = t + " "
        .return t
}

// A row of the list, from the effect data itself (the module's assembly-time lists), so the
// screen can't disagree with the tables: number, name, the design's voice (1-3), priority, frames.
.macro SpikeEffectRow(i, name) {
        .var frames = 0
        .for (var s = sfx_d_first.get(i); sfx_d_frames.get(s) != 0; s++) .eval frames = frames + sfx_d_frames.get(s)
        SpikeText(ROW_LIST + i, 3, toIntString(i, 2) + " " + SpikePad(name, 17) + "  " + (sfx_d_voice.get(i) + 1) + "     " + sfx_d_prio.get(i) + "    " + toIntString(frames, 3))
}

.macro SpikeHex(value, addr) {
        lda value
        lsr
        lsr
        lsr
        lsr
        tax
        lda spike_hex_chars,x
        sta addr
        lda value
        and #$0f
        tax
        lda spike_hex_chars,x
        sta addr + 1
}

* = * "Spike"
start:
        lda #BLACK
        sta VIC_BORDER
        sta VIC_BACKGROUND
        ldx #0
!:      lda #' '
        sta SCREEN,x
        sta SCREEN + $100,x
        sta SCREEN + $200,x
        sta SCREEN + $2e8,x
        lda #LIGHT_GREY
        sta COLOUR_RAM,x
        sta COLOUR_RAM + $100,x
        sta COLOUR_RAM + $200,x
        sta COLOUR_RAM + $2e8,x
        inx
        bne !-

        // Print spike_texts.
        lda #<spike_texts
        sta zp_tmp0
        lda #>spike_texts
        sta zp_tmp1
!entry: ldy #0
        lda (zp_tmp0),y
        sta zp_tmp2
        iny
        lda (zp_tmp0),y
        sta zp_tmp3
        ora zp_tmp2
        beq !done+
        iny
        lda (zp_tmp0),y
        tax                             // length
        clc
        lda zp_tmp0
        adc #3
        sta zp_tmp0
        bcc !+
        inc zp_tmp1
!:      ldy #0
!char:  lda (zp_tmp0),y
        sta (zp_tmp2),y
        iny
        dex
        bne !char-
        tya
        clc
        adc zp_tmp0
        sta zp_tmp0
        bcc !entry-
        inc zp_tmp1
        bne !entry-
!done:
        jsr sfx_init                    // before irq_init
        jsr input_init
        jsr irq_init

spike_main:
        jsr irq_wait_frame
spike_frame:                            // check.py stops here: the last tick is over, this frame's
        jsr input_read                  // requests are not yet made
        lda zp_joy_pressed
        beq !+
        lda spike_mode
        cmp #MODE_PHASES
        bne !+
        lda #MODE_STICK                 // any movement or fire leaves the test pattern
        sta spike_mode
!:      lda #SITE_OTHER
        sta spike_site
        lda spike_mode
        bne !+
        jmp spike_script
!:      cmp #MODE_PHASES
        beq spike_phases
        cmp #MODE_STICK
        bne !+
        jmp spike_stick
!:      jmp spike_display

// ---- mode 1: the phase cycle -------------------------------------------------------------
spike_phases:
        ldx spike_phase
        lda spike_site_tab,x
        sta spike_site                  // what this frame's tick will be
        cpx #PHASE_TRIPLE
        bne !+
        lda #SFX_PROBE_0
        jsr spike_take
        lda #SFX_PROBE_1
        jsr spike_take
        lda #SFX_PROBE_2
        jsr spike_take
        inc spike_triple_count          // saturating at $FFFF
        bne !+
        inc spike_triple_count + 1
        bne !+
        dec spike_triple_count
        dec spike_triple_count + 1
!:      ldx spike_phase
        cpx #PHASE_REPLACE
        bne !+
        lda #SFX_PLAYER_SHOT
        jsr spike_take
        lda #SFX_ENEMY_SHOT             // voice 0, priority 1 again: replaces the pending shot
spike_play_replace:
        jsr sfx_play
spike_play_replace_end:
!:      ldx spike_phase
        cpx #PHASE_KEEP
        bne !+
        lda #SFX_START
        jsr spike_take
        lda #SFX_PLAYER_SHOT            // voice 0, priority 1 against a pending 3: kept
spike_play_keep:
        jsr sfx_play
spike_play_keep_end:
!:      ldx spike_phase
        inx
        cpx #PHASE_COUNT
        bcc !+
        ldx #0
!:      stx spike_phase
        jmp spike_show

// A request with nothing pending on the effect's voice. In: A = effect.
spike_take:
spike_play_take:
        jsr sfx_play
spike_play_take_end:
        rts

// ---- mode 0: commands from check.py -------------------------------------------------------
spike_script:
        ldx #0
!loop:  lda spike_cmd,x
        beq !skip+
        sec
        sbc #1
        stx spike_x
        jsr sfx_play
        ldx spike_x
        lda #0
        sta spike_cmd,x
!skip:  inx
        cpx #4
        bne !loop-
        jmp spike_show

// ---- mode 2: the stick ----------------------------------------------------------------------
spike_stick:
        lda zp_joy_pressed
        and #JOY_UP | JOY_LEFT
        beq !+
        dec spike_sel
        bpl !+
        lda #SPIKE_ENTRIES - 1
        sta spike_sel
!:      lda zp_joy_pressed
        and #JOY_DOWN | JOY_RIGHT
        beq !+
        inc spike_sel
        lda spike_sel
        cmp #SPIKE_ENTRIES
        bcc !+
        lda #0
        sta spike_sel
!:      lda zp_joy_pressed
        and #JOY_FIRE
        beq !none+
        lda spike_sel
        cmp #SPIKE_ENTRY_HIT
        bne !+
        lda #SFX_PLAYER_HIT_A           // the pair, started together as the game does
        jsr sfx_play
        lda #SFX_PLAYER_HIT_B
!:      jsr sfx_play
!none:  jmp spike_show

// ---- mode 3: sfx_play in the display, for measure.py -------------------------------------
// The three paths on voice 0, starting on line 100-107 (107 is a badline) at a cycle that
// changes with the frame, so that over 64 frames each call meets the badline at many offsets.
spike_display:
        inc spike_disp_n
        lda spike_disp_n
        and #7
        clc
        adc #SPIKE_DISP_LINE
!:      cmp VIC_RASTER
        bne !-
        lda spike_disp_n
        lsr
        lsr
        lsr
        and #7
        tax
        inx
!:      dex                             // 5 cycles a step
        bne !-
        lda #SFX_PLAYER_SHOT            // nothing pending: the last tick took it
spike_disp_take:
        jsr sfx_play
spike_disp_take_end:
        lda #SFX_ENEMY_SHOT             // equal priority pending
spike_disp_replace:
        jsr sfx_play
spike_disp_replace_end:
        lda #SFX_START                  // (priority 3 over the pending 1: replaced, unmeasured)
        jsr sfx_play
        lda #SFX_PLAYER_SHOT            // priority 1 against the pending 3
spike_disp_keep:
        jsr sfx_play
spike_disp_keep_end:

// ---- the screen: after the frame's requests ---------------------------------------------
spike_show:
        lda spike_mode
        asl
        asl
        asl
        tax
        ldy #0
!:      lda spike_mode_names,x
        sta SCREEN + ROW_MODE * 40 + 6,y
        inx
        iny
        cpy #8
        bne !-

        ldx spike_sel_shown             // the marker
        lda spike_row_lo,x
        sta zp_tmp0
        lda spike_row_hi,x
        sta zp_tmp1
        ldy #0
        lda #' '
        sta (zp_tmp0),y
        ldx spike_sel
        stx spike_sel_shown
        lda spike_row_lo,x
        sta zp_tmp0
        lda spike_row_hi,x
        sta zp_tmp1
        lda #'>'
        sta (zp_tmp0),y

        ldx #2                          // what each voice is playing (sfx_cur: the IRQ's, one byte)
!loop:  ldy spike_playing_col,x
        lda sfx_cur,x
        bne !+
        lda #'-'
        sta SCREEN + ROW_PLAYING * 40,y
        sta SCREEN + ROW_PLAYING * 40 + 1,y
        bne !next+
!:      sec
        sbc #1
        sta zp_tmp2
        lsr
        lsr
        lsr
        lsr
        stx zp_tmp3
        tax
        lda spike_hex_chars,x
        sta SCREEN + ROW_PLAYING * 40,y
        lda zp_tmp2
        and #$0f
        tax
        lda spike_hex_chars,x
        sta SCREEN + ROW_PLAYING * 40 + 1,y
        ldx zp_tmp3
!next:  dex
        bpl !loop-

        SpikeHex(spike_triple_count + 1, SCREEN + ROW_TRIPLE * 40 + 22)
        SpikeHex(spike_triple_count, SCREEN + ROW_TRIPLE * 40 + 24)
        jmp spike_main

// ---- IRQ handlers -----------------------------------------------------------------------------
spike_h0:
        IrqDone()

// The sound tick, line $FB. One call site per kind of tick; the main loop says which.
// TIMING: the choice costs 7 / 11 / 13 / 12 cycles (idle / slide / start3 / other) before the jsr.
spike_bottom:
        lda spike_site                  // 4
        beq spike_tick_idle             // 2 / 3
        cmp #SITE_START3                // 2
        bcc spike_tick_slide            // 2 / 3
        beq spike_tick_start3           // 2 / 3
spike_tick_other:
        jsr sfx_update
spike_tick_other_end:
        IrqDone()
spike_tick_idle:
        jsr sfx_update
spike_tick_idle_end:
        IrqDone()
spike_tick_slide:
        jsr sfx_update
spike_tick_slide_end:
        IrqDone()
spike_tick_start3:
        jsr sfx_update
spike_tick_start3_end:
        IrqDone()

// ---- data ---------------------------------------------------------------------------------------
spike_mode:         .byte MODE_PHASES
spike_cmd:          .byte 0, 0, 0, 0    // mode 0: effect + 1, or 0
spike_site:         .byte SITE_OTHER    // main loop writes, the IRQ reads: one byte
spike_phase:        .byte 0
spike_triple_count: .word 0
spike_sel:          .byte 0
spike_sel_shown:    .byte 0
spike_disp_n:       .byte 0
spike_x:            .byte 0

spike_site_tab:
        .for (var f = 0; f < PHASE_COUNT; f++) {
            .var site = SITE_IDLE
            .if (f == 0) .eval site = SITE_START3
            .if (f >= 1 && f <= 39) .eval site = SITE_SLIDE
            .if (f == 40) .eval site = SITE_OTHER
            .if (f >= 50 && f <= 56) .eval site = SITE_OTHER
            .if (f >= 58 && f <= 68) .eval site = SITE_OTHER
            .byte site
        }

spike_row_lo:
        .for (var i = 0; i < SPIKE_ENTRIES; i++) .byte <(SCREEN + (ROW_LIST + i) * 40 + 1)
spike_row_hi:
        .for (var i = 0; i < SPIKE_ENTRIES; i++) .byte >(SCREEN + (ROW_LIST + i) * 40 + 1)
spike_playing_col:
        .byte 17, 23, 29
spike_hex_chars:
        .text "0123456789ABCDEF"
spike_mode_names:
        .text "SCRIPT  "
        .text "PHASES  "
        .text "STICK   "
        .text "DISPLAY "

spike_texts:
        SpikeText(0, 1, "ENGINE/SFX.ASM   JOYSTICK IN PORT 2")
        SpikeText(1, 1, "UP/DOWN: CHOOSE AN EFFECT  FIRE: PLAY")
        SpikeText(ROW_MODE, 0, "MODE:")
        SpikeText(ROW_LIST - 1, 3, "NO EFFECT          VOICE PRIO FRAMES")
        SpikeEffectRow(SFX_PLAYER_SHOT, "PLAYER SHOT")
        SpikeEffectRow(SFX_ENEMY_SHOT, "ENEMY SHOT")
        SpikeEffectRow(SFX_DIVE, "DIVE")
        SpikeEffectRow(SFX_ENEMY_EXPLOSION, "ENEMY EXPLOSION")
        SpikeEffectRow(SFX_PLAYER_HIT_A, "PLAYER HIT A")
        SpikeEffectRow(SFX_PLAYER_HIT_B, "PLAYER HIT B")
        SpikeEffectRow(SFX_WAVE_START, "WAVE START")
        SpikeEffectRow(SFX_WAVE_CLEAR, "WAVE CLEAR")
        SpikeEffectRow(SFX_START, "START")
        SpikeEffectRow(SFX_GAME_OVER, "GAME OVER")
        SpikeEffectRow(SFX_PROBE_0, "PROBE 1")
        SpikeEffectRow(SFX_PROBE_1, "PROBE 2")
        SpikeEffectRow(SFX_PROBE_2, "PROBE 3")
        SpikeText(ROW_LIST + SPIKE_ENTRY_HIT, 3, "13 PLAYER HIT A+B    2+3    3     60")
        SpikeText(ROW_PLAYING, 0, "PLAYING  VOICE 1 --  2 --  3 --")
        SpikeText(ROW_TRIPLE, 0, "THREE-START TICKS    $")
        .word 0
