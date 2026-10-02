// Swarm: the character set and the screen (init only: nothing here runs per frame).
// docs/games/swarm/memory-map.md "Configuration", "The panel", "Character set".

// Build the 64-glyph character set at CHARSET: copy the character ROM's codes 0-63 (upper case
// set, ROM $D000-$D1FF), then patch codes 27-29 with glyph_data (star high, star low, ship).
// MUST run before irq_init: it sets I and writes $01 ($33 to see the ROM, then back to $37),
// which nothing may do once the engine's IRQs run. Returns with I still set; irq_init enables
// interrupts.
// In:  nothing       Out: I set, $01 = $37
// Uses: A, X
// Cost: init only, about 9,300 cycles (counted)
screen_charset_init:
        sei
        lda #$33                        // character ROM at $D000, no I/O
        sta CPU_PORT
        ldx #0
!:      lda CHAR_ROM,x
        sta CHARSET,x
        lda CHAR_ROM + $100,x
        sta CHARSET + $100,x
        inx
        bne !-
        lda #$37                        // I/O back (the value BASIC started us with)
        sta CPU_PORT
        ldx #GLYPH_DATA_SIZE - 1
!:      lda glyph_data,x
        sta CHARSET + GLYPH_STAR_HI * 8,x
        dex
        bpl !-
        rts
.errorif CHARSET_SIZE != $200, "screen_charset_init copies exactly two pages"

// Set the VIC-II up for the game and clear the play area: black border and background, the
// panel's blue in ECM background 1, extended colour mode, charset at CHARSET, no sprite
// expansion. Play-area cells become spaces with colour RAM at the message text colour, so a text
// is written later with screen writes only. The panel row is panel_init's, the stars stars_init's.
// $D011 is written here once and never again (bit 7 clear, YSCROLL 3).
// In:  nothing       Out: nothing
// Uses: A, X
// Cost: init only
screen_init:
        lda colour_table + COL_BORDER
        sta VIC_BORDER
        lda colour_table + COL_BACKGROUND
        sta VIC_BACKGROUND
        lda colour_table + COL_PANEL_BG
        sta VIC_BG1
        lda #0
        sta VIC_SPR_YEXP                // engine v1: no sprite expansion
        sta VIC_SPR_XEXP
        sta VIC_SPR_PRIO                // sprites in front of characters

        ldx #0
!:      lda #GLYPH_SPACE
        sta SCREEN,x
        sta SCREEN + $100,x
        sta SCREEN + $200,x
        sta SCREEN + PLAY_CELLS - $100,x
        lda colour_table + COL_MESSAGE_TEXT
        sta COLOUR_RAM,x
        sta COLOUR_RAM + $100,x
        sta COLOUR_RAM + $200,x
        sta COLOUR_RAM + PLAY_CELLS - $100,x
        inx
        bne !-

        lda #VIC_MEMORY_INIT
        sta VIC_MEMORY
        lda #VIC_CTRL2_INIT
        sta VIC_CTRL2
        lda #VIC_CTRL1_INIT
        sta VIC_CTRL1
        rts
.errorif (VIC_CTRL1_INIT & $80) != 0, "$D011 bit 7 must stay clear (IRQ framework)"
