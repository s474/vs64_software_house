// Swarm: the status panel, text row 24 (design.md#screen-layout, memory-map.md#the-panel).
// White text on a blue bar: extended colour mode, so every screen code stored here is the
// glyph's code + PANEL_BG, blanks included (a plain space would be a black hole in the bar).
// Nothing else in the game adds PANEL_BG, and nothing else writes row 24.
//
// The values shown are the game's own variables, declared at the end of this file: game_score
// and game_hiscore (BCD), zp_wave (BCD) and zp_lives. Whoever changes one sets its PANEL_DIRTY_*
// bit in panel_dirty; panel_update redraws the fields whose bits are set and clears them.

.const PANEL_DIRTY_SCORE = $01
.const PANEL_DIRTY_LIVES = $02
.const PANEL_DIRTY_WAVE  = $04
.const PANEL_DIRTY_HI    = $08
.const PANEL_DIRTY_ALL   = $0f
.const PANEL_DIRTY_PLAY  = PANEL_DIRTY_SCORE | PANEL_DIRTY_LIVES | PANEL_DIRTY_WAVE     // the most that changes in one frame of play

.const PANEL_DIGIT = GLYPH_ZERO + PANEL_BG      // OR a BCD digit in: 0-9 only touch the low nibble
.errorif (PANEL_DIGIT & $0f) != 0, "PanelDigits ORs the digit into the code for '0'"

// Two digits from one BCD byte to two panel cells. 30 cycles.
.macro PanelDigits(value, column) {
        lda value                       // 3-4
        lsr                             // 2
        lsr                             // 2
        lsr                             // 2
        lsr                             // 2
        ora #PANEL_DIGIT                // 2
        sta PANEL + column              // 4
        lda value                       // 3-4
        and #$0f                        // 2
        ora #PANEL_DIGIT                // 2
        sta PANEL + column + 1          // 4
}

// Write all 40 cells of the panel (the template's text and spaces, + PANEL_BG) and their colour,
// reset the score, the high score, the wave and the lives, and draw the values.
// In:  nothing       Out: panel_dirty = 0
// Uses: A, X, zp_tmp0
// Cost: init only
panel_init:
        ldx #SCREEN_COLS - 1
!:      lda panel_template,x
        ora #PANEL_BG
        sta PANEL,x
        lda colour_table + COL_PANEL_TEXT
        sta PANEL_COLOUR,x
        dex
        bpl !-
        lda #0
        sta game_score
        sta game_score + 1
        sta game_score + 2
        lda #<(HISCORE_START >> 16)
        sta game_hiscore
        lda #<(HISCORE_START >> 8)
        sta game_hiscore + 1
        lda #<HISCORE_START
        sta game_hiscore + 2
        lda #PLAYER_LIVES
        sta zp_lives
        lda #$01
        sta zp_wave
        lda #PANEL_DIRTY_ALL
        sta panel_dirty
        // falls through: draw every field

// Redraw the panel fields whose PANEL_DIRTY_* bits are set in panel_dirty, and clear the bits.
// In:  panel_dirty   Out: panel_dirty = 0
// Uses: A, X, zp_tmp0
// Cost: to panel_update_end, raster cycles: 9 with nothing dirty (measured, vice_profile, the usual
//       frame); 231 with score + lives + wave dirty, the most one frame of play can ask for
//       (measured: make test ARGS=swarm, 300 passes, AUTOPLAY sets the three every frame; budget
//       250); about 325 with the high score as well (counted: + 3 x 30 + 4), which happens only
//       at init and when a game ends, never in a frame of play. Runs in the top border: no DMA
panel_update:
        lda panel_dirty                 // 4
        bne !+                          // 2 not taken: nothing to do, the usual frame
        jmp panel_update_end            // 3
!:      lsr panel_dirty                 // 6  bit 0: score
        bcc !+
        PanelDigits(game_score, PANEL_COL_SCORE)
        PanelDigits(game_score + 1, PANEL_COL_SCORE + 2)
        PanelDigits(game_score + 2, PANEL_COL_SCORE + 4)
!:      lsr panel_dirty                 // bit 1: lives. Spare ships = lives - 1, one marker each
        bcc !nolives+
        ldx zp_lives
        beq !+                          // no lives: no markers
        dex
!:      stx zp_tmp0
        ldx #PANEL_SHIPS_MAX - 1
!ship:  lda #GLYPH_SPACE + PANEL_BG
        cpx zp_tmp0
        bcs !+
        lda #GLYPH_SHIP + PANEL_BG
!:      sta PANEL + PANEL_COL_SHIPS,x
        dex
        bpl !ship-
!nolives:
        lsr panel_dirty                 // bit 2: wave
        bcc !+
        PanelDigits(zp_wave, PANEL_COL_WAVE)
!:      lsr panel_dirty                 // bit 3: high score (changes only when a game ends)
        bcc !+
        PanelDigits(game_hiscore, PANEL_COL_HI)
        PanelDigits(game_hiscore + 1, PANEL_COL_HI + 2)
        PanelDigits(game_hiscore + 2, PANEL_COL_HI + 4)
!:      lda #0
        sta panel_dirty
panel_update_end:
        rts

// Six BCD digits each, most significant byte first: $00 $12 $50 shows 001250.
game_score:     .byte 0, 0, 0
game_hiscore:   .byte 0, 0, 0
panel_dirty:    .byte 0                 // PANEL_DIRTY_* bits: fields panel_update must redraw
