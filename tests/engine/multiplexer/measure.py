"""Measure engine/multiplexer.asm in the multiplexer spike, slot by slot.

Stops at every zone-IRQ block (mux_zone_0..7, one per slot written), mux_irq_zone, mux_irq_top,
irq_dispatch and irq_exit_rti for N frames, reading the raster and the slot index (X) at each
stop and the slot arrays from memory, so it gives:

  - per slot written by a zone IRQ: margin = slot Y - raster line at the write (the DEBUG late
    check fails when it is <= 0), histogram, and the worst cases with their context
  - zone IRQ trigger: how many lines after the slot's free line the handler starts (MUX_IRQ_LINES)
  - per-slot write time, in lines, for back-to-back slots in one IRQ (MUX_WRITE_LINES)
  - the last zone IRQ's end line relative to the lowest slot's Y (for the fixed-entry spacing)
  - zone IRQs per frame, slots per IRQ, IRQ time per frame (runner definition)

    uv run python tests/engine/multiplexer/measure.py [frames] [warmup]

Needs a build first: make GAME=multiplexer SRC_DIR=tests/engine/multiplexer
"""

import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "mcp" / "vice"))

from vice_monitor import CPU_OP_EXEC, ViceMonitor, free_port, load_symbols  # noqa: E402

CPL = 63
FRAME = 312 * CPL


def hist(values) -> str:
    if not values:
        return "(none)"
    c = Counter(values)
    return f"min {min(values)} max {max(values)}  [" + ", ".join(f"{k}:{v}" for k, v in sorted(c.items())) + "]"


def main() -> None:
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    warmup = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    prg = REPO / "build" / "multiplexer" / "multiplexer.prg"
    sym = load_symbols(prg)
    blocks = {sym[f"mux_zone_{j}"]: j for j in range(8)}
    marks = {sym[n]: n for n in ("mux_irq_top", "mux_irq_zone", "irq_dispatch", "irq_exit_rti", "mux_zone_done")}
    port = free_port()
    proc = subprocess.Popen(
        ["x64sc", "-default", "-pal", "-sounddev", "dummy", "-warp", "-minimized",
         "-binarymonitor", "-binarymonitoraddress", f"ip4://127.0.0.1:{port}", "-autostartprgmode", "1"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    mon = ViceMonitor(port=port)
    mon.connect()
    mon.drain_events(0.3)
    s_y, s_free, zp_end = sym["mux_s_y"], sym["mux_s_free"], sym["zp_mux_end"]
    try:
        mon.autostart(str(prg), run=True)
        cp = mon.checkpoint_set(sym["mux_irq_top"], sym["mux_irq_top"], CPU_OP_EXEC)
        for _ in range(warmup):
            mon.exit()
            if not mon.wait_stopped(20):
                raise SystemExit("mux_irq_top never reached")
        mon.checkpoint_delete(cp.number)
        addrs = list(blocks) + list(marks)
        cps = [mon.checkpoint_set(a, a, CPU_OP_EXEC) for a in addrs]
        ev = []  # (name, t, line, cycle, x, y_of_slot, free_of_slot)
        base, prev, tops = 0, -1, 0
        mem_y = mem_free = None
        while tops <= frames:
            mon.exit()
            if not mon.wait_stopped(5):
                raise SystemExit("timed out")
            r = mon.registers()
            t = r["LIN"] * CPL + r["CYC"]
            if t < prev:
                base += FRAME
            prev = t
            pc = r["PC"]
            if pc == sym["mux_irq_top"]:
                tops += 1
                mem_y = mon.mem_get(s_y, s_y + 63)
                mem_free = mon.mem_get(s_free, s_free + 63)
            name = f"blk{blocks[pc]}" if pc in blocks else marks[pc]
            x = r["X"]
            y = mem_y[x] if (mem_y and pc in blocks) else None
            f = mem_free[x] if (mem_free and pc in blocks) else None
            end = mon.mem_get(zp_end, zp_end)[0] if name == "mux_zone_done" else None
            ev.append((name, base + t, r["LIN"], r["CYC"], x, y, f, end))
        for c in cps:
            mon.checkpoint_delete(c.number)
        late = mon.mem_get(sym["mux_late_count"], sym["mux_late_count"])[0]
        irq_late = mon.mem_get(sym["irq_late_count"], sym["irq_late_count"])[0]
    finally:
        mon.quit()
        mon.close()
        proc.wait(timeout=5)

    # trim to whole frames: first mux_irq_top's dispatch .. last mux_irq_top's dispatch
    idx = [i for i, e in enumerate(ev) if e[0] == "mux_irq_top"]
    ev = ev[idx[0] - 1: idx[-1] - 1]
    margins, trig, per_slot, worst = [], [], [], []
    irq_slots, last_end = [], []
    cur_slots, in_zone, first_in_irq = 0, False, None
    prev_blk = None
    for i, e in enumerate(ev):
        name = e[0]
        if name == "mux_irq_zone":
            in_zone, cur_slots, prev_blk = True, 0, None
            first_in_irq = True
        elif name.startswith("blk"):
            margin = e[5] - e[2]
            margins.append(margin)
            if first_in_irq:
                trig.append(e[2] - e[6])  # lines after the free line
                first_in_irq = False
            if prev_blk is not None:
                per_slot.append((e[1] - prev_blk[1], e[2]))
            prev_blk = e
            cur_slots += 1
            worst.append((margin, e[2], e[3], e[4], e[5], e[6]))
        elif name == "mux_zone_done":
            # the last written slot's Y vs the raster now
            last_end.append((e[2], max(y for (_, _, _, x, y, _) in worst[-cur_slots:])))
        elif name == "irq_exit_rti" and in_zone:
            irq_slots.append(cur_slots)
            in_zone, prev_blk = False, None
    n_frames = sum(1 for e in ev if e[0] == "mux_irq_top")
    print(f"multiplexer: {n_frames} frames after {warmup} warm-up; mux_late_count {late}, irq_late_count {irq_late}")
    print(f"  zone slots written: {len(margins)}; margin (slot Y - raster line at the block): {hist(margins)}")
    print(f"  zone IRQ first write, lines after the slot's free line: {hist(trig)}")
    cyc = [c for c, _ in per_slot]
    print(f"  back-to-back slot, cycles block to block (incl. waits): {hist(cyc)}")
    print(f"  slots per zone IRQ: {hist(irq_slots)}; zone IRQs per frame ~ {len(irq_slots) / max(n_frames, 1):.1f}")
    print(f"  last zone IRQ: raster at mux_zone_done - lowest slot Y: {hist([a - b for a, b in last_end])}")
    print("  worst margins (margin, line, cycle, X, Y, free):")
    for w in sorted(worst)[:12]:
        print("   ", w)


if __name__ == "__main__":
    main()
