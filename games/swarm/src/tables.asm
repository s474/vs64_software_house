// Swarm: game tables, $3800-$3FFF (docs/games/swarm/memory-map.md#game-tables). Imported by
// main.asm at GAME_TABLES. Only colour_table's address is fixed; the rest follow in the memory
// map's order and are found by label. So far: colours, stars, custom glyphs, collision pairs,
// the formation's tables, scores, explosion shapes, the respawn flash, dive paths, fire steps,
// wave tables, strings (the panel's template and the play-area texts).

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
// columns 10-29 of rows 5, 9, 12, 15, 18 and 21 (the six text rows: the title's layout of
// 2026-10-02, every third row from 9), and no two stars in one cell. The generator
// rejects such cells and draws again; the checks below run over the finished lists, so an edited
// generator or a hand-made list can't break the rule silently.
// Generator: the Lehmer sequence seed = (seed * 75 + 74) mod 65537 (exact in KickAssembler's
// arithmetic); cell = seed mod 960, glyph = the next value's bit 3.
.const STAR_SEED = 4711
.var star_band_rows = Hashtable()
.for (var r = 0; r < 6; r++) .eval star_band_rows.put(List().add(5, 9, 12, 15, 18, 21).get(r), true)

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

// The column whose box a shot is in, by sx - collide_fx (0-255): 0-5, or $FF between two boxes
// and to the right of the last one.
grid_col:       .fill 256, (mod(i, FORM_COL_DX) < GRID_WIDTH && floor(i / FORM_COL_DX) < FORM_COLS) ? floor(i / FORM_COL_DX) : $ff

// The respawned ship's colour by its invulnerability timer after the frame's countdown (149 down
// to 0), as a colour_table index: dark grey while bit 2 of the timer is set, cyan otherwise, so 4
// frames each and cyan when the timer runs out (design.md "Colours", Stage 3 rule 10). A table of
// indices, not colours: the colours themselves live only in colour_table.
player_flash:           .fill PLAYER_INVULN_FRAMES + 1, ((i & 4) != 0) ? COL_RESPAWN_ALT : COL_PLAYER

// Enemy shots: Y step a frame by loop 0-3 (design "What faster means").
eshot_dy:               .byte 2, 2, 3, 3
.errorif * - eshot_dy != GAME_LOOP_MAX + 1, "eshot_dy: one entry per loop"

// ------------------------------------------------------------------------------------------
// Dive paths (design.md "Dive paths"; memory-map.md "Dive paths as data"). One path per row:
// Plunge (row 0), Sweep (row 1), Hook (row 2). A path is a list of segments (dx, dy, steps): add
// (dx, dy) to the position once per step. steps = 0: repeat until X reaches 0 or 344, then wrap.
// Each path is stored twice, as authored (heading right) and mirrored (dx negated), so a diver's
// mirror choice is only which copy its segment index starts in. Each copy ends with a
// PATH_END_RETURN entry: when the last counted segment runs out the diver goes to Return (the
// Hook; the other two never get past their steps = 0 segment).
// Three parallel arrays indexed by segment number; path_first,(row * 2 + mirror) is a copy's
// first segment.
.const PATH_END_RETURN = $ff            // in path_steps: not a segment, the path's end
.var path_plunge = List().add(List().add(0, -1, 6), List().add(1, 2, 20), List().add(2, 3, 20), List().add(1, 3, 16),
                              List().add(0, 2, 9), List().add(2, -1, 24), List().add(2, 0, 0))
.var path_sweep  = List().add(List().add(-1, 1, 8), List().add(1, 2, 16), List().add(2, 2, 14), List().add(2, 0, 0))
.var path_hook   = List().add(List().add(1, 1, 8), List().add(2, 2, 12), List().add(1, 3, 12), List().add(0, 2, 6),
                              List().add(-2, 0, 12), List().add(-1, -2, 8))
.var path_rows   = List().add(path_plunge, path_sweep, path_hook)       // by row 0-2
.var path_dx_list    = List()
.var path_dy_list    = List()
.var path_steps_list = List()
.var path_first_list = List()
.for (var r = 0; r < FORM_ROWS; r++) {
        .for (var m = 0; m < 2; m++) {
                .eval path_first_list.add(path_dx_list.size())
                .for (var g = 0; g < path_rows.get(r).size(); g++) {
                        .var seg = path_rows.get(r).get(g)
                        .eval path_dx_list.add(m == 0 ? seg.get(0) : -seg.get(0))
                        .eval path_dy_list.add(seg.get(1))
                        .eval path_steps_list.add(seg.get(2))
                }
                .eval path_dx_list.add(0)
                .eval path_dy_list.add(0)
                .eval path_steps_list.add(PATH_END_RETURN)
        }
}
// The design's totals, so a mistyped segment stops the build: fixed steps and the offset after them.
.function PathSum(path, field) {
        .var t = 0
        .for (var g = 0; g < path.size(); g++) .eval t = t + (field == 2 ? path.get(g).get(2) : path.get(g).get(field) * path.get(g).get(2))
        .return t
}
.errorif PathSum(path_hook, 2) != 58 || PathSum(path_hook, 0) != 12 || PathSum(path_hook, 1) != 64, "Hook: 58 steps, ending at offset (12, 200 - 136)"
.errorif PathSum(path_sweep, 2) != 38 || PathSum(path_sweep, 0) != 36 || PathSum(path_sweep, 1) != 68, "Sweep: 38 fixed steps to offset (36, 164 - 96)"
.errorif PathSum(path_plunge, 2) != 95 || PathSum(path_plunge, 0) != 124 || PathSum(path_plunge, 1) != 136, "Plunge: 95 fixed steps to offset (124, 192 - 56)"
path_dx:        .fill path_dx_list.size(), mod(path_dx_list.get(i) + 256, 256)  // signed
path_dy:        .fill path_dy_list.size(), mod(path_dy_list.get(i) + 256, 256)  // signed
path_steps:     .fill path_steps_list.size(), path_steps_list.get(i)
path_first:     .fill path_first_list.size(), path_first_list.get(i)
.errorif path_dx_list.size() > 255, "segment numbers are one byte"

// Fire steps (steps are numbered from 1 through the whole path), one list per row, each ended
// by 0, which no step number matches. path_fire_first,row is a list's first entry; PATH_FIRE_NONE
// is the index of a 0: where a diver's fire index is put when its shots are used up.
path_fire:      .byte 26, 36, 46, 0             // Plunge
                .byte 24, 38, 62, 86, 0         // Sweep
                .byte 8, 16, 0                  // Hook
path_fire_first: .byte 0, 4, 9
.const PATH_FIRE_NONE = 3

// Waves (design.md "Waves"), by pattern index 0-2 and loop 0-3: entry pattern * 4 + loop.
wave_max_divers:        .byte 1, 2, 2, 2,  2, 2, 3, 3,  2, 3, 3, 3      // most diving at once
wave_interval:          .byte 150, 120, 100, 80,  120, 100, 80, 64,  100, 80, 64, 50   // launch interval, frames
.errorif * - wave_interval != 3 * (GAME_LOOP_MAX + 1), "wave tables: 3 patterns x 4 loops"
// By pattern: the rows that dive (bit r = row r) and the shots per dive at loop 0 (+ 1 a loop).
wave_rows:              .byte %100, %110, %111
wave_shots:             .byte 1, 2, 2
diver_row_bit:          .fill FORM_ROWS, 1 << i
// By loop: the wind-up's length, and the frames in which every diver takes 2 path steps: those
// whose frame number AND the mask equals the compare value (never at loop 0, every 4th at loop
// 1, every 2nd from loop 2).
windup_frames:          .byte 24, 20, 16, 12
diver_extra_mask:       .byte 0, 3, 1, 1
diver_extra_cmp:        .byte 1, 0, 0, 0

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

// Play-area texts (design.md "Text cells and the star rule"): the three messages on row 9
// (MSG_ROW) and the title's six. Each is centred, first column (40 - length) div 2, except the
// three score lines, which are right-aligned in columns 17-23 (written here with their leading
// space). All are inside the star-free band (columns 10-29 of a band row), so a text is written
// and erased without looking at the stars. game_text_draw / game_text_erase (game.asm) take a
// TEXT_* index into these tables.
.const TEXT_PRESS_FIRE = 0      // the title's texts are 0-5, in the order the title draws them:
.const TEXT_SWARM      = 1      // PRESS FIRE in the title's frame 0 (the blink's first "on"), the
.const TEXT_PTS_A      = 2      // rest one a frame in frames 1-5
.const TEXT_PTS_B      = 3
.const TEXT_PTS_C      = 4
.const TEXT_DIVING     = 5
.const TEXT_READY      = 6
.const TEXT_GAME_OVER  = 7
.const TEXT_WAVE       = 8      // "WAVE 00": game_wave_intro writes the shown wave's digits over the 00
.const TEXT_COUNT      = 9
.const TITLE_TEXTS     = 6
.var text_list = List()         // (string, row, first column; -1 = centred)
.eval text_list.add(List().add("PRESS FIRE", 21, -1))
.eval text_list.add(List().add("SWARM", 5, -1))
.eval text_list.add(List().add("150 PTS", 9, 17))
.eval text_list.add(List().add(" 80 PTS", 12, 17))
.eval text_list.add(List().add(" 50 PTS", 15, 17))
.eval text_list.add(List().add("DIVING SCORES DOUBLE", 18, -1))
.eval text_list.add(List().add("READY", MSG_ROW, -1))
.eval text_list.add(List().add("GAME OVER", MSG_ROW, -1))
.eval text_list.add(List().add("WAVE 00", MSG_ROW, -1))
.errorif text_list.size() != TEXT_COUNT, "text_list: TEXT_COUNT texts"
.function TextLen(t) { .return text_list.get(t).get(0).size() }
.function TextRow(t) { .return text_list.get(t).get(1) }
.function TextCol(t) { .return text_list.get(t).get(2) < 0 ? floor((SCREEN_COLS - TextLen(t)) / 2) : text_list.get(t).get(2) }
.function TextLast(t) {         // offset in text_data of the text's last character
        .var n = -1
        .for (var i = 0; i <= t; i++) .eval n = n + TextLen(i)
        .return n
}
text_data:
        .for (var t = 0; t < TEXT_COUNT; t++) { GameText(text_list.get(t).get(0)) }
.errorif * - text_data > 256, "text_data is indexed by one byte"
text_last:      .fill TEXT_COUNT, TextLast(i)           // index in text_data of the last character
text_len1:      .fill TEXT_COUNT, TextLen(i) - 1        // length - 1
text_scr_lo:    .fill TEXT_COUNT, <(SCREEN + TextRow(i) * SCREEN_COLS + TextCol(i))
text_scr_hi:    .fill TEXT_COUNT, >(SCREEN + TextRow(i) * SCREEN_COLS + TextCol(i))
.for (var t = 0; t < TEXT_COUNT; t++) {
        .errorif !star_band_rows.containsKey(TextRow(t)) || TextCol(t) < STAR_BAND_COL_MIN || TextCol(t) + TextLen(t) - 1 > STAR_BAND_COL_MAX, "text " + t + " is outside the star-free bands"
}
.errorif TextCol(TEXT_READY) != 17 || TextCol(TEXT_GAME_OVER) != 15 || TextCol(TEXT_WAVE) != 16, "design: READY at columns 17-21, GAME OVER at 15-23, WAVE nn at 16-22"
.errorif TextCol(TEXT_SWARM) != 17 || TextCol(TEXT_DIVING) != 10 || TextCol(TEXT_PRESS_FIRE) != 15, "design: SWARM at columns 17-21, DIVING SCORES DOUBLE at 10-29, PRESS FIRE at 15-24"
.errorif TextCol(TEXT_READY) < TextCol(TEXT_GAME_OVER) || TextCol(TEXT_READY) + TextLen(TEXT_READY) > TextCol(TEXT_GAME_OVER) + TextLen(TEXT_GAME_OVER), "erasing GAME OVER's cells must erase READY"
.errorif TextCol(TEXT_WAVE) < TextCol(TEXT_GAME_OVER) || TextCol(TEXT_WAVE) + TextLen(TEXT_WAVE) > TextCol(TEXT_GAME_OVER) + TextLen(TEXT_GAME_OVER), "erasing GAME OVER's cells must erase WAVE nn"
.const MSG_WAVE_DIGITS = MSG + TextCol(TEXT_WAVE) + 5   // the two digits of WAVE nn
