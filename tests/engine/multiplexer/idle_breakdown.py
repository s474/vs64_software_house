"""Where each frame of the multiplexer spike goes: a per-frame breakdown of the main loop, for the
free-CPU promise (spike_idle_min x 16 >= 5,300, M3 brief rule 3). Written for the M3 stage 4
diagnosis (pinning), and usable on a stage 3 engine build too (labels it lacks are skipped).

One trace (checkpoints through the budget runner's Vice session, so raster times match
`make test`). A main-loop frame runs from one spike_main to the next. Every raster cycle of it is
charged to exactly one segment, so the segments add up to the frame (19,656 unless it overran):

  move        spike_main -> mux_update            the spike's own motion code (the "game")
  head        mux_update -> mux_sort
  sort        mux_sort -> mux_select
  select      mux_select -> mux_slow / mux_sel_done   the fast-path walk
  slow_setup  mux_slow -> mux_pin_pass (or _end)      mux_fill_kept and setup
  pin_pass    mux_pin_pass -> mux_pin_pass_end        pinning: mark the pinned sprites
  slow_walk   the slow loop, and unpinned fail decisions (search, dry run, drops)
  pin_fail    mux_pin_fail -> mux_ev_remove / mux_slow_loop   pinning: a pinned sprite's decision
  evict       mux_ev_remove -> mux_slow_loop, for an unpinned sprite (fair flicker)
  evict_pin   the same, for a pinned sprite            pinning
  build       mux_sel_done -> mux_rebuild / mux_build_end
  restore     mux_rebuild -> mux_rebuild + 43          pinning: the saved ages back (stage 4 only)
  rebuild     the rest of mux_rebuild and of mux_build after it
  tail        mux_build_end -> spike_idle_start        rts and the spike's DEBUG statistics
  idle        spike_idle_start -> the next spike_main  raster span of the idle loop (DMA included)
  irq         every IRQ, dispatch - 7 to rti + 6, wherever it lands

"free" is the spike's own measure: the idle loop's iteration count for that frame (read from
zp_spike_idle_lo/hi at the next spike_main) x 16. It is CPU time, so it is less than the idle
raster span by the DMA that lands in the idle loop.

Run (from the repo root; needs a build first: make GAME=multiplexer SRC_DIR=tests/engine/multiplexer):

    uv run --package budget-runner python tests/engine/multiplexer/idle_breakdown.py \
        [--frames 6000] [--warmup 100] [--prg build/multiplexer/multiplexer.prg] \
        [--no-pin] [--limit 5300] [--out run.json]

  --no-pin   clears mux_flags bit 7 of every sprite before the trace (same motion, nothing pinned)
  --out      saves the per-frame records as JSON, for --compare

    uv run --package budget-runner python tests/engine/multiplexer/idle_breakdown.py \
        --compare a.json b.json [--limit 5300]

  Lines the two runs up frame by frame on the spike's motion state and prints, for a's worst
  frames, what b (e.g. the stage 3 engine on the same motion) spent in the same frame.

Put --out files in a scratch directory, not in build/ (make clean deletes it) or the repo.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from budget_runner.evaluate import CYCLES_PER_LINE, FRAME, IRQ_SEQUENCE, RTI_TAIL
from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice
from vice_monitor import CPU_OP_EXEC  # on sys.path once budget_runner.session is imported

REPO = Path(__file__).resolve().parents[3]
SEGS = ["move", "head", "sort", "select", "slow_setup", "pin_pass", "slow_walk", "pin_fail",
        "evict", "evict_pin", "build", "restore", "rebuild", "tail", "idle", "irq"]
PIN_SEGS = ["pin_pass", "pin_fail", "evict_pin", "restore"]
MUX_SEGS = [s for s in SEGS if s not in ("move", "tail", "idle", "irq")]
STATE = ["spike_b", "spike_db", "spike_d", "spike_dd", "spike_amp", "spike_damp", "spike_dir",
         "spike_py", "spike_pdy"]
COUNTERS = [("mux_max_age", 1), ("mux_pin_drop_count", 1), ("mux_pin_excess_count", 1),
            ("mux_late_count", 1), ("irq_late_count", 1), ("spike_overrun_count", 1),
            ("spike_idle_min_normal", 2), ("spike_idle_min_stress", 2),
            ("spike_idle_min", 2),  # builds before the stage 4 labels
            ("spike_drop_total", 2), ("spike_flicker_frames", 2)]
RESTORE_LEN = 43  # bytes from mux_rebuild to the end of the pinned-age restore (stage 4 layout)
SORT_STRESS = 1500  # a sort above this is the spike's reversal of the groups (normal ~700)


def trace(frames: int, warmup: int, prg: Path, no_pin: bool) -> dict:
    v = Vice(prg, warmup)
    try:
        sym = v.symbols
        stage4 = "mux_pin_pass" in sym
        if no_pin:
            v.mon.mem_set(sym["mux_flags"], bytes(b & 0x7F for b in
                          v.mon.mem_get(sym["mux_flags"], sym["mux_flags"] + 23)))
        # pc -> segment that starts there
        starts = {"spike_main": "move", "mux_update": "head", "mux_sort": "sort",
                  "mux_select": "select", "mux_slow": "slow_setup", "mux_pin_pass": "pin_pass",
                  "mux_pin_pass_end": "slow_walk", "mux_slow_loop": "slow_walk",
                  "mux_pin_fail": "pin_fail", "mux_ev_remove": "evict", "mux_sel_done": "build",
                  "mux_build_end": "tail", "spike_idle_start": "idle"}
        seg_at = {sym[n]: s for n, s in starts.items() if n in sym}
        if "mux_slow" in sym and "mux_pin_pass_end" not in sym:
            pass  # stage 3: slow_setup runs until the first mux_slow_loop / fail label
        if "mux_rebuild" in sym:
            if stage4:
                seg_at[sym["mux_rebuild"]] = "restore"
                seg_at[sym["mux_rebuild"] + RESTORE_LEN] = "rebuild"
            else:
                seg_at[sym["mux_rebuild"]] = "rebuild"
        main, disp, rti = sym["spike_main"], sym["irq_dispatch"], sym["irq_exit_rti"]
        idle_zp = sym["zp_spike_idle_lo"]
        have_state = all(n in sym for n in STATE)
        cps = [v.mon.checkpoint_set(a, a, CPU_OP_EXEC) for a in [*seg_at, disp, rti]]

        rows, cur, seg, last = [], None, None, 0
        stack: list[str] = []
        base, prev = 0, -1
        while len(rows) < frames:
            v.mon.exit()
            if not v.mon.wait_stopped(STOP_TIMEOUT):
                raise MeasureError(f"timed out after {len(rows)} frames")
            r = v.mon.registers()
            t = r["LIN"] * CYCLES_PER_LINE + r["CYC"]
            if t < prev:
                base += FRAME
            prev = t
            t += base
            pc = r["PC"]
            if pc == main:
                if cur is not None:
                    cur["segs"][seg] += t - last
                    idle = v.mon.mem_get(idle_zp, idle_zp + 1)
                    cur["iters"] = int.from_bytes(idle, "little") if cur["segs"]["idle"] else 0
                    rows.append(cur)
                cur = {"t": t, "line": r["LIN"], "cyc": r["CYC"], "segs": dict.fromkeys(SEGS, 0),
                       "ev": 0, "ev_pin": 0, "pin_fails": 0, "slow": False,
                       "state": list(v.mon.mem_get(sym[STATE[0]], sym[STATE[0]] + len(STATE) - 1))
                       if have_state else None}
                seg, last, stack = "move", t, []
                continue
            if cur is None:
                continue
            if pc == disp:
                cur["segs"][seg] += (t - IRQ_SEQUENCE) - last
                stack.append(seg)
                seg, last = "irq", t - IRQ_SEQUENCE
            elif pc == rti:
                if stack:
                    cur["segs"][seg] += (t + RTI_TAIL) - last
                    seg, last = stack.pop(), t + RTI_TAIL
            else:
                new = seg_at[pc]
                if new == "evict":
                    if seg == "pin_fail":
                        new = "evict_pin"
                        cur["ev_pin"] += 1
                    else:
                        cur["ev"] += 1
                elif new == "pin_fail":
                    cur["pin_fails"] += 1
                elif new == "slow_setup":
                    cur["slow"] = True
                if stack:  # not expected: a main-loop label inside an IRQ
                    raise MeasureError(f"main-loop label ${pc:04x} hit inside an IRQ")
                cur["segs"][seg] += t - last
                seg, last = new, t
        for c in cps:
            v.mon.checkpoint_delete(c.number)
        mem = {n: int.from_bytes(v.mon.mem_get(sym[n], sym[n] + s - 1), "little")
               for n, s in COUNTERS if n in sym}
    finally:
        v.close()
    return {"prg": str(prg), "warmup": warmup, "no_pin": no_pin, "stage4": stage4,
            "counters": mem, "rows": rows}


def free(x) -> int:
    return x["iters"] * 16


def pin_cost(x) -> int:
    return sum(x["segs"][s] for s in PIN_SEGS)


def amp_after(rows, i):
    """spike_amp after frame i's move (0 = the frame in which the groups reverse)."""
    return rows[i + 1]["state"][4] if i + 1 < len(rows) and rows[i + 1]["state"] else None


def describe(rows, i) -> str:
    x = rows[i]
    st = x["state"]
    s = f"frame {i} (starts line {x['line']} cycle {x['cyc']})"
    if st:
        s += f": D {st[2]}, b {st[0]}, amp {st[4]} -> {amp_after(rows, i)}, dir {st[6]}, player Y {st[7]}"
    return s


def breakdown(x) -> None:
    span = sum(x["segs"].values())
    for s in SEGS:
        if x["segs"][s]:
            print(f"      {s:<11}{x['segs'][s]:>7,}")
    print(f"      {'(frame)':<11}{span:>7,}   mux_update total {sum(x['segs'][s] for s in MUX_SEGS):,}, "
          f"of it pinning {pin_cost(x):,}; evictions: {x['ev']} fair, {x['ev_pin']} pinned "
          f"({x['pin_fails']} pinned fails)")
    print(f"      free = {x['iters']} iterations x 16 = {free(x):,} "
          f"(idle raster span {x['segs']['idle']:,}: DMA in the idle loop {x['segs']['idle'] - free(x):,})")


def report(run: dict, limit: int) -> None:
    rows = run["rows"]
    print(f"{run['prg']}: {len(rows)} frames after {run['warmup']} warm-up frames"
          + (", pin flags cleared" if run["no_pin"] else "") + (" (stage 4 labels)" if run["stage4"] else " (no pin labels)"))
    c = run["counters"]
    print("  counters:", ", ".join(f"{n} {x}" for n, x in c.items()),
          "(" + ", ".join(f"{n} x 16 = {c[n] * 16:,}" for n in c if n.startswith("spike_idle_min"))
          + ", since the spike's own warm-up)")
    frees = [free(x) for x in rows]
    order = sorted(range(len(rows)), key=lambda i: frees[i])
    low = [i for i in order if frees[i] < limit]
    print(f"  free per frame, min / avg / max: {min(frees):,} / {sum(frees) / len(frees):,.0f} / {max(frees):,}")
    print(f"  frames below {limit:,}: {len(low)} of {len(rows)}")
    stress = [i for i in range(len(rows)) if rows[i]["segs"]["sort"] >= SORT_STRESS]
    print(f"  sort-stress frames (sort >= {SORT_STRESS:,}): {len(stress)}; "
          f"of the frames below the limit, {sum(1 for i in low if i in set(stress))} are stress frames")
    slow = [x for x in rows if x["slow"]]
    print(f"  slow (overflow) frames: {len(slow)}; evictions per frame, fair: "
          f"{sorted(Counter(x['ev'] for x in slow).items())}; pinned: {sorted(Counter(x['ev_pin'] for x in slow).items())}")
    print("  segment min / avg / max over the frames it ran in:")
    for s in SEGS:
        xs = [x["segs"][s] for x in rows if x["segs"][s]]
        if xs:
            print(f"      {s:<11}{min(xs):>7,} /{sum(xs) / len(xs):>7,.0f} /{max(xs):>7,}   (n={len(xs):,})")
    for label, xs in (("fast frames", [x for x in rows if not x["slow"]]), ("slow frames", slow)):
        if xs:
            u = [sum(x["segs"][s] for s in MUX_SEGS) for x in xs]
            print(f"  mux_update, {label}: {min(u):,} / {sum(u) / len(u):,.0f} / {max(u):,} (n={len(xs):,})")
    print(f"  frames below the limit (free, sort, mux_update, pinning, evictions fair/pinned, irq, move):")
    for i in low[:40]:
        x = rows[i]
        print(f"    {frees[i]:>6,}  sort {x['segs']['sort']:>5,}  mux {sum(x['segs'][s] for s in MUX_SEGS):>6,}  "
              f"pin {pin_cost(x):>5,}  ev {x['ev']}/{x['ev_pin']}  irq {x['segs']['irq']:>5,}  "
              f"move {x['segs']['move']:>5,}  {describe(rows, i)}")
    if len(low) > 40:
        print(f"    ... and {len(low) - 40} more")
    print(f"  the frame with the least free time: {describe(rows, order[0])}")
    breakdown(rows[order[0]])
    med = order[len(order) // 2]
    print(f"  for scale, the median frame: {describe(rows, med)}")
    breakdown(rows[med])


def compare(a: dict, b: dict, limit: int) -> None:
    ra, rb = a["rows"], b["rows"]
    off = next((k for k in range(-5, 6)
                if all(ra[i]["state"] == rb[i + k]["state"] for i in range(10, 60))), None)
    if off is None:
        sys.exit("the two runs' motion states don't line up (different spike motion?)")
    pairs = [(i, i + off) for i in range(len(ra)) if 0 <= i + off < len(rb)]
    bad = sum(1 for i, j in pairs if ra[i]["state"] != rb[j]["state"])
    print(f"a = {a['prg']}{' (pin flags cleared)' if a['no_pin'] else ''}")
    print(f"b = {b['prg']}{' (pin flags cleared)' if b['no_pin'] else ''}")
    print(f"{len(pairs)} frames paired (b is {off:+d} frames from a), {bad} with a different motion state")
    fa = [free(ra[i]) for i, _ in pairs]
    fb = [free(rb[j]) for _, j in pairs]
    print(f"free min: a {min(fa):,}, b {min(fb):,}; below {limit:,}: a {sum(f < limit for f in fa)}, b {sum(f < limit for f in fb)}")
    d = [x - y for x, y in zip(fa, fb)]
    print(f"a - b free per frame, min / avg / max: {min(d):,} / {sum(d) / len(d):,.0f} / {max(d):,}")
    worst = sorted(range(len(pairs)), key=lambda k: fa[k])[:8]
    for k in worst:
        i, j = pairs[k]
        print(f"a's {describe(ra, i)}: free a {fa[k]:,}, b {fb[k]:,} ({fa[k] - fb[k]:+,})")
        print(f"      {'segment':<11}{'a':>7}{'b':>7}{'a - b':>7}")
        for s in SEGS:
            x, y = ra[i]["segs"][s], rb[j]["segs"][s]
            if x or y:
                print(f"      {s:<11}{x:>7,}{y:>7,}{x - y:>+7,}")
        print(f"      evictions fair/pinned: a {ra[i]['ev']}/{ra[i]['ev_pin']}, b {rb[j]['ev']}/{rb[j]['ev_pin']}")
    kb = min(range(len(pairs)), key=lambda k: fb[k])
    print(f"b's worst frame: {describe(rb, pairs[kb][1])}: free b {fb[kb]:,}, a {fa[kb]:,}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--frames", type=int, default=6000)
    p.add_argument("--warmup", type=int, default=100)
    p.add_argument("--prg", type=Path, default=REPO / "build" / "multiplexer" / "multiplexer.prg")
    p.add_argument("--no-pin", action="store_true")
    p.add_argument("--limit", type=int, default=5300)
    p.add_argument("--out", type=Path)
    p.add_argument("--compare", nargs=2, type=Path, metavar=("A", "B"))
    args = p.parse_args()
    if args.compare:
        compare(*(json.loads(f.read_text()) for f in args.compare), args.limit)
        return
    run = trace(args.frames, args.warmup, args.prg, args.no_pin)
    if args.out:
        args.out.write_text(json.dumps(run))
    report(run, args.limit)


if __name__ == "__main__":
    main()
