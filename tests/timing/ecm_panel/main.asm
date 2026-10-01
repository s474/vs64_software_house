// ecm_panel: can a one-row status panel have WHITE text on a BLUE bar with no raster split?
//
// Backs docs/games/swarm/memory-map.md ("The panel"). Two pictures from one program:
//   1. As started: extended colour mode (ECM, $D011 bit 6). Row 24 holds screen codes $40 + c, which
//      select background 1 ($D022 = blue) with the glyph of code c; colour RAM gives white text.
//      Rows 0-23 use codes 0-63 (background 0, $D021 = black).
//   2. After writing $1B to $D011 (ECM off) from the monitor: row 22 holds reverse-video codes
//      ($80 + c) in blue. The bar is blue and the glyph is the background colour: black text.
//
// Build: make GAME=ecm_panel SRC_DIR=tests/timing/ecm_panel
// Run:   vice_start build/ecm_panel/ecm_panel.prg, vice_run_frames 20, vice_screenshot;
//        then vice_write_memory $d011 = $1b, vice_run_frames 2, vice_screenshot.
// No IRQs: the program sets the screen up and stops in a loop.

.encoding "screencode_upper"
.const SCREEN = $0400
.const COLOUR = $d800

BasicUpstart2(start)

start:  sei
        lda #BLACK
        sta $d020
        sta $d021               // background 0: play area
        sta $d023               // background 2: what a reverse-video code selects under ECM
        lda #BLUE
        sta $d022               // background 1: the panel
        ldx #0
!:      lda #$20                // spaces, white
        sta SCREEN,x
        sta SCREEN + $100,x
        sta SCREEN + $200,x
        sta SCREEN + $2e8,x
        lda #WHITE
        sta COLOUR,x
        sta COLOUR + $100,x
        sta COLOUR + $200,x
        sta COLOUR + $2e8,x
        inx
        bne !-
        ldx #39
!:      lda panel,x             // row 24: ECM background 1
        ora #$40
        sta SCREEN + 24 * 40,x
        lda panel,x             // row 22: reverse video, blue (for the ECM-off picture)
        ora #$80
        sta SCREEN + 22 * 40,x
        lda #BLUE
        sta COLOUR + 22 * 40,x
        dex
        bpl !-
        ldx #6
!:      lda message,x           // row 12: plain text, and two stars
        sta SCREEN + 12 * 40 + 16,x
        dex
        bpl !-
        lda #$2e
        sta SCREEN + 3 * 40 + 5
        sta SCREEN + 8 * 40 + 30
        lda #$5b                // ECM on, screen on, 25 rows, YSCROLL 3, raster compare bit 8 clear
        sta $d011
        jmp *

panel:   .text " SCORE 000150  HI 005000  WAVE 01  AAA  "
message: .text "WAVE 01"
