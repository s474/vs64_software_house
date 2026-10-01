"""Soak with one stop a frame at spike_main: free CPU split into stress / non-stress frames.
Stress frame = spike_move left spike_amp at 2 or 3 with spike_damp = +1."""
import sys, time
from pathlib import Path
from budget_runner.session import Vice, STOP_TIMEOUT
from vice_monitor import CPU_OP_EXEC
REPO = Path("/Volumes/Samsung4TB/projects/VSCode/repos/vs64_software_house")
total, chunk = int(sys.argv[1]), int(sys.argv[2])
v = Vice(REPO/"build/multiplexer/multiplexer.prg", 100)
try:
    s = v.symbols
    assert s["spike_damp"] == s["spike_amp"] + 1
    cp = v.mon.checkpoint_set(s["spike_main"], s["spike_main"], CPU_OP_EXEC)
    mn = {0: 1 << 30, 1: 1 << 30}; low = {0: 0, 1: 0}; n = {0: 0, 1: 0}; t0 = time.time()
    lows = []
    for f in range(total + 1):
        v.mon.exit()
        if not v.mon.wait_stopped(STOP_TIMEOUT): raise SystemExit("timeout")
        if f == 0: continue   # first stop: partial frame
        it = int.from_bytes(v.mon.mem_get(s["zp_spike_idle_lo"], s["zp_spike_idle_lo"] + 1), "little") * 16
        amp, damp = v.mon.mem_get(s["spike_amp"], s["spike_amp"] + 1)
        k = 1 if (damp == 1 and amp in (2, 3)) else 0
        n[k] += 1; mn[k] = min(mn[k], it)
        if it < 5300: low[k] += 1; lows.append(it)
        if f % chunk == 0:
            ov = v.mon.mem_get(s["spike_overrun_count"], s["spike_overrun_count"])[0]
            ma = v.mon.mem_get(s["mux_max_age"], s["mux_max_age"])[0]
            print(f, f"non-stress: n {n[0]} min {mn[0]} below5300 {low[0]} | stress: n {n[1]} min {mn[1]} below5300 {low[1]} | overruns {ov} max_age {ma} {time.time()-t0:.0f}s", flush=True)
    print("sorted lows:", sorted(lows)[:40])
finally:
    v.close()
