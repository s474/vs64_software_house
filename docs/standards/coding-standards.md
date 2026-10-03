# Coding standards

Rules for all 6502 code in this repo. Reviewers check against this page.

## Files and structure

- One program = one `main.asm` that `#import`s everything else.
- Game code lives in `games/<title>/src/`. Code that more than one game could use goes in `engine/`
  as a module with a short header explaining its API, cost and constraints.
- A file owns one subsystem (`player.asm`, `enemies.asm`, `irq.asm`). Keep files under about 500 lines.
- Every routine starts with a header comment:

```
// Move all active enemies one step along their paths.
// In:  nothing       Out: nothing
// Uses: A, X, Y, zp_tmp0-1
// Cost: 40 + 38/enemy cycles (measured, 8 enemies: 344)
enemies_update:
```

## Naming

| Kind | Style | Example |
|---|---|---|
| Labels and routines | `snake_case`, prefixed by subsystem | `player_update`, `enemy_spawn` |
| Scoped labels | `{ }` block, used as `scope.name` | `irq.top` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_ENEMIES`, `VIC_BORDER` |
| Zero-page labels | `zp_` prefix | `zp_ptr_lo` |
| Macros | `PascalCase` | `SetBorder(RED)` |
| Local loop labels | multi-labels | `!loop:` … `bne !loop-` |

Use named constants for hardware registers (`VIC_BORDER = $d020`), not bare addresses, except
in the tiniest examples.

## Zero page

Zero page is scarce and shared, so it is **allocated, never grabbed**:

- Each game has exactly one file, `games/<title>/src/zp.asm`, that declares every zero-page
  location with `.label`, grouped by owner, with a comment for each.
- Engine modules document the zero page they need. The game's `zp.asm` assigns it.
- `$00/$01` are the processor port: never used for data.
- Scratch registers `zp_tmp0`–`zp_tmp7` may be used by any routine that doesn't call another routine
  while holding them (exception: across a call to a routine documented as using no zero page, such as
  `sfx_play`, which is how a caller keeps a register it clobbers), and **never inside IRQ handlers** (an IRQ could interrupt a routine using them).
  IRQ handlers get their own `zp_irq_*` locations.
- The game's memory map doc lists the zero-page ranges.

## IRQ ownership

- Only the IRQ framework (`engine/irq.asm` once it exists; until then, one clearly marked file per
  game) writes `$FFFE/$FFFF`, `$FFFA/$FFFB`, `$D012`, `$D019`, `$D01A`, `$DC0D/$DD0D`, and the
  raster-compare bit of `$D011`. Its API and rules are in [engine/README.md](../../engine/README.md#irq-framework-engineirqasm).
- Every other write to `$D011` keeps **bit 7 clear** (`and #$7f`): chain lines are 0–255.
- `$01` stays `$35` whenever interrupts are enabled. Code that needs `$34` (RAM under I/O) runs
  with interrupts off, at init time or where no IRQ is due.
- Each game has a **raster timeline** in its memory map doc: every handler's start line, job and
  measured worst-case cost.
- With `engine/irq.asm`, the framework saves and restores A, X and Y, clears `D`, and acknowledges
  `$D019`; handlers do neither and end with `IrqDone()`. Without it (older code such as `hello`),
  handlers save and restore every register they touch (KERNAL-out mode), and acknowledge `$D019`.
- Anything shared between an IRQ and the main loop (flags, counters, buffers) is documented as such.
  Multi-byte values written by an IRQ are read with interrupts off, or double-buffered.

## Timing-critical code

- Mark it with `// TIMING:` at the top, with the budget (e.g. `// TIMING: must finish within lines $F8-$FF, 504 cycles`).
- Every line carries its cycle count, and loops state their per-iteration and total cost
  ([6502-timing.md](../reference/6502-timing.md)).
- Tables read in timing-critical loops are `.align $100`ed so page crossings can't add cycles.
- The claimed cost must be **measured** with `vice_profile` before the work is called done, and the
  measured figure goes in the routine header.

## Memory

- Every game keeps `docs/games/<title>/memory-map.md` up to date
  ([template](memory-map-template.md)). Changing the layout means changing the doc in the same commit.
- Use `* = $xxxx "Name"` for each block so `-showmem` output is readable, and `.errorif` to guard
  limits (e.g. code running into graphics).

## Verification ("done" means all of these)

1. `make GAME=<title>` builds with no errors or warnings.
2. The change was **seen working in VICE** through the MCP tools: a screenshot in `screenshots/`
   named after the task (e.g. `screenshots/enemy-spawn-wave2.png`), and memory reads for state.
3. Timing-critical code has a measured cost within its budget.
4. The memory map and raster timeline docs are updated if anything moved.
5. If `mcp/vice` changed: `cd mcp/vice && uv run smoke_test.py` passes.
6. If engine code changed: `make test` passes (or its `budget.json` is deliberately re-baselined).

Report what you verified and how, including the screenshot paths. "Should work" is not done.
