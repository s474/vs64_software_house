"""Measure what VICE's SID does, through the two registers a program can read back: the figures
behind docs/reference/sid.md (facts 2-9, 14 and 15 of engine/sfx.md's list).

Drives tests/timing/sid_readback/main.asm (its header describes the three tests and the cfg_*
block this script pokes). Everything is voice 3: $D41B is the top 8 bits of its waveform output,
$D41C its envelope. What is measured is VICE 3.10's reSID emulation, not the chip.

Sections of the output (results.txt is the committed run):

  1 HARNESS    For each way VICE gets started here (the budget runner and MCP server's own
               start_vice, the same without warp, this script's own, VICE's defaults with real
               sound, sound switched off, and Simon's own settings as `make run` uses them): the
               SID resources, whether $D41B and $D41C read live, and what the MONITOR returns for
               $D400-$D418 after the program has written them (the test tools' read).
  2 READBACK   What a CPU read of $D400-$D41C returns: 4 cycles after writing the register, a
               frame later, and after a write to another register.
  3 OSC        The accumulator: sawtooth at three frequency values, 256 reads of $D41B 16 cycles
               apart, compared with floor(F x t / 65536) mod 256 for every read.
  4 ENVELOPE   $D41C tick by tick (once a frame, line 251) for every attack/decay and
               sustain/release pair Swarm's ten effects use, gate off on the effect's last tick;
               and the attack seen 22-42 cycles apart.
  5 RETRIGGER  (a) a control write with the gate already set; (b) a start (control 0, then the
               gate again 63 cycles later) on a sounding voice; (c) a one-tick gate-off step.
  6 PULSE      Pulse width n/16: the share of $D41B reads that are $FF over exactly one period.
  7 NOISE      Control $81: how often $D41B changes, against the frequency value.
  8 LATE       How long after the gate-on write the envelope first rises, for the successions
               of effects Swarm can produce (the envelope's rate-counter oddity), each in 9 phases.
  9 VARIANT    The same with a start sequence of 8 writes (decay 0 until the gate is on): evidence
               for a decision that is the Technical Director's, not something the module does.

Why this script starts VICE itself: under `-sounddev dummy` (what the budget runner and the MCP
server use) $D41B and $D41C do not read live (section 1 shows it). Sections 2-9 run under
`-sounddev dump -soundarg /dev/null`: reSID is clocked, nothing is played. Section 1 also opens
the Mac's real sound device for a few seconds; the probe keeps $D418 = 0, so it is silent.

Run from the repo root (build first: make GAME=sid_readback SRC_DIR=tests/timing/sid_readback):

    uv run --package budget-runner python tests/timing/sid_readback/measure.py \
        | tee tests/timing/sid_readback/results.txt

About three minutes (sections 8 and 9 are some 1,500 runs). --only 2,3 runs some sections. --skip-real leaves out the two configurations that open the real sound device.
Exit code 1 if a check marked [FAIL] fails (the hard facts: the accumulator fit, the pulse
counts, the monitor read, the live readings under this script's own settings).
"""

import argparse
import subprocess
import sys
from pathlib import Path

import budget_runner.session  # noqa: F401  puts mcp/vice on sys.path
from vice_monitor import (CPU_OP_EXEC, ViceMonitor, basic_sys_address, free_port, load_symbols,
                          start_vice)

REPO = Path(__file__).resolve().parents[3]
PRG = REPO / "build/sid_readback/sid_readback.prg"
RESOURCES = ["SidEngine", "SidModel", "Sound", "SoundDeviceName", "SoundSampleRate", "SidResidSampling"]
PROBE_SOUND = ["-sounddev", "dump", "-soundarg", "/dev/null"]
FRAME = 19656
PAL_CLOCK = 985248  # docs/reference/vic-ii-timing.md: unmeasured

# Nominal envelope times (the SID data sheet's table: standard figures, unverified), in ms.
ATTACK_MS = [2, 8, 16, 24, 38, 56, 68, 80, 100, 250, 500, 800, 1000, 3000, 5000, 8000]
DECAY_MS = [6, 24, 48, 72, 114, 168, 204, 240, 300, 750, 1500, 2400, 3000, 9000, 15000, 24000]

# Every attack/decay and sustain/release pair of Swarm's ten effects (games/swarm/src/sfx_data.asm),
# with the frames the gate is held (the effect's length, or its first note's).
SWARM_ENV = [
    ("player shot", 0x00, 0xA0, 8),
    ("enemy shot", 0x00, 0xF0, 6),
    ("dive", 0x10, 0x80, 30),
    ("enemy explosion", 0x08, 0x00, 16),
    ("player hit (both voices), game over (a note: 15)", 0x0A, 0x00, 60),
    ("wave start, wave clear (a note), start", 0x09, 0x00, 9),
]

fails = []


def out(s=""):
    print(s, flush=True)


def check(ok, text):
    out(f"   [{'ok' if ok else 'FAIL'}] {text}")
    if not ok:
        fails.append(text)
    return ok


def hexs(b):
    return " ".join(f"{x:02x}" for x in b)


class Probe:
    """One VICE running the probe, stopped at probe_done between tests."""

    def __init__(self, args=None, warp=True, std=None):
        self.sym = load_symbols(PRG)
        if std is not None:  # the harness's own start: start_vice(warp=std)
            self.proc, self.mon = start_vice(warp=std, show_window=False)
            self.cmdline = "start_vice(warp=%s): x64sc -default -pal -sounddev dummy%s -minimized" % (
                std, " -warp" if std else "")
        else:
            port = free_port()
            cmd = ["x64sc", *args, "-binarymonitor", "-binarymonitoraddress", f"ip4://127.0.0.1:{port}",
                   "-autostartprgmode", "1", "-minimized"] + (["-warp"] if warp else [])
            self.cmdline = " ".join(["x64sc", *args] + (["-warp"] if warp else []) + ["-minimized"])
            self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
            self.mon = ViceMonitor(port=port)
            try:
                self.mon.connect()
                self.mon.drain_events(0.3)
            except BaseException:
                self.proc.kill()
                raise
        mon = self.mon
        try:
            mon.autostart(str(PRG), run=True)
            entry = basic_sys_address(PRG)
            cp = mon.checkpoint_set(entry, entry, CPU_OP_EXEC)
            mon.exit()
            if not mon.wait_stopped(40):
                raise RuntimeError("the probe did not start")
            mon.checkpoint_delete(cp.number)
            self.done = mon.checkpoint_set(self.sym["probe_done"], self.sym["probe_done"], CPU_OP_EXEC)
        except BaseException:
            self.close()
            raise

    def close(self):
        try:
            self.mon.quit()
            self.mon.close()
        finally:
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def poke(self, label, data, offset=0):
        self.mon.mem_set(self.sym[label] + offset, bytes(data))

    def buf(self, label, n):
        a = self.sym[label]
        return self.mon.mem_get(a, a + n - 1)

    def go(self, test, stops=()):
        """Run one test to probe_done. `stops`: labels to stop at on the way; returns
        {label: [(time in cycles, monitor read of $D400-$D41C), ...]} for those."""
        self.poke("cfg_test", [test])
        self.poke("cfg_go", [1])
        cps = {self.mon.checkpoint_set(self.sym[s], self.sym[s], CPU_OP_EXEC).number: s for s in stops}
        addr = {self.sym[s]: s for s in stops}
        seen = {s: [] for s in stops}
        base, prev = 0, -1
        try:
            while True:
                self.mon.exit()
                if not self.mon.wait_stopped(60):
                    raise RuntimeError("the probe did not reach probe_done")
                r = self.mon.registers()
                t = r["LIN"] * 63 + r["CYC"]
                if t < prev:
                    base += FRAME
                prev = t
                if r["PC"] == self.sym["probe_done"]:
                    return seen
                s = addr[r["PC"]]
                if len(seen[s]) < 3:
                    seen[s].append((base + t, self.mon.mem_get(0xD400, 0xD41C)))
                if len(seen[s]) >= 3:  # enough: stop watching this one (a loop would stop 256 times)
                    for n, name in list(cps.items()):
                        if name == s:
                            self.mon.checkpoint_delete(n)
                            del cps[n]
        finally:
            for n in cps:
                self.mon.checkpoint_delete(n)

    # -- the three tests ----------------------------------------------------------------------

    def osc(self, freq, ctrl, pw=8, stops=()):
        self.poke("cfg_flo", [freq & 255])
        self.poke("cfg_fhi", [freq >> 8])
        self.poke("cfg_pw", [pw])
        self.poke("cfg_ctrl", [ctrl])
        seen = self.go(1, stops)
        return self.buf("fine_buf", 256), seen

    def env(self, sets, acts, frames, fine_k=None, fine_delay=1, gap=4, fine_reg=0x1C, stops=(), phase=1):
        """sets: up to two (ad, sr, pw, freq, ctrl). acts: {tick: 1 | 2 | 5 | 6 | (3, control value)}."""
        for i, (ad, sr, pw, freq, ctrl) in enumerate(sets):
            for label, v in (("set_ad", ad), ("set_sr", sr), ("set_pw", pw), ("set_flo", freq & 255),
                             ("set_fhi", freq >> 8), ("set_ctrl", ctrl)):
                self.poke(label, [v], i)
        act, val = bytearray(256), bytearray(256)
        for k, a in acts.items():
            if isinstance(a, tuple):
                act[k], val[k] = a
            else:
                act[k] = a
        self.poke("cfg_act", act)
        self.poke("cfg_actval", val)
        self.poke("cfg_frames", [frames])
        self.poke("cfg_gap", [gap])
        self.poke("cfg_fine_k", [0xFF if fine_k is None else fine_k])
        self.poke("cfg_fine_delay", [fine_delay])
        self.poke("cfg_phase", [phase])
        self.poke("fine_read", [fine_reg], 1)
        seen = self.go(2, stops)
        return self.buf("env_buf", frames), self.buf("fine_buf", 256), seen


def saw_model(freq, d, n=256):
    return bytes(((freq * (d + 16 * i)) >> 16) & 0xFF for i in range(n))


def saw_fit(freq, got):
    """The read offsets d (cycles from the oscillator starting to the first read) that fit all reads."""
    return [d for d in range(0, 17) if saw_model(freq, d) == got]


# ---------------------------------------------------------------------------------------------


def section_harness(skip_real):
    out("== 1 HARNESS: does the SID read back under each way of starting VICE? ==")
    out("   live osc = sawtooth at $1000 on voice 3, 256 reads of $D41B 16 cycles apart, all as the accumulator model")
    out("   live env = attack 0, sustain 15, gate on: $D41C is $FF one frame later")
    out("   monitor  = the program writes ($A5 eor n) to register n of $D400-$D418; the monitor then reads them")
    configs = [
        ("budget runner and MCP server (start_vice, warp)", dict(std=True)),
        ("the same without warp", dict(std=False)),
        ("this script (-sounddev dump -soundarg /dev/null, warp)", dict(args=["-default", "-pal", *PROBE_SOUND])),
        ("the same without warp", dict(args=["-default", "-pal", *PROBE_SOUND], warp=False)),
        ("sound switched off (+sound, warp)", dict(args=["-default", "-pal", "+sound"])),
    ]
    if not skip_real:
        configs += [
            ("VICE's defaults, real sound device, no warp", dict(args=["-default", "-pal"], warp=False)),
            ("VICE's defaults, real sound device, warp", dict(args=["-default", "-pal"])),
            ("Simon's own settings, as `make run` starts it (no -default)", dict(args=[], warp=False)),
        ]
    for name, kw in configs:
        p = Probe(**kw)
        try:
            res = {r: p.mon.resource_get(r) for r in RESOURCES}
            got, _ = p.osc(0x1000, 0x20)
            fit = saw_fit(0x1000, got)
            if fit:
                osc = "LIVE"
            elif len(set(got)) == 1:
                osc = f"NOT LIVE: every read ${got[0]:02x}"
            else:
                osc = f"NOT THE OSCILLATOR: {hexs(got[:8])} ..."
            e, _, _ = p.env([(0x00, 0xF0, 8, 0x1000, 0x21)], {0: 1}, 4)
            env = "LIVE" if e[1] == 0xFF else f"NOT LIVE: {hexs(e)}"
            p.poke("cfg_val", [0xA5])
            seen = p.go(0, stops=["rb_written"])
            mon = seen["rb_written"][0][1][:25]
            want = bytes(0xA5 ^ r for r in range(25))
            out(f"   {name}")
            out(f"      {p.cmdline}")
            out("      " + ", ".join(f"{k} = {v}" for k, v in res.items()))
            out(f"      $D41B: {osc}.  $D41C: {env}")
            out(f"      monitor read of $D400-$D418: {'the values written' if mon == want else hexs(mon)}")
            if "dump" in p.cmdline:
                check(bool(fit) and e[1] == 0xFF, "this script's settings read $D41B and $D41C live")
            check(mon == want, "the monitor returns the last value written to each of $D400-$D418")
        finally:
            p.close()
    out("   SidEngine 1 = reSID. SidModel 0 = 6581, 1 = 8580, 2 = 8580 + digi boost (x64sc -help, -sidenginemodel:")
    out("   256 reSID 6581, 257 reSID 8580, 258 reSID 8580 + digiboost).")
    out()


def section_readback(p):
    out("== 2 READBACK: what the program reads from $D400-$D41C ==")
    p.poke("cfg_val", [0xA5])
    seen = p.go(0, stops=["rb_written"])
    now, later, bus = p.buf("rb_now", 25), p.buf("rb_later", 29), p.buf("rb_bus", 29)
    want = bytes(0xA5 ^ r for r in range(25))
    out(f"   written           : {hexs(want)}")
    out(f"   read 4 cycles on  : {hexs(now)}")
    out(f"   read a frame later: {hexs(later[:25])} | $D419-$D41C: {hexs(later[25:])}")
    out(f"   after $5A -> $D401: {hexs(bus[:25])} | $D419-$D41C: {hexs(bus[25:])}")
    out(f"   monitor, no side effects, at the same moment as the first row: {hexs(seen['rb_written'][0][1][:25])}")
    check(now == want, "a read 4 cycles after the write returns the value just written")
    check(len(set(later[:25])) == 1, f"a frame later every write-only register reads the same: ${later[0]:02x}"
          f" (the last byte written to the chip was ${want[24]:02x})")
    check(set(bus[:25]) == {0x5A}, "after a write to one register, every write-only register reads that byte")
    out("   So a read does not return the register: it returns the last byte written to ANY SID register")
    out("   (how long that lasts on a chip is not measured here: the read a frame later still had it).")
    out()


def section_osc(p):
    out("== 3 OSC: the accumulator (sawtooth, $D41B = bits 23-16) ==")
    first = True
    for freq in (0x1000, 0x1D45, 0xF123, 0x0001):
        got, seen = p.osc(freq, 0x20, stops=["osc_release", "osc_read"] if first else ())
        if first:
            rel, rd = seen["osc_release"][0][0], [t for t, _ in seen["osc_read"]]
            out(f"   spacing, measured at the labels: release write -> first read {rd[0] - rel} cycles "
                f"(instruction starts; the write and the read are each its 4th cycle), read period "
                f"{rd[1] - rd[0]}, {rd[2] - rd[1]}")
            check(rd[1] - rd[0] == 16 and rd[2] - rd[1] == 16 and rd[0] - rel == 4, "the reads are 16 cycles apart, the first 4 after the write")
            first = False
        fit = saw_fit(freq, got)
        out(f"   F = ${freq:04x}: reads {hexs(got[:12])} ... {hexs(got[-4:])}")
        if freq > 1:
            check(bool(fit), f"all 256 reads = floor(F x (d + 16 i) / 65536) mod 256 with d = {fit} cycles")
        else:
            check(set(got) == {0}, "F = 1: all 256 reads 0 (4,084 cycles x 1 is below 65,536)")
    out("   So the oscillator is a 24-bit count that adds the frequency value once a cycle, from the cycle the")
    out("   test bit is cleared: Hz = F x clock / 16,777,216. With the PAL clock figure (985,248, unmeasured)")
    out(f"   F = Hz x {16777216 / PAL_CLOCK:.4f}; A4 (440 Hz) = {round(440 * 16777216 / PAL_CLOCK)} = ${round(440 * 16777216 / PAL_CLOCK):04x}.")
    out()


def frames_to(e, start, pred):
    for k in range(start, len(e)):
        if pred(e[k]):
            return k - start
    return None


def section_envelope(p):
    out("== 4 ENVELOPE: $D41C at each tick (before the tick's write), for Swarm's values ==")
    out("   tick 0 = the start (gate on); G = the tick the gate is cleared. One tick = 19,656 cycles = 19.95 ms.")
    for name, ad, sr, gate in SWARM_ENV:
        n = min(gate + 40, 120)
        e, _, _ = p.env([(ad, sr, 8, 0x1D45, 0x41)], {0: 1, gate: (3, 0x40)}, n)
        a, d, s, r = ad >> 4, ad & 15, sr >> 4, sr & 15
        out(f"   {name}: AD ${ad:02x} SR ${sr:02x}, G = {gate}"
            f"   (nominal: attack {ATTACK_MS[a]} ms, decay {DECAY_MS[d]} ms to sustain ${s * 17:02x}, release {DECAY_MS[r]} ms)")
        for i in range(0, n, 20):
            out(f"      tick {i:3d}: {hexs(e[i:i + 20])}")
        peak = max(e[1:gate + 1])
        at_gate = e[gate]
        zero = frames_to(e, gate, lambda x: x == 0)
        out(f"      highest value seen at a tick ${peak:02x}; at G ${at_gate:02x}; "
            f"0 first read {zero if zero is not None else 'not within the run:'} ticks after G"
            + ("" if zero is not None else f" ${e[-1]:02x} at tick {n - 1}"))
        if s:
            check(any(x == s * 17 for x in e[1:gate + 1]), f"the sustain level is the nibble x 17 = ${s * 17:02x}")
    out("   The attack, read finely (period 22 or 42 cycles), gate on from silence (rate counter at rate 0):")
    for a in (0, 1):
        delay = 1 if a == 0 else 5
        e, f, seen = p.env([(a << 4, 0xF0, 8, 0x1D45, 0x41)], {0: 1}, 2, fine_k=0, fine_delay=delay,
                           stops=["env_gate", "fine_read"])
        t0 = seen["fine_read"][0][0] - seen["env_gate"][0][0]
        per = seen["fine_read"][1][0] - seen["fine_read"][0][0]
        top = next((i for i, x in enumerate(f) if x == 0xFF), None)
        rise = next((i for i, x in enumerate(f) if x > 0), None)
        out(f"      attack {a}: first read {t0} cycles after the gate-on write, then every {per}: {hexs(f[:10])} ...")
        if top is None:
            check(False, f"attack {a}: $FF not reached in the window")
            continue
        out(f"         first non-zero read at {t0 + rise * per} cycles; $FF first read at {t0 + top * per} cycles = "
            f"{(t0 + top * per) / PAL_CLOCK * 1000:.2f} ms (nominal {ATTACK_MS[a]} ms)")
    out()


def rise_of(f):
    """Index of the first read higher than the one before it, and of the first read of $F0 or more
    (at 132 cycles a read, $FF itself can fall between two reads when the decay is fast)."""
    return (next((i for i in range(1, 256) if f[i] > f[i - 1]), None),
            next((i for i, x in enumerate(f) if x >= 0xF0), None))


def section_retrigger(p):
    out("== 5 RETRIGGER ==")
    slow = (0x0A, 0x00, 8, 0x1D45, 0x41)  # attack 0, decay 10 (1.5 s), sustain 0: falls slowly from $FF
    fast = (0x00, 0xA0, 8, 0x1D45, 0x41)  # attack 0, decay 0, sustain 10: sits at $AA
    out("   (a) a control write with the gate already set, at tick 5; $D41C then read every 132 cycles for 33,800")
    out("       cycles. A restarted attack would show as a read higher than the one before it.")
    for name, sett in (("AD $0A SR $00 (falling slowly from $FF)", slow), ("AD $00 SR $A0 (sustaining at $AA)", fast)):
        for val, what in ((0x41, "$41 again"), (0x21, "$21 (another waveform, gate still set)")):
            e, f, _ = p.env([sett], {0: 1, 5: (3, val)}, 6, fine_k=5, fine_delay=23)
            rise, _ = rise_of(f)
            out(f"       {name}, tick 5 writes {what}: level ${e[5]:02x}, reads {hexs(f[:4])} ... {hexs(f[-2:])}")
            check(rise is None and f[0] <= e[5], f"writing {what} with the gate set does not restart the attack")
    ref, _, _ = p.env([slow], {0: 1}, 12)
    e, _, _ = p.env([slow], {0: 1, 5: (3, 0x41)}, 12)
    out(f"       AD $0A SR $00 tick by tick, no write   : {hexs(ref)}")
    out(f"       the same with $41 written at tick 5    : {hexs(e)}")
    out("       (two rows that differ by a shift are a start that was late in one of them: section 8)")
    out("   (b) a start on a sounding voice at tick 5: control 0, then the gate again (the module's 7 writes).")
    out("       $D41C read every 132 cycles from the gate-on write.")
    for name, sett in (("AD $00 SR $A0 (every rate 0; sustaining at $AA)", fast),
                       ("AD $0A SR $00 (decay 10; falling)", slow)):
        out(f"       {name}")
        for gap in (4, 2, 1):
            e, f, seen = p.env([sett], {0: 1, 5: 1}, 12, fine_k=5, fine_delay=23, gap=gap,
                               stops=["env_ctrl0", "env_gate", "fine_read"])
            sp = seen["env_gate"][-1][0] - seen["env_ctrl0"][-1][0]
            t0 = seen["fine_read"][0][0] - seen["env_gate"][-1][0]
            per = seen["fine_read"][1][0] - seen["fine_read"][0][0]
            rise, top = rise_of(f)
            out(f"          control 0 -> gate {sp} cycles (measured): level at tick 5 ${e[5]:02x}; first reads {hexs(f[:5])}; "
                f"first rise {'none' if rise is None else f'{t0 + rise * per:,d}'} cycles after the gate, "
                f"$F0 or more {'not reached' if top is None else f'at {t0 + top * per:,d}'}")
            check(top is not None and rise is not None and min(f[:rise]) >= e[5] - 0x12,
                  "the attack restarts from about the level the envelope was at, not from 0, and reaches the top")
    e, _, _ = p.env([slow], {0: 1, 5: 1}, 12)
    out(f"       AD $0A SR $00 tick by tick: {hexs(e)}")
    out("   (c) a gate-off step between notes: AD $09 SR $00 (the note effects), gate off at tick 9.")
    note = (0x09, 0x00, 8, 0x1D45, 0x41)
    for off_ticks in (1, 2):
        on = 9 + off_ticks
        acts = {0: 1, 9: (3, 0x40), on: (3, 0x41)}
        e2, _, _ = p.env([note], acts, 22)
        e, f, seen = p.env([note], acts, on + 1, fine_k=on, fine_delay=23, stops=["fine_read"])
        per = seen["fine_read"][1][0] - seen["fine_read"][0][0]
        rise, top = rise_of(f)
        out(f"       gate off for {off_ticks} tick(s), on again at tick {on}: {hexs(e2)}")
        out(f"          level when the gate is set again ${e2[on]:02x}; first reads {hexs(f[:5])}; first rise at read "
            f"{rise}, $F0 or more at read {top} (reads {per} cycles apart, the first a few cycles after the write)")
        check(top is not None and e2[on + 1] > e2[9], "the gate-on starts a new attack: the top is reached again within the tick")
    out()


def section_pulse(p):
    out("== 6 PULSE: control $40, F = $1000, 256 reads 16 cycles apart = exactly one period ==")
    out("   n = the high register ($D411), low register 0")
    ok = True
    rows = []
    for n in range(16):
        got, _ = p.osc(0x1000, 0x40, pw=n)
        hi, lo = sum(1 for x in got if x == 0xFF), sum(1 for x in got if x == 0x00)
        rows.append((n, hi, lo))
        ok &= hi + lo == 256 and lo == 16 * n
    for i in range(0, 16, 4):
        out("      " + "   ".join(f"n={n:2d}: $FF {hi:3d}, $00 {lo:3d}" for n, hi, lo in rows[i:i + 4]))
    check(ok, "every read is $00 or $FF, and the share of $00 reads is exactly n/16 (so $FF is 1 - n/16): "
              "the output is low while the top 12 bits of the accumulator are below the width")
    out("   n = 0 is a constant $FF: no sound from that voice. n and 16 - n are the same wave upside down.")
    out()


def section_noise(p):
    out("== 7 NOISE: control $81 (after the test bit), 256 reads of $D41B 16 cycles apart ==")
    for freq in (0x0400, 0x1000, 0x4000, 0xFFFF):
        got, _ = p.osc(freq, 0x81)
        changes = sum(1 for i in range(1, 256) if got[i] != got[i - 1])
        step = (1 << 20) / freq
        out(f"   F = ${freq:04x}: {changes:3d} changes in 4,080 cycles; one shift every 2^20 / F = {step:.0f} cycles "
            f"would be {4080 / step:.0f}.  {hexs(got[:10])} ...")
    got1, _ = p.osc(0x1000, 0x81)
    got2, _ = p.osc(0x1000, 0x81)
    out(f"   the same run twice gives {'the same' if got1 == got2 else 'different'} reads"
        + ("" if got1 == got2 else " (about 1,300 cycles of the test bit do not reset the noise register)"))
    out("   So the noise value changes at a rate that follows the frequency value: once every 2^20 / F cycles.")
    out()


PHASES = range(1, 10)  # 5 cycles a step: every phase of a 9-cycle rate period
MANY = range(1, 46)    # the same five times over, for the from-silence counts
LATE = 2000            # cycles: a first rise later than this is "late" (a prompt one is under 200)


def first_rise(p, sets, acts, tick, phase):
    """Run `acts` up to `tick`, whose action is followed by reads of $D41C every 132 cycles.
    Returns (level at the tick, cycles from the gate-on write to the first rising read or None)."""
    e, f, seen = p.env(sets, acts, tick + 1, fine_k=tick, fine_delay=23, stops=["env_gate", "fine_read"], phase=phase)
    per = seen["fine_read"][1][0] - seen["fine_read"][0][0]
    t0 = seen["fine_read"][0][0] - seen["env_gate"][-1][0]
    rise, _ = rise_of(f)
    return e[tick], (None if rise is None else t0 + rise * per)


def sweep(p, sets, acts, tick, phases=PHASES):
    """The same run in each phase: (levels seen, prompt count, [late rises], no-rise count)."""
    levels, prompt, late, none = set(), 0, [], 0
    for ph in phases:
        lvl, tr = first_rise(p, sets, acts, tick, ph)
        levels.add(lvl)
        if tr is None:
            none += 1
        elif tr > LATE:
            late.append(tr)
        else:
            prompt += 1
    return levels, prompt, late, none


def sweep_text(levels, prompt, late, none):
    t = f"level {'/'.join(f'${x:02x}' for x in sorted(levels))}: prompt in {prompt} of {prompt + len(late) + none} phases"
    if late:
        t += f", LATE in {len(late)}: first rise {min(late):,d}-{max(late):,d} cycles ({max(late) / PAL_CLOCK * 1000:.1f} ms)"
    if none:
        t += f", no rise in {none} (already at the top, falling to the sustain level)"
    return t


def section_late(p):
    out("== 8 LATE: how long after the gate-on write does the envelope first rise? ==")
    out("   `new` is started (the module's 7 writes, DEBUG spacing) at the tick given, on a voice that `previous`")
    out("   was started on at tick 0 (from silence) with its gate cleared at tick G. $D41C is then read every 132")
    out("   cycles; the first read higher than the one before it is the first rise, in cycles after the gate-on")
    out("   write (resolution 132 cycles = 0.13 ms; a tick is 19,656 = 19.95 ms). 'Prompt' = within 2,000 cycles")
    out("   (measured: 154). Every run is made 9 times, the tick's writes moved 5 cycles each time, so that the")
    out("   envelope's rate counter is met in every phase of a 9-cycle period: the game's tick lands on any.")
    pw, fr = 8, 0x1D45
    out("   From silence (the voice's last gate-off used release 0, long ago), 45 runs each. The count of late")
    out("   runs is a sample: which phase the rate counter is in at the tick is not under the probe's control.")
    for name, ad, sr in (("player shot", 0x00, 0xA0), ("enemy shot", 0x00, 0xF0), ("dive", 0x10, 0x80),
                         ("enemy explosion", 0x08, 0x00), ("a note (wave start, wave clear, start)", 0x09, 0x00),
                         ("player hit, game over", 0x0A, 0x00)):
        r = sweep(p, [(ad, sr, pw, fr, 0x41)], {0: 1}, 0, MANY)
        out(f"      {name}, AD ${ad:02x} SR ${sr:02x}: {sweep_text(*r)}")
    cases = [
        ("player shot after player shot (fire held: 10 or 11 ticks apart)", (0x00, 0xA0), 8, (0x00, 0xA0), [10, 11]),
        ("player shot cutting an enemy shot short", (0x00, 0xF0), 6, (0x00, 0xA0), [1, 3, 5, 6, 7]),
        ("enemy shot cutting a player shot short", (0x00, 0xA0), 8, (0x00, 0xF0), [1, 4, 8, 9]),
        ("player shot after the start note (cooldown 25)", (0x09, 0x00), 10, (0x00, 0xA0), [25, 26]),
        ("player shot cutting the start note (not possible in Swarm: for the rule)", (0x09, 0x00), 10, (0x00, 0xA0), [3, 9, 10, 11, 12]),
        ("enemy explosion after enemy explosion", (0x08, 0x00), 16, (0x08, 0x00), [1, 3, 8, 12, 16, 17, 18, 30]),
        ("player hit after an enemy explosion", (0x08, 0x00), 16, (0x0A, 0x00), [1, 5, 16, 18, 25]),
        ("enemy explosion after the player hit's rumble", (0x0A, 0x00), 60, (0x08, 0x00), [60, 61, 62, 100]),
        ("dive restarted by a new dive", (0x10, 0x80), 30, (0x10, 0x80), [1, 12, 24, 30, 31, 40]),
        ("wave start (a note) after a dive", (0x10, 0x80), 30, (0x09, 0x00), [15, 30, 31, 40]),
        ("game over after a player shot", (0x00, 0xA0), 8, (0x0A, 0x00), [3, 8, 9, 12]),
        ("NOT Swarm's data: a slow release left on an idle voice (SR $85, release 5), then the dive", (0x10, 0x85), 30, (0x10, 0x85), [12, 40, 100, 150]),
        ("NOT Swarm's data: the same, then a player shot", (0x10, 0x85), 30, (0x00, 0xA0), [60, 100, 150]),
    ]
    for name, (ad1, sr1), gate, (ad2, sr2), ticks in cases:
        out(f"   {name}: previous AD ${ad1:02x} SR ${sr1:02x} G = {gate}; new AD ${ad2:02x} SR ${sr2:02x}")
        for tick in ticks:
            acts = {0: 1, tick: 2}
            if gate < tick:
                acts[gate] = (3, 0x40)
            r = sweep(p, [(ad1, sr1, pw, fr, 0x41), (ad2, sr2, pw, fr, 0x41)], acts, tick)
            out(f"      new at tick {tick:3d}: {sweep_text(*r)}")
    out("   A note sequence's own step (AD $09 SR $00): gate off for one or two ticks, then the control write alone.")
    note = (0x09, 0x00, pw, fr, 0x41)
    for off, gap in ((9, 1), (9, 2), (3, 1), (3, 2)):
        levels, prompt, late, none = set(), 0, [], 0
        for ph in PHASES:
            e, f, seen = p.env([note], {0: 1, off: (3, 0x40), off + gap: (3, 0x41)}, off + gap + 1, fine_k=off + gap,
                               fine_delay=23, stops=["fine_read"], phase=ph)
            per = seen["fine_read"][1][0] - seen["fine_read"][0][0]
            rise, _ = rise_of(f)
            levels.add(e[off + gap])
            if rise is None:
                none += 1
            elif rise * per > LATE:
                late.append(rise * per)
            else:
                prompt += 1
        out(f"      gate off at tick {off}, on at {off + gap}: {sweep_text(levels, prompt, late, none)}")
    out("   Reading it. The envelope steps when its rate counter (counting up once a cycle) equals the period of")
    out("   the rate in force; if the period in force becomes SMALLER than the count, the counter must run on to")
    out("   32,768 and wrap before it matches again: up to 33.3 ms = 1.67 ticks in which the envelope holds the")
    out("   level it had. That happens to a start (1) always, when the voice was stepping at a slow rate: in a")
    out("   slow decay (the explosion, the notes, the hit) or idle after a release above 0; (2) in some phases")
    out("   even from silence, when the new effect's own decay is slower than its attack (the same three): the")
    out("   gate-on write puts the decay period in force for a moment before the attack period. Effects whose")
    out("   rates are all 0 (the shots) or whose decay is no slower than their attack (the dive) are never late,")
    out("   from silence or on top of each other.")
    out()


def section_variant(p):
    out("== 9 VARIANT, for the Technical Director: decay 0 until the gate is on ==")
    out("   The start sequence with one more write: attack/decay is written with decay 0 where the module writes")
    out("   it, and whole again 18 cycles after the gate-on write (8 writes; probe actions 5 and 6). Same 9 phases.")
    pw, fr = 8, 0x1D45
    out("   From silence, 45 runs each:")
    for name, ad, sr in (("enemy explosion", 0x08, 0x00), ("a note", 0x09, 0x00), ("player hit, game over", 0x0A, 0x00),
                         ("player shot", 0x00, 0xA0), ("dive", 0x10, 0x80)):
        a = sweep(p, [(ad, sr, pw, fr, 0x41)], {0: 1}, 0, MANY)
        b = sweep(p, [(ad, sr, pw, fr, 0x41)], {0: 5}, 0, MANY)
        out(f"      {name}, AD ${ad:02x} SR ${sr:02x}")
        out(f"         as the module does it: {sweep_text(*a)}")
        out(f"         the variant          : {sweep_text(*b)}")
    out("   The envelope tick by tick, explosion (AD $08 SR $00): the variant must not change the sound. (A row")
    out("   that starts 00 00 is a run that happened to be late.)")
    for ph in (1, 2, 3):
        a, _, _ = p.env([(0x08, 0x00, pw, fr, 0x41)], {0: 1}, 12, phase=ph)
        b, _, _ = p.env([(0x08, 0x00, pw, fr, 0x41)], {0: 5}, 12, phase=ph)
        out(f"         as the module does it: {hexs(a)}")
        out(f"         the variant          : {hexs(b)}")
    out("   On top of a sounding effect (enemy explosion after enemy explosion, G = 16):")
    for tick in (3, 8, 16, 18):
        sets = [(0x08, 0x00, pw, fr, 0x41), (0x08, 0x00, pw, fr, 0x41)]
        acts = {0: 1, tick: 2}
        acts5 = {0: 1, tick: 6}
        if tick > 16:
            acts[16] = acts5[16] = (3, 0x40)
        out(f"      new at tick {tick:2d}, as the module does it: {sweep_text(*sweep(p, sets, acts, tick))}")
        out(f"      new at tick {tick:2d}, the variant          : {sweep_text(*sweep(p, sets, acts5, tick))}")
    out()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-real", action="store_true", help="leave out the configurations that open the real sound device")
    ap.add_argument("--only", help="comma-separated section numbers, e.g. 4,8")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None

    def want(n):
        return only is None or str(n) in only

    info = None
    if want(1):
        section_harness(a.skip_real)
    p = Probe(args=["-default", "-pal", *PROBE_SOUND])
    try:
        info = p.mon.vice_info()
        out(f"Sections 2-9: VICE {info}, {p.cmdline}; "
            + ", ".join(f"{r} = {p.mon.resource_get(r)}" for r in RESOURCES))
        out()
        for n, fn in ((2, section_readback), (3, section_osc), (4, section_envelope), (5, section_retrigger),
                      (6, section_pulse), (7, section_noise), (8, section_late), (9, section_variant)):
            if want(n):
                fn(p)
    finally:
        p.close()
    out("FAILED: " + "; ".join(fails) if fails else "ALL CHECKS OK")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
