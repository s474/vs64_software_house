"""Fast soak: stop at spike_main only in frames with few idle iterations, or once per player sweep
(py == MUX_Y_MIN going down: every 438 frames) to count frames. args: sweeps"""
import sys, time
from collections import Counter
from pathlib import Path
from budget_runner.session import Vice
from vice_monitor import CPU_OP_EXEC
REPO = Path("/Volumes/Samsung4TB/projects/VSCode/repos/vs64_software_house")
sweeps = int(sys.argv[1]); THR = 0x170   # iterations: log frames below 368 x 16 = 5,888
N = ["b","db","d","dd","amp","damp","dir","py","pdy"]
v = Vice(REPO/"build/multiplexer/multiplexer.prg", 100)
try:
    s = v.symbols
    cp = v.mon.checkpoint_set(s["spike_main"], s["spike_main"], CPU_OP_EXEC)
    lo, hi, py, pdy = s["zp_spike_idle_lo"], s["zp_spike_idle_hi"], s["spike_py"], s["spike_pdy"]
    v.mon.checkpoint_condition(cp.number,
        f"(@cpu:(${hi:04x}) == $00) || (@cpu:(${hi:04x}) == $01 && @cpu:(${lo:04x}) < ${THR & 255:02x}) || (@cpu:(${py:04x}) == $1e && @cpu:(${pdy:04x}) == $01)")
    n = 0; t0 = time.time(); defs = {"amp 2-3": (2, 3), "amp 2-5": (2, 5), "amp 2-8": (2, 8)}
    mn = {k: [1 << 30, 1 << 30] for k in defs}; below = {k: [0, 0] for k in defs}; hist = Counter(); logged = []
    while n < sweeps:
        v.mon.exit()
        if not v.mon.wait_stopped(60): raise SystemExit("timeout")
        st = dict(zip(N, v.mon.mem_get(s["spike_b"], s["spike_b"] + 8)))
        it = int.from_bytes(v.mon.mem_get(lo, lo + 1), "little")
        if st["py"] == 0x1e and st["pdy"] == 1:
            n += 1
            if n % 200 == 0:
                c = {x: v.mon.mem_get(s[x], s[x])[0] for x in ("spike_overrun_count","mux_max_age","mux_pin_drop_count","mux_late_count","irq_late_count")}
                print(f"~{n*438:,} frames {time.time()-t0:.0f}s", {k: (mn[k][0]*16, mn[k][1]*16, below[k]) for k in defs}, c, flush=True)
        if it < THR:
            for k, (a, b) in defs.items():
                j = 1 if (st["damp"] == 1 and a <= st["amp"] <= b) else 0
                mn[k][j] = min(mn[k][j], it)
                if it * 16 < 5300: below[k][j] += 1
            if it * 16 < 5600 and not (st["damp"] == 1 and st["amp"] in (2, 3)):
                logged.append((n * 438, it * 16, st)); print("  low non-(2,3):", n*438, it*16, st, flush=True)
            if it * 16 < 5300: hist[(st["amp"], st["damp"])] += 1
    print("below 5,300 by (amp, damp):", sorted(hist.items()))
    print("definition: [non-stress min, stress min] x16, [non-stress below 5300, stress below 5300] (non-stress min only among logged frames < 5,888)")
    for k in defs: print(k, [x*16 for x in mn[k]], below[k])
finally:
    v.close()
