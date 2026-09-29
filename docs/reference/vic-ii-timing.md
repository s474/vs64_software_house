# VIC-II timing

How much CPU time a frame really has, and where the VIC-II takes it away. Figures marked
**measured** were verified in VICE 3.10 (x64sc, PAL) with
[tests/timing/badline](../../tests/timing/badline/main.asm) and `vice_profile` on 2026-09-29.
If you rely on a figure that isn't marked, measure it before you build on it.

## Frame geometry

| | PAL (6569), **our target** | NTSC (6567R8) | Old NTSC (6567R56A) |
|---|---|---|---|
| Raster lines per frame | 312 (0–311) | 263 | 262 |
| CPU cycles per line | 63 | 65 | 64 |
| CPU cycles per frame | **19,656** | 17,095 | 16,768 |
| CPU clock | 985,248 Hz | 1,022,727 Hz | 1,022,727 Hz |
| Frames per second | 50.125 | 59.826 | 60.99 |

- Raster line 256 and up need bit 8: `$D011` bit 7 (read = current line bit 8, write = compare bit 8).
- The 320×200 display window with 25 rows (`RSEL`=1, `$D011` bit 3) and the default
  `YSCROLL`=3 covers raster lines 51–250 ($33–$FA). With 24 rows (`RSEL`=0) it's 55–246.
- Sprite Y coordinates are raster lines: a sprite at Y is displayed from line Y+1, so
  Y=50 lines up with the first text row.
- VICE's normal PAL frame is 384×272: 32 px of side border and 36 lines of top and bottom border
  around the 320×200 window (this is what `vice_screenshot` returns by default).

## Badlines

On a badline the VIC-II fetches the next text row's 40 screen codes and colours and holds
the CPU off the bus to do it.

**When:** a raster line is a badline if all of these are true:

1. It's in the range $30–$F7 (48–247).
2. Its low 3 bits equal `YSCROLL` (`$D011` bits 0–2).
3. `DEN` (`$D011` bit 4, display enable) was set at some point during line $30.

That gives one badline per text row: 25 per frame with the default settings.

**Cost:** 40 cycles of fetches, plus 3 cycles of warning beforehand (the VIC-II pulls BA low
3 cycles early, and the CPU stops at its next read cycle). A CPU doing only reads loses all
43; one in the middle of up to 3 write cycles keeps running for those.

- **Measured: 43 cycles stolen** from a stream of `NOP`s. The CPU gets **20** of the line's 63 cycles.
- Per frame: 25 × 43 = **1,075 cycles** (5.5% of a PAL frame) with the screen on.

**Levers:**

- Clearing `DEN` removes badlines, but only from the next frame: the bit is sampled during
  line $30. (**Measured:** clearing it mid-frame left that frame's badlines in place.)
- Changing `YSCROLL` moves badlines. Repeatedly pushing them away is the basis of FLD, and
  forcing them is the basis of FLI and similar tricks.
- The border lines (below 48 and above 247) never have badlines. They're the cheapest place
  for heavy per-frame work such as music, sorting and game logic.

## Sprite DMA

A sprite whose DMA is active on a line costs CPU time on that line. That's every line it's
displayed on (21, or 42 if Y-expanded), whether or not it's under the border.

The VIC-II fetches sprites in order 0→7: sprites 0–2 at the end of a raster line and 3–7 at the
start of the next. Each active sprite costs **2 cycles**, and each *group* of consecutive fetches
costs **3 more** for the BA warning. The VIC-II keeps the bus across a gap of one unused
sprite (so 0 and 2 behave like 0, 1, 2), but a gap of two or more starts a new group.

| Sprites active on the line | **Measured** cycles stolen |
|---|---|
| 0 | 5 |
| 0, 1 | 7 |
| 0, 2 | 9 (gap bridged: counts as 0–2) |
| 0, 3 | 10 (two groups: 5 + 5) |
| 0–7 | 19 (8 × 2 + 3) |

**Implications:**

- Assign sprite numbers in **consecutive runs** (e.g. a multiplexer fills 0, 1, 2… in order), never
  scattered.
- 8 sprites on a line cost 19 of its 63 cycles. On a line that is **also a badline**, the CPU is left
  with almost nothing: expect single-digit cycles, and measure if code has to run there.
- A band of 8 sprites costs about 21 × 19 = 399 cycles per frame. A 32-sprite multiplexer
  (4 bands) costs about 1,600 cycles in DMA alone, before any multiplexer code runs.

## Frame budget worked example (PAL)

| Item | Cycles |
|---|---|
| Whole frame | 19,656 |
| Badlines, screen on | −1,075 |
| 8 sprites × 21 lines | −399 |
| **Left for all code** | **≈18,180** |

Code that must finish within a region of the screen, such as an IRQ between two splits, has
to fit into the region's lines × 63 minus the DMA on those lines.

## Measuring instead of guessing

Raster time is what counts, and `vice_profile(start, end)` measures exactly that: it reports
cycles elapsed on the raster between two labels, including everything the VIC-II stole. Stolen
cycles = raster time − the code's own cycle count
(see [6502-timing.md](6502-timing.md)). To isolate one effect, remove the others first: blank the
screen (then run a frame so DEN is resampled), move sprites into the border, or disable them.
