"""VICE MCP server: lets agents drive the VICE C64 emulator.

Runs over stdio (launched by Claude Code via .mcp.json). Each server process owns at
most one x64sc instance, on a free TCP port, so parallel sessions don't collide.
Never print to stdout here: stdout is the MCP transport.
"""

from __future__ import annotations

import atexit
import functools
import re
import struct
import subprocess
import time
import zlib
from datetime import datetime
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from vice_monitor import (
    CPU_OP_EXEC,
    CPU_OP_LOAD,
    CPU_OP_STORE,
    ViceError,
    ViceMonitor,
    free_port,
    load_symbols,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCREENSHOT_DIR = REPO_ROOT / "screenshots"

PAL_LINES = 312
PAL_CYCLES_PER_LINE = 63
PAL_FPS = 50.125

# Visible PAL area in VICE's "normal" border mode, relative to the inner 320x200 screen
# (checked pixel-for-pixel against x64sc -exitscreenshot)
BORDER_LEFT, BORDER_TOP = 32, 36
VISIBLE_W, VISIBLE_H = 384, 272

# VICE joyport device ids. The monitor can only drive the I/O simulation device. In VICE 3.10
# it holds pins 5-7 low, which on port 1 ($dc01, shared with the keyboard rows) looks like held
# keys (SHIFT+C= flips the charset), so port 1 only gets it while vice_joystick is using it.
JOYPORT_JOYSTICK = 1
JOYPORT_IO_SIMULATION = 37
JOY_BITS = {"up": 0x01, "down": 0x02, "left": 0x04, "right": 0x08, "fire": 0x10}

mcp = MCPServer(
    "vice",
    instructions=(
        "Drive the VICE C64 emulator (x64sc, PAL). Typical flow: vice_start(program) -> "
        "vice_run_frames / vice_joystick -> vice_screenshot / vice_read_memory -> vice_stop. "
        "The machine is paused between tool calls. Addresses accept $c000, 0xc000, 49152, "
        "or an assembler label (optionally label+N) from the program's KickAssembler .vs file."
    ),
)


class Session:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.mon: ViceMonitor | None = None
        self.symbols: dict[str, int] = {}
        self.program: Path | None = None

    def require(self) -> ViceMonitor:
        if not self.mon or not self.proc or self.proc.poll() is not None:
            raise ViceError("VICE is not running; call vice_start first")
        return self.mon

    def stop(self) -> None:
        if self.mon:
            self.mon.quit()
            self.mon.close()
            self.mon = None
        if self.proc:
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None


session = Session()
atexit.register(session.stop)


# -- helpers ---------------------------------------------------------------


def _resolve_path(path: str) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else (REPO_ROOT / p).resolve()


def _basic_sys_address(program: Path) -> int | None:
    """Entry point of a PRG with a BASIC upstart line ('10 SYS 2062'), or None."""
    if program.suffix.lower() != ".prg":
        return None
    data = program.read_bytes()
    if len(data) < 8 or data[0:2] != b"\x01\x08":
        return None
    m = re.search(rb"\x9e\s*\(?(\d+)", data[6:40])  # $9e = SYS token
    return int(m.group(1)) if m else None


def _addr(value: str | int) -> int:
    if isinstance(value, int):
        return value
    text = value.strip()
    m = re.fullmatch(r"([A-Za-z_][\w.]*)\s*([+-]\s*\d+)?", text)
    if m and m.group(1) in session.symbols:
        return session.symbols[m.group(1)] + int((m.group(2) or "0").replace(" ", ""))
    if text.startswith("$"):
        return int(text[1:], 16)
    if text.lower().startswith("0x"):
        return int(text, 16)
    if text.isdigit():
        return int(text)
    raise ViceError(f"unknown address or label: {value!r}")


def _label_for(addr: int) -> str:
    best = None
    for name, a in session.symbols.items():
        if a <= addr and (best is None or a > best[1]):
            best = (name, a)
    if best and addr - best[1] < 256:
        return best[0] if addr == best[1] else f"{best[0]}+{addr - best[1]}"
    return ""


def _status(mon: ViceMonitor) -> str:
    r = mon.registers()
    label = _label_for(r["PC"])
    where = f"PC=${r['PC']:04x}" + (f" ({label})" if label else "")
    return (
        f"{where} A=${r['A']:02x} X=${r['X']:02x} Y=${r['Y']:02x} SP=${r['SP']:02x} "
        f"FL=%{r['FL']:08b} raster line {r['LIN']} cycle {r['CYC']}"
    )


def _run_frames(mon: ViceMonitor, frames: int) -> None:
    """Advance exactly `frames` PAL frames, stopping at the start of raster line 0."""
    cp = mon.checkpoint_set(0x0000, 0xFFFF, CPU_OP_EXEC)
    try:
        for _ in range(frames):
            for line in (PAL_LINES // 2, 0):  # mid-frame then line 0 = one frame boundary
                mon.checkpoint_condition(cp.number, f"RL == ${line:02x}")
                mon.exit()
                if not mon.wait_stopped(timeout=5.0):
                    mon.ping()  # halts the machine
                    if mon.state.jammed_pc is not None:
                        raise ViceError(f"CPU jammed at ${mon.state.jammed_pc:04x}")
                    raise ViceError("frame did not complete within 5s (CPU jammed or interrupts off?)")
    finally:
        mon.checkpoint_delete(cp.number)


def _png(width: int, height: int, indices: bytes, palette: list[tuple[int, int, int]]) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + indices[y * width : (y + 1) * width] for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0))
        + chunk(b"PLTE", b"".join(bytes(c) for c in palette))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _hexdump(start: int, data: bytes) -> str:
    lines = []
    for i in range(0, len(data), 16):
        row = data[i : i + 16]
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        lines.append(f"${start + i:04x}: {row.hex(' '):<47}  {text}")
    return "\n".join(lines)


# -- tools -----------------------------------------------------------------


def tool(fn):
    """Register fn as an MCP tool, reporting anticipated failures to the model as ToolError.

    MCPServer hides the text of any other exception from the client ("Error executing
    tool X"), which would leave an agent guessing. Returns fn unwrapped so tools can call
    each other and still see the original exception.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ViceError, OSError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    mcp.tool()(wrapper)
    return fn


@tool
def vice_start(program: str = "", warp: bool = True, show_window: bool = False, boot_frames: int = 250) -> str:
    """Launch a fresh x64sc (PAL, default settings) and optionally autostart a program.

    program: .prg/.d64/.crt path (relative paths are from the repo root); empty = just boot.
    warp: run as fast as possible (recommended; timing inside the emulation is unaffected).
    show_window: bring the VICE window up so a human can watch; otherwise it starts minimized.
    boot_frames: max frames to wait for the program to start (see vice_load).
    Joystick ports 1 and 2 are wired to the monitor (see vice_joystick); real joysticks are ignored.
    """
    session.stop()
    port = free_port()
    args = [
        "x64sc", "-default", "-pal", "-sounddev", "dummy",
        "-binarymonitor", "-binarymonitoraddress", f"ip4://127.0.0.1:{port}",
        "-autostartprgmode", "1",
    ]
    if warp:
        args.append("-warp")
    if not show_window:
        args.append("-minimized")
    session.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    session.mon = mon = ViceMonitor(port=port)
    mon.connect()
    mon.drain_events(0.3)
    mon.resource_set("JoyPort2Device", JOYPORT_IO_SIMULATION)
    mon.joyport_set(1, 0x1F)  # lines are active-low: $1f = nothing pressed
    result = f"VICE {mon.vice_info()} started (monitor port {port})."
    if program:
        result += "\n" + vice_load(program, boot_frames)
    else:
        _run_frames(mon, boot_frames)
        result += "\n" + _status(mon)
    return result


@tool
def vice_load(program: str, boot_frames: int = 250, settle_frames: int = 10) -> str:
    """Autostart a .prg/.d64/.crt in the running VICE and load its symbols.

    For a PRG with a BASIC 'SYS' line, runs until the CPU reaches that entry point (up to
    boot_frames), then settle_frames more. Otherwise just runs boot_frames frames.
    """
    mon = session.require()
    path = _resolve_path(program)
    if not path.exists():
        raise ViceError(f"file not found: {path}")
    session.program = path
    session.symbols = load_symbols(path)
    mon.autostart(str(path), run=True)
    entry = _basic_sys_address(path)
    if entry is None:
        _run_frames(mon, boot_frames)
        how = f"ran {boot_frames} frames"
    else:
        cp = mon.checkpoint_set(entry, entry, CPU_OP_EXEC)
        try:
            mon.exit()
            reached = mon.wait_stopped(timeout=5.0 + boot_frames / PAL_FPS)
        finally:
            if not reached:
                mon.ping()
                mon.drain_events()
            mon.checkpoint_delete(cp.number)
        if not reached:
            raise ViceError(f"program entry ${entry:04x} not reached within {boot_frames} frames")
        _run_frames(mon, settle_frames)
        how = f"entered at ${entry:04x}, then ran {settle_frames} frames"
    return f"Loaded {path.name} ({len(session.symbols)} symbols), {how}.\n{_status(mon)}"


@tool
def vice_stop() -> str:
    """Quit VICE."""
    session.stop()
    return "VICE stopped."


@tool
def vice_reset(hard: bool = False) -> str:
    """Reset the C64 (soft by default) and run 150 frames so BASIC is ready."""
    mon = session.require()
    mon.reset(hard)
    _run_frames(mon, 150)
    return _status(mon)


@tool
def vice_run_frames(frames: int = 1) -> str:
    """Advance exactly N PAL frames (19,656 cycles each); stops at the start of raster line 0."""
    mon = session.require()
    _run_frames(mon, frames)
    return f"Ran {frames} frame(s).\n{_status(mon)}"


@tool
def vice_run_until(address: str, access: str = "exec", timeout_frames: int = 500) -> str:
    """Run until the CPU executes (or loads/stores, via access="load"/"store") the given address or label."""
    mon = session.require()
    ops = {"exec": CPU_OP_EXEC, "load": CPU_OP_LOAD, "store": CPU_OP_STORE}
    if access not in ops:
        raise ViceError(f"access must be one of {', '.join(ops)}")
    op = ops[access]
    target = _addr(address)
    cp = mon.checkpoint_set(target, target, op)
    try:
        mon.exit()
        if mon.wait_stopped(timeout=5.0 + timeout_frames / PAL_FPS):
            return f"Hit {access} ${target:04x}.\n{_status(mon)}"
        mon.ping()
        mon.drain_events()
        return f"Timed out: ${target:04x} not reached.\n{_status(mon)}"
    finally:
        mon.checkpoint_delete(cp.number)


@tool
def vice_screenshot(name: str = "", area: str = "visible") -> list:
    """Capture the screen as PNG, save it under screenshots/, and return the image.

    area: "visible" = 384x272 PAL screen with normal borders (what a TV shows),
          "full" = the whole emulated frame including side/top borders (open-border effects),
          "inner" = only the 320x200 display window.
    """
    mon = session.require()
    d = mon.display_get()
    pixels = d.pixels.ljust(d.width * d.height, b"\x00")  # VICE sends a few bytes short
    if area == "full":
        x0, y0, w, h = 0, 0, d.width, d.height
    elif area == "inner":
        x0, y0, w, h = d.offset_x, d.offset_y, d.inner_width, d.inner_height
    else:
        x0, y0, w, h = d.offset_x - BORDER_LEFT, d.offset_y - BORDER_TOP, VISIBLE_W, VISIBLE_H
    cropped = b"".join(pixels[(y0 + y) * d.width + x0 : (y0 + y) * d.width + x0 + w] for y in range(h))
    png = _png(w, h, cropped, mon.palette())
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    stem = re.sub(r"[^\w.-]", "_", name) if name else datetime.now().strftime("vice-%Y%m%d-%H%M%S")
    path = SCREENSHOT_DIR / f"{stem}.png"
    path.write_bytes(png)
    return [Image(data=png, format="png"), f"Saved {path.relative_to(REPO_ROOT)} ({w}x{h})"]


@tool
def vice_read_memory(address: str, length: int = 64) -> str:
    """Hex dump memory as the CPU sees it (current $01 banking). Reads have no I/O side effects."""
    mon = session.require()
    start = _addr(address)
    end = min(start + max(length, 1) - 1, 0xFFFF)
    return _hexdump(start, mon.mem_get(start, end))


@tool
def vice_write_memory(address: str, hex_bytes: str) -> str:
    """Write bytes (hex, e.g. "a9 00 8d 20 d0") to memory at address/label."""
    mon = session.require()
    start = _addr(address)
    data = bytes.fromhex(hex_bytes.replace("$", "").replace(",", " "))
    mon.mem_set(start, data)
    return f"Wrote {len(data)} byte(s) at ${start:04x}."


@tool
def vice_registers(set_values: dict[str, int] | None = None) -> str:
    """Show CPU registers and raster position; optionally set some first, e.g. {"PC": 2064, "A": 0}."""
    mon = session.require()
    for name, value in (set_values or {}).items():
        mon.set_register(name.upper(), value)
    return _status(mon)


@tool
def vice_joystick(input: str = "none", port: int = 2, frames: int = 10, release: bool = True) -> str:
    """Hold joystick input for N frames. input: "none" or directions joined by +, e.g. "up+fire", "left".

    Most games read port 2. release=False keeps the input held after the call. While port 1
    input is held, the keyboard matrix is disturbed (keyboard rows share port 1's lines).
    """
    mon = session.require()
    if port not in (1, 2):
        raise ViceError("port must be 1 or 2")
    pressed = 0
    for part in filter(None, input.lower().replace(" ", "").split("+")):
        if part == "none":
            continue
        if part not in JOY_BITS:
            raise ViceError(f"unknown joystick input {part!r}; use up, down, left, right, fire or none")
        pressed |= JOY_BITS[part]
    if port == 1:
        mon.resource_set("JoyPort1Device", JOYPORT_IO_SIMULATION)
    mon.joyport_set(port - 1, ~pressed & 0x1F)
    _run_frames(mon, frames)
    if release:
        mon.joyport_set(port - 1, 0x1F)
        if port == 1:
            mon.resource_set("JoyPort1Device", JOYPORT_JOYSTICK)
    return f"Port {port}: held {input} for {frames} frame(s){'' if release else ' (still held)'}.\n{_status(mon)}"


@tool
def vice_type(text: str, frames: int = 20) -> str:
    """Type text via the KERNAL keyboard buffer (works at the BASIC prompt / KERNAL input, not for
    games that scan the keyboard matrix). Newlines become RETURN. Runs `frames` frames afterwards."""
    mon = session.require()
    mon.keyboard_feed(text.upper().replace("\n", "\r"))
    _run_frames(mon, frames)
    return f"Typed {len(text)} character(s).\n{_status(mon)}"


@tool
def vice_profile(start: str, end: str, samples: int = 50) -> str:
    """Measure CPU cycles from executing `start` up to (not including) `end`, over several passes.

    Uses the VIC-II raster position (line, cycle) so the figure includes cycles stolen by
    badlines and sprite DMA, i.e. the real cost in raster time. Accepts labels or addresses.
    """
    mon = session.require()
    a, b = _addr(start), _addr(end)
    frame = PAL_LINES * PAL_CYCLES_PER_LINE
    cp_a = mon.checkpoint_set(a, a, CPU_OP_EXEC)
    cp_b = mon.checkpoint_set(b, b, CPU_OP_EXEC)
    costs: list[int] = []
    started_at: int | None = None  # raster time of the latest `start` hit not yet paired with an `end`
    try:
        # Stops can arrive in any order (e.g. we begin between start and end), so pair each
        # `end` with the most recent `start` rather than assuming they alternate.
        for _ in range(samples * 4):
            if len(costs) >= samples:
                break
            mon.exit()
            if not mon.wait_stopped(timeout=5.0):
                mon.ping()
                mon.drain_events()
                break
            r = mon.registers()
            now = r["LIN"] * PAL_CYCLES_PER_LINE + r["CYC"]
            if r["PC"] == a:
                started_at = now
            elif r["PC"] == b and started_at is not None:
                costs.append((now - started_at) % frame)
                started_at = None
    finally:
        mon.checkpoint_delete(cp_a.number)
        mon.checkpoint_delete(cp_b.number)
    if not costs:
        return f"No complete start->end passes measured between ${a:04x} and ${b:04x}."
    avg = sum(costs) / len(costs)
    return (
        f"${a:04x} -> ${b:04x} over {len(costs)} pass(es): "
        f"min {min(costs)}, avg {avg:.1f}, max {max(costs)} cycles "
        f"(max = {max(costs) / PAL_CYCLES_PER_LINE:.1f} raster lines, "
        f"{100 * max(costs) / frame:.1f}% of a PAL frame)."
    )


@tool
def vice_symbols(filter: str = "") -> str:
    """List the loaded program's labels (optionally only those containing `filter`)."""
    items = sorted((a, n) for n, a in session.symbols.items() if filter.lower() in n.lower())
    if not items:
        return "No matching symbols loaded."
    return "\n".join(f"${a:04x} {n}" for a, n in items)


if __name__ == "__main__":
    mcp.run()
