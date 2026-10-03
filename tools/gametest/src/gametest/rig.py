"""The rig: one headless VICE running one game build, stepped one game frame at a time.

Generic parts of every game's behaviour script: start x64sc on a free port (budget_runner's `Vice`,
which loads the labels from the build's main.vs), read and write memory by label, drive joystick
port 2, run to the next execution of the game's frame label, stop on every execution of an address
(or every store to one), run to a label.

A game subclasses Rig for its own state readers and placing helpers (tests/games/swarm/swarmtest.py).
"""

from __future__ import annotations

from pathlib import Path

from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice
from vice_monitor import CPU_OP_EXEC, CPU_OP_LOAD, CPU_OP_STORE  # on sys.path once budget_runner.session is imported

__all__ = ["BITS", "JOYPORT_IO_SIMULATION", "MeasureError", "Rig", "Watch", "stick_mask"]

BITS = {"up": 0x01, "down": 0x02, "left": 0x04, "right": 0x08, "fire": 0x10}
JOYPORT_IO_SIMULATION = 37  # VICE's "I/O simulation" joyport device: the monitor sets the lines (mcp/vice/README.md)
_OPS = {"exec": CPU_OP_EXEC, "store": CPU_OP_STORE, "load": CPU_OP_LOAD}


def stick_mask(pressed) -> int:
    """An active-high joystick mask from an int, or from names ('up', 'fire', ...)."""
    if isinstance(pressed, int):
        return pressed
    mask = 0
    for name in pressed:
        if name not in BITS:
            raise ValueError(f"unknown joystick input {name!r} (expected one of {sorted(BITS)})")
        mask |= BITS[name]
    return mask


class Watch:
    """A checkpoint that stops the machine: every execution of an address, or every store to it."""

    def __init__(self, rig: Rig, number: int, label: str, kind: str):
        self.rig, self.number, self.label, self.kind = rig, number, label, kind

    def delete(self) -> None:
        if self.number is not None:
            self.rig.mon.checkpoint_delete(self.number)
            self.number = None


class Rig:
    """One running game: `mon` (the ViceMonitor), `sym` (label -> address), the frame label.

    frame_label: a label executed once per game frame (e.g. game_update_end). The machine is stopped
        there on every frame() and nowhere else, so each sample is exactly one game frame apart.
    joyport: 1 or 2. The port is switched to the monitor-driven device and all lines released.
    debug_labels: labels that exist only in a DEBUG build; `is_debug` is true when they are all there
        (a release build has no counters, so cases read them only `if t.is_debug`).
    vice_factory: how the emulator is started (default budget_runner's `Vice`); tests pass a fake.
    """

    def __init__(self, prg: Path | str, *, frame_label: str, joyport: int = 2, warmup_frames: int = 0,
                 debug_labels: tuple[str, ...] = (), vice_factory=Vice):
        if joyport not in (1, 2):
            raise ValueError("joyport must be 1 or 2")
        self.prg = Path(prg)
        self.frame_label = frame_label
        self.joyport = joyport
        self.debug_labels = tuple(debug_labels)
        self.vice = vice_factory(self.prg, warmup_frames)
        self.mon, self.sym = self.vice.mon, self.vice.symbols
        self.frame_stop: Watch | None = None
        self.frames_run = 0
        self.mon.resource_set(f"JoyPort{joyport}Device", JOYPORT_IO_SIMULATION)
        self.stick = 0
        self.mon.joyport_set(joyport - 1, 0x1F)
        self.frame_stop = self.watch(frame_label)

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self.vice.close()

    def __enter__(self) -> Rig:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def is_debug(self) -> bool:
        """True for a DEBUG build: every label in `debug_labels` exists (release builds drop them)."""
        return bool(self.debug_labels) and all(label in self.sym for label in self.debug_labels)

    # -- labels and memory --------------------------------------------------

    def addr(self, label: str | int) -> int:
        if isinstance(label, int):
            return label
        if label not in self.sym:
            raise MeasureError(f"label '{label}' is not in the build's symbols ({self.prg.name})")
        return self.sym[label]

    def mem(self, addr: int, n: int = 1) -> bytes:
        """n bytes at a numeric address."""
        return self.mon.mem_get(addr, addr + n - 1)

    def peek(self, label: str, off: int = 0) -> int:
        return self.mem(self.addr(label) + off)[0]

    def peek16(self, label: str, off: int = 0) -> int:
        b = self.mem(self.addr(label) + off, 2)
        return b[0] + 256 * b[1]

    def peeks(self, label: str, n: int, off: int = 0) -> bytes:
        return self.mem(self.addr(label) + off, n)

    def poke(self, label: str, data, off: int = 0) -> None:
        """Write bytes (a list, bytes or one int) at a label + off."""
        self.mon.mem_set(self.addr(label) + off, bytes([data]) if isinstance(data, int) else bytes(data))

    def poke16(self, label: str, value: int, off: int = 0) -> None:
        self.poke(label, [value & 255, value >> 8 & 255], off)

    # -- the joystick -------------------------------------------------------

    def set_stick(self, pressed) -> None:
        """Set the stick now (names or an active-high mask); it is read by the next frame."""
        self.stick = stick_mask(pressed)
        self.mon.joyport_set(self.joyport - 1, ~self.stick & 0x1F)

    # -- running ------------------------------------------------------------

    def resume(self, what: str = "the next stop", registers: bool = False):
        """Let the machine run to its next stop (any watch); returns the registers if asked for.
        A stop that doesn't come within STOP_TIMEOUT halts the machine and raises MeasureError."""
        self.mon.exit()
        if not self.mon.wait_stopped(STOP_TIMEOUT):
            self.mon.ping()
            raise MeasureError(f"{what} not reached: jam? (jammed_pc={self.mon.state.jammed_pc})")
        return self.mon.registers() if registers else None

    def step(self, pressed=None) -> None:
        """Optionally set the stick, then run to the next execution of the frame label."""
        if pressed is not None:
            self.set_stick(pressed)
        self.resume(f"{self.frame_label} (frame {self.frames_run + 1})")
        self.frames_run += 1

    def frame(self, pressed=None):
        """One game frame; a game's rig overrides this to also return its state."""
        self.step(pressed)

    def frames(self, n: int, pressed=None) -> None:
        """n frames; `pressed` applies from the first."""
        for i in range(n):
            self.frame(pressed if i == 0 else None)

    def watch(self, label: str | int, kind: str = "exec", end: str | int | None = None) -> Watch:
        """Stop the machine at every execution of (kind 'exec'), store to or load from an address
        (or the range label..end). Delete it with .delete() when done."""
        if kind not in _OPS:
            raise ValueError(f"kind must be one of {sorted(_OPS)}")
        a = self.addr(label)
        cp = self.mon.checkpoint_set(a, self.addr(end) if end is not None else a, _OPS[kind])
        return Watch(self, cp.number, str(label), kind)

    def run_to(self, label: str | int):
        """Run to the next execution of a label (the frame stop stays set, so it can stop first:
        loops until PC is the label) and return the registers. For one stop in a known place."""
        target = self.addr(label)
        w = None if self.addr(self.frame_label) == target else self.watch(label)
        try:
            for _ in range(10_000):
                regs = self.resume(str(label), registers=True)
                if regs["PC"] == target:
                    return regs
            raise MeasureError(f"{label} not reached in 10,000 stops")
        finally:
            if w:
                w.delete()
