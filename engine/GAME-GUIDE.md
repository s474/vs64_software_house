# What a game needs from the engine

One page for a gameplay engineer starting a game on engine v1. **This is a guide, not a source of
truth**: every figure is copied from [README.md](README.md) or a module contract
([input.md](input.md), [rng.md](rng.md), [collision.md](collision.md), [sfx.md](sfx.md)), and if
they disagree, they are right and this page gets fixed. Read the game's own
`docs/games/<title>/memory-map.md` first; a worked example is `games/swarm/src/main.asm`.

## 1. Imports, in this order

```
BasicUpstart2(start)
#import "zp.asm"                        // every zero-page label below
.const MUX_SCREEN = $0400               // before the multiplexer import
.const MUX_Y_MAX  = 221                 // largest sprite Y shown: 80-249
* = $0810 "Engine"                      // allow about 6 KB (6,045 bytes measured, DEBUG)
#import "engine/irq.asm"
#import "engine/multiplexer.asm"
#import "engine/input.asm"              // 32 bytes
#import "engine/rng.asm"                // 37 bytes
        IrqChainBegin()
        IrqNormal(MUX_TOP_LINE, mux_irq_top)    // entry 0 is always this, at line 16
        IrqNormal($fb, game_irq_bottom)         // entry 1, line 251: sound, later music
        IrqChainEnd()
```

`collision.asm` and `sfx.asm` are contracts only until the README's status table says otherwise.
Chain: 1–16 entries, ascending lines 0–255, each handler ends with `IrqDone()`; with the
multiplexer, none before line 16 and none from there to `MUX_Y_MAX + 2` (`+ 3` when `MUX_Y_MAX` is
243 or less): [Declaring the chain](README.md#declaring-the-chain), [Raster timeline](README.md#raster-timeline).

## 2. Zero page the game's `zp.asm` must define

| Labels | Used by | Game code may |
|---|---|---|
| `zp_tmp0`–`zp_tmp3` | `mux_update` (scratch) | Use them in the main loop, never across a `jsr mux_update`, never in an IRQ |
| `zp_irq_idx`, `zp_mux_front`, `zp_mux_ready`, `zp_mux_slot`, `zp_mux_end` | IRQ framework, multiplexer | Not touch them |
| `zp_irq_frame` | Frame counter, +1 at entry 0 | Read it |
| `zp_joy`, `zp_joy_pressed` | `input.asm` | Read them in the main loop. No IRQ handler reads `zp_joy_pressed` |
| `zp_rng_lo`, `zp_rng_hi` | `rng.asm` | Not touch them |

One byte each; any free addresses. Suggested block: [Zero page](README.md#zero-page).

## 3. Start-up and the main loop

```
start:  ...                     // anything needing sei or a $01 write: here, before irq_init
        jsr mux_init            // hides all 24 sprites
        ...                     // write mux_flags once, all 24 entries
        jsr input_init
        jsr rng_seed            // A = low, X = high
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

## 5. Rules that must not be broken

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

## 6. What it costs, and what is left (raster cycles a frame, PAL, DEBUG, round figures)

| | Cycles |
|---|---|
| Whole frame | 19,656 |
| All IRQs with 24 sprites | up to 4,000 |
| `mux_update`: average with no flicker / worst flicker frame measured | about 4,300 / about 12,300 |
| **Left for the game, promised in every frame** | **7,200** (about 6,400 in the README's [one exception](README.md#the-v1-promise-and-its-one-exception)) |
| Left for the game in a normal frame | about 11,600 |
| `jsr input_read` / `jsr rng_next`, whole call, no DMA | 40 / 42 |
| A chain entry of your own | 93 + its work |

Budget the game against 7,200, sound included. Code that runs through the display costs about
1.27 times its CPU count; a routine's profile span leaves out its `jsr` and `rts` (12):
[Which span a figure is](README.md#which-span-a-figure-is).

## 7. Limits ([v1 limits](README.md#v1-limits))

- **24 sprites, 4 pinned.** No expanded sprites, one screen for the sprite pointers.
- **Row spacing.** At most 8 sprites in any 25-line window show without flicker; a full row of 8
  directly below another needs **39 lines**. Exactly: a sprite at Y is shown every frame if at most
  7 others have Y within Y − 38 … Y + 25. Beyond that, unpinned sprites take turns: missing at
  most 2 frames running, 4 with 4 pinned sprites in the crowd (measured).
- **Bottom panel only.** For a panel starting on line P, `MUX_Y_MAX` = P − 22. No top panel, no
  splits in the play area.
- If the frame's work overruns, the previous frame's sprites are shown again: a stutter, never
  corruption.

## 8. Testing ([Budget files](README.md#budget-files))

- `make test` runs every `tests/**/budget.json`; `make test ARGS=<name>` runs one.
- The game's budget build is `tests/games/<title>/main.asm`: `#define AUTOPLAY`, then `#import`
  the game, which then plays its worst case with no stick. Put `name:` and `name_end:` (on the
  final `rts`) around each budgeted routine, and keep the DEBUG overrun count and idle minimum.
- Stick-driven behaviour is checked by a script beside the budget file (Swarm:
  `tests/games/swarm/check.py`), on DEBUG and release.
- A failing budget check is reported with the measured figure. Limits aren't edited to pass.
