"""As split.py, but logs every non-stress frame below a threshold with its motion state, and
classifies by several candidate definitions."""
import sys, time
from collections import Counter
from pathlib import Path
from budget_runner.session import Vice, STOP_TIMEOUT
from vice_monitor import CPU_OP_EXEC
REPO = Path("/Volumes/Samsung4TB/projects/VSCode/repos/vs64_software_house")
total, thr = int(sys.argv[1]), int(sys.argv[2])
v = Vice(REPO/"build/multiplexer/multiplexer.prg", 100)
N = ["b","db","d","dd","amp","damp","dir","py","pdy"]
try:
    s = v.symbols
    cp = v.mon.checkpoint_set(s["spike_main"], s["spike_main"], CPU_OP_EXEC)
    hist = Counter(); prev = None; t0 = time.time()
    for f in range(total + 1):
        v.mon.exit()
        if not v.mon.wait_stopped(STOP_TIMEOUT): raise SystemExit("timeout")
        st = dict(zip(N, v.mon.mem_get(s["spike_b"], s["spike_b"] + 8)))
        if f:
            it = int.from_bytes(v.mon.mem_get(s["zp_spike_idle_lo"], s["zp_spike_idle_lo"] + 1), "little") * 16
            stress = st["damp"] == 1 and st["amp"] in (2, 3)
            if it < thr:
                key = (st["amp"], st["damp"])
                hist[key] += 1
                if not stress:
                    print(f, it, st, "prev", prev, flush=True)
        prev = st
        if f and f % 50000 == 0: print(f, f"{time.time()-t0:.0f}s", flush=True)
    print("frames below", thr, "by (amp, damp) after the move:", sorted(hist.items()))
finally:
    v.close()
