"""Scratch (TD review): where does each zone slot's LAST write land relative to line Y, cycle 55?"""
import sys
from collections import Counter
from pathlib import Path
from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice
from vice_monitor import CPU_OP_EXEC

REPO = Path("/Volumes/Samsung4TB/projects/VSCode/repos/vs64_software_house")
STOPS = int(sys.argv[1]) if len(sys.argv) > 1 else 50000
v = Vice(REPO / "build/multiplexer/multiplexer.prg", 100)
try:
    sym, mon = v.symbols, v.mon
    inxs = {}
    for j in range(8):
        ad = sym["mux_zone_0"] + 81 * j + 45
        assert mon.mem_get(ad, ad)[0] == 0xE8, hex(ad)
        inxs[ad] = j
    for ad in inxs:
        mon.checkpoint_set(ad, ad, CPU_OP_EXEC)
    sy = sym["mux_s_y"]
    hist = Counter(); worst = []; n = 0; on_y = 0; on_y_bad = 0; ybad = 0
    lines_before = Counter()
    while n < STOPS:
        mon.exit()
        if not mon.wait_stopped(STOP_TIMEOUT):
            raise MeasureError("no stop")
        r = mon.registers()
        lin, cyc, x = r["LIN"], r["CYC"], r["X"]
        y = mon.mem_get(sy + x, sy + x)[0]
        n += 1
        slack = (y - lin) * 63 + (55 - cyc)
        bad = 51 <= y <= 243 and y % 8 == 3
        ybad += bad
        lines_before[min(y - lin, 6)] += 1
        if lin == y:
            on_y += 1; on_y_bad += bad
        worst.append((slack, y, lin, cyc, x & 7, bad))
        worst.sort(); worst = worst[:40]
        if n % 10000 == 0: print("...", n, flush=True)
    late = mon.mem_get(sym["mux_late_count"], sym["mux_late_count"])[0]
finally:
    v.close()
print(f"{n} zone slots; slots whose Y line is a badline: {ybad}; mux_late_count {late}")
print("lines from last write to Y (6 = 6+):", sorted(lines_before.items()))
print(f"finished on line Y: {on_y}, of which Y is a badline: {on_y_bad}")
print("smallest slack to (line Y, cycle 55): slack, Y, line, cycle, hw sprite, Y is badline")
for w in worst: print("  ", w)
