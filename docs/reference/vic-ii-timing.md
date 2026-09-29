# VIC-II timing

How much CPU time a frame really has, and where the VIC-II takes it away. Every figure below is
marked either **measured**, with the probe that shows it, or *unmeasured*, meaning it's the
standard figure but nobody here has verified it. Measurements were made in VICE 3.10 (x64sc,
PAL) on 2026-09-29. Each probe's header comment has the exact steps to rerun it and the results
it gave:

| Probe | Measures |
|---|---|
| [tests/timing/rasterline](../../tests/timing/rasterline/main.asm) | Cycles per line and per frame, with a CIA timer |
| [tests/timing/badline](../../tests/timing/badline/main.asm) | Badline steal on a free-running `NOP` stream |
| [tests/timing/badline_writes](../../tests/timing/badline_writes/main.asm) | Badline steal while the CPU runs write cycles (`INC abs`, `JSR`) |
| [tests/timing/sprites](../../tests/timing/sprites/main.asm) | Sprite DMA per line; sprites and a badline on the same line |
| [tests/timing/sprites/trace_badline.py](../../tests/timing/sprites/trace_badline.py) | Instruction trace: which cycles of the badline the CPU actually gets |

If you rely on a figure marked *unmeasured*, measure it before you build on it.

## Frame geometry

| | PAL (6569), **our target** | NTSC (6567R8) | Old NTSC (6567R56A) |
|---|---|---|---|
| Raster lines per frame | **312** (0–311), measured | 263, *unmeasured* | 262, *unmeasured* |
| CPU cycles per line | **63**, measured | 65, *unmeasured* | 64, *unmeasured* |
| CPU cycles per frame | **19,656**, measured | 17,095, *unmeasured* | 16,768, *unmeasured* |
| CPU clock | 985,248 Hz, *unmeasured* | 1,022,727 Hz, *unmeasured* | 1,022,727 Hz, *unmeasured* |
| Frames per second | 50.125 (clock ÷ 19,656), *unmeasured* | 59.826, *unmeasured* | 60.99, *unmeasured* |

- **Measured (tests/timing/rasterline):** CIA1 timer A, which counts every clock cycle whether
  or not the VIC-II has the bus, gave 12,598 cycles for 200 raster lines (200 × 63 = 12,600)
  and 19,655 for one frame (312 × 63 = 19,656). The −2/−1 is a constant from the CIA's start/stop
  latency and the poll phase. All 8 samples were identical. At 64 or 65 cycles per line the
  200-line result would have been 12,800 or 13,000.
- `vice_profile` assumes 63 cycles and 312 lines when it turns raster positions into cycles, so
  it can't measure these two figures itself. The CIA measurement above is what justifies it.
- Raster lines 256 and up need bit 8, which is `$D011` bit 7 (read: bit 8 of the current line;
  write: bit 8 of the compare line). *Unmeasured* as a stand-alone fact, but every probe's
  `WaitFrameStart` relies on reading it and they all synchronise correctly.
- The 320×200 display window with 25 rows (`RSEL`=1, `$D011` bit 3) and the default
  `YSCROLL`=3 covers raster lines 51–250 ($33–$FA). With 24 rows (`RSEL`=0) it's 55–246. *Unmeasured.*
- Sprite Y coordinates are raster lines: a sprite at Y is displayed from line Y+1, so Y=50
  lines up with the first text row. *Unmeasured.*
- VICE's normal PAL frame is 384×272: 32 px of side border and 36 lines of top and bottom border
  around the 320×200 window. This is what `vice_screenshot` returns by default. Checked pixel for
  pixel against `x64sc -exitscreenshot` (see `BORDER_LEFT` in `mcp/vice/server.py`).

## Badlines

On a badline the VIC-II fetches the next text row's 40 screen codes and colours and holds
the CPU off the bus to do it.

**When:** a raster line is a badline if all of these are true (*unmeasured* as rules, but the
probes find badlines exactly where they predict: $33, $3B and $43 with `YSCROLL`=3):

1. It's in the range $30–$F7 (48–247).
2. Its low 3 bits equal `YSCROLL` (`$D011` bits 0–2).
3. `DEN` (`$D011` bit 4, display enable) was set at some point during line $30.

That gives one badline per text row: 25 per frame with the default settings.

**Cost:** 40 cycles of fetches, plus 3 cycles of warning beforehand. The VIC-II pulls BA low
3 cycles early, and the CPU stops at its next read cycle, so write cycles in progress keep running.

| CPU is running… | **Measured** cycles stolen | Probe |
|---|---|---|
| Reads only (`NOP` stream) | **43**, every pass | tests/timing/badline; tests/timing/badline_writes `nop_bl` |
| `INC abs` stream (2 consecutive writes per 6 cycles) | **41–43**, depending on phase (avg 42.3 over 128 passes) | tests/timing/badline_writes `inc_bl` |
| `JSR`/`RTS` stream (2 consecutive writes per 12 cycles) | **41–43**, depending on phase (avg 42.8 over 128 passes) | tests/timing/badline_writes `jsr_bl` |
| 3 consecutive writes (`BRK`, IRQ/NMI entry) | 40 expected, *unmeasured* | |

- **Measured: the CPU gets 20 of the badline's 63 cycles** with no sprites (63 − 43). The
  instruction trace confirms it directly: 20 CPU cycles executed on line 51 in 32 of 32 passes.
- **Measured (trace, VICE cycle numbering):** the CPU is halted for 43 consecutive cycles,
  from cycle 12 or 13 of the badline (depending on how instructions line up) to cycle 54 or 55.
  It runs in cycles 0–11 and 55/56–62.
- The worst case is 43, and the only way to get less is to be in the middle of write cycles, so
  budget 43. The write cases only matter for cycle-exact code that crosses a badline.
- Per frame: 25 × 43 = **1,075 cycles** (5.5% of a PAL frame) with the screen on, worked out
  from the measured 43.

**Levers:**

- Clearing `DEN` removes badlines, but only from the next frame, because the bit is sampled
  during line $30. Recorded earlier as measured (clearing it mid-frame left that frame's badlines
  in place), but the steps weren't written down. *Rerun this to confirm* before depending on it.
- Changing `YSCROLL` moves badlines. Repeatedly pushing them away is the basis of FLD, and
  forcing them is the basis of FLI and similar tricks. *Unmeasured.*
- The border lines (below 48 and above 247) never have badlines. They're the cheapest place
  for heavy per-frame work such as music, sorting and game logic. **Measured:** the probes'
  control blocks on line 16 run at exactly their CPU cycle count.

## Sprite DMA

A sprite whose DMA is active on a line costs CPU time on that line. That's every line it's
displayed on, whether or not the line is under the border. **Measured:** sprites on lines 17–37,
all in the top border, cost exactly what the table below says (tests/timing/sprites `spr_blk`).
The number of DMA lines per sprite (21, or 42 if Y-expanded) is *unmeasured*.

The VIC-II fetches sprites in order 0→7: sprites 0–2 at the end of a raster line and 3–7 at the
start of the next. **Measured (trace):** sprites 0–2 halt the CPU at the end of the line (it
resumes at cycle 0 or 1), and sprites 3–7 until cycle 10 of the next line. Each active sprite costs **2 cycles**, and each *group* of consecutive fetches
costs **3 more** for the BA warning. The VIC-II keeps the bus across a gap of one unused
sprite (so 0 and 2 behave like 0, 1, 2), but a gap of two or more starts a new group.

All figures below are **measured with tests/timing/sprites** (`spr_blk`, max − 40 over 96
passes, in the border so no badline is involved):

| Sprites active on the line | Cycles stolen |
|---|---|
| 0 | **5** |
| 0, 1 | **7** |
| 0, 2 | **9** (gap bridged: counts as 0–2) |
| 0, 3 | **10** (two groups: 5 + 5) |
| 3–7 | **13** (5 × 2 + 3) |
| 0–7 | **19** (8 × 2 + 3) |

- **Measured (trace):** with sprites 0–7 the CPU is halted from cycle 55 of one line to cycle 10
  of the next (19 cycles), so a non-badline with 8 sprites leaves the CPU **44** cycles (11–54).
- **Measured:** a 126-cycle window through sprite lines costs 126 + 3 × the per-line figure
  (sprite 0: 136, sprites 0–7: 183). DMA adds up linearly from line to line.

**Implications:**

- Assign sprite numbers in **consecutive runs** (e.g. a multiplexer fills 0, 1, 2… in order), never
  scattered.
- A band of 8 sprites costs about 21 × 19 = 399 cycles per frame (19 is measured; the 21 lines
  are *unmeasured*). A 32-sprite multiplexer (4 bands) costs about 1,600 cycles in DMA alone,
  before any multiplexer code runs.

## Badline and sprites on the same line

The steals add up exactly, with no overlap. The badline has **no free cycles at all** when
sprites 0–7 are on it and on the lines either side.

**Measured with tests/timing/sprites**: `bls_blk`, 126 CPU cycles across badline 51 with the
sprites on lines 41–61. The last column comes from `trace_badline.py` over 32 passes.

| Sprites active | Window steal (`vice_profile`) | Breakdown | CPU cycles on the badline (trace) |
|---|---|---|---|
| none | 43 | badline | **20** |
| 0 | 58 | 43 + 3 × 5 | **15** |
| 0–2 | 70 | 43 + 3 × 9 | **10–12** |
| 3–7 | 82 | 43 + 3 × 13 | **6–8** |
| 0–7 | 119 | 43 + 4 × 19 | **0–2** |

- With sprites 0–7 the CPU is halted for **81 consecutive cycles** (19 + 43 + 19): from cycle
  55/56 of the line before the badline to cycle 10 of the line after. The only gap is cycles
  11–12 of the badline. The CPU gets those 2 cycles when an instruction happens to start at
  cycle 11, and none otherwise (16 of 32 passes each).
- The ranges in the last column come from the trace's 2-cycle `NOP`s: an instruction can't use
  one lone free cycle. Real code gets no more than that.

```mermaid
flowchart LR
    A["Line 50, cycles 55–62<br/>sprites 0–2: BA warning + fetch"] --> B["Line 51 (badline), cycles 0–10<br/>sprites 3–7 fetch"]
    B --> C["Cycles 11–12<br/>CPU: 0 or 2 cycles"]
    C --> D["Cycles 12/13–54<br/>BA warning + 40 screen/colour fetches"]
    D --> E["Cycles 55–62<br/>sprites 0–2: BA warning + fetch"]
    E --> F["Line 52, cycles 0–10<br/>sprites 3–7 fetch"]
    F --> G["Cycle 11 on<br/>CPU runs again"]
```

Cycle numbers are VICE's raster cycle (the `CYC` that `vice_registers` reports).

**What this means for raster code:** don't schedule any work on a badline that also has
sprites 0–7 active. An IRQ that becomes due there is delayed until the CPU gets the bus back,
up to 81 cycles later. Put timing-critical writes on non-badlines, or in the border.

## Frame budget worked example (PAL)

| Item | Cycles | Basis |
|---|---|---|
| Whole frame | 19,656 | Measured (rasterline) |
| Badlines, screen on | −1,075 | 25 × measured 43 |
| 8 sprites × 21 lines | −399 | Measured 19 × *unmeasured* 21 lines |
| **Left for all code** | **≈18,180** | |

Code that must finish within a region of the screen, such as an IRQ between two splits, has
to fit into the region's lines × 63 minus the DMA on those lines.

## Measuring instead of guessing

Raster time is what counts, and `vice_profile(start, end)` measures exactly that: it reports
cycles elapsed on the raster between two labels, including everything the VIC-II stole. Stolen
cycles = raster time − the code's own cycle count
(see [6502-timing.md](6502-timing.md)). To isolate one effect, remove the others first: blank the
screen (then run a frame so DEN is resampled), move sprites into the border, or disable them.

Pitfalls found while building the probes:

- **Don't put the `end` label on a busy-wait loop.** The profiler stops every time the loop
  runs and uses up its stop budget ("No complete start->end passes"). Put one instruction,
  such as a `nop`, between the end label and the loop.
- **To vary where an effect lands in a block, add the delay *before* the raster poll.** A delay
  placed only after a `lda $d012 / cmp / bne` poll is mostly cancelled: the poll's 9-cycle exit
  grid moves with it. That's how the first `JSR` run showed 43 on every pass.
- `vice_profile` reports only min/avg/max. To see *where* in a line the CPU is halted, trace
  it instruction by instruction the way `tests/timing/sprites/trace_badline.py` does.
