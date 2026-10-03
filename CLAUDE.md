# C64 Software House

An AI-assisted studio making commercial-quality Commodore 64 games that push the hardware.
The human (Simon) is creative director and playtester. The overall plan and milestones are in
[C64_SOFTWARE_HOUSE.md](C64_SOFTWARE_HOUSE.md).

Target: **PAL C64** (6510 + VIC-II 6569 + SID), KickAssembler 5.25, VICE 3.10 (`x64sc`).

## Commands

| Task | Command |
|---|---|
| Build a game | `make GAME=<title>` → `build/<title>/<title>.prg` (default `GAME=hello`) |
| Build something outside `games/` | `make GAME=<name> SRC_DIR=<dir>` |
| Run in VICE for a human | `make run GAME=<title>` |
| Release build | `make BUILD=release GAME=<title>` (no `DEBUG` define) |
| Ship a release | `make release GAME=<title>` → `dist/<title>/<title>.d64` (+ `-sfx.prg`, `.prg`, `main.vs`); release build in its own `build/<title>-release/`, Exomizer-crunched. `make crunch` / `make d64` are aliases |
| Verify a release | `make test-release GAME=<title>` (builds it, checks the d64 directory, boots the d64 and the crunched PRG in headless VICE to the title) |
| Draft a GitHub release | `make publish GAME=<title> TAG=<tag> [DRY_RUN=1]`: refuses unless the tree is clean, HEAD is pushed and `make test-release` passes; then an annotated tag (that one tag pushed), a **draft** release with the d64 and crunched PRG, and a kept copy in `releases/<tag>/`. Simon publishes the draft. `DRY_RUN=1` changes nothing |
| Behaviour test of a game | `uv run --package gametest python tests/games/<title>/check.py [--prg …] [--only CASE] [--list] [--results FILE]` (Swarm's: about 1 min; also run by `make test`) |
| Test the tools | `make test-tools` (pytest for every Python project under `tools/`) |
| Check engine budgets in VICE | `make test` (builds each `tests/**/budget.json` spike, runs it headless, fails on an overrun; `make test ARGS=irq_chain` for one). `uv run budget-runner --no-build -v <spike>` also prints each profile check's premise: where it starts and ends on screen, and IRQs inside |
| Long budget run (soak) | `make test-long` (every sample/frame count x 34, ~30 min for the multiplexer; `make test-long LONG_SCALE=10 ARGS=multiplexer` for another factor or one spike). For milestone sign-off, not every change |
| Test the VICE MCP server | `cd mcp/vice && uv run smoke_test.py` |
| Set up / refresh the Python environment | `uv sync --all-packages` (one workspace: root `.venv` and `uv.lock`) |

Build outputs in `build/<title>/`: `.prg`, `main.vs` (labels), `main.dump` (address of every source line).
`make clean` and VS64's clean delete all of `build/`, so **scripts or data you'll need again go in
`tests/` or `tools/`, never `build/`** (stage 3's long-run scripts were lost that way).

## Layout

| Path | Contents |
|---|---|
| `games/<title>/src/main.asm` | Each game's single entry file; imports the rest |
| `engine/` | Shared, reusable modules (import as `#import "engine/x.asm"`: the repo root is on the include path) |
| `tests/timing/` | Timing probes backing the figures in the reference docs |
| `docs/reference/` | C64 hardware facts: **read before writing hardware code** |
| `docs/standards/` | Coding standards, memory-map template |
| `docs/games/<title>/` | Per game: design doc, memory map, raster timeline |
| `mcp/vice/` | VICE MCP server (Python, uv project) |
| `tools/` | Python asset converters and utilities: `png2sprites/`, `budget-runner/`, `release-check/` (also `make publish`), `gametest/` (game behaviour tests: rig, case runner, clean-state guard) (uv workspace members, never system pip) |
| `screenshots/` | Git-ignored. All screenshots and visual output go here |
| `dist/<title>/` | Git-ignored. Release disk images and crunched PRGs; survives `make clean`, overwritten by the next release build |
| `releases/<tag>/` | Git-ignored. A kept copy of every published release, by tag; never overwritten |

## Reference docs

- [vic-ii-timing.md](docs/reference/vic-ii-timing.md): frame geometry, badlines (43 cycles, measured), sprite DMA, frame budget
- [memory-map.md](docs/reference/memory-map.md): `$01` banking, VIC banks, `$D018`, zero page, typical game layout
- [raster-interrupts.md](docs/reference/raster-interrupts.md): IRQ setup, chaining, jitter, common bugs
- [6502-timing.md](docs/reference/6502-timing.md): cycle counts, page crossings, illegal opcodes
- [kickassembler.md](docs/reference/kickassembler.md): how we build and the syntax we use
- [sid.md](docs/reference/sid.md): SID registers, what can and can't be read back, frequency and envelope (measured in VICE's 8580), late starts, what only ears can check
- [coding-standards.md](docs/standards/coding-standards.md): naming, zero page, IRQ ownership, **definition of done**
- [engine/GAME-GUIDE.md](engine/GAME-GUIDE.md): **start here for a game**: how to use the engine, its rules, limits and costs, on a few pages
- [engine/README.md](engine/README.md): the engine in full: IRQ framework, multiplexer, input, rng, collision and sound effects, zero page, raster timeline, frame budget

If a doc is wrong or missing something you had to find out, fix the doc in the same change, and
mark measured facts as measured (with the probe that shows it).

## Working rules

- **Verify in VICE, don't assume.** Use the `vice_*` MCP tools: `vice_start` the build,
  `vice_run_frames` / `vice_joystick` to drive it, `vice_screenshot` to see it, `vice_read_memory` to
  check state, and `vice_profile` for any timing claim. Addresses accept labels from the build.
- **Call `vice_stop` when you've finished with VICE.** The emulator belongs to the session's MCP
  server, not to you, so otherwise it keeps running after you've reported.
- Screenshots: always pass a descriptive `name`; they land in `screenshots/`. Mention the paths
  when reporting (as relative Markdown links).
- Follow the [definition of done](docs/standards/coding-standards.md#verification-done-means-all-of-these)
  and report what was verified and how.
- Timing figures come from measurement ([vic-ii-timing.md](docs/reference/vic-ii-timing.md)), not memory.
  If a number isn't in the docs, measure it and add it.
- Zero page is allocated in each game's `zp.asm`. Only the IRQ framework touches the IRQ vectors and `$D012`.
- Python: one **uv workspace** rooted at `pyproject.toml` (members `mcp/vice`, `tools/png2sprites`, `tools/budget-runner`, `tools/release-check`, `tools/gametest`), with a single `uv.lock` and `.venv/` at the repo root. Add a dependency with `uv add --package <member> <pkg>`, run with `uv run` (from the root, or from inside a member's directory: both use the root `.venv`). A new Python project is added to `[tool.uv.workspace] members`. Never `pip install` into the system Python.
- **Stay in your role.** Agents change only the files their role owns (see the team table below).
  For anything else, report what's needed and the producer assigns it to the owner.
- Diagrams in docs are Mermaid.
- Git: commit and push only when Simon asks. Never commit `build/`, `screenshots/` or `.venv/`.

## The team

Specialist subagents are in `.claude/agents/`:

| Agent | Use for |
|---|---|
| `technical-director` | Memory maps, raster timelines, frame budgets, architecture and feasibility calls, reviewing designs |
| `game-designer` | Game design docs: rules, entities, attack patterns and waves as data, difficulty, feel targets. No code |
| `raster-engineer` | Engine modules and cycle-exact display code: IRQ framework, stable rasters, multiplexers, effects |
| `gameplay-engineer` | Implementing game features in 6502: player, enemies, collisions, game loop |
| `tools-engineer` | Python converters, build tooling, test harnesses |
| `qa-tester` | Playing builds in VICE, regression checks, bug reports with screenshots |

The main session acts as producer: it breaks work into tasks, delegates to these agents, and
checks their reports against the definition of done.

Producer rules (from M4's lessons, [M4 brief](docs/milestones/M4-training-game.md#m4-result-and-lessons-signed-off-2026-10-03)):

- Every brief names who owns each file and measuring script it touches, and which builds a condition
  applies to. Agents working in parallel get disjoint files, and one agent at a time uses the VICE MCP emulator.
- A design tuning goes to the Technical Director before it is built.
- Art and sound are put to Simon to approve, with a preview; nothing is "approved" by default.
- Long runs (`make test-long`) are Simon's, in his terminal: background commands stop at 10 minutes.
