# VICE MCP server

Gives Claude Code (and every agent in this repo) tools to drive the VICE C64 emulator:
boot a program, step exact frames, take screenshots, read and write memory, use the
joystick, and measure cycle costs.

## How the pieces fit

```
Claude Code ──stdio (MCP JSON-RPC)──▶ server.py ──TCP (VICE binary monitor)──▶ x64sc
             ◀── tool results ───────          ◀── memory, registers, display ──
```

- **`.mcp.json`** (repo root) tells Claude Code how to launch the server:
  `uv run --directory mcp/vice server.py`. Claude Code starts it when a session opens and
  talks to it over stdin/stdout. That's why the server must never `print()`.
- **`server.py`** uses the official MCP Python SDK (`mcp` 2.x, `MCPServer`). Each
  `@mcp.tool()` function becomes a tool; its type hints become the tool's input schema,
  and its docstring is the description the model reads.
- **`vice_monitor.py`** is a plain Python client for VICE's
  [binary monitor protocol](https://vice-emu.sourceforge.io/vice_13.html). It has no MCP in it,
  so you can use it from scripts too.
- **`smoke_test.py`** launches the server exactly as `.mcp.json` does and calls every tool
  against `hello`. Run it after changing anything here.

Python environment: `uv` reads `pyproject.toml` (dependency: `mcp[cli]`),
`.python-version` (3.13) and `uv.lock` (exact pinned versions), and keeps the virtual
env in `.venv/` (git-ignored). `uv sync` recreates it; `uv add <pkg>` adds a dependency.

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

## VICE details worth knowing (found while building this, with VICE 3.10)

- **Frame stepping** uses an exec checkpoint over `$0000-$ffff` with the condition
  `RL == $9c` and then `RL == $00`: two stops per frame, so the count is exact (verified
  against the KERNAL jiffy clock).
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
uv run smoke_test.py                       # full end-to-end check (build hello first: make)
uv run mcp dev server.py                   # MCP Inspector: a web UI for calling the tools yourself
```

`mcp dev` downloads the Inspector with `npx`, so it needs Node.js, which isn't installed yet.
