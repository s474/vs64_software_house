# What a game needs from the engine

A few pages for a gameplay engineer starting a game on engine v1. **This is a guide, not a source of
truth**: every figure is copied from [README.md](README.md), a module contract
([input.md](input.md), [rng.md](rng.md), [collision.md](collision.md), [sfx.md](sfx.md)), a
hardware reference page (for sound, [docs/reference/sid.md](../docs/reference/sid.md): what the
SID does, measured in VICE, and what only ears can check) or,
where it says Swarm, [Swarm's memory map](../docs/games/swarm/memory-map.md), and if
they disagree, they are right and this page gets fixed. Read the game's own
`docs/games/<title>/memory-map.md` first; a worked example is `games/swarm/src/main.asm`.

## 1. Imports, in this order

```
BasicUpstart2(start)
#import "zp.asm"                        // every zero-page label below
.const MUX_SCREEN = $0400               // before the multiplexer import
.const MUX_Y_MAX  = 221                 // largest sprite Y shown: 80-249
* = $0810 "Engine"                      // allow about 7.2 KB (Swarm, with sound: 7,033 measured)
#import "engine/irq.asm"
#import "engine/multiplexer.asm"
#import "engine/input.asm"              // 32 bytes
#import "engine/rng.asm"                // 37 bytes
#import "engine/collision.asm"          // 148 bytes. After the multiplexer: it reads its arrays
#import "engine/sfx.asm"                // 632 bytes + up to 255 of padding (it is page-aligned)
        IrqChainBegin()
        IrqNormal(MUX_TOP_LINE, mux_irq_top)    // entry 0 is always this, at line 16
        IrqNormal($fb, game_irq_bottom)         // entry 1, line 251: sound, later music
        IrqChainEnd()
```

With `sfx.asm` the `$fb` handler is `jsr sfx_update` then `IrqDone()` and nothing else, and the
effect data is written after the import (section 6). `collision.asm` needs a `col_pairs` label
in the game (section 5).
Chain: 1–16 entries, ascending lines 0–255, each handler ends with `IrqDone()`; with the
multiplexer, none before line 16 and none from there to `MUX_Y_MAX + 2` (`+ 3` when `MUX_Y_MAX` is
243 or less): [Declaring the chain](README.md#declaring-the-chain), [Raster timeline](README.md#raster-timeline).

## 2. Zero page the game's `zp.asm` must define

| Labels | Used by | Game code may |
|---|---|---|
| `zp_tmp0`–`zp_tmp3` | `mux_update` (scratch) | Use them in the main loop, never across a `jsr mux_update`, never in an IRQ |
| `zp_irq_idx`, `zp_mux_front`, `zp_mux_ready`, `zp_mux_slot`, `zp_mux_end` | IRQ framework, multiplexer | Not touch them |
| `zp_irq_frame` | Frame counter, +1 at entry 0. **Nothing zeroes it at start**, so it is not "frames since boot": use differences, or keep your own counter | Read it |
| `zp_joy`, `zp_joy_pressed` | `input.asm` | Read them in the main loop. No IRQ handler reads `zp_joy_pressed` |
| `zp_rng_lo`, `zp_rng_hi` | `rng.asm` | Not touch them |

One byte each; any free addresses. Suggested block: [Zero page](README.md#zero-page).
`collision.asm` and `sfx.asm` need none.

## 3. Start-up and the main loop

```
start:  ...                     // anything needing sei or a $01 write: here, before irq_init
        jsr mux_init            // hides all 24 sprites
        ...                     // write mux_flags once, all 24 entries
        jsr input_init
        jsr rng_seed            // A = low, X = high. A constant here; see below
        jsr sfx_init            // silences the SID, volume 15. Before irq_init: the tick is an IRQ
        jsr irq_init            // $01 = $35, chain running, interrupts on. Last
main:   jsr irq_wait_frame      // A = frame number
main_frame:
        sta zp_game_frame
        jsr input_read          // exactly once a frame, first thing
        ...                     // game logic: write the mux_* arrays
        jsr mux_update          // once a frame, after the arrays are written
        jmp main                // release
```

A DEBUG build replaces the last line with: compare `zp_irq_frame` with `zp_game_frame`; if they
differ the frame overran (count it, `jmp main`); otherwise count idle-loop iterations until
`zp_irq_frame` changes, then **`jmp main_frame`, not `main`**: the idle loop has already waited
for the tick, and a second wait halves the frame rate. Copy Swarm's.

- **Order the frame so that short, fixed work comes first**, in the top border (the tick is at
  line 16, the first badline at 51, no sprite before line 30): input, panel, anything that
  depends on nothing else. There its cost is its CPU count. Then the movers, then the collisions.
- **Seed when the player starts, and step the generator while the title waits** (`jsr rng_next`
  once a title frame). `$D012` read by main-loop code on a title screen is the same line, or one of two
  lines, every frame (measured: Swarm's read falls between line 26 cycle 61 and line 27 cycle 11, so
  it returns 26 or 27; `tests/games/swarm/stage5_newgame_trace.py`), so
  "frame counter and raster line" alone is about 256 different games
  ([Swarm's rule](../docs/games/swarm/memory-map.md#stage-4-what-must-be-done-to-stay-in-budget), (d)).

## 4. Sprites: the multiplexer's arrays

24 virtual sprites, index 0–23, written by the main loop only, before `mux_update`:

| Array | Contents |
|---|---|
| `mux_x_lo`, `mux_x_hi` | X bits 0–7; bit 8 in bit 0 of `mux_x_hi` |
| `mux_y` | Y as the VIC-II register. `MUX_OFF` (`$FF`) hides the sprite, at no cost |
| `mux_ptr`, `mux_col` | Sprite pointer; colour |
| `mux_flags` | Bit 0 multicolour, bit 7 **pinned** (never flickers), bits 1–6 zero |

- Positions written in frame N are on screen in frame N + 1. Shown range: Y 30 to `MUX_Y_MAX`.
- The game never writes `$D000–$D010`, `$D015`, `$D01C`, `$D027–$D02E` or the sprite pointers.
- Only the first **4** flagged sprites, in index order, are pinned: put the player at 0.
- Keep bit 0 the same on all 24 if you can: the uniform path is cheaper and has the larger margin.
- **Checking sprites from a test.** The hardware registers (`$D000`–`$D010`, `$D015`, `$D027`–)
  read at `game_update_end` hold only the first 8 sprites in Y order; the rest are written by the
  zone IRQs further down the frame. Read them at line 251 (`vice_run_until` the `$FB` handler) to
  see the last 8 written, or read the `mux_*` arrays for all 24.
- **`mux_drop_count`, `mux_max_age`, `mux_late_count`, `mux_pin_drop_count`,
  `mux_pin_excess_count` and `irq_late_count` exist in DEBUG builds only**: game code that reads
  one goes inside `#if DEBUG`. `mux_drop_count` is the *last* `mux_update`'s result: read it after
  the `jsr mux_update`; before it, it is the previous frame's
  ([Debug counters](README.md#debug-counters-debug-builds)).

## 5. Collisions ([collision.md](collision.md))

Bounding boxes between virtual sprites, read from the `mux_*` arrays. No zero page.

```
col_pairs:                                   // the game's label; one row per pair of kinds
        ColPair(11,12, 0,7,   4,19, 3,17)    // pair 0: A's box x0,x1,y0,y1, then B's (inclusive,
                                             // pixels inside the 24 x 21 cell)
        ldx #SHOT                            // A: the object
        ldy #0                               // the pair
        jsr collision_begin                  // copies A's position now
        ldx #LAST_ENEMY                      // highest target index
        lda #FIRST_ENEMY                     // lowest
        jsr collision_range                  // C = 1: X = the target hit (counting down). C = 0: none
        bcc none
        ...                                  // not a real hit (exploding)? jsr collision_next: carries
                                             // on below X, same result convention
```

| Routine (whole call, CPU cycles, **measured**) | In | Clobbers | Cost |
|---|---|---|---|
| `collision_begin` | X = A, Y = pair | A. X and Y kept | 95 |
| `collision_range` / `collision_next` | X = last target, A = first / X = the last hit | A, X, Y | 22 + 17 a target rejected on Y + 39 a target tested on X |
| `collision_one` | X = target | A, Y. X kept | up to 52 |

- **Move A before `collision_begin`**: its position is captured there. Targets are read as tested.
- **A hidden sprite (`MUX_OFF`) never hits and is never hit.** Don't spend a `collision_begin`
  (95) on a free slot all the same: test it yourself first.
- **The module knows positions, not states.** A target that is on screen but can't be hit (an
  exploding enemy) is still reported: check its state and `collision_next` past it.
- **Never `collision_one` with X = A**: A is skipped in a range, not there.
- One `collision_begin` at a time; main loop only. Each pair needs `MUX_Y_MAX + ay1 − by0 < 255`
  (`ColPair` stops the build otherwise).
- Budget the whole frame's calls with [the formula](collision.md#what-a-frame-of-calls-costs),
  then × 1.27 to 1.35 through the display. Swarm's 42 tests: 1,813, about 2,335 in the display.
- **Objects that stand on a fixed grid don't need a scan.** Find the one cell the object is over
  by arithmetic and test that candidate with the same box; keep the module for what moves freely.
  Swarm's player shots against 18 parked enemies (**measured**, stage 3): the average frame went
  from 938 to 434 and the worst sampled frame from 2,004 to 1,399.
- **Changing the algorithm moves the worst frame: find it again from the new code's paths.**
  Swarm's worst frame for the scan (2,836) read 1,846 after the change, but the lookup's own worst
  frame, a diver in each shot's Y band, is 2,469, and in that frame the lookup is dearer than the
  scan was ([the collision budget](../docs/games/swarm/memory-map.md#the-collision-budget)).

## 6. Sound effects ([sfx.md](sfx.md))

Three SID voices, one effect a voice at a time, priorities 1–3. No music. Two halves: the main
loop leaves a **request** (one byte a voice), and the **tick**, an IRQ at line 251, starts and
steps the effects, so sound keeps its tempo when the main loop is late.

```
#import "engine/sfx.asm"                // in the engine block, with the other modules
        ...
        SfxBegin()                      // the effect data: in a file the GAME owns, placed with
#import "sfx_data.asm"                  // the game's tables. SfxEnd() emits the tables here
        SfxEnd()
        ...
start:  jsr sfx_init                    // before irq_init
        ...
game_irq_bottom:                        // chain entry 1, line $FB
        jsr sfx_update                  // the tick. This and IrqDone(), NOTHING else, ever
        IrqDone()
        ...
        lda #SFX_PLAYER_SHOT            // main loop: ask for an effect
        jsr sfx_play                    // A, X and Y are gone; no zero page is touched
```

An effect in the data file (voice 0–2 is SID voice 1–3):

```
.label SFX_PLAYER_SHOT = SfxEffect(0, 1, $00, $a0, 8)   // voice, priority, AD, SR, pulse width 0-15
        SfxStep(8, $41, $9000, -$0e00)                   // frames, control, frequency, slide a frame
        SfxStep(1, $40, SfxHz(523.25), 0)                // SfxHz: a pitch in Hz as a PAL frequency value
```

- **`sfx_play` from the main loop only**, never from an IRQ handler; `sfx_update` from the IRQ
  only. `sfx_play` clobbers **A, X and Y**: a caller that needs X or Y afterwards saves it (6
  cycles each through a `zp_tmp` byte, which the call doesn't touch).
- **The priority rule, which the game never codes**: a new effect starts if its voice is idle or
  playing an effect of **equal or lower** priority, which it cuts off; otherwise it is dropped,
  not queued. Of several requests for one voice in one frame the highest priority survives, and
  **the latest call on a tie**. So every routine asks for its sound without looking at what else
  happened, and the order of calls is the order of the frame.
- A request made before line 251 starts in that frame's tick. An effect that needs two voices is
  two effects and two calls.
- **What a request costs** (`lda #` + `jsr sfx_play`, CPU cycles, **measured**): **36** with
  nothing pending on the voice, **51** replacing a pending request, **39** keeping a higher one.

  | Where | Raster cycles to allow |
  |---|---|
  | Border (no badline, no sprites) | 36 / 51 / 39 |
  | Display, no sprites on the lines | 79 / 94 / 82 at worst: + a badline (**measured**) |
  | Display, 8 sprites on the lines | 117 / 151 / 120 at worst (*counted*) |

  So: ask in the border where the event allows it; **ask once a frame** for an effect that
  several events in a frame would ask for (a flag, tested once at the routine's end); don't ask
  for an effect that a higher priority on its voice has already beaten in that frame. Inside a
  routine in the display, add the requests' CPU to the routine's and count the routine again
  ([sfx.md](sfx.md#what-a-request-costs-a-game); Swarm's nine requests:
  [memory map](../docs/games/swarm/memory-map.md#stage-4-part-b-sound-requests)).
- **The tick** costs IRQ time, no DMA: 56 with nothing playing, 214 with three voices sliding,
  **429** when three effects start in one frame (whole calls, **measured**); the chain entry
  around that worst tick is 498 to its `rti`.
- **The SID can't be read back** ([sid.md](../docs/reference/sid.md), fact 2). Tests read the
  module instead: `sfx_request` (3 bytes: what the main loop asked for this frame, effect + 1,
  cleared by the tick), `sfx_cur` (3 bytes: what each voice is playing, effect + 1, 0 = idle),
  and in DEBUG `sfx_shadow` (25 bytes: the last value written to each of `$D400–$D418`). The
  VICE monitor's own read of `$D400–$D418` (`vice_read_memory`) does return the last value
  written, in release builds too ([sid.md](../docs/reference/sid.md), fact 3). Read
  `sfx_request` at `game_update_end`, before the tick takes it.
- **Envelope values decide whether an effect starts on time** ([sid.md](../docs/reference/sid.md),
  fact 15): release 0 on every effect; every rate 0 on one that must never be late. A start that
  cuts off a slowly decaying effect is about 33 ms late. And nothing here can tell you how it
  sounds: that is a person's job, in VICE and on the real machine.

## 7. Rules that must not be broken

The four conditions engine v1 was measured under ([verdict](README.md#verdict-safe-for-m4-with-the-zone-code-frozen)):
1. **The zone code and its three scheduling constants are frozen.** A game needing an engine
   change reports it; it doesn't edit `engine/`.
2. **The main loop never sets `I` while the multiplexer runs**: no `sei`, no `$01` write after
   `irq_init` (`$01` stays `$35`). The closest zone write has 3 cycles in hand. Decimal mode is fine.
3. **YSCROLL is the same on every line of the play area.**
4. **No sprite expansion**: `$D017` = `$D01D` = 0.

- **IRQ ownership.** Only `irq.asm` writes `$FFFA–$FFFF`, `$D012`, `$D019`, `$D01A`, `$DC0D`,
  `$DD0D` and bit 7 of `$D011` (game writes to `$D011` keep bit 7 clear). Handlers never `cli`
  ([Ownership](README.md#ownership), [Handler conventions](README.md#handler-conventions)).
- **Input.** `input_read` once a frame straight after `irq_wait_frame`; nothing else writes
  `$DC00` or `$DC02`; no keyboard scan after `input_init`. Bits are active high: `JOY_UP` `$01`,
  `JOY_DOWN` `$02`, `JOY_LEFT` `$04`, `JOY_RIGHT` `$08`, `JOY_FIRE` `$10`.
- **Random numbers.** Main loop only; `rng_next` returns A and preserves X and Y. Never write
  code that waits for a particular value to turn up, and bound any mask-and-retry loop yourself.
- **Sound.** Only `sfx.asm` writes `$D400–$D418`. `sfx_play` in the main loop, `sfx_update` in
  the `$FB` handler, never the other way round (section 6).

## 8. What it costs, and what is left (raster cycles a frame, PAL, DEBUG, round figures)

| | Cycles |
|---|---|
| Whole frame | 19,656 |
| All IRQs with 24 sprites | up to 4,000 |
| `mux_update`: average with no flicker / worst flicker frame measured | about 4,300 / about 12,300 |
| **Left for the game, promised in every frame** | **7,200** (about 6,400 in the README's [one exception](README.md#the-v1-promise-and-its-one-exception)) |
| Left for the game in a normal frame | about 11,600 |
| `jsr input_read` / `jsr rng_next`, whole call, no DMA | 40 / 42 |
| `jsr collision_begin` / a target rejected / a target tested / `jsr collision_one` | 95 / 17 / 39 / up to 52 |
| `lda #` + `jsr sfx_play`: nothing pending / replacing / keeping, no DMA | 36 / 51 / 39 |
| The sound tick (`jsr sfx_update` in the `$FB` handler): idle / three slides / three starts | 56 / 214 / 429, + 6 more in `irq_exit` when it ends past line 255 |
| A chain entry of your own | 93 + its work |

Budget the game against 7,200, sound included. A **long** routine (thousands of cycles) that runs
through the display costs about 1.27 times its CPU count, up to 1.36 across a row of 8 sprites. A
**short** one (up to a few hundred) doesn't scale: it either misses every badline or loses a whole
one, so budget CPU + 43 + (2 × sprites + 3) for each line it touches, or better, run it in the
border ([Swarm's table](../docs/games/swarm/memory-map.md#short-routines-in-the-display)). A
routine's profile span leaves out its `jsr` and `rts` (12):
[Which span a figure is](README.md#which-span-a-figure-is).

**Frames that aren't frames of play.** A frame in which the state machine sets something up (a
new game, a formation re-parked) can run thousands of cycles of set-up before the routines the
border rows assume come first. Budget such a frame as a whole, not row by row, and only if
nothing that makes a frame of play expensive can be in it; measure its idle time, not just its
routines; and spread set-up that grows with the number of objects over several frames (Swarm:
[one-off frames](../docs/games/swarm/memory-map.md#one-off-frames)).

## 9. Limits ([v1 limits](README.md#v1-limits))

- **24 sprites, 4 pinned.** No expanded sprites, one screen for the sprite pointers.
- **Row spacing.** At most 8 sprites in any 25-line window show without flicker; a full row of 8
  directly below another needs **39 lines**. Exactly: a sprite at Y is shown every frame if at most
  7 others have Y within Y − 38 … Y + 25. Beyond that, unpinned sprites take turns: missing at
  most 2 frames running, 4 with 4 pinned sprites in the crowd (measured).
- **Bottom panel only.** For a panel starting on line P, `MUX_Y_MAX` = P − 22. No top panel, no
  splits in the play area.
- If the frame's work overruns, the previous frame's sprites are shown again: a stutter, never
  corruption.

## 10. Testing ([Budget files](README.md#budget-files))

- `make test` runs every `tests/**/budget.json`; `make test ARGS=<name>` runs one.
- The game's budget build is `tests/games/<title>/main.asm`: `#define AUTOPLAY`, then `#import`
  the game, which then plays its worst case with no stick. Put `name:` and `name_end:` (on the
  final `rts`) around each budgeted routine, and keep the DEBUG overrun count and idle minimum.
- Stick-driven behaviour is checked by a script beside the budget file (Swarm:
  `tests/games/swarm/check.py`). `make test` runs it as a `script` check in the budget file
  (DEBUG build); run it by hand with `--prg` on the release build.
- **A budget build in which nothing dies can't measure what dying costs**, and a scripted run
  doesn't place a worst frame. Those are measured on the game's DEBUG build, with the state set
  through the monitor, by a script beside the budget file whose output is committed (Swarm:
  `tests/games/swarm/stage3_costs.py`).
- **A sampled maximum of a routine that runs in the display is a look, not a bound**: it lands on
  a different raster line every frame. Its limit is the counted worst case; a border routine's
  sampled maximum is its maximum once the samples cover its own state's cycle.
- A failing budget check is reported with the measured figure. Limits aren't edited to pass.
- `"stage"` and `from_stage` are whole numbers: a stage built in parts can't switch on half its
  checks. Number a new game's stages in tens; Swarm's way round it is in its
  [memory map](../docs/games/swarm/memory-map.md#labels-the-game-must-provide).
