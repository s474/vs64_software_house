// Swarm: game tables, $3800-$3FFF (docs/games/swarm/memory-map.md#game-tables). Imported by
// main.asm at GAME_TABLES. Only colour_table's address is fixed; the rest follow in the memory
// map's order and are found by label. So far: colours, stars, custom glyphs, collision pairs,
// the formation's tables, scores, explosion shapes, strings.

// ------------------------------------------------------------------------------------------
// Colours. EVERY colour the game writes comes from here, indexed by a COL_* constant
// (consts.asm): the code's copy of design.md#colours. Change a colour here (or poke $3800 + index
// from the monitor during art review) and nowhere else.
colour_table:
        .byte BLACK             //  0 COL_BORDER
        .byte BLACK             //  1 COL_BACKGROUND
        .byte BLUE              //  2 COL_PANEL_BG
        .byte CYAN              //  3 COL_PLAYER
        .byte CYAN              //  4 COL_PLAYER_SHOT
        .byte PURPLE            //  5 COL_ENEMY_A (row 0)
        .byte YELLOW            //  6 COL_ENEMY_B (row 1)
        .byte LIGHT_GREEN       //  7 COL_ENEMY_C (row 2)
        .byte WHITE             //  8 COL_WINDUP_FLASH
        .byte LIGHT_RED         //  9 COL_ENEMY_SHOT
        .byte ORANGE            // 10 COL_ENEMY_EXPLODE
        .byte WHITE             // 11 COL_PLAYER_EXPLODE
        .byte DARK_GREY         // 12 COL_RESPAWN_ALT
        .byte WHITE             // 13 COL_PANEL_TEXT (ship markers too)
        .byte WHITE             // 14 COL_MESSAGE_TEXT
        .byte WHITE             // 15 COL_STAR_0
        .byte LIGHT_GREY        // 16 COL_STAR_1
        .byte GREY              // 17 COL_STAR_2
        .byte DARK_GREY         // 18 COL_STAR_3
.errorif * - colour_table != COL_TABLE_USED, "colour_table: COL_TABLE_USED entries expected"
        .fill COL_TABLE_SIZE - COL_TABLE_USED, 0        // 19-31 spare
.errorif colour_table != GAME_TABLES, "colour_table must be at the start of the game tables ($3800)"

// ------------------------------------------------------------------------------------------
// Stars: 48 fixed cells in rows 0-23, generated at assembly time from a fixed seed, so every
// build has the same sky. The band rule (design.md "Text cells and the star rule"): no star in
// columns 10-29 of rows 5, 9, 11, 12, 13, 16 and 19, and no two stars in one cell. The generator
// rejects such cells and draws again; the checks below run over the finished lists, so an edited
// generator or a hand-made list can't break the rule silently.
// Generator: the Lehmer sequence seed = (seed * 75 + 74) mod 65537 (exact in KickAssembler's
// arithmetic); cell = seed mod 960, glyph = the next value's bit 3.
.const STAR_SEED = 4711
.var star_band_rows = Hashtable()
.for (var r = 0; r < 7; r++) .eval star_band_rows.put(List().add(5, 9, 11, 12, 13, 16, 19).get(r), true)

.function StarCellAllowed(cell) {
        .var row = floor(cell / SCREEN_COLS)
        .var col = mod(cell, SCREEN_COLS)
        .if (cell < 0 || cell >= PLAY_CELLS) .return false
        .if (star_band_rows.containsKey(row) && col >= STAR_BAND_COL_MIN && col <= STAR_BAND_COL_MAX) .return false
        .return true
}

.var star_cells  = List()
.var star_glyphs = List()
.var star_used   = Hashtable()
.var star_rand   = STAR_SEED
.for (var n = 0; n < 1000; n++) {
        .if (star_cells.size() < STAR_COUNT) {
                .eval star_rand = mod(star_rand * 75 + 74, 65537)
                .var cell = mod(star_rand, PLAY_CELLS)
                .eval star_rand = mod(star_rand * 75 + 74, 65537)
                .if (StarCellAllowed(cell) && !star_used.containsKey(cell)) {
                        .eval star_used.put(cell, true)
                        .eval star_cells.add(cell)
                        .eval star_glyphs.add((star_rand & 8) == 0 ? GLYPH_STAR_HI : GLYPH_STAR_LO)
                }
        }
}
// The checks: 48 stars, every one in an allowed cell of rows 0-23, no cell twice.
.errorif star_cells.size() != STAR_COUNT, "star table: STAR_COUNT stars expected"
.var star_check = Hashtable()
.for (var i = 0; i < star_cells.size(); i++) {
        .errorif !StarCellAllowed(star_cells.get(i)), "star table: star " + i + " is outside rows 0-23 or inside a text band"
        .errorif star_check.containsKey(star_cells.get(i)), "star table: two stars in cell " + star_cells.get(i)
        .eval star_check.put(star_cells.get(i), true)
}

// Indexed by star number 0-47. star_lo / star_hi: the cell's offset from the start of the screen
// (row * 40 + column, 0-959). star_glyph: GLYPH_STAR_HI or GLYPH_STAR_LO.
star_lo:        .fill STAR_COUNT, <star_cells.get(i)
star_hi:        .fill STAR_COUNT, >star_cells.get(i)
star_glyph:     .fill STAR_COUNT, star_glyphs.get(i)

// ------------------------------------------------------------------------------------------
// Custom glyphs: 3 x 8 bytes copied to the charset at codes 27-29 after the ROM copy.
.errorif GLYPH_STAR_LO != GLYPH_STAR_HI + 1 || GLYPH_SHIP != GLYPH_STAR_HI + 2, "glyph_data is one patch: the three codes must be adjacent"
glyph_data:
        // GLYPH_STAR_HI: one pixel, high in the cell
        .byte %00000000
        .byte %00000000
        .byte %00010000
        .byte %00000000
        .byte %00000000
        .byte %00000000
        .byte %00000000
        .byte %00000000
        // GLYPH_STAR_LO: one pixel, low in the cell
        .byte %00000000
        .byte %00000000
        .byte %00000000
        .byte %00000000
        .byte %00000000
        .byte %00000100
        .byte %00000000
        .byte %00000000
        // GLYPH_SHIP: the spare-ship marker in the panel
        .byte %00000000
        .byte %00011000
        .byte %00011000
        .byte %00111100
        .byte %01111110
        .byte %11111111
        .byte %11011011
        .byte %00000000
glyph_data_end:
.const GLYPH_DATA_SIZE = glyph_data_end - glyph_data
.errorif GLYPH_DATA_SIZE != 24, "glyph_data is 3 glyphs"

// ------------------------------------------------------------------------------------------
// Collision pairs (engine/collision.md): one ColPair row per pair of kinds, A's box then B's, in
// the contract's order (COL_PAIR_* in consts.asm). The boxes are consts.asm's BOX_*, the design's
// hit-box table. Pairs 1 and 2 are the player's scans: stage 3 (collide.asm).
col_pairs:
        ColPair(BOX_PSHOT_X0, BOX_PSHOT_X1, BOX_PSHOT_Y0, BOX_PSHOT_Y1,     BOX_ENEMY_X0, BOX_ENEMY_X1, BOX_ENEMY_Y0, BOX_ENEMY_Y1)  // 0: player shot against enemy
        ColPair(BOX_PLAYER_X0, BOX_PLAYER_X1, BOX_PLAYER_Y0, BOX_PLAYER_Y1, BOX_ESHOT_X0, BOX_ESHOT_X1, BOX_ESHOT_Y0, BOX_ESHOT_Y1)  // 1: player against enemy shot
        ColPair(BOX_PLAYER_X0, BOX_PLAYER_X1, BOX_PLAYER_Y0, BOX_PLAYER_Y1, BOX_ENEMY_X0, BOX_ENEMY_X1, BOX_ENEMY_Y0, BOX_ENEMY_Y1)  // 2: player against enemy
.errorif * - col_pairs != 12, "col_pairs: 3 pairs of 4 bytes (memory-map.md#game-tables)"

// ------------------------------------------------------------------------------------------
// The formation (design.md "The formation"; formation.asm).
// Column X with fx = 0, and row Y: the design's "one table" each. formation_update's unrolled code
// takes the same FORM_* constants as immediates, so a change is made in consts.asm, not by a poke.
formation_col_x:        .fill FORM_COLS, FORM_X0 + FORM_COL_DX * i      // 34, 70, 106, 142, 178, 214
formation_row_y:        .fill FORM_ROWS, FORM_ROW_Y0 + FORM_ROW_DY * i  // 56, 96, 136
// Frames between 1-pixel drift steps, by loop 0-3 (design "What faster means": 1 px / 2 frames,
// 1 px / frame from loop 2).
formation_drift_period: .byte 2, 2, 1, 1
.errorif * - formation_drift_period != GAME_LOOP_MAX + 1, "formation_drift_period: one entry per loop"
// Each enemy's row (its type, colour, score and path) and column, by enemy index 0-17.
enemy_row:              .fill ENEMY_COUNT, floor(i / FORM_COLS)
enemy_col:              .fill ENEMY_COUNT, mod(i, FORM_COLS)

// Scores (design.md "Scoring"), BCD, by row 0-2 (types A, B, C): parked 150 / 80 / 50, then the
// diving values (WindUp, Dive, Return: state bit 7 set) 300 / 160 / 100 at index row + 3.
.const SCORE_DIVING = FORM_ROWS         // index offset of the diving values
score_lo:               .byte $50, $80, $50,  $00, $60, $00
score_hi:               .byte $01, $00, $00,  $03, $01, $01
// An exploding enemy's shape by its enemy_timer (frames left, 15 down to 1; the hit's own frame
// shows the first shape with the timer at 16): 4 frames each, 16 frames in all.
explosion_shape:        .fill EXPLOSION_FRAMES + 1, SHAPE_EXPLOSION + EXPLOSION_SHAPES - 1 - floor((max(i, 1) - 1) / EXPLOSION_SHAPE_FRAMES)

// The respawned ship's colour by its invulnerability timer after the frame's countdown (149 down
// to 0), as a colour_table index: dark grey while bit 2 of the timer is set, cyan otherwise, so 4
// frames each and cyan when the timer runs out (design.md "Colours", Stage 3 rule 10). A table of
// indices, not colours: the colours themselves live only in colour_table.
player_flash:           .fill PLAYER_INVULN_FRAMES + 1, ((i & 4) != 0) ? COL_RESPAWN_ALT : COL_PLAYER

// Enemy shots: Y step a frame by loop 0-3 (design "What faster means").
eshot_dy:               .byte 2, 2, 3, 3
.errorif * - eshot_dy != GAME_LOOP_MAX + 1, "eshot_dy: one entry per loop"

// ------------------------------------------------------------------------------------------
// Strings. Stored as glyph codes 0-63 and written to the play area as they are; the panel
// routine adds PANEL_BG. GameText() is the only way a text gets into the tables: it accepts
// capitals, digits, the space and the ROM's punctuation, and stops the build on anything else
// (lower case, a graphics character, or one of the three codes the custom glyphs took).
.const GLYPH_OF_CHAR = @"@ABCDEFGHIJKLMNOPQRSTUVWXYZ~~~~~ !\"#$%&'()*+,-./0123456789:;<=>?"    // index = screen code; ~ = not for text
.errorif GLYPH_OF_CHAR.size() != 64, "GLYPH_OF_CHAR has one character per screen code 0-63"

.function GlyphCode(ch) {
        .for (var i = 0; i < 64; i++) {
                .if (GLYPH_OF_CHAR.charAt(i) == ch && ch != '~') .return i
        }
        .return -1
}

.macro GameText(text) {
        .for (var i = 0; i < text.size(); i++) {
                .errorif GlyphCode(text.charAt(i)) < 0 || GlyphCode(text.charAt(i)) > 63, "GameText: '" + text + "' has a character outside the 64-glyph set"
                .byte GlyphCode(text.charAt(i))
        }
}

// The panel as first drawn, all 40 columns (design.md#screen-layout): SCORE 1-5, digits 7-12;
// HI 15-16, digits 18-23; WAVE 26-29, digits 31-32; spare ships 35-37. The digit and ship cells
// are spaces here: panel_update fills them.
panel_template:
        //        0         1         2         3
        //        0123456789012345678901234567890123456789
        GameText(" SCORE         HI         WAVE          ")
.errorif * - panel_template != SCREEN_COLS, "panel_template is 40 cells"

// Messages on row 12, centred (design.md "Text cells and the star rule"): first column
// (40 - length) div 2, all inside the star-free band (columns 10-29).
.const TEXT_READY_LEN     = 5
.const TEXT_READY_COL     = floor((SCREEN_COLS - TEXT_READY_LEN) / 2)   // 17
.const TEXT_GAME_OVER_LEN = 9
.const TEXT_GAME_OVER_COL = floor((SCREEN_COLS - TEXT_GAME_OVER_LEN) / 2)       // 15
text_ready:     GameText("READY")
.errorif * - text_ready != TEXT_READY_LEN, "text_ready's length"
text_game_over: GameText("GAME OVER")
.errorif * - text_game_over != TEXT_GAME_OVER_LEN, "text_game_over's length"
.errorif TEXT_READY_COL != 17 || TEXT_GAME_OVER_COL != 15, "design: READY at columns 17-21, GAME OVER at 15-23"
.errorif TEXT_GAME_OVER_COL < STAR_BAND_COL_MIN || TEXT_GAME_OVER_COL + TEXT_GAME_OVER_LEN - 1 > STAR_BAND_COL_MAX, "messages must stay inside the star-free band"
