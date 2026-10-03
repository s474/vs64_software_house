"""Run one built spike in VICE and measure its checks. Uses mcp/vice/vice_monitor.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .evaluate import (
    FRAME, CYCLES_PER_LINE, Event, Result, eval_irq_time, eval_memory, eval_profile,
    SampleCounter, eval_start_cycle, irq_time_by_frame, profile_passes,
)
from .spec import REPO, Budget, Check

sys.path.insert(0, str(REPO / "mcp" / "vice"))

from vice_monitor import (  # noqa: E402
    CPU_OP_EXEC, ViceError, ViceMonitor, basic_sys_address, load_symbols, run_frames, start_vice,
)

STOP_TIMEOUT = 5.0  # seconds to wait for the next watched address before giving up


class MeasureError(Exception):
    """The program did not behave well enough to measure (label never reached, no symbols...)."""


def build_program(game: str, src_dir: str | None = None, asset_dir: list[str] | None = None) -> Path:
    """make GAME=<game> [SRC_DIR=<src_dir>] [ASSET_DIR=<dirs>] (DEBUG build); returns the PRG path."""
    args = [f"GAME={game}"] + ([f"SRC_DIR={src_dir}"] if src_dir else []) \
        + ([f"ASSET_DIR={' '.join(asset_dir)}"] if asset_dir else [])
    proc = subprocess.run(["make", "-s", *args], cwd=REPO, capture_output=True, text=True)
    if proc.returncode:
        raise MeasureError(f"build failed (make {' '.join(args)}):\n" + (proc.stdout + proc.stderr).strip())
    prg = REPO / "build" / game / f"{game}.prg"
    if not prg.exists():
        raise MeasureError(f"build produced no {prg}")
    return prg


def build(budget: Budget) -> Path:
    """Build the spike: make GAME=<spike> SRC_DIR=<src_dir> [ASSET_DIR=...] (DEBUG build)."""
    return build_program(budget.spike, budget.src_dir, budget.asset_dir)


class Vice:
    """One VICE instance running one program, with the symbols of that build."""

    def __init__(self, prg: Path, warmup_frames: int, boot_frames: int = 250):
        self.symbols = load_symbols(prg)
        if not self.symbols:
            raise MeasureError(f"no labels found beside {prg} (expected main.vs from the build)")
        self.proc, self.mon = start_vice(warp=True, show_window=False)
        try:
            self.mon.autostart(str(prg), run=True)
            entry = basic_sys_address(prg)
            if entry is None:
                run_frames(self.mon, boot_frames)
            else:
                cp = self.mon.checkpoint_set(entry, entry, CPU_OP_EXEC)
                self.mon.exit()
                reached = self.mon.wait_stopped(5.0 + boot_frames / 50)
                if not reached:
                    self.mon.ping()
                    self.mon.drain_events()
                self.mon.checkpoint_delete(cp.number)
                if not reached:
                    raise MeasureError(f"program entry ${entry:04x} not reached within {boot_frames} frames")
            run_frames(self.mon, warmup_frames)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        try:
            self.mon.quit()
            self.mon.close()
        finally:
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def addr(self, label: str) -> int:
        if label in self.symbols:
            return self.symbols[label]
        try:
            return int(label.lstrip("$"), 16) if label.startswith("$") else int(label, 0)
        except ValueError:
            raise MeasureError(f"label '{label}' is not in the build's symbols") from None

    def trace(self, addrs: list[int], done, what: str) -> list[Event]:
        """Stop at every execution of `addrs` until done(events); returns the events in order."""
        cps = [self.mon.checkpoint_set(a, a, CPU_OP_EXEC) for a in dict.fromkeys(addrs)]
        events: list[Event] = []
        base, prev = 0, -1
        try:
            while not done(events):
                self.mon.exit()
                if not self.mon.wait_stopped(STOP_TIMEOUT):
                    self.mon.ping()
                    self.mon.drain_events()
                    raise MeasureError(f"timed out waiting for {what} ({len(events)} events seen)")
                r = self.mon.registers()
                t = r["LIN"] * CYCLES_PER_LINE + r["CYC"]
                if t < prev:
                    base += FRAME
                prev = t
                events.append(Event(r["PC"], base + t, r["LIN"], r["CYC"]))
        finally:
            for c in cps:
                self.mon.checkpoint_delete(c.number)
        return events

    def run(self, check: Check) -> Result:
        try:
            return getattr(self, "_" + check.kind)(check)
        except (MeasureError, ViceError) as e:
            return Result(check, error=str(e))

    # -- check kinds ------------------------------------------------------

    def _profile(self, check: Check, excl_irq: bool = False) -> Result:
        p = check.params
        a, b = (self.addr(x) for x in p["routine"])
        extra = [self.addr("irq_dispatch"), self.addr("irq_exit_rti")] if excl_irq else []
        dr = tuple(extra) if extra else (None, None)
        # Count the IRQs that fire inside each pass (the premise) when the build has the IRQ framework
        dispatch = self.symbols.get("irq_dispatch")
        if dispatch is None and p.get("irqs_inside_max") is not None:
            raise MeasureError("'irqs_inside_max' needs the label irq_dispatch, which this build does not have")
        counter = SampleCounter(a, b)  # incremental: each stop costs O(1), not a rescan of all events
        events = self.trace(
            [a, b, *extra, *([dispatch] if dispatch is not None else [])],
            lambda ev: counter.update(ev) >= p["samples"],
            f"{p['routine'][0]} -> {p['routine'][1]}")
        return eval_profile(check, profile_passes(events, a, b, *dr, count_dispatch=dispatch)[: p["samples"]])

    def _profile_excl_irq(self, check: Check) -> Result:
        return self._profile(check, excl_irq=True)

    def _start_cycle(self, check: Check) -> Result:
        p = check.params
        a = self.addr(p["label"])
        events = self.trace([a], lambda ev: len(ev) >= p["frames"], p["label"])
        return eval_start_cycle(check, events)

    def _irq_time_per_frame(self, check: Check) -> Result:
        p = check.params
        d, r = self.addr("irq_dispatch"), self.addr("irq_exit_rti")
        events = self.trace([d, r], lambda ev: bool(ev) and ev[-1].t // FRAME >= p["frames"] + 1,
                            "irq_dispatch / irq_exit_rti")
        return eval_irq_time(check, irq_time_by_frame(events, d, r, p["frames"]))

    def _memory(self, check: Check) -> Result:
        p = check.params
        a = self.addr(p["address"])
        run_frames(self.mon, p["after_frames"])
        data = self.mon.mem_get(a, a + p["size"] - 1)
        return eval_memory(check, int.from_bytes(data, "little"))
