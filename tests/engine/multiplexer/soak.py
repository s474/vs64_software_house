"""QA soak test of the multiplexer spike (M3 sign-off, deliverable 2).

From a fresh start: SOAK frames of normal running, then an excess-pin phase (mux_flags+4 bit 7
set for EXCESS frames, then cleared for RECOVER frames). The machine is stopped at
spike_idle_start in EVERY frame (the end of that frame's mux_update, so mux_y / mux_age / mux_flags
are that frame's decisions) and 24-byte copies of mux_y and mux_age are read. Nothing is sampled
sparsely. A skipped or doubled frame (zp_irq_frame delta != 1) is reported.

Checks (exit code 1 on any failure):
  1. counters at the end: mux_late, irq_late, spike_overrun, pin_drop, pin_excess all 0
     (pin_excess > 0 required after the excess phase); mux_max_age <= 4; no CPU jam
  2. pinned sprites 0-3: mux_age = 0 in every frame in which mux_y is in MUX_Y_MIN..MUX_Y_MAX
  3. unpinned sprites: longest run of consecutive frames with age > 0 (in range) <= 4
     (README flicker table, 4 pinned + 20 unpinned)
     "<= 8 on a row" criterion (brief: no sprite missing > 2 consecutive frames): a sprite is
     "uncrowded" in a frame when at most 8 in-range sprites (itself included) have Y within
     +-39 lines of it (README: 25-line window, 39 for back-to-back full rows). Any uncrowded sprite with
     age > 0 is a violation (stronger than the brief: it must not miss even 1 frame).
     Also reported: the longest missing run containing only uncrowded frames.
  4. excess phase: pin_excess_count grows, sprites 0-3 never dropped, no jam; sprite 4 (flagged, but
     unpinned then: only 4 are honoured) must be SEEN to flicker (missing run >= 1, else the check fails as
     "not exercised") and its missing run must stay <= 4; after clearing (the counter is zeroed first, as it
     saturates at 255), pin_excess_count must stay 0
  5. spike_idle_min_normal x 16 >= 5,300 and spike_idle_min_stress x 16 >= 4,250

Run from the repo root (build first: make GAME=multiplexer SRC_DIR=tests/engine/multiplexer):

    uv run --package budget-runner python tests/engine/multiplexer/soak.py \
        [--frames 10000] [--excess 1000] [--recover 200] [--prg build/multiplexer/multiplexer.prg]

About 11,000 frames takes about 40 s (one monitor stop per frame, measured ~3 ms each).
The excess phase defaults to 1000 frames because the spike overflows in only ~10-40% of frames, and
sprite 4 is evicted only occasionally: 100 frames never saw it flicker.
"""

import argparse
import sys
from pathlib import Path

from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice
from vice_monitor import CPU_OP_EXEC  # on sys.path once budget_runner.session is imported

REPO = Path(__file__).resolve().parents[3]
N = 24
Y_MIN, Y_MAX = 0x1E, 0xF9
PINNED = range(4)
CROWD_R = 39  # lines: the README's window for back-to-back full rows (25 alone)


def u(v, sym, name, size=1):
    return int.from_bytes(v.mon.mem_get(sym[name], sym[name] + size - 1), "little")


class Tracker:
    def __init__(self, label):
        self.label = label
        self.frames = 0
        self.run = [0] * N               # current missing run (age > 0, in range)
        self.max_run = [0] * N
        self.crowd_run = [0] * N         # current run of missing frames, all uncrowded
        self.max_crowd_run = [0] * N
        self.pin_miss = []               # (frame, sprite, y, age) pinned in range with age != 0
        self.uncrowded_miss = []         # (frame, sprite, y, age)
        self.frame_skips = []
        self.uncrowded_n = 0
        self.in_range_frames = [0] * N
        self.max_age_seen = [0] * N
        self.miss_frames = [0] * N       # frames each sprite was missing (age > 0, in range)
        self.overflow_frames = 0         # frames in which any unpinned in-range sprite was missing

    def sample(self, fno, ys, ages, pinned):
        self.frames += 1
        inr = [Y_MIN <= y <= Y_MAX for y in ys]
        ylist = [y for y, i in zip(ys, inr) if i]
        self.overflow_frames += any(inr[s] and ages[s] > 0 and s not in pinned for s in range(N))
        for s in range(N):
            if not inr[s]:
                self.run[s] = self.crowd_run[s] = 0
                continue
            self.in_range_frames[s] += 1
            y = ys[s]
            crowd = sum(1 for z in ylist if abs(z - y) <= CROWD_R)
            missing = ages[s] > 0
            self.uncrowded_n += crowd <= 8 and s not in pinned
            if s in pinned:
                if missing:
                    self.pin_miss.append((fno, s, y, ages[s]))
                continue
            self.max_age_seen[s] = max(self.max_age_seen[s], ages[s])
            if missing:
                self.miss_frames[s] += 1
                self.run[s] += 1
                self.max_run[s] = max(self.max_run[s], self.run[s])
                if crowd <= 8:
                    self.uncrowded_miss.append((fno, s, y, ages[s]))
                    self.crowd_run[s] += 1
                    self.max_crowd_run[s] = max(self.max_crowd_run[s], self.crowd_run[s])
                else:
                    self.crowd_run[s] = 0
            else:
                self.run[s] = self.crowd_run[s] = 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=10000)
    ap.add_argument("--excess", type=int, default=1000)
    ap.add_argument("--recover", type=int, default=200)
    ap.add_argument("--prg", default=str(REPO / "build/multiplexer/multiplexer.prg"))
    a = ap.parse_args()
    prg = Path(a.prg)
    fails = []

    v = Vice(prg, 0)  # fresh start: no warm-up frames
    try:
        sym = v.symbols
        cp = v.mon.checkpoint_set(sym["spike_idle_start"], sym["spike_idle_start"], CPU_OP_EXEC)
        flags4 = sym["mux_flags"] + 4
        state = {"last": None}

        def step(tr, pinned):
            v.mon.exit()
            if not v.mon.wait_stopped(STOP_TIMEOUT):
                v.mon.ping()
                raise MeasureError(f"no spike_idle_start within {STOP_TIMEOUT}s: jam? "
                                   f"jammed_pc={v.mon.state.jammed_pc}")
            ys = list(v.mon.mem_get(sym["mux_y"], sym["mux_y"] + N - 1))
            ages = list(v.mon.mem_get(sym["mux_age"], sym["mux_age"] + N - 1))
            fr = u(v, sym, "zp_irq_frame")
            if state["last"] is not None and (fr - state["last"]) & 0xFF != 1:
                tr.frame_skips.append((tr.frames, state["last"], fr))
            state["last"] = fr
            tr.sample(tr.frames, ys, ages, pinned)

        def counters():
            names = ["mux_late_count", "irq_late_count", "spike_overrun_count", "mux_pin_drop_count",
                     "mux_pin_excess_count", "mux_max_age", "mux_drop_count"]
            d = {n: u(v, sym, n) for n in names}
            d["idle_normal"] = u(v, sym, "spike_idle_min_normal", 2) * 16
            d["idle_stress"] = u(v, sym, "spike_idle_min_stress", 2) * 16
            return d

        # Phase A: normal
        A = Tracker("normal")
        for i in range(a.frames):
            step(A, set(PINNED))
            if i % 1000 == 999:
                print(f"  ...{i + 1} frames", flush=True)
        ca = counters()

        # Phase B: 5 flagged
        B = Tracker("excess")
        flags = bytearray(v.mon.mem_get(sym["mux_flags"], sym["mux_flags"] + N - 1))
        v.mon.mem_set(flags4, bytes([flags[4] | 0x80]))
        for _ in range(a.excess):
            step(B, set(PINNED))
        cb = counters()

        # Phase C: cleared
        C = Tracker("recover")
        v.mon.mem_set(flags4, bytes([flags[4] & 0x7F]))
        v.mon.mem_set(sym["mux_pin_excess_count"], bytes([0]))  # saturates at 255: restart from 0
        for _ in range(a.recover):
            step(C, set(PINNED))
        cc = counters()
        v.mon.checkpoint_delete(cp.number)
    finally:
        v.close()

    def rep(name, ok, text):
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {text}")
        if not ok:
            fails.append(name)

    print("\nCounters after phase A / B / C:")
    for n in ca:
        print(f"  {n:<22}{ca[n]:>8}{cb[n]:>8}{cc[n]:>8}")
    print(f"Frame-counter skips: A {A.frame_skips[:5]} ({len(A.frame_skips)}), B {len(B.frame_skips)}, C {len(C.frame_skips)}")

    zero = ["mux_late_count", "irq_late_count", "spike_overrun_count", "mux_pin_drop_count", "mux_pin_excess_count"]
    rep("1 counters (A)", all(ca[n] == 0 for n in zero) and ca["mux_max_age"] <= 4 and not A.frame_skips,
        ", ".join(f"{n}={ca[n]}" for n in zero) + f", mux_max_age={ca['mux_max_age']}, mux_drop_count(last)={ca['mux_drop_count']}")
    rep("2 pinned never dropped (A)", not A.pin_miss,
        f"{len(A.pin_miss)} misses over {sum(A.in_range_frames[s] for s in PINNED)} in-range sprite-frames {A.pin_miss[:5]}")
    ur = max(A.max_run[s] for s in range(4, N))
    rep("3a unpinned missing run <= 4 (A)", ur <= 4,
        f"longest run {ur}; per sprite {[A.max_run[s] for s in range(4, N)]}")
    rep("3b uncrowded (<= 8 within +-39 lines) sprite never missing (A)", not A.uncrowded_miss,
        f"{len(A.uncrowded_miss)} violations {A.uncrowded_miss[:8]}; longest uncrowded missing run "
        f"{max(A.max_crowd_run)}; uncrowded unpinned sprite-frames checked {A.uncrowded_n}")
    rep("4a excess counted (B)", cb["mux_pin_excess_count"] > 0, f"mux_pin_excess_count {ca['mux_pin_excess_count']} -> {cb['mux_pin_excess_count']}")
    rep("4b pinned 0-3 never dropped in excess + recovery", not B.pin_miss and not C.pin_miss and
        cb["mux_pin_drop_count"] == 0 and cc["mux_pin_drop_count"] == 0,
        f"misses B {len(B.pin_miss)} C {len(C.pin_miss)}, mux_pin_drop_count {cb['mux_pin_drop_count']}/{cc['mux_pin_drop_count']}")
    rep("4c sprite 4 flickers within target (B)", 1 <= B.max_run[4] <= 4,
        f"sprite 4 longest missing run {B.max_run[4]} (needs 1..4; 0 = NOT EXERCISED), missing in {B.miss_frames[4]} of "
        f"{B.frames} frames, max age {B.max_age_seen[4]}; frames with any unpinned sprite missing {B.overflow_frames}; "
        f"other unpinned longest {max(B.max_run[s] for s in range(5, N))}")
    rep("4d no excess growth after clearing (C)", cc["mux_pin_excess_count"] == 0 and not C.pin_miss
        and max(C.max_run[s] for s in range(4, N)) <= 4 and not B.frame_skips + C.frame_skips,
        f"excess (zeroed at start of C) -> {cc['mux_pin_excess_count']}, unpinned longest run in C {max(C.max_run[s] for s in range(4, N))}")
    rep("5a idle normal >= 5,300", cc["idle_normal"] >= 5300, f"{cc['idle_normal']} (after A: {ca['idle_normal']})")
    rep("5b idle stress >= 4,250", cc["idle_stress"] >= 4250, f"{cc['idle_stress']} (after A: {ca['idle_stress']})")
    print("\nFAILED: " + ", ".join(fails) if fails else "\nALL PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL (jam/hang): {e}")
        sys.exit(2)
