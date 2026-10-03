// Swarm: the title screen (design.md "Title and game-over screens", "Stage 4 rules" 9-12;
// memory-map.md "Stage 4" (c) and (d)). Game state GAME_STATE_TITLE: the play routines don't run
// (main.asm), only input_read, panel_update, stars_update, title_update and mux_update.
//
// The title's frames are counted in zp_state_timer, which WRAPS here (the blink reads it mod 64).
// Frame 0 is the frame the title is entered in (title_enter: at power-on, before the first frame;
// otherwise GameOver's last frame + 1). title_step says what the title is doing:
//   0-7    being drawn: title_step = the frame number. Frame 0: every sprite hidden, row 9's
//          message erased, the three title enemies placed, PRESS FIRE written (the blink's first
//          "on"). Frames 1-5: one more text a frame. Fire is not read
//   8      waiting (from frame 8 on): fire is read; PRESS FIRE is written when the frame count
//          mod 64 is 0 and erased when it is 32
//   9-14   after the press: the six texts erased, one a frame (the first in the press's frame)
//   15     the new game (game_new), in the frame after the last erase: Intro's frame 0
// A NEW PRESS is fire down in this frame and up in the frame before (zp_joy_pressed): a button
// held since GameOver, or since power-on, starts nothing until it is let go.
// RANDOM NUMBERS: rng_next once in every title frame up to the press, result unused; in the
// press's frame the generator is seeded from its own state mixed with zp_irq_frame and the
// raster line. Nothing else reseeds. (The budget build has no title and keeps the constant seed.)
// The title never draws more than one text in a frame: at most 20 cells.

.const TITLE_STEP_WAIT  = 8             // the first frame fire is read in (Stage 4 rule 9)
.const TITLE_STEP_ERASE = 9
.const TITLE_STEP_NEW   = TITLE_STEP_ERASE + TITLE_TEXTS
.const TITLE_SPRITE_X   = 120           // the three title enemies: X 120, Y 115 / 139 / 163,
.const TITLE_SPRITE_Y   = 115           // beside rows 9, 12 and 15's scores: Y = 43 + 8 x the row,
.const TITLE_SPRITE_DY  = 24            // so the art is centred on the letters and 24 lines apart
.const TITLE_BLINK      = 32            // PRESS FIRE: on for 32 frames, off for 32

// Enter the title: its frame 0. Every sprite hidden, row 9's message erased, the three title
// enemies (types A, B, C on the first enemy sprite of each row: 6, 12, 18) in their colours and
// first shapes, PRESS FIRE written. The panel is left as it is. Called at power-on (before
// irq_init) and when GameOver ends.
// In:  nothing       Out: zp_game_state = Title, zp_state_timer = 0
// Uses: A, X, Y, zp_tmp4-5
// Cost: about 600 cycles (counted: 150 the sprites, 130 the row, 90 the three enemies, 220 the
//       text). Measured as game_update for the frame GameOver ends in: 965 raster cycles, 12,784
//       idle (tests/games/swarm/stage4_costs.txt, item 5; a one-off frame: limit 4,000)
title_enter:
        lda #GAME_STATE_TITLE
        sta zp_game_state
        lda #0
        sta zp_state_timer
        sta title_step
        ldx #MUX_COUNT - 1
        lda #MUX_OFF
!:      sta mux_y,x
        dex
        bpl !-
        ldx #TEXT_GAME_OVER             // row 9: the widest message's cells
        jsr game_text_erase
        .for (var r = 0; r < FORM_ROWS; r++) {
                .var spr = SPR_ENEMY + r * FORM_COLS
                lda #<TITLE_SPRITE_X
                sta mux_x_lo + spr
                lda #>TITLE_SPRITE_X
                sta mux_x_hi + spr
                lda #TITLE_SPRITE_Y + r * TITLE_SPRITE_DY
                sta mux_y + spr
                lda colour_table + COL_ENEMY_A + r
                sta mux_col + spr
                lda #SHAPE_ENEMY + r * 2
                sta mux_ptr + spr
        }
        ldx #TEXT_PRESS_FIRE
        jmp game_text_draw

// A frame of the title (every frame after the one it was entered in). No sound is asked for
// at the title except the start sound, in the frame of the press.
// In:  zp_joy_pressed, title_step, zp_state_timer
// Out: texts drawn or erased, the three sprites' shapes, the generator stepped or seeded, a new game
// Uses: A, X, Y, zp_tmp4-5
// Cost: about 95 cycles in a steady frame (counted: 42 of it rng_next); + up to 390 in a frame
//       that draws a text, + 60 on a shape swap; the new game's frame is game_new's. Measured as
//       game_update for a title frame (stage4_costs.txt, item 5): 250-263 steady, 282 on a shape
//       swap, 387-608 drawing a text, 415-476 on a blink, 446 in the press's frame; mux_update
//       1,067 with the three sprites; at least 16,000 cycles idle. The $D012 read at the press
//       is on raster line 26 or 27 (it falls within a few cycles of the boundary)
title_update:
        inc zp_state_timer              // wraps: the blink and the shapes read it
        lda title_step
        cmp #TITLE_STEP_ERASE
        bcs !erase+
        jsr rng_next                    // once every title frame, result unused: the generator's
                                        // state at the press depends on how long the title was up
        lda zp_state_timer              // the shapes swap every 16 frames, all three together
        and #ENEMY_ANIM_FRAMES - 1
        bne !+
        lda zp_state_timer
        lsr
        lsr
        lsr
        lsr
        and #1
        clc
        adc #SHAPE_ENEMY                // no carry out of any of these
        sta mux_ptr + SPR_ENEMY
        adc #2
        sta mux_ptr + SPR_ENEMY + FORM_COLS
        adc #2
        sta mux_ptr + SPR_ENEMY + 2 * FORM_COLS
!:      ldx title_step
        cpx #TITLE_STEP_WAIT
        bcs !wait+
        inx                             // being drawn: this frame's number, 1-8
        stx title_step
        cpx #TITLE_TEXTS
        bcc !draw+                      // frames 1-5: texts 1-5
        cpx #TITLE_STEP_WAIT
        bcc !out+                       // frames 6 and 7: nothing
!wait:  lda zp_joy_pressed              // from frame 8: a NEW press of fire starts a game
        and #JOY_FIRE
        bne !press+
        lda zp_state_timer              // PRESS FIRE: on when the frame count mod 64 is 0-31
        and #2 * TITLE_BLINK - 1
        beq !show+
        cmp #TITLE_BLINK
        bne !out+
        ldx #TEXT_PRESS_FIRE
        jmp game_text_erase
!show:  ldx #TEXT_PRESS_FIRE
!draw:  jmp game_text_draw
!out:   rts

        // The press: seed the generator (memory-map.md "Stage 4" (d)), take the three sprites
        // away, and start erasing: the first text in this frame.
!press: lda VIC_RASTER
        eor zp_rng_hi
        tax
        lda zp_irq_frame                // has run since power-on; never zeroed
        eor zp_rng_lo
        jsr rng_seed                    // A = low, X = high; it replaces 0/0 itself
        lda #SFX_START                  // the start sound (voice 1, priority 3). In the border;
        jsr sfx_play                    // nothing is pending: 36 cycles. A, X, Y are free here
        lda #MUX_OFF
        sta mux_y + SPR_ENEMY
        sta mux_y + SPR_ENEMY + FORM_COLS
        sta mux_y + SPR_ENEMY + 2 * FORM_COLS
        lda #TITLE_STEP_ERASE
        sta title_step
!erase: sec
        sbc #TITLE_STEP_ERASE           // the text to erase, 0-5
        cmp #TITLE_TEXTS
        bcs !new+
        tax
        inc title_step
        jmp game_text_erase
!new:   jmp game_new                    // all in this frame, which is Intro's frame 0 of wave 1
.errorif (ENEMY_ANIM_FRAMES & (ENEMY_ANIM_FRAMES - 1)) != 0 || ENEMY_ANIM_FRAMES != 16, "title_update takes the shape from bit 4 of the frame count"
.errorif TITLE_TEXTS > TITLE_STEP_WAIT, "the title's texts must be drawn before fire is read"
.errorif SHAPE_ENEMY + 5 > 255, "title_update's shape sums must not carry"

title_step:     .byte 0         // what the title is doing: see the top of the file
