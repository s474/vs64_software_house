"""Measure engine/irq.asm in the irq_chain spike, frame by frame.

vice_run_until reports one hit per call; this stops at every framework and handler label for
many consecutive frames and reads the raster (line, cycle) at each stop, so it gives:

  - each handler's start line and cycle over N frames (min / max / spread / histogram)
  - irq_dispatch's cycle per entry (the IRQ-taken cycle is that minus 7)
  - irq_exit -> irq_exit_rti and irq_stable_begin -> spike_h2 costs
  - IRQ time per frame, as the budget runner defines it: each IRQ spans from its irq_dispatch
    hit - 7 to its irq_exit_rti hit + 6
  - irq_late_count at the end

    cd mcp/vice && uv run python ../../tests/engine/irq_chain/measure.py [frames] [warmup]

Needs a build first: make GAME=irq_chain SRC_DIR=tests/engine/irq_chain
Stopping at a checkpoint freezes the emulated machine, so the raster figures are exact.
"""

import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "mcp" / "vice"))

from vice_monitor import CPU_OP_EXEC, ViceMonitor, free_port, load_symbols  # noqa: E402

CYCLES_PER_LINE = 63  # measured: tests/timing/rasterline
FRAME = 312 * CYCLES_PER_LINE
HANDLERS = ["spike_h0", "spike_h1", "spike_h2", "spike_h3"]
MARKS = ["irq_dispatch", "irq_exit", "irq_exit_rti", "irq_stable_begin", "irq_stable_stage2"]


def stats(values: list[int]) -> str:
    hist = ", ".join(f"{v}:{c}" for v, c in sorted(Counter(values).items()))
    return f"min {min(values)} max {max(values)} spread {max(values) - min(values)}  [{hist}]"


def main() -> None:
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    warmup = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    prg = REPO / "build" / "irq_chain" / "irq_chain.prg"
    sym = load_symbols(prg)
    names = {sym[n]: n for n in HANDLERS + MARKS}
    port = free_port()
    proc = subprocess.Popen(
        ["x64sc", "-default", "-pal", "-sounddev", "dummy", "-warp", "-minimized",
         "-binarymonitor", "-binarymonitoraddress", f"ip4://127.0.0.1:{port}", "-autostartprgmode", "1"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    mon = ViceMonitor(port=port)
    mon.connect()
    mon.drain_events(0.3)
    try:
        mon.autostart(str(prg), run=True)
        # Warm up: count frames at spike_h0.
        cp = mon.checkpoint_set(sym["spike_h0"], sym["spike_h0"], CPU_OP_EXEC)
        for _ in range(warmup):
            mon.exit()
            if not mon.wait_stopped(20):
                raise SystemExit("spike_h0 never reached")
        mon.checkpoint_delete(cp.number)

        cps = [mon.checkpoint_set(a, a, CPU_OP_EXEC) for a in names]
        events: list[tuple[str, int]] = []  # (label, absolute raster cycle)
        base, prev, h0_seen = 0, -1, 0
        while h0_seen <= frames:
            mon.exit()
            if not mon.wait_stopped(5):
                raise SystemExit("timed out waiting for a checkpoint")
            r = mon.registers()
            t = r["LIN"] * CYCLES_PER_LINE + r["CYC"]
            if t < prev:
                base += FRAME
            prev = t
            name = names[r["PC"]]
            if name == "spike_h0":
                h0_seen += 1
            events.append((name, base + t, r["LIN"], r["CYC"]))
        for c in cps:
            mon.checkpoint_delete(c.number)
        late = mon.mem_get(sym["irq_late_count"], sym["irq_late_count"])[0]
    finally:
        mon.quit()
        mon.close()
        proc.wait(timeout=5)

    # Trim to whole frames: from the first irq_dispatch before a spike_h0 to the last one.
    firsts = [i for i, e in enumerate(events) if e[0] == "spike_h0"]
    start = max(i for i in range(firsts[0]) if events[i][0] == "irq_dispatch") if firsts[0] > 0 else 0
    end = max(i for i in range(firsts[-1]) if events[i][0] == "irq_dispatch")
    ev = events[start:end]
    n_frames = sum(1 for e in ev if e[0] == "spike_h0")

    print(f"irq_chain: {n_frames} frames after {warmup} warm-up frames")
    for h in HANDLERS:
        hits = [e for e in ev if e[0] == h]
        lines = sorted({e[2] for e in hits})
        print(f"  {h:10s} line {lines}  cycle {stats([e[3] for e in hits])}")

    # Dispatch cycle per entry: the dispatch hit that precedes each handler (or stage 1).
    disp: dict[str, list[int]] = {h: [] for h in HANDLERS}
    exit_cost: dict[str, list[int]] = {h: [] for h in HANDLERS}
    last_disp, current = None, None
    for i, e in enumerate(ev):
        if e[0] == "irq_dispatch":
            last_disp = e
        elif e[0] in HANDLERS:
            current = e[0]
            disp[current].append(last_disp[3])
        elif e[0] == "irq_exit":
            nxt = next(x for x in ev[i + 1:] if x[0] in ("irq_exit_rti", "irq_dispatch", "spike_h0"))
            if nxt[0] == "irq_exit_rti":
                exit_cost[current].append(nxt[1] - e[1])
    for h in HANDLERS:
        print(f"  dispatch before {h:10s} cycle {stats(disp[h])}")
    for h in HANDLERS:
        print(f"  irq_exit -> irq_exit_rti after {h:10s} {stats(exit_cost[h])}")

    stable = []
    stage2 = []
    for i, e in enumerate(ev):
        if e[0] == "irq_stable_begin":
            h2 = next(x for x in ev[i + 1:] if x[0] == "spike_h2")
            s2 = next(x for x in ev[i + 1:] if x[0] == "irq_stable_stage2")
            stable.append(h2[1] - e[1])
            stage2.append((s2[2], s2[3]))
    print(f"  irq_stable_begin -> spike_h2  {stats(stable)}")
    print(f"  irq_stable_stage2 arrival (line, cycle) {sorted(Counter(stage2).items())}")
    sb = [e for e in ev if e[0] == "irq_stable_begin"]
    print(f"  irq_stable_begin at line {sorted({e[2] for e in sb})} cycle {stats([e[3] for e in sb])}")

    # IRQ time per frame (runner definition), split at each entry-0 dispatch.
    frame_totals: list[int] = []
    acc, t0 = 0, None
    for i, e in enumerate(ev):
        if e[0] == "irq_dispatch":
            nxt = next((x for x in ev[i + 1:] if x[0] in HANDLERS or x[0] == "irq_stable_begin"), None)
            if nxt and nxt[0] == "spike_h0" and acc:
                frame_totals.append(acc)
                acc = 0
            t0 = e[1] - 7
        elif e[0] == "irq_exit_rti" and t0 is not None:
            acc += e[1] + 6 - t0
            t0 = None
    frame_totals.append(acc)
    print(f"  IRQ time per frame {stats(frame_totals)}")
    print(f"  irq_late_count = {late}")


if __name__ == "__main__":
    main()
