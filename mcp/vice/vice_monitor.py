"""Client for the VICE binary monitor protocol (API version 2).

Start VICE with `-binarymonitor -binarymonitoraddress ip4://127.0.0.1:<port>`.
Protocol reference: VICE manual, "Binary Monitor" chapter.

Wire format (all integers little-endian):
  request:  STX(0x02) api(0x02) body_len:u32 request_id:u32 command:u8 body
  response: STX(0x02) api(0x02) body_len:u32 response_type:u8 error:u8 request_id:u32 body

Responses with request_id 0xffffffff are unsolicited events (stopped, resumed, JAM,
checkpoint hit). Any command sent while the machine runs halts it; send `exit()`
to resume.
"""

from __future__ import annotations

import re
import socket
import struct
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

STX = 0x02
API_VERSION = 0x02
EVENT_ID = 0xFFFFFFFF

# Commands
CMD_MEM_GET = 0x01
CMD_MEM_SET = 0x02
CMD_CHECKPOINT_GET = 0x11
CMD_CHECKPOINT_SET = 0x12
CMD_CHECKPOINT_DELETE = 0x13
CMD_CHECKPOINT_LIST = 0x14
CMD_CHECKPOINT_TOGGLE = 0x15
CMD_CONDITION_SET = 0x22
CMD_REGISTERS_GET = 0x31
CMD_REGISTERS_SET = 0x32
CMD_RESOURCE_GET = 0x51
CMD_RESOURCE_SET = 0x52
CMD_ADVANCE_INSTRUCTIONS = 0x71
CMD_KEYBOARD_FEED = 0x72
CMD_EXECUTE_UNTIL_RETURN = 0x73
CMD_PING = 0x81
CMD_BANKS_AVAILABLE = 0x82
CMD_REGISTERS_AVAILABLE = 0x83
CMD_DISPLAY_GET = 0x84
CMD_VICE_INFO = 0x85
CMD_PALETTE_GET = 0x91
CMD_JOYPORT_SET = 0xA2
CMD_EXIT = 0xAA
CMD_QUIT = 0xBB
CMD_RESET = 0xCC
CMD_AUTOSTART = 0xDD

# Response / event types
RESP_CHECKPOINT_INFO = 0x11
RESP_REGISTER_INFO = 0x31
RESP_JAM = 0x61
RESP_STOPPED = 0x62
RESP_RESUMED = 0x63

MEMSPACE_MAIN = 0x00

CPU_OP_LOAD = 0x01
CPU_OP_STORE = 0x02
CPU_OP_EXEC = 0x04

ERRORS = {
    0x01: "object does not exist",
    0x02: "invalid memspace",
    0x80: "command length incorrect",
    0x81: "invalid parameter",
    0x82: "unsupported API version",
    0x83: "unknown command",
    0x8F: "general failure",
}


class ViceError(Exception):
    pass


@dataclass
class Response:
    type: int
    error: int
    request_id: int
    body: bytes


@dataclass
class Checkpoint:
    number: int
    hit: bool
    start: int
    end: int
    stop: bool
    enabled: bool
    op: int
    temporary: bool
    hit_count: int


@dataclass
class Display:
    width: int
    height: int
    # visible area inside the full debug-sized buffer
    offset_x: int
    offset_y: int
    inner_width: int
    inner_height: int
    pixels: bytes  # 8-bit palette indices, width*height


@dataclass
class MonitorState:
    running: bool = True
    stopped_pc: int | None = None
    jammed_pc: int | None = None
    hit_checkpoints: list[int] = field(default_factory=list)


class ViceMonitor:
    def __init__(self, host: str = "127.0.0.1", port: int = 6502):
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self._next_id = 1
        self._buf = b""
        self.state = MonitorState()
        self._register_ids: dict[str, int] | None = None

    # -- connection -------------------------------------------------------

    def connect(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self.sock = socket.create_connection((self.host, self.port), timeout=2.0)
                self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                return
            except OSError as e:
                last_err = e
                time.sleep(0.1)
        raise ViceError(f"could not connect to VICE monitor on {self.host}:{self.port}: {last_err}")

    def close(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None

    # -- framing ----------------------------------------------------------

    def _recv_exact(self, n: int, timeout: float) -> bytes:
        assert self.sock
        self.sock.settimeout(timeout)
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ViceError("VICE closed the monitor connection")
            self._buf += chunk
        data, self._buf = self._buf[:n], self._buf[n:]
        return data

    def _read_message(self, timeout: float) -> Response:
        header = self._recv_exact(12, timeout)
        stx, api, length, rtype, err, rid = struct.unpack("<BBIBBI", header)
        if stx != STX:
            raise ViceError(f"bad frame start byte {stx:#x}")
        body = self._recv_exact(length, timeout)
        resp = Response(rtype, err, rid, body)
        self._track_event(resp)
        return resp

    def _track_event(self, r: Response) -> None:
        if r.type == RESP_STOPPED:
            self.state.running = False
            self.state.stopped_pc = struct.unpack_from("<H", r.body)[0]
        elif r.type == RESP_RESUMED:
            self.state.running = True
        elif r.type == RESP_JAM:
            self.state.running = False
            self.state.jammed_pc = struct.unpack_from("<H", r.body)[0]
        elif r.type == RESP_CHECKPOINT_INFO and r.request_id == EVENT_ID:
            self.state.hit_checkpoints.append(struct.unpack_from("<I", r.body)[0])

    def request(self, command: int, body: bytes = b"", timeout: float = 10.0) -> Response:
        """Send a command and return its response. Events that arrive first are tracked."""
        assert self.sock, "not connected"
        rid = self._next_id
        self._next_id = (self._next_id + 1) & 0x7FFFFFFF
        header = struct.pack("<BBIIB", STX, API_VERSION, len(body), rid, command)
        self.sock.sendall(header + body)
        while True:
            r = self._read_message(timeout)
            if r.request_id == rid:
                if r.error:
                    raise ViceError(f"command {command:#04x} failed: {ERRORS.get(r.error, hex(r.error))}")
                return r

    def drain_events(self, timeout: float = 0.05) -> None:
        """Consume any pending unsolicited events without blocking long."""
        try:
            while True:
                self._read_message(timeout)
        except (socket.timeout, TimeoutError):
            pass

    def wait_stopped(self, timeout: float) -> bool:
        """Block until the machine stops (checkpoint hit or JAM). Returns False on timeout."""
        deadline = time.monotonic() + timeout
        while self.state.running:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                self._read_message(remaining)
            except (socket.timeout, TimeoutError):
                return False
        return True

    # -- execution --------------------------------------------------------

    def ping(self) -> None:
        self.request(CMD_PING)

    def exit(self) -> None:
        """Resume execution."""
        self.state.hit_checkpoints.clear()
        self.request(CMD_EXIT)
        self.state.running = True

    def reset(self, hard: bool = False) -> None:
        self.request(CMD_RESET, bytes([1 if hard else 0]))

    def quit(self) -> None:
        try:
            self.request(CMD_QUIT, timeout=2.0)
        except (ViceError, OSError):
            pass

    def autostart(self, path: str, run: bool = True, file_index: int = 0) -> None:
        name = path.encode()
        self.request(CMD_AUTOSTART, struct.pack("<BHB", 1 if run else 0, file_index, len(name)) + name)

    def advance(self, count: int = 1, step_over: bool = False) -> None:
        self.request(CMD_ADVANCE_INSTRUCTIONS, struct.pack("<BH", 1 if step_over else 0, count))

    # -- memory -----------------------------------------------------------

    def mem_get(self, start: int, end: int, side_effects: bool = False) -> bytes:
        """Read start..end inclusive from the CPU's view of memory."""
        r = self.request(CMD_MEM_GET, struct.pack("<BHHBH", int(side_effects), start, end, MEMSPACE_MAIN, 0))
        length = struct.unpack_from("<H", r.body)[0] or 0x10000
        return r.body[2 : 2 + length]

    def mem_set(self, start: int, data: bytes, side_effects: bool = False) -> None:
        end = start + len(data) - 1
        self.request(CMD_MEM_SET, struct.pack("<BHHBH", int(side_effects), start, end, MEMSPACE_MAIN, 0) + data)

    # -- registers --------------------------------------------------------

    def register_ids(self) -> dict[str, int]:
        if self._register_ids is None:
            r = self.request(CMD_REGISTERS_AVAILABLE, bytes([MEMSPACE_MAIN]))
            count = struct.unpack_from("<H", r.body)[0]
            pos, ids = 2, {}
            for _ in range(count):
                size = r.body[pos]
                reg_id, _bits, name_len = r.body[pos + 1], r.body[pos + 2], r.body[pos + 3]
                ids[r.body[pos + 4 : pos + 4 + name_len].decode()] = reg_id
                pos += size + 1
            self._register_ids = ids
        return self._register_ids

    def registers(self) -> dict[str, int]:
        r = self.request(CMD_REGISTERS_GET, bytes([MEMSPACE_MAIN]))
        return self._parse_registers(r.body)

    def _parse_registers(self, body: bytes) -> dict[str, int]:
        names = {v: k for k, v in self.register_ids().items()}
        count = struct.unpack_from("<H", body)[0]
        pos, regs = 2, {}
        for _ in range(count):
            size = body[pos]
            reg_id, value = body[pos + 1], struct.unpack_from("<H", body, pos + 2)[0]
            regs[names.get(reg_id, f"r{reg_id}")] = value
            pos += size + 1
        return regs

    def set_register(self, name: str, value: int) -> None:
        reg_id = self.register_ids()[name]
        self.request(CMD_REGISTERS_SET, struct.pack("<BHBBH", MEMSPACE_MAIN, 1, 3, reg_id, value))

    # -- checkpoints ------------------------------------------------------

    def checkpoint_set(
        self,
        start: int,
        end: int | None = None,
        op: int = CPU_OP_EXEC,
        stop: bool = True,
        temporary: bool = False,
        enabled: bool = True,
    ) -> Checkpoint:
        body = struct.pack(
            "<HHBBBB", start, start if end is None else end, int(stop), int(enabled), op, int(temporary)
        )
        return self._parse_checkpoint(self.request(CMD_CHECKPOINT_SET, body).body)

    def checkpoint_delete(self, number: int) -> None:
        self.request(CMD_CHECKPOINT_DELETE, struct.pack("<I", number))

    def checkpoint_condition(self, number: int, condition: str) -> None:
        """Attach a text-monitor condition expression, e.g. 'RL == $30'."""
        cond = condition.encode()
        self.request(CMD_CONDITION_SET, struct.pack("<IB", number, len(cond)) + cond)

    @staticmethod
    def _parse_checkpoint(body: bytes) -> Checkpoint:
        number, hit, start, end, stop, enabled, op, temp, hits = struct.unpack_from("<IBHHBBBBI", body)
        return Checkpoint(number, bool(hit), start, end, bool(stop), bool(enabled), op, bool(temp), hits)

    # -- input ------------------------------------------------------------

    def keyboard_feed(self, text: str) -> None:
        """Queue text into the KERNAL keyboard buffer (PETSCII; use \\r for RETURN)."""
        data = text.encode("latin-1")
        for i in range(0, len(data), 255):
            chunk = data[i : i + 255]
            self.request(CMD_KEYBOARD_FEED, bytes([len(chunk)]) + chunk)

    def joyport_set(self, port: int, value: int) -> None:
        """Set a joystick port. port is 1 or 2; value bits: up=1 down=2 left=4 right=8 fire=16."""
        self.request(CMD_JOYPORT_SET, struct.pack("<HH", port, value))

    # -- resources --------------------------------------------------------

    def resource_set(self, name: str, value: int | str) -> None:
        n = name.encode()
        if isinstance(value, int):
            v, kind = struct.pack("<i", value), 1
        else:
            v, kind = value.encode(), 0
        self.request(CMD_RESOURCE_SET, struct.pack("<BB", kind, len(n)) + n + struct.pack("<B", len(v)) + v)

    def resource_get(self, name: str) -> int | str:
        n = name.encode()
        r = self.request(CMD_RESOURCE_GET, struct.pack("<B", len(n)) + n)
        kind, length = r.body[0], r.body[1]
        raw = r.body[2 : 2 + length]
        if kind == 1:
            return int.from_bytes(raw, "little", signed=True)
        return raw.decode()

    # -- display ----------------------------------------------------------

    def display_get(self) -> Display:
        r = self.request(CMD_DISPLAY_GET, struct.pack("<BB", 1, 0))  # VIC-II, 8bpp indexed
        b = r.body
        info_len = struct.unpack_from("<I", b)[0]
        w, h, ox, oy, iw, ih, bpp = struct.unpack_from("<HHHHHHB", b, 4)
        buf_len = struct.unpack_from("<I", b, 4 + info_len)[0]
        start = 8 + info_len
        return Display(w, h, ox, oy, iw, ih, b[start : start + buf_len])

    def palette(self) -> list[tuple[int, int, int]]:
        r = self.request(CMD_PALETTE_GET, bytes([1]))
        count = struct.unpack_from("<H", r.body)[0]
        pos, colours = 2, []
        for _ in range(count):
            size = r.body[pos]
            colours.append(tuple(r.body[pos + 1 : pos + 4]))
            pos += size + 1
        return colours

    def vice_info(self) -> str:
        r = self.request(CMD_VICE_INFO)
        vlen = r.body[0]
        version = ".".join(str(x) for x in r.body[1 : 1 + vlen])
        return version


def free_port() -> int:
    """Ask the OS for an unused TCP port on localhost."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def load_symbols(program: Path) -> dict[str, int]:
    """Read KickAssembler VICE symbols ('al C:080e .start') from .vs files beside the program."""
    candidates = [program.with_suffix(".vs")] + sorted(program.parent.glob("*.vs"))
    symbols: dict[str, int] = {}
    for vs in dict.fromkeys(candidates):
        if vs.exists():
            for line in vs.read_text().splitlines():
                m = re.match(r"al\s+C:([0-9a-fA-F]+)\s+\.(\S+)", line)
                if m:
                    symbols[m.group(2)] = int(m.group(1), 16)
    return symbols


PAL_LINES = 312
PAL_CYCLES_PER_LINE = 63


def start_vice(warp: bool = True, show_window: bool = False) -> tuple[subprocess.Popen, ViceMonitor]:
    """Launch a fresh x64sc (PAL, default settings) with the binary monitor on a free port.

    Returns (process, connected monitor). The caller owns both: `mon.quit(); mon.close()`
    then `proc.wait()`. Used by the MCP server's vice_start and by the budget runner.
    """
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
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    mon = ViceMonitor(port=port)
    try:
        mon.connect()
        mon.drain_events(0.3)
    except BaseException:
        proc.kill()
        raise
    return proc, mon


def run_frames(mon: ViceMonitor, frames: int) -> None:
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


def basic_sys_address(program: Path) -> int | None:
    """Entry point of a PRG with a BASIC upstart line ('10 SYS 2062'), or None."""
    if program.suffix.lower() != ".prg":
        return None
    data = program.read_bytes()
    if len(data) < 8 or data[0:2] != b"\x01\x08":
        return None
    m = re.search(rb"\x9e\s*\(?(\d+)", data[6:40])  # $9e = SYS token
    return int(m.group(1)) if m else None
