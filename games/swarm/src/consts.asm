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

// Hit boxes (design.md#hit-boxes, the only place the numbers live): columns x0-x1 and rows y0-y1
// inside the 24 x 21 cell, inclusive. col_pairs (tables.asm) and the Y guards below are built
// from these; nothing else types a box number.
.const BOX_PLAYER_X0 = 6
.const BOX_PLAYER_X1 = 17
.const BOX_PLAYER_Y0 = 6
.const BOX_PLAYER_Y1 = 20
.const BOX_ENEMY_X0  = 4
.const BOX_ENEMY_X1  = 19
.const BOX_ENEMY_Y0  = 3
.const BOX_ENEMY_Y1  = 17
.const BOX_PSHOT_X0  = 11
.const BOX_PSHOT_X1  = 12
.const BOX_PSHOT_Y0  = 0
.const BOX_PSHOT_Y1  = 7
.const BOX_ESHOT_X0  = 11
.const BOX_ESHOT_X1  = 12
.const BOX_ESHOT_Y0  = 14
.const BOX_ESHOT_Y1  = 20
// Rows of col_pairs, in the order of engine/collision.md's contract
.const COL_PAIR_PSHOT_ENEMY  = 0        // A = a player shot, targets = the 18 enemies
.const COL_PAIR_PLAYER_ESHOT = 1        // A = the player, targets = the 3 enemy shots (stage 3)
.const COL_PAIR_PLAYER_ENEMY = 2        // A = the player, targets = diving enemies (stage 3)
// The lowest Y at which a target can touch the player (memory-map.md "The collision budget",
// rule 3): stage 3 tests mux_y against these before spending a collision_begin on the player.
.const PLAYER_HIT_ESHOT_Y = MUX_Y_MAX + BOX_PLAYER_Y0 - BOX_ESHOT_Y1    // 207
.const PLAYER_HIT_ENEMY_Y = MUX_Y_MAX + BOX_PLAYER_Y0 - BOX_ENEMY_Y1    // 210
.errorif PLAYER_HIT_ESHOT_Y != 207 || PLAYER_HIT_ENEMY_Y != 210, "design: an enemy shot hits from Y 207, an enemy from Y 210"

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
.const EXPLOSION_SHAPES      = 4        // design "Sprite shapes": 4 shapes x 4 frames, stationary
.const EXPLOSION_SHAPE_FRAMES = 4
.const EXPLOSION_FRAMES      = EXPLOSION_SHAPES * EXPLOSION_SHAPE_FRAMES        // 16
.const WAVE_CLEAR_PAUSE      = 75       // design "Waves": frames between the last explosion's end and the next wave's Intro
.errorif SPR_ENEMY + ENEMY_COUNT != 24, "the enemies are virtual sprites 6-23"
.errorif FORM_X0 + FORM_FX_MAX + FORM_COL_DX * (FORM_COLS - 1) != 310, "design: the formation's sprite X is 34-310"

// The grid lookup of collide_update (memory-map.md "The collision budget", the fallback): its
// constants, from the hit boxes above and the formation's geometry.
// A shot at (sx, sy) is inside the box of an enemy at (ex, ey) when
//   0 <= sy + GRID_Y_OFF - ey < GRID_BAND        (the module's Y test: ay1 - by0 and range_y)
//   0 <= sx - ex + GRID_X_OFF < GRID_WIDTH       (the module's X test)
// and a Parked enemy is at ex = FORM_X0 + fx + FORM_COL_DX * column, ey = its row's Y.
.const GRID_Y_OFF = BOX_PSHOT_Y1 - BOX_ENEMY_Y0                                                 // 4
.const GRID_BAND  = (BOX_PSHOT_Y1 - BOX_PSHOT_Y0) + (BOX_ENEMY_Y1 - BOX_ENEMY_Y0) + 1           // 22
.const GRID_X_OFF = BOX_PSHOT_X1 - BOX_ENEMY_X0                                                 // 8
.const GRID_WIDTH = (BOX_PSHOT_X1 - BOX_PSHOT_X0) + (BOX_ENEMY_X1 - BOX_ENEMY_X0) + 1           // 17
.const GRID_X0    = FORM_X0 - GRID_X_OFF        // collide_fx = fx + this; sx - collide_fx indexes grid_col
.errorif GRID_BAND > FORM_ROW_DY || GRID_WIDTH > FORM_COL_DX, "the grid lookup needs a shot to be in at most one row's band and one column's box"
.errorif GRID_X0 < 0 || GRID_X0 + FORM_FX_MAX > 255, "collide_fx is one byte"
.errorif FORM_ROWS != 3, "collide_update's row test is written for three rows"
.errorif MUX_Y_MAX + GRID_Y_OFF > 255, "sy + GRID_Y_OFF is one byte"


// --- Enemy shots, divers, the launcher (design.md "Enemy behaviour", "Firing", "Waves") -------
.const DIVER_SLOTS     = 3      // enemies in WindUp, Dive or Return at once (the waves' maximum)
.const DIVER_X_MIN     = 0      // a diver's and an enemy shot's X is clamped to 0-344: both ends
.const DIVER_X_MAX     = 344    // are off screen
.const DIVER_WRAP_Y    = 30     // a wrapping diver re-enters at (home X, 30), under the top border
.const DIVER_RETURN_SPEED = 2   // Return: X and Y toward home by at most 2 a frame
.const ESHOT_FIRE_X_MIN = 24    // a diver fires only with its X in 24-320
.const ESHOT_FIRE_X_MAX = 320
.const ESHOT_AIM_DEAD  = 15     // a shot's dx is 0 when |player X - shot X| <= 15
.const LAUNCH_TIMER_START = 50  // the launch timer when Play is entered and when a formation returns
.const LAUNCH_HALVE_ALIVE = 4   // the interval is halved with 4 or fewer enemies alive
.const FIGHT_LAUNCH_TIMER = LAUNCH_TIMER_START + 1      // set in Fight's first frame, before diver_update counts it
                                // once in that same frame (in Play): it reads 50 at that frame's end and the
                                // first launch is 50 frames later, 150 after the wave appeared (design, Stage 4
                                // rule 8: Fight at d + 191, first launch at d + 241)
.const PATTERN_COUNT   = 3      // the pattern index cycles 0-2
.errorif DIVER_WRAP_Y < 30 || DIVER_X_MAX > 511, "divers stay inside the multiplexer's range"

// --- Waves (design.md "Game flow", "Stage 4 rules" 1-8) ----------------------------------------
// The wave phase, beside the game state. Fight is 0 so that "in Play and in Fight" is one ora.
.const WAVE_PHASE_FIGHT = 0
.const WAVE_PHASE_INTRO = 1     // 100 frames: WAVE nn for 75, enemy k appears in frame 2k
.const WAVE_PHASE_CLEAR = 2     // 75 frames of empty sky after the last explosion ended
.const INTRO_FRAMES     = 100
.const INTRO_MSG_FRAMES = 75    // WAVE nn is erased in Intro's frame 75
.const WAVE_START       = $01   // BCD: a new game's shown wave
.const WAVE_MAX         = $99   // BCD: the shown wave stops here; the game carries on
.const WAVE_BONUS_MID   = $10   // + 1,000: BCD, added to the score's middle byte
#if AUTOPLAY
.const NEW_GAME_WAVE    = $12   // the budget build plays wave 12: pattern 3 (index 2), loop 3
.const NEW_GAME_PATTERN = 2     // (memory-map.md "Labels the game must provide")
.const NEW_GAME_LOOP    = GAME_LOOP_MAX
#else
.const NEW_GAME_WAVE    = WAVE_START
.const NEW_GAME_PATTERN = 0
.const NEW_GAME_LOOP    = 0
#endif
.const NEW_GAME_COOLDOWN = 25   // Stage 4 rule 10: the press that started the game is still held. The ship
                                // can't fire in the new game's frame or the 24 after it
.errorif INTRO_MSG_FRAMES < 2 * ENEMY_COUNT || (INTRO_MSG_FRAMES & 1) == 0, "wave_step: the erase frame must be odd or past the last enemy's frame (2 * 17)"

// --- Game core and the game states (design.md "Game flow", "Stage 3 rules" 8-13) --------------
// The order matters: the ship is shown (and moves and fires) in the states below
// GAME_STATE_DYING, and Play is 0 so that "in Play" is one beq.
.const GAME_STATE_PLAY     = 0
.const GAME_STATE_RESPAWN  = 1  // READY: 50 frames, the ship back and controllable
.const GAME_STATE_DYING    = 2  // PlayerDying: the explosion, then the wait for the divers
.const GAME_STATE_GAMEOVER = 3
.const PLAYER_EXPLOSION_FRAMES = 32     // the hit's frame and the 31 after: 4 shapes of 8 frames
.const PLAYER_INVULN_FRAMES = 150       // from the first frame of Respawn: 50 of READY + 100 of play
.const RESPAWN_FRAMES      = 50
.const DYING_MIN_FRAMES    = 100        // PlayerDying ends in the first frame, 100 or later, with no diver out
.const GAMEOVER_FRAMES     = 200
.const GAMEOVER_SKIP_FRAME = 50         // from this frame of GameOver a new press of fire ends it
.const MSG_ROW             = 9          // WAVE nn, READY, GAME OVER: row 9, centred, between formation rows 1
                                        // and 2 (design "Text cells and the star rule": never row 12, which
                                        // the formation's bottom row covers)
.const MSG = SCREEN + MSG_ROW * SCREEN_COLS
.const GAME_IDLE_WARMUP = 200   // frames before game_idle_min starts counting
.const HISCORE_START    = $005000       // BCD
.const GAME_RNG_SEED    = $1d5a  // any non-zero value: the fixed seed of AUTOPLAY runs (and of stage 1)
.errorif PLAYER_EXPLOSION_FRAMES != 2 * EXPLOSION_FRAMES, "player_update reads the enemies' explosion_shape table at half speed"
.errorif PLAYER_EXPLOSION_FRAMES >= DYING_MIN_FRAMES, "the player's explosion must be over before PlayerDying can end"
