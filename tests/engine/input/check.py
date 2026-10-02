"""Joystick-driven checks of engine/input.asm in its spike (engine/input.md, spike items 1-3).

`make test` can't press buttons, so this drives joystick port 2 through the VICE monitor (the
"I/O simulation" joyport device, active-low values: mcp/vice/README.md) and reads the module's
outputs. The machine is stopped at spike_frame_done in EVERY frame (after that frame's input_read),
the joystick lines are changed while it is stopped, and zp_joy / zp_joy_pressed /
spike_fire_presses are read at the next stop, so each sample is exactly one input_read later.

Cases (PASS/FAIL each, exit code 1 on any failure):
  idle        nothing pressed: zp_joy = zp_joy_pressed = 0. The raw $DC00 value is printed: any 0
              in its bits 5-7 would show as a 1 in zp_joy without the mask
  single      each of up, down, left, right, fire: its own bit and no other in zp_joy; the same
              bit in zp_joy_pressed in the first frame only, 0 while held (5 frames); released: 0
  combos      two to five inputs at once, including left+right and up+down: reported as they are
  edge-add    fire held, then left added: zp_joy_pressed = left only; fire released while left
              is held: nothing pressed
  hold-50     fire held 50 frames: zp_joy_pressed has fire in exactly 1 frame, spike_fire_presses +1
  press-10    fire pressed 10 times (1 frame down, 1 frame up): 10 edges, spike_fire_presses +10
  port1       every input on port 1: zp_joy stays 0
  ddr         $DC02 = $00 after input_init; with it, a $00 output latch in $DC00 changes nothing
              (idle reads 0, fire reads fire). Then the control: $DC02 = $FF with the latch $00
              makes an idle stick read $1F: input_init's write is needed whenever the latch can
              hold a 0 in bits 0-4. $DC02 = $00 restored afterwards and re-checked.
  start       the program was started from BASIC with RUN (the KERNAL's keyboard scan had run)
              and irq_init has run: $01 = $35

Run from the repo root (build first: make GAME=input SRC_DIR=tests/engine/input):

    uv run --package budget-runner python tests/engine/input/check.py [--prg build/input/input.prg]

Takes about 2 s. Works on a release build too (make BUILD=release ...): it uses no DEBUG label.
"""

import argparse
import sys
from pathlib import Path

from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice
from vice_monitor import CPU_OP_EXEC  # on sys.path once budget_runner.session is imported

REPO = Path(__file__).resolve().parents[3]
BITS = {"up": 0x01, "down": 0x02, "left": 0x04, "right": 0x08, "fire": 0x10}
JOYPORT_JOYSTICK, JOYPORT_IO_SIMULATION = 1, 37
PORT1, PORT2 = 0, 1  # the monitor's port index


def mask(names):
    m = 0
    for n in names:
        m |= BITS[n]
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prg", default=str(REPO / "build/input/input.prg"))
    a = ap.parse_args()
    fails = []

    def rep(name, ok, text):
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {text}")
        if not ok:
            fails.append(name)

    v = Vice(Path(a.prg), 20)
    try:
        mon, sym = v.mon, v.symbols
        mon.resource_set("JoyPort2Device", JOYPORT_IO_SIMULATION)
        mon.joyport_set(PORT2, 0x1F)
        cp = mon.checkpoint_set(sym["spike_frame_done"], sym["spike_frame_done"], CPU_OP_EXEC)

        def byte(addr):
            return mon.mem_get(addr, addr)[0]

        def frame(pressed=None, port=PORT2):
            """Optionally set the stick (active-high mask), run to the next spike_frame_done."""
            if pressed is not None:
                mon.joyport_set(port, ~pressed & 0x1F)
            mon.exit()
            if not mon.wait_stopped(STOP_TIMEOUT):
                mon.ping()
                raise MeasureError("spike_frame_done not reached: jam?")
            return byte(sym["zp_joy"]), byte(sym["zp_joy_pressed"]), byte(sym["spike_fire_presses"])

        frame(0)
        frame()

        # start
        rep("start", byte(0x01) & 7 == 5, f"$01 = ${byte(0x01):02x} (irq_init has run; program started with RUN)")

        # idle
        s = [frame() for _ in range(5)]
        raw = byte(0xDC00)
        rep("idle", all(x[:2] == (0, 0) for x in s), f"zp_joy/zp_joy_pressed over 5 frames {[x[:2] for x in s]}; "
            f"raw $DC00 = ${raw:02x}")

        # single
        for n, b in BITS.items():
            first = frame(b)
            held = [frame() for _ in range(5)]
            rel = [frame(0), frame()]
            ok = (first[:2] == (b, b) and all(h[:2] == (b, 0) for h in held)
                  and all(r[:2] == (0, 0) for r in rel))
            rep(f"single {n}", ok, f"first frame joy=${first[0]:02x} pressed=${first[1]:02x}; held "
                f"{sorted({h[:2] for h in held})}; released {sorted({r[:2] for r in rel})}")

        # combos
        combos = [("up", "fire"), ("down", "fire"), ("left", "fire"), ("right", "fire"), ("up", "left"),
                  ("up", "right"), ("down", "left"), ("down", "right"), ("up", "left", "fire"),
                  ("down", "right", "fire"), ("left", "right"), ("up", "down"),
                  ("up", "down", "left", "right", "fire")]
        bad = []
        for c in combos:
            m = mask(c)
            first, second, rel = frame(m), frame(), frame(0)
            if not (first[:2] == (m, m) and second[:2] == (m, 0) and rel[:2] == (0, 0)):
                bad.append(("+".join(c), first[:2], second[:2], rel[:2]))
        rep("combos", not bad, f"{len(combos)} combinations (incl. left+right, up+down, all five): "
            f"{'each reported as pressed' if not bad else bad}")

        # edge-add
        f, l = BITS["fire"], BITS["left"]
        seq = [frame(f), frame(), frame(f | l), frame(), frame(l), frame(), frame(0)]
        want = [(f, f), (f, 0), (f | l, l), (f | l, 0), (l, 0), (l, 0), (0, 0)]
        rep("edge-add", [x[:2] for x in seq] == want,
            f"fire, +left, -fire, -left: {[f'{j:02x}/{p:02x}' for j, p, _ in seq]}")

        # hold-50
        before = frame()[2]
        s = [frame(f)] + [frame() for _ in range(49)]
        after = frame(0)[2]
        edges = sum(1 for x in s if x[1] & f)
        rep("hold-50", edges == 1 and s[0][1] == f and (after - before) & 0xFF == 1
            and all(x[0] == f for x in s),
            f"fire held 50 frames: pressed set in {edges} frame(s) (the first), spike_fire_presses {before} -> {after}")

        # press-10
        before = after
        edges = 0
        for _ in range(10):
            edges += bool(frame(f)[1] & f)
            edges += bool(frame(0)[1] & f)
        after = frame()[2]
        rep("press-10", edges == 10 and (after - before) & 0xFF == 10,
            f"10 one-frame presses: {edges} edges, spike_fire_presses {before} -> {after}")

        # port1
        mon.resource_set("JoyPort1Device", JOYPORT_IO_SIMULATION)
        seen = {}
        for n, b in list(BITS.items()) + [("all", 0x1F)]:
            x = [frame(b, PORT1), frame()]
            seen[n] = sorted({y[:2] for y in x})
        frame(0, PORT1)
        mon.resource_set("JoyPort1Device", JOYPORT_JOYSTICK)
        frame()
        rep("port1", all(s == [(0, 0)] for s in seen.values()), f"port 1 inputs -> zp_joy/pressed {seen}")

        # ddr
        ddr = byte(0xDC02)
        rep("ddr $DC02 = $00 after input_init", ddr == 0, f"$DC02 = ${ddr:02x}")
        mon.mem_set(0xDC00, bytes([0x00]), side_effects=True)   # output latch all 0: every column "driven low"
        idle, fire, _ = frame(0), frame(f), frame(0)
        rep("ddr latch $00 has no effect with $DC02 = $00", idle[:2] == (0, 0) and fire[:2] == (f, f),
            f"idle {idle[:2]}, fire {fire[:2]}")
        mon.mem_set(0xDC02, bytes([0xFF]), side_effects=True)   # control: what input_init prevents
        ctl = frame(0)
        rep("ddr control: $DC02 = $FF with latch $00 reads a phantom stick", ctl[0] == 0x1F,
            f"idle stick, zp_joy = ${ctl[0]:02x} (so input_init's write is needed whenever the latch has a 0 in bits 0-4)")
        mon.mem_set(0xDC00, bytes([0x7F]), side_effects=True)   # the value the KERNAL scan leaves
        ctl2 = [frame(0), frame()][1]
        fire2 = frame(f)
        frame(0)
        print(f"       (info) $DC02 = $FF with latch $7F (what the KERNAL leaves): idle zp_joy = ${ctl2[0]:02x}, "
              f"fire zp_joy = ${fire2[0]:02x}")
        mon.mem_set(0xDC02, bytes([0x00]), side_effects=True)
        back = [frame(0), frame()][1]
        rep("ddr restored", back[:2] == (0, 0) and byte(0xDC02) == 0, f"idle {back[:2]}")

        mon.checkpoint_delete(cp.number)
    finally:
        v.close()

    print("\nFAILED: " + ", ".join(fails) if fails else "\nALL PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL (jam/hang): {e}")
        sys.exit(2)
