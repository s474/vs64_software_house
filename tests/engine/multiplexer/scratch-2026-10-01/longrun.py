"""One trace of every budget label for N mux_update passes; the runner's own cost functions."""
import sys
from pathlib import Path
from budget_runner.evaluate import FRAME, profile_costs, irq_time_by_frame
from budget_runner.session import Vice
REPO = Path("/Volumes/Samsung4TB/projects/VSCode/repos/vs64_software_house")
n, warm = int(sys.argv[1]), int(sys.argv[2])
L = ["mux_update","mux_update_end","mux_update_fast","mux_sort","mux_sort_end","mux_select","mux_select_end",
     "mux_build","mux_build_end","mux_irq_top","mux_irq_zone","irq_dispatch","irq_exit_rti"]
v = Vice(REPO/"build/multiplexer/multiplexer.prg", warm)
try:
    a = {x: v.addr(x) for x in L}
    cnt = [0]
    def done(ev):
        if ev and ev[-1].pc == a["mux_update"]: cnt[0] += 1
        return cnt[0] > n
    ev = v.trace(list(a.values()), done, "mux_update")
finally:
    v.close()
d, r = a["irq_dispatch"], a["irq_exit_rti"]
def st(xs, k=None):
    xs = xs[:k] if k else xs
    return f"{min(xs):,} / {sum(xs)/len(xs):,.1f} / {max(xs):,} (n={len(xs):,})"
for name, s, e, ex in (("mux_sort","mux_sort","mux_sort_end",1),("mux_select","mux_select","mux_select_end",1),
    ("mux_build","mux_build","mux_build_end",1),("mux_update all","mux_update","mux_update_end",1),
    ("mux_update fast","mux_update","mux_update_fast",1),("mux_irq_top","mux_irq_top","irq_exit_rti",0),
    ("mux_irq_zone","mux_irq_zone","irq_exit_rti",0)):
    c = profile_costs(ev, a[s], a[e], d, r) if ex else profile_costs(ev, a[s], a[e])
    frac = len(c) * 3000 // n
    print(f"{name:<16} first ~3000 frames: {st(c, frac)}   all: {st(c)}")
    if name == "mux_irq_top":
        from collections import Counter; print("   ", sorted(Counter(c).items()))
    if name == "mux_irq_zone":
        print("    top 8:", sorted(c)[-8:])
frames = ev[-1].t // FRAME - 1
it = irq_time_by_frame(ev, d, r, frames)
print("irq per frame    first 3000:", st(it, 3000), "  all:", st(it), " top 6:", sorted(it)[-6:])
