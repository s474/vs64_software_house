# VICE MCP server

Gives Claude Code (and every agent in this repo) tools to drive the VICE C64 emulator:
boot a program, step exact frames, take screenshots, read and write memory, use the
joystick, and measure cycle costs.

## Tools

| Tool | What it does |
|---|---|
| `vice_start(program, warp, show_window)` | Fresh x64sc (PAL, default settings, own port). Autostarts `program` if given |
| `vice_load(program)` | Autostart a .prg/.d64/.crt; for a PRG with a `SYS` line, runs until the CPU reaches it |
| `vice_stop()` / `vice_reset(hard)` | Quit / reset |
| `vice_run_frames(n)` | Advance exactly n frames; stops at the start of raster line 0 |
| `vice_run_until(address, access)` | Run until an address or label is executed, read or written |
| `vice_screenshot(name, area)` | PNG saved to `screenshots/`: `visible` 384×272, `full` 504×312 (with open borders), `inner` 320×200 |
| `vice_read_memory` / `vice_write_memory` | Hex dump / poke; addresses take `$c000`, `0xc000`, `49152`, `label`, `label+3` |
| `vice_registers(set_values)` | CPU registers plus raster line and cycle; optionally set registers |
| `vice_joystick(input, port, frames)` | e.g. `"up+fire"` for 10 frames on port 2 |
| `vice_type(text)` | Type into the KERNAL keyboard buffer (BASIC prompt, not games that scan the matrix) |
| `vice_profile(start, end)` | Cycles from `start` to `end` over several passes, measured in raster time (includes badlines and sprite DMA) |
| `vice_symbols(filter)` | Labels loaded from KickAssembler's `.vs` file next to the program |

The machine is **paused between tool calls**, so everything an agent sees is deterministic.

## How it works

> The diagrams are [Mermaid](https://mermaid.js.org): GitHub renders them automatically.
> In VS Code, install *Markdown Preview Mermaid Support* (`bierner.markdown-mermaid`) and
> open the Markdown preview (⇧⌘V).

### The pieces

```mermaid
flowchart LR
    CFG[".mcp.json"] -.->|"how to launch it:<br/>uv run --directory mcp/vice server.py"| CC
    CC["Claude Code<br/>(or an agent)"] -->|"stdio: MCP JSON-RPC<br/>tools/list, tools/call"| SRV["server.py<br/>MCPServer + @tool functions"]
    SRV -->|"Python calls"| MON["vice_monitor.py<br/>ViceMonitor"]
    MON -->|"TCP 127.0.0.1:(free port)<br/>binary monitor frames"| VICE["x64sc<br/>PAL C64"]
    SRV -->|"writes PNGs"| SHOTS[("screenshots/")]
    SRV -->|"reads labels"| SYMS[("build/.../main.vs")]
```

- **`.mcp.json`** (repo root) tells Claude Code how to launch the server. Claude Code starts
  it when a session opens and talks to it over stdin/stdout, which is why the server must
  never `print()`.
- **`server.py`** uses the official MCP Python SDK (`mcp` 2.x, `MCPServer`). Each function
  decorated with `@tool` becomes an MCP tool: its type hints become the tool's input schema,
  and its docstring is the description the model reads.
- **`vice_monitor.py`** is a plain Python client for VICE's
  [binary monitor protocol](https://vice-emu.sourceforge.io/vice_13.html). It has no MCP in it,
  so you can use it from scripts too.
- **`smoke_test.py`** builds `hello`, launches the server exactly as `.mcp.json` does, and calls
  every tool. Run it after changing anything here.

Python environment: `uv` reads `pyproject.toml` (dependency: `mcp[cli]`),
`.python-version` (3.13) and `uv.lock` (exact pinned versions), and keeps the virtual
env in `.venv/` (git-ignored). `uv sync` recreates it; `uv add <pkg>` adds a dependency.

### A session, start to finish

```mermaid
sequenceDiagram
    autonumber
    participant CC as Claude Code
    participant S as server.py
    participant V as x64sc
    Note over CC,S: Session opens
    CC->>S: spawn "uv run ... server.py" with stdin/stdout pipes
    CC->>S: initialize, tools/list
    S-->>CC: 14 tools, each with a JSON schema built from its type hints
    Note over CC,V: vice_start(program="build/hello/hello.prg")
    CC->>S: tools/call vice_start
    S->>V: launch x64sc -binarymonitor on a free port
    S->>V: TCP connect (the machine halts)
    S->>V: JoyPort2Device = 37, joystick port 2 = $1f (released)
    S->>V: autostart hello.prg
    S->>V: exec checkpoint at $080e (the SYS address)
    S->>V: exit (resume)
    V-->>S: stopped event, PC = $080e
    S->>V: run 10 settle frames, then registers_get
    S-->>CC: "Loaded hello.prg (4 symbols) ... PC=$0841 (start+51)"
    Note over CC,V: Later calls reuse the same x64sc, paused in between
    CC->>S: tools/call vice_screenshot
    S->>V: display_get, palette_get
    S-->>CC: PNG image + "Saved screenshots/....png"
```

### VICE under the monitor

VICE only runs the C64 while the server lets it. Every monitor command halts the machine,
and nothing moves until the server sends `exit`:

```mermaid
stateDiagram-v2
    [*] --> Stopped: connect
    Stopped --> Running: exit
    Running --> Stopped: halt
    Running --> Jammed: JAM opcode
    note right of Stopped
        Memory, register, display and
        checkpoint commands run here
    end note
```

| Transition | Caused by |
|---|---|
| connect | The server opens the TCP connection, and VICE halts the machine |
| exit | The server's `exit` command resumes emulation |
| halt | A checkpoint is hit (VICE sends a `stopped` event), or the server sends any other command, e.g. `ping` |
| JAM opcode | The CPU executes an illegal JAM instruction and locks up. The server reports this instead of waiting forever |

This is why every tool that runs the machine does it the same way: set up a checkpoint,
send `exit`, wait for the `stopped` event, then read whatever it needs.

### Stepping exact frames (`vice_run_frames`)

VICE has no "run one frame" command, so the server builds one from a checkpoint that
matches *any* executed instruction, filtered by a condition on the raster line (`RL`):

```mermaid
flowchart TD
    A["exec checkpoint over $0000-$ffff"] --> B{"frames left?"}
    B -->|yes| C["condition: RL == $9c (line 156, mid-frame)"]
    C --> D["exit, wait for stop"]
    D --> E["condition: RL == $00"]
    E --> F["exit, wait for stop"]
    F --> B
    B -->|no| G["delete checkpoint<br/>machine paused at the start of line 0"]
    D -.->|"no stop within 5 s"| X["ping to halt it<br/>report JAM or error"]
    F -.->|"no stop within 5 s"| X
```

Why two stops per frame? The condition `RL == $00` stays true for every instruction on
line 0, so resuming from line 0 with that same condition would stop again straight away.
Going via a mid-frame line guarantees each loop passes exactly one frame boundary. The
count is verified against the KERNAL jiffy clock: 300 frames = 359 jiffies, as PAL expects.

### Loading a program (`vice_load`)

```mermaid
flowchart TD
    A["vice_load(program)"] --> B{"file exists?"}
    B -->|no| ERR["ToolError: file not found"]
    B -->|yes| C["read labels from .vs files next to it"]
    C --> D["autostart via the monitor (PRG inject mode)"]
    D --> E{"PRG with a BASIC SYS line?"}
    E -->|"no (.d64, .crt, raw PRG)"| F["run boot_frames frames"]
    E -->|yes| G["exec checkpoint at the SYS address"]
    G --> H["exit, wait up to boot_frames"]
    H --> I{"entry reached?"}
    I -->|no| ERR2["ToolError: entry not reached"]
    I -->|yes| J["delete checkpoint, run settle_frames"]
    F --> Z["return status: PC, label, raster position"]
    J --> Z
```

Waiting for the real entry point matters: a fixed 150-frame wait sometimes returned while
autostart was still at the BASIC prompt.

### Measuring cycles (`vice_profile`)

```mermaid
flowchart TD
    A["exec checkpoints at start and end"] --> B["exit, wait for stop"]
    B --> C{"stopped?"}
    C -->|"no (5 s)"| R
    C -->|yes| D["read PC and raster position<br/>t = line × 63 + cycle"]
    D --> E{"which checkpoint?"}
    E -->|start| F["started_at = t"]
    E -->|"end, after a start"| G["cost = (t − started_at) mod 19656<br/>clear started_at"]
    E -->|"end, no start yet"| L
    F --> L{"enough samples?"}
    G --> L
    L -->|no| B
    L -->|yes| R["delete checkpoints<br/>report min / avg / max"]
```

Timing comes from the raster position, not a CPU cycle counter. So the result is *raster
time*: it includes cycles the VIC-II steals for badlines and sprites, which is what
matters for fitting work into a frame. `mod 19656` (one PAL frame) handles a routine that
crosses line 0. Pairing each `end` with the latest `start` means it copes with starting
anywhere, even between the two. The loop gives up after `samples × 4` stops.

### Errors

Tools raise `ViceError` (or `ValueError`/`OSError`) for failures they can foresee. The
`@tool` decorator in `server.py` converts those to the SDK's `ToolError`, so the model sees
the message, e.g. `file not found: .../build/nope.prg`. Any other exception is treated as a
crash, and the SDK deliberately hides its text: the model only sees `Error executing tool X`,
and the traceback goes to the server's log.

## VICE details worth knowing (found while building this, with VICE 3.10)

- **Joystick:** the monitor can only drive VICE's "I/O simulation" joyport device (id 37),
  with active-low values (`$1f` = nothing pressed). In 3.10 the device holds pins 5–7 low.
  On port 1 those pins are keyboard rows, so the KERNAL sees SHIFT+C= held and switches
  to lowercase. The server therefore attaches the device to port 2 at start, and to port 1
  only while `vice_joystick(port=1)` is holding input.
- **Display capture** arrives 4 bytes short of `width × height`, and the server pads it.
  The visible crop (32 px left border, 36 px top) matches `x64sc -exitscreenshot` pixel for pixel.
- **Warp** is a command-line flag (`-warp`). There is no `WarpMode` resource in 3.10.
- **Autostart** uses PRG inject mode (`-autostartprgmode 1`), which is faster than loading from a
  virtual disk.

## Running it by hand

```bash
cd mcp/vice
uv run smoke_test.py                       # full end-to-end check (builds hello first)
uv run mcp dev server.py                   # MCP Inspector: a web UI for calling the tools yourself
```

`mcp dev` downloads the Inspector with `npx`, so it needs Node.js, which isn't installed yet.
