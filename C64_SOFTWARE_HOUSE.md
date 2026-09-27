# C64 Software House — Plan

A plan for building a team of AI agents that works like a small software company and produces commercial-quality Commodore 64 games that push the hardware.

---

## 1. The short answer

**Don't start with a multi-agent framework. Start with a feedback loop.**

The thing that separates "AI writes some 6502 that probably works" from "AI ships a polished C64 game" isn't the number of agents. It's whether the agents can **build, run, look at, measure and test** what they wrote without you in the middle. So the order of work is:

1. **Toolchain.** A one-command build from source to `.prg`/`.d64`/`.crt`.
2. **Eyes and hands (MCP).** A small MCP server that lets agents drive the VICE emulator: load, run N frames, take a screenshot, read memory, press the joystick, count cycles.
3. **Knowledge.** A curated C64 reference library in the repo, because models make subtle mistakes about VIC-II timing.
4. **The team.** Role-specific Claude Code subagents plus skills, with the main Claude Code session as the orchestrator ("producer").
5. **Process.** Design docs, a vertical slice, and automated QA gates, kept in git.
6. **Scale up.** Parallel agents in git worktrees, and later a headless pipeline built on the Claude Agent SDK if you want it to run unattended.

Everything here uses tools you already have (VS Code, Claude Code). MCP is the only new technology, and it's smaller than it sounds (see §4).

---

## 2. Realistic expectations

| Area | How well AI agents do today | Implication |
|---|---|---|
| 6502 code, game logic, data structures | Good, with mistakes around cycle-exact code | Needs the emulator loop plus cycle audits |
| Raster tricks (stable IRQ, sprite multiplexing, FLD, FLI, open borders) | Knows the ideas; timing details are often off by a few cycles | Build each one as an isolated R&D spike, verified in VICE |
| Tooling (Python converters, build scripts, test harnesses) | Very good | Let agents write *all* the tooling |
| Pixel art within C64 limits | Weak by hand; OK through a pipeline (generate or draw → quantize → validate) | A human art director, or you, approves every asset |
| SID music and SFX | Weak | Plan for a human musician, a commissioned composer, or licensed tunes. Agents do the player integration |
| Game feel, fun and difficulty | Can't judge by itself | **You are the playtester and creative director** |

The agents are the engineering department. You stay the studio head: you set the vision, approve milestones and judge feel.

---

## 3. Phase 0: Foundations (a day or two)

### 3.1 Toolchain

The folder name suggests the **VS64** VS Code extension, which is a good hub. It supports ACME, KickAssembler, cc65, LLVM-MOS and Oscar64, and it integrates VICE debugging.

Recommended stack:

- **Assembler: KickAssembler.** Its scripting language (loops, lists, `LoadBinary`, `LoadPicture`, macros, pseudo-commands) lets agents generate tables and import assets at build time, and it's widely used in the demo scene, so there are plenty of examples. 64tass or ACME are fine alternatives. Pick **one** and stick to it.
- **Emulator: VICE (`x64sc`)**, the cycle-exact C64 core. Install it with `brew install vice`.
- **Compression and packaging:** Exomizer (crunching); `c1541` (from VICE) for `.d64`; `cartconv` for EasyFlash or Magic Desk `.crt`.
- **Tooling language: Python 3**, for asset converters, test harness and MCP server.
- **Build:** a `Makefile` (or `build.py`) so that `make`, `make run` and `make test` work from the terminal. Agents need a CLI, not just a VS Code button.
- **Git:** initialise now. This folder isn't a repo yet. Every agent change goes through commits and branches.

### 3.2 Repository layout

```
vs64_software_house/
├── CLAUDE.md                  # Studio handbook: loaded into every agent's context
├── C64_SOFTWARE_HOUSE.md      # This plan
├── .claude/
│   ├── agents/                # One .md per role (see §6)
│   ├── skills/                # Reusable procedures and knowledge packs (see §5)
│   └── settings.json          # Permissions, hooks
├── .mcp.json                  # Registers the VICE MCP server for the project
├── docs/
│   ├── reference/             # C64 hardware knowledge base (see §5)
│   ├── standards/             # Coding conventions, memory map template, zero-page policy
│   └── games/<title>/         # GDD, tech design, raster timeline, milestone log
├── engine/                    # Shared, reusable library: IRQ framework, multiplexer, loader glue, SID player
├── games/<title>/src/         # Per-game source
├── assets/<title>/            # Source PNGs, tracker files, maps (human-editable)
├── tools/                     # Python: png2sprites, png2charset, map tools, validators
├── mcp/vice/                  # The VICE MCP server
└── tests/                     # Emulator-driven tests: screenshots, memory assertions, cycle budgets
```

The `engine/` folder is the "company asset". Every game makes it better, which is how a real software house compounds its advantage.

---

## 4. Phase 1: Give the agents eyes and hands (MCP), the most important step

### 4.1 What MCP is, briefly

**MCP (Model Context Protocol)** is a standard way to give Claude new tools. An MCP server is a small program, usually around 100–300 lines of Python, that exposes functions such as `screenshot()` or `read_memory(addr, len)`. Claude Code launches it and the functions appear as tools that Claude can call. You register it once:

```bash
claude mcp add vice --scope project -- python3 mcp/vice/server.py
```

This writes `.mcp.json`, so every agent in the project gets the tools.

### 4.2 The VICE MCP server

VICE has a **binary remote monitor** (start `x64sc -binarymonitor`, which listens on TCP port 6502). It can get and set memory, get registers, set breakpoints and checkpoints, step, feed keyboard input, set joystick state, autostart a file, reset, and **grab the display buffer**. Wrap it in MCP tools:

| Tool | Purpose |
|---|---|
| `vice_start(prg, pal=True, warp=False)` / `vice_stop()` | Launch or kill an emulator instance (one per agent or worktree, each on its own port) |
| `vice_run_frames(n)` | Advance exactly N frames (PAL: 312 lines × 63 cycles = 19,656 cycles per frame) |
| `vice_screenshot()` | Return a PNG so that Claude can **see** the screen, including borders |
| `vice_read_mem(addr, len)` / `vice_write_mem(addr, bytes)` | Inspect or poke state (score, lives, object tables) |
| `vice_registers()` | CPU state |
| `vice_breakpoint(addr)` / `vice_run_until(addr, timeout_frames)` | Stop at code points |
| `vice_joystick(port, dirs, fire, frames)` | Play the game with scripted input |
| `vice_keys(text)` | Type into BASIC or menus |
| `vice_raster_profile(start_label, end_label)` | Measure the cycles or raster lines a routine takes; the core of performance work |
| `vice_symbols(file)` | Load the assembler's label file so that tools accept `label` names instead of hex addresses |

**Status: built in M1.** See [mcp/vice/README.md](mcp/vice/README.md) for the actual tool list (names differ slightly from the sketch above: `vice_profile`, `vice_type`, `vice_run_until` with read/write watchpoints), how it's wired together, and the VICE 3.10 quirks found along the way. It uses the official MCP Python SDK 2.x (`MCPServer`, the successor to v1's `FastMCP`) in a `uv`-managed project.

### 4.3 Real hardware later (optional, but valuable)

An **Ultimate 64** or **1541 Ultimate II+** exposes a network REST API (run PRG, mount disk, reset, read and write memory). A second MCP server around it lets agents test on real hardware as a final QA stage, which matters for timing-critical effects that emulators might get subtly wrong.

---

## 5. Phase 2: The knowledge base (the studio's "senior engineer memory")

Models know 6502 reasonably well. They're less reliable on exact VIC-II behaviour. Put the ground truth in the repo and point agents to it.

**`docs/reference/`** (curate from primary sources; summarise into Markdown that agents can read):

- Memory map, banking (`$01`), VIC bank selection (`$DD00`), and where charsets, screen and sprites can live
- **VIC-II timing:** cycles per line (PAL 63, NTSC 65), badlines, sprite DMA cycle stealing, per-line cycle diagrams. Christian Bauer's *"The MOS 6567/6569 video controller (VIC-II)"* article is the canonical source
- Stable raster IRQ techniques (double IRQ, timer-based jitter correction)
- Sprite multiplexing (sorting, zone and slot allocation, IRQ chaining)
- Scrolling (hardware fine scroll plus colour RAM shifting, double buffering)
- Effects catalogue: FLD, FLI, AGSP, VSP, open side and top borders, sprite stretching, NUFLI and so on, with cost, constraints and risk (for example, VSP crashes some real machines)
- SID: registers, ADSR bug, digi playback, 2SID, player integration (for example, GoatTracker and SID Wizard player routines)
- Illegal opcodes: which ones are stable
- Loaders and formats: Krill's loader and Spindle for disk streaming; EasyFlash and Magic Desk for cartridges
- 6502 cycle table for every opcode, including page-crossing penalties

**`docs/standards/`**: zero-page allocation policy, IRQ ownership rules, naming conventions, required comments (cycle counts on timing-critical code), and the memory-map template that each game must fill in.

**Skills (`.claude/skills/<name>/SKILL.md`)** turn procedures into on-demand playbooks that agents load when relevant, for example:

- `raster-timing`: how to write and verify a stable raster routine using the VICE tools
- `sprite-multiplexer`: the engine's multiplexer API and its limits
- `asset-pipeline`: how to add a sprite sheet, charset or map and validate it
- `cycle-audit`: how to profile a frame and report the raster budget
- `release-build`: crunch, package, create `.d64`/`.crt`, smoke test

**`CLAUDE.md`** (the studio handbook, always loaded) stays short: the build and test commands, the repo layout, "always verify in VICE before claiming something works", "never touch `$0000–$00FF` outside your allocation", the definition of done, and pointers to `docs/`.

---

## 6. Phase 3: The team

### 6.1 How to implement "a team of agents"

Use Claude Code's built-in **subagents**: Markdown files in `.claude/agents/`, each with a role prompt, a tool allowlist and optionally a model choice. The main Claude Code session acts as the **Producer or orchestrator**. It breaks work down and delegates to specialists, and each specialist works in its own context window and reports back. This needs no extra infrastructure, and you can watch and steer everything from VS Code.

Example `.claude/agents/raster-engineer.md`:

```markdown
---
name: raster-engineer
description: Writes and verifies cycle-exact VIC-II code: raster IRQs, multiplexers, border/FLD/FLI effects. Use for any timing-critical display work.
tools: Read, Edit, Write, Bash, Grep, Glob, mcp__vice
model: opus
---
You are a senior C64 demo-scene coder. Before writing code, read
docs/reference/vic-timing.md and the game's docs/games/<title>/raster-timeline.md.
Every timing-critical routine must carry cycle-count comments and be verified with
vice_raster_profile and a vice_screenshot before you report success. Report: what
changed, measured cycle/raster cost, screenshot path, known risks.
```

### 6.2 The roles

| Role | Responsibility | Key tools |
|---|---|---|
| **Producer** (main session, steered by you) | Breaks milestones into tasks, delegates, merges, keeps the milestone log | All |
| **Game Designer** | GDD, level design, enemy patterns, difficulty curves, as data tables | Read/Write docs |
| **Technical Director** | Memory map, raster timeline (who owns which lines), frame budget, engine architecture, approves design changes | Read, VICE |
| **Gameplay Engineer** | Player, enemies, collision, state machines, game loop | Code + VICE |
| **Raster/Effects Engineer** | IRQs, multiplexer, scrolling, the boundary-pushing effects | Code + VICE profiling |
| **Tools & Pipeline Engineer** | Python converters (PNG → sprites or chars, with constraint validation), map tools, build and test harness | Python, Bash |
| **Audio Integrator** | SID player integration, SFX-over-music channel stealing, digi samples | Code + VICE |
| **QA Tester** | Scripted playthroughs through joystick input, screenshot regression, soak tests (run 100,000 frames and check invariants) | VICE, tests/ |
| **Performance Auditor** | Profiles every frame phase, flags budget overruns, suggests unrolling, tables and speedcode | VICE profiling |
| **Code Reviewer** | Reviews every branch against standards, zero-page policy and IRQ ownership before merge | Read, Grep, git |

Start with **four**: Technical Director, Gameplay Engineer, Tools Engineer and QA. Add roles when you feel the lack of them. Too many agents early on just multiplies coordination errors.

### 6.3 Human roles (you)

- **Creative Director:** approves the GDD and the look and feel of each milestone
- **Playtester:** the agents can't tell you whether it's fun
- **Art and music sign-off,** or bring in human collaborators for these

---

## 7. Phase 4: Process (how the studio works)

### 7.1 Per-game pipeline

1. **Pitch** (Designer and you): one page covering the hook, the genre and the technical "wow" feature.
2. **Tech feasibility spike** (Technical Director and Raster Engineer): prove the wow feature in isolation, in `games/<title>/spikes/`, with a measured cycle budget. **Kill or adjust the pitch here, not later.**
3. **GDD and tech design:** memory map, raster timeline (a line-by-line table of what happens where), per-frame cycle budget, asset list.
4. **Vertical slice:** one level, fully polished, with final-quality art, sound and effects. This is the real proof of quality.
5. **Production:** the remaining content, built mostly as data plus reused engine code.
6. **Alpha → Beta → Gold:** soak tests, real-hardware test, PAL and NTSC decisions, loader and packaging, manual and box art.

### 7.2 Quality gates (enforced by hooks and tests, not by trust)

- `make test` must pass: it builds, boots in VICE, runs the scripted playthrough, applies memory assertions (for example, lives never go negative and the object table stays in bounds), compares screenshots, and checks the frame budget (no frame overruns its raster budget over N seconds).
- **Claude Code hooks** (`.claude/settings.json`) can run `make` after every edit to `.asm` files and block a "done" claim if tests fail.
- Every branch gets a Code Reviewer pass plus the Performance Auditor report before merge.
- You play every milestone build.

### 7.3 Parallel work

When there are independent tasks (for example, the Tools Engineer on the map editor while the Gameplay Engineer works on enemies), run agents in separate **git worktrees** so they don't trample each other's files. Give each its own VICE instance on a different monitor port.

---

## 8. Phase 5: Scaling up (only once Phases 0–4 feel solid)

- **Headless and scheduled runs:** `claude -p "…"` in scripts or CI, for example nightly soak tests with the QA agent triaging failures.
- **Claude Agent SDK** (Python or TypeScript): builds your own orchestrator program with the same agents, tools and MCP servers, running unattended for longer stretches. Move here only when you know exactly which workflow you want to automate. Starting here is how people end up debugging frameworks instead of making games.
- **More MCP servers:** Ultimate 64 hardware, a SID renderer (render `.sid` to WAV or a spectrum image so that agents can "hear" roughly), and an image-generation service for concept art that feeds the asset pipeline.

---

## 9. Pushing the boundaries: an R&D track

Keep a standing `rnd/` track, separate from game production, where the Raster Engineer builds and measures techniques into `engine/` modules, each with a spike demo, cycle cost and documented constraints. Candidate list:

- Robust 24–32+ sprite multiplexer with flicker-free sorting
- 8-way smooth scrolling with colour RAM double buffering
- Sprites in the side borders during gameplay
- AGSP or VSP-style full-screen scrolling (note the VSP real-hardware risk)
- FLD- or FLI-based bitmap tricks for title and cut scenes
- Streaming disk or cartridge loader for large worlds (Krill or Spindle; EasyFlash for up to 1 MB of content)
- Digi samples mixed with SID music
- Speedcode generators (KickAssembler scripts that emit unrolled code)

Each game then picks one or two headline techniques from this shelf. That's how commercial-era studios pushed the machine: through accumulated in-house tech.

---

## 10. Suggested first milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | Git repo, KickAssembler + VICE + Makefile, "hello border colour" builds and runs from `make run` | ✅ one command, from source to running |
| M1 | VICE MCP server with screenshot, memory, joystick, frame-step | Claude can boot a PRG, press fire, and describe the screenshot |
| M2 | `CLAUDE.md`, the first five reference docs, the first four agents | An agent answers "how many cycles on a badline?" from the repo docs |
| M3 | Engine basics: stable raster IRQ framework, sprite multiplexer v1, PNG → sprite converter | Spike demos pass automated cycle-budget tests |
| M4 | **Training game:** a small single-screen game (Robotron- or Galaga-like) | Playable, tested, and you find it fun for five minutes |
| M5 | First real title: pitch → feasibility spike → vertical slice | Vertical slice you'd be proud to show on CSDb or Lemon64 |

M4 is deliberately modest. It shakes out the tools, process and agent prompts on something small before you bet on an ambitious title.

---

## 11. Next actions

1. `git init`, and install VICE, KickAssembler (needs Java) and Exomizer.
2. Ask Claude Code to build the Makefile and a hello-world raster bar (M0).
3. Ask Claude Code to build the VICE MCP server (M1). **This is the key milestone.**
4. Write `CLAUDE.md` and the first agent files together with Claude (M2).
5. Iterate: after each milestone, update agent prompts and docs with whatever went wrong. The studio's "culture" lives in those files.
