"""Rig tests against a fake emulator (no VICE): labels, memory, stick, frame stepping, watches."""

from types import SimpleNamespace

import pytest

from gametest import BITS, MeasureError, Rig, stick_mask
from gametest.guard import expect_memory

CPU_OP_EXEC, CPU_OP_STORE = 4, 2


class FakeMon:
    def __init__(self):
        self.ram = bytearray(65536)
        self.resources, self.joy, self.cps, self.log = {}, [], {}, []
        self.stops = []                    # PCs the machine will stop at, in order; empty = jam
        self.state = SimpleNamespace(jammed_pc=None)
        self.pc = 0
        self.n = 0

    def resource_set(self, name, value): self.resources[name] = value
    def joyport_set(self, port, value): self.joy.append((port, value))
    def mem_get(self, a, b): return bytes(self.ram[a:b + 1])
    def mem_set(self, a, data): self.ram[a:a + len(data)] = data

    def checkpoint_set(self, start, end, op):
        self.n += 1
        self.cps[self.n] = (start, end, op)
        return SimpleNamespace(number=self.n)

    def checkpoint_delete(self, n): del self.cps[n]
    def exit(self): self.log.append("exit")
    def ping(self): self.log.append("ping")

    def wait_stopped(self, timeout):
        if not self.stops:
            return False
        self.pc = self.stops.pop(0)
        return True

    def registers(self): return {"PC": self.pc, "A": 7}


class FakeVice:
    def __init__(self, prg, warmup):
        self.mon, self.symbols, self.closed = FakeMon(), {"frame_end": 0x1000, "zp_x": 0x10, "dbg": 0x2000, "sub": 0x3000}, False

    def close(self): self.closed = True


def rig(**kw):
    return Rig("x.prg", frame_label="frame_end", vice_factory=FakeVice, **kw)


def test_setup_switches_joyport_and_sets_frame_stop():
    r = rig()
    assert r.mon.resources == {"JoyPort2Device": 37}
    assert r.mon.joy == [(1, 0x1F)]
    assert list(r.mon.cps.values()) == [(0x1000, 0x1000, CPU_OP_EXEC)]
    assert rig(joyport=1).mon.resources == {"JoyPort1Device": 37}


def test_memory_by_label():
    r = rig()
    r.poke("zp_x", [1, 2, 3])
    r.poke("zp_x", 9, off=3)
    assert r.mem(0x10, 4) == bytes([1, 2, 3, 9])
    assert r.peek("zp_x", 2) == 3 and r.peek16("zp_x") == 0x0201
    r.poke16("zp_x", 0xBEEF)
    assert r.peeks("zp_x", 2) == bytes([0xEF, 0xBE])


def test_unknown_label_names_the_file():
    with pytest.raises(MeasureError, match="'nope'.*x.prg"):
        rig().peek("nope")


def test_stick_mask_and_names():
    assert stick_mask(["up", "fire"]) == BITS["up"] | BITS["fire"]
    assert stick_mask(0x0C) == 0x0C
    with pytest.raises(ValueError, match="jump"):
        stick_mask(["jump"])


def test_step_sets_the_stick_active_low_and_counts_frames():
    r = rig()
    r.mon.stops = [0x1000, 0x1000]
    r.step(["right", "fire"])
    assert r.mon.joy[-1] == (1, ~0x18 & 0x1F) and r.frames_run == 1
    r.step()                                  # no change to the stick
    assert len(r.mon.joy) == 2 and r.frames_run == 2


def test_frames_presses_only_in_the_first():
    r = rig()
    r.mon.stops = [0x1000] * 3
    r.frames(3, ["fire"])
    assert r.mon.joy[1:] == [(1, ~BITS["fire"] & 0x1F)] and r.frames_run == 3


def test_a_jam_raises_with_the_frame_number():
    r = rig()
    with pytest.raises(MeasureError, match="frame_end.*frame 1"):
        r.step()
    assert "ping" in r.mon.log


def test_is_debug_needs_every_debug_label():
    assert not rig().is_debug
    assert rig(debug_labels=("dbg",)).is_debug
    assert not rig(debug_labels=("dbg", "gone")).is_debug


def test_watch_and_delete():
    r = rig()
    w = r.watch("zp_x", "store")
    assert (0x10, 0x10, CPU_OP_STORE) in r.mon.cps.values()
    w.delete()
    w.delete()                                # twice is harmless
    assert (0x10, 0x10, CPU_OP_STORE) not in r.mon.cps.values()
    with pytest.raises(ValueError):
        r.watch("zp_x", "bogus")


def test_run_to_skips_other_stops_and_cleans_up():
    r = rig()
    r.mon.stops = [0x1000, 0x1000, 0x3000]
    regs = r.run_to("sub")
    assert regs["PC"] == 0x3000
    assert len(r.mon.cps) == 1                # only the frame stop is left


def test_close_closes_the_emulator():
    r = rig()
    with r:
        pass
    assert r.vice.closed


def test_expect_memory_reports_each_mismatch():
    r = rig()
    r.poke("zp_x", [5, 6])
    assert expect_memory(r, {"zp_x": 5, "zp_x+1": 6, "zp_x+0": [5, 6]}) == []
    got = expect_memory(r, {"zp_x": 4, "zp_x+1": lambda v: v > 9, "zp_x+0": (lambda b: b == bytes([5, 7]), 2)})
    assert len(got) == 3 and "zp_x = 5, expected 4" in got[0]
