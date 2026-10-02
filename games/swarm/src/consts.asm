// Swarm: constants shared by every file. Hardware registers, the memory layout
// (docs/games/swarm/memory-map.md) and the design's numbers (docs/games/swarm/design.md).
// No code and no data: this file assembles to nothing.

// --- Hardware -----------------------------------------------------------------------------
.const CPU_PORT       = $01     // written at init only, before irq_init
.const VIC_CTRL1      = $d011   // every write keeps bit 7 clear (the IRQ framework's)
.const VIC_CTRL2      = $d016
.const VIC_SPR_YEXP   = $d017   // stays 0 (engine v1 condition 4)
.const VIC_MEMORY     = $d018
.const VIC_SPR_PRIO   = $d01b
.const VIC_SPR_XEXP   = $d01d   // stays 0
.const VIC_BORDER     = $d020
.const VIC_BACKGROUND = $d021   // play area background
.const VIC_BG1        = $d022   // ECM background 1: the panel
.const COLOUR_RAM     = $d800
.const CHAR_ROM       = $d000   // character ROM, upper case / graphics set, seen with $01 = $33

// --- Memory layout ------------------------------------------------------------------------
.const SCREEN        = $0400
.const ENGINE_START  = $0810
.const CHARSET       = $2800    // 64 glyphs, $2800-$29FF
.const CHARSET_SIZE  = 64 * 8
.const SPRITE_DATA   = $3000    // pointers $C0-$DF
.const GAME_TABLES   = $3800
.const GAME_CODE     = $4000
.const GAME_CODE_END = $6000

.const VIC_CTRL1_INIT  = $5b    // ECM on, screen on, 25 rows, YSCROLL 3, bit 7 clear
.const VIC_CTRL2_INIT  = $c8    // 40 columns, no multicolour, XSCROLL 0
.const VIC_MEMORY_INIT = ((SCREEN / $0400) << 4) | ((CHARSET / $0800) << 1)     // $1A
.errorif VIC_MEMORY_INIT != $1a, "memory map: $D018 is $1A (screen $0400, charset $2800)"

.const MUX_SCREEN = SCREEN      // multiplexer: sprite pointers at $07F8-$07FF
.const MUX_Y_MAX  = 221         // panel line 243 - 22

// --- Screen -------------------------------------------------------------------------------
.const SCREEN_COLS = 40
.const PLAY_ROWS   = 24                         // text rows 0-23
.const PLAY_CELLS  = PLAY_ROWS * SCREEN_COLS    // 960
.const PANEL_ROW   = 24
.const PANEL       = SCREEN + PANEL_ROW * SCREEN_COLS
.const PANEL_COLOUR = COLOUR_RAM + PANEL_ROW * SCREEN_COLS
.const PANEL_BG    = $40        // added to every screen code the panel stores: ECM background 1

// Glyphs (screen codes 0-63). Letters 1-26, digits 48-57 and the space are the ROM's.
.const GLYPH_SPACE   = 32
.const GLYPH_ZERO    = 48
.const GLYPH_STAR_HI = 27       // custom, replaces '['
.const GLYPH_STAR_LO = 28       // custom, replaces the pound sign
.const GLYPH_SHIP    = 29       // custom, replaces ']'. Panel only (as 29 + PANEL_BG)

// Panel columns (design.md#screen-layout)
.const PANEL_COL_SCORE = 7      // six digits, 7-12
.const PANEL_COL_HI    = 18     // six digits, 18-23
.const PANEL_COL_WAVE  = 31     // two digits, 31-32
.const PANEL_COL_SHIPS = 35     // spare ships, 35-37
.const PANEL_SHIPS_MAX = 3

// Stars (design.md#screen-layout and "Text cells and the star rule")
.const STAR_COUNT    = 48
.const STAR_BAND_COL_MIN = 10   // no star in columns 10-29 of the text rows
.const STAR_BAND_COL_MAX = 29

// --- Colour table indices (memory-map.md#game-tables). The values are in tables.asm -------
.const COL_BORDER         = 0
.const COL_BACKGROUND     = 1
.const COL_PANEL_BG       = 2
.const COL_PLAYER         = 3
.const COL_PLAYER_SHOT    = 4
.const COL_ENEMY_A        = 5
.const COL_ENEMY_B        = 6
.const COL_ENEMY_C        = 7
.const COL_WINDUP_FLASH   = 8
.const COL_ENEMY_SHOT     = 9
.const COL_ENEMY_EXPLODE  = 10
.const COL_PLAYER_EXPLODE = 11
.const COL_RESPAWN_ALT    = 12
.const COL_PANEL_TEXT     = 13
.const COL_MESSAGE_TEXT   = 14
.const COL_STAR_0         = 15  // 15-18: the twinkle's four steps, in order
.const COL_TABLE_USED     = 19
.const COL_TABLE_SIZE     = 32

// --- Sprites ------------------------------------------------------------------------------
// Virtual sprite allocation (memory-map.md#sprite-allocation)
.const SPR_PLAYER      = 0      // pinned
.const SPR_ESHOT       = 1      // 1-3, pinned
.const SPR_ESHOT_COUNT = 3
.const SPR_PSHOT       = 4      // 4-5
.const SPR_PSHOT_COUNT = 2
.const SPR_ENEMY       = 6      // 6-23: 6 + row * 6 + column
.const SPR_PINNED      = 4      // virtual sprites 0-3 are pinned
.const MUX_FLAG_PINNED = $80

// Shape pointers: sheet order from games/swarm/art/README.md
.const SPRITE_PTR0      = SPRITE_DATA / 64      // $C0
.const SHAPE_PLAYER     = SPRITE_PTR0 + 0
.const SHAPE_PSHOT      = SPRITE_PTR0 + 1
.const SHAPE_ESHOT      = SPRITE_PTR0 + 2
.const SHAPE_ENEMY      = SPRITE_PTR0 + 3       // A1 A2 B1 B2 C1 C2
.const SHAPE_EXPLOSION  = SPRITE_PTR0 + 9       // 4 shapes
.const SHAPE_COUNT      = 13

// --- Player and player shots (design.md "Controls and rules", "Entities") -------------------
.const PLAYER_X_MIN    = 24
.const PLAYER_X_MAX    = 318
.const PLAYER_X_START  = 171    // the design's respawn X: the middle of 24-318
.const PLAYER_Y        = 221
.const PLAYER_SPEED    = 3
.const PLAYER_LIVES    = 3
.const PSHOT_SPAWN_Y   = 213
.const PSHOT_SPEED     = 8
.const PSHOT_KILL_Y    = 46     // removed when Y < 46
.const PSHOT_COOLDOWN  = 10
.errorif PLAYER_Y != MUX_Y_MAX, "the player sits at MUX_Y_MAX"

// --- Formation and enemies (design.md "The formation", "Entities", "Sprite shapes") ---------
.const FORM_ROWS       = 3
.const FORM_COLS       = 6
.const ENEMY_COUNT     = FORM_ROWS * FORM_COLS  // 18: enemy e = row * 6 + column, sprite SPR_ENEMY + e
.const FORM_X0         = 34     // home X = FORM_X0 + fx + FORM_COL_DX * column
.const FORM_COL_DX     = 36
.const FORM_ROW_Y0     = 56     // home Y = FORM_ROW_Y0 + FORM_ROW_DY * row: 56, 96, 136
.const FORM_ROW_DY     = 40
.const FORM_FX_MAX     = 96     // fx runs 0 -> 96 -> 0
.const FORM_FX_START   = 48     // moving right
.const ENEMY_ANIM_FRAMES = 16   // the two shapes of a type swap every 16 frames, all together
.const GAME_LOOP_MAX   = 3      // loops past 3 play as loop 3
.errorif SPR_ENEMY + ENEMY_COUNT != 24, "the enemies are virtual sprites 6-23"
.errorif FORM_X0 + FORM_FX_MAX + FORM_COL_DX * (FORM_COLS - 1) != 310, "design: the formation's sprite X is 34-310"

// --- Game core ----------------------------------------------------------------------------
.const GAME_STATE_PLAY  = 0     // stage 1 has no other state
.const GAME_IDLE_WARMUP = 200   // frames before game_idle_min starts counting
.const HISCORE_START    = $005000       // BCD
.const GAME_RNG_SEED    = $1d5a  // any non-zero value: the fixed seed of AUTOPLAY runs (and of stage 1)
