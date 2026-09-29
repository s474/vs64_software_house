# M3: Engine basics

The first milestone the team builds rather than the producer. It produces the studio's first
reusable engine modules, and the automated test that proves they fit their cycle budgets.
Everything after this (the M4 training game onwards) is built on it.

**Done when:** each module has a spike demo in `tests/engine/`, and `make test` runs every demo's
cycle-budget checks in VICE and passes, with no human in the loop.

## Decisions (agreed with Simon, 2026-09-29)

| Question | Options | Decision |
|---|---|---|
| Multiplexer size for v1 | 16 / **24** / 32 virtual sprites | **24**: enough for a busy shooter, and leaves room to find the limits before v2 |
| More than 8 sprites on one row | Drop the lowest-priority ones / **flicker them in turn** | **Flicker**: nothing vanishes permanently, which is what players notice most |
| Who writes engine code | Gameplay engineer / **a new `raster-engineer` agent** | **New agent**: cycle-exact IRQ and multiplexer work needs a different mindset from game logic (it's in the plan's role list) |

## Deliverables

### 1. IRQ framework: `engine/irq.asm`

- Machine setup: `$01=$35`, CIA interrupts off, NMI pointed at an `rti`, raster IRQ on.
  This replaces the boilerplate every program currently copies from `hello`.
- A **raster chain** defined as a table of (line, handler) pairs. The framework does the vector and
  `$D012` switching, acknowledgement, and register save/restore, so handlers only contain their work.
- A **stable raster** option for handlers that need exact-cycle timing (double IRQ, per
  [raster-interrupts.md](../reference/raster-interrupts.md#jitter-and-stable-rasters)).
- Documented cost: framework overhead per handler, in cycles, measured.

**Acceptance:**
- Spike `tests/engine/irq_chain/`: 4 handlers changing the border colour at 4 lines, with a screenshot.
- Normal handlers start within the measured jitter (≤ 7 cycles). Stable handlers start on the
  **same cycle every time** over 100 frames (checked with `vice_run_until`, which reports the raster cycle).
- Budget checks in `make test`.

### 2. Sprite multiplexer v1: `engine/multiplexer.asm`

- 24 virtual sprites (x, y, colour, frame), sorted by Y each frame (insertion sort: the list
  stays nearly sorted between frames, so it's cheap).
- The IRQ chain reuses the 8 hardware sprites down the screen, assigning them in consecutive runs
  (sprite DMA is cheapest that way: [vic-ii-timing.md](../reference/vic-ii-timing.md#sprite-dma)).
- More than 8 on a row: rotate which ones are shown, so they flicker rather than vanish.
- Documented, measured cost per frame: the sort, the IRQs, and the DMA, against the frame budget.

**Acceptance:**
- Spike `tests/engine/multiplexer/`: 24 sprites bouncing around the screen, with screenshots.
- `qa-tester` soak test: 10,000 frames with no crash or jam, and no sprite missing for more
  than 2 consecutive frames when ≤ 8 are on a row.
- Worst-case frame cost measured and within the budget the Technical Director sets.

### 3. PNG → sprite converter: `tools/png2sprites/`

- A uv project. Converts a PNG sprite sheet to a `.bin` of 64-byte sprites, in hires and multicolour.
- **Validates** C64 rules and fails with the file, sprite and pixel position: 24×21 cells (12×21 in
  multicolour), C64 palette colours only, at most 3 colours plus transparent per multicolour sprite,
  with the two shared colours consistent across the sheet.
- Tests: a good sheet converts byte-for-byte to the expected output, and each bad sheet fails with the right message.

**Acceptance:** the multiplexer spike's sprites come from a PNG through this tool, wired into `make`.

### 4. Cycle-budget test runner: `make test`

- A Python runner (using `mcp/vice/vice_monitor.py`) that builds each spike in `tests/engine/`,
  runs it in VICE, measures the declared routines, and fails if any exceeds its budget.
- Budgets live next to each spike, e.g. `tests/engine/multiplexer/budget.json`:
  `{"routine": ["mux_sort", "mux_sort_end"], "max_cycles": 1800}`, written by the Technical Director.
- Output: one line per check (measured / budget / pass or fail) and a non-zero exit on failure.

## Who does what

```mermaid
flowchart TD
    TD1["technical-director<br/>design: engine/README, IRQ and multiplexer APIs,<br/>zero page, raster timeline, budgets"] --> RE1["raster-engineer<br/>engine/irq.asm + irq_chain spike"]
    TD1 --> TE2["tools-engineer<br/>make test budget runner"]
    RE1 --> RE2["raster-engineer<br/>engine/multiplexer.asm + multiplexer spike"]
    TE1["tools-engineer<br/>tools/png2sprites"] --> RE2
    TE2 --> QA["qa-tester<br/>soak + visual checks"]
    RE2 --> QA
    QA --> TD2["technical-director<br/>review against budgets and standards"]
    TD2 --> S["Simon<br/>watch the demos, sign off M3"]
```

`png2sprites` and the budget runner don't depend on engine code, so the tools-engineer can do
them in parallel with the IRQ work.

## Running it

Each step is a prompt to the named agent in a fresh session. The producer (main session)
reviews each report against the definition of done before starting the next step.

1. *"technical-director: design the M3 engine per docs/milestones/M3-engine-basics.md. Write
   engine/README.md with the IRQ framework and multiplexer APIs, zero-page needs, raster timeline
   and budget.json files. Don't write the implementation."*
2. *"tools-engineer: build tools/png2sprites per the M3 brief."*
3. *"raster-engineer: implement engine/irq.asm and the irq_chain spike per engine/README.md."*
4. And so on, following the diagram.

**Parallel sessions:** agents working at the same time must touch different files, and commit only
their own paths (`git add <their files>`, never `git add -A`). If that gets awkward, use git worktrees,
as the plan describes.

## Out of scope for M3

Music player integration, scrolling, loaders and cartridge formats, and NTSC. They come later, as
engine modules of their own.
