import json, sys
from collections import defaultdict
run = json.load(open(sys.argv[1])); rows = run["rows"]
MUX = ["head","sort","select","slow_setup","pin_pass","slow_walk","pin_fail","evict","evict_pin","build","restore","rebuild"]
SEL = ["select","slow_setup","pin_pass","slow_walk","pin_fail","evict","evict_pin"]
BLD = ["build","restore","rebuild"]
g = defaultdict(list)
for i in range(len(rows)-1):
    a = rows[i+1]["state"]  # after this frame's move
    g[(a[4], a[5])].append(i)
print("amp_after,damp_after: n, sort min/avg/max, n sort>=1500, free min")
for k in sorted(g):
    ix = g[k]; s = [rows[i]["segs"]["sort"] for i in ix]; f = [rows[i]["iters"]*16 for i in ix]
    if max(s) >= 1200 or min(f) < 5700 or k[0] <= 9:
        print(k, len(ix), min(s), round(sum(s)/len(s)), max(s), sum(x>=1500 for x in s), min(f))
def tot(x, segs): return sum(x["segs"][s] for s in segs)
for name, segs in (("mux_update(MUX_SEGS)", MUX), ("select->sel_done", SEL), ("build->build_end", BLD), ("sort", ["sort"]), ("irq", ["irq"]), ("move", ["move"])):
    v = [tot(x, segs) for x in rows]
    print(name, min(v), round(sum(v)/len(v)), max(v), " first6000 max", max(v[:6000]))
fast = [tot(x, MUX) for x in rows if not x["slow"]]
print("fast frames", len(fast), min(fast), round(sum(fast)/len(fast),1), max(fast))
for lo, hi in ((1,2),(1,3),(1,4),(1,5),(1,8),(0,8)):
    st = [i for i in range(len(rows)-1) if rows[i+1]["state"][5] == 1 and lo <= rows[i+1]["state"][4] <= hi]
    S = set(st); ns = [i for i in range(len(rows)-1) if i not in S]
    hs = sum(1 for i in ns if rows[i]["segs"]["sort"] >= 1500)
    print(f"stress = amp_after {lo}..{hi} rising: n {len(st)}, stress free min {min(rows[i]['iters']*16 for i in st)}, normal free min {min(rows[i]['iters']*16 for i in ns)}, normal max sort {max(rows[i]['segs']['sort'] for i in ns)}, normal frames with sort>=1500: {hs}, normal <5300: {sum(1 for i in ns if rows[i]['iters']*16<5300)}")
ns = [i for i in range(len(rows)) if rows[i]["segs"]["sort"] < 1500]
print("sort<1500 normal free min", min(rows[i]["iters"]*16 for i in ns))
