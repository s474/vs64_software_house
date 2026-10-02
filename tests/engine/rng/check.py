"""Model check of engine/rng.asm: period, distribution, and the model against the 6502 in VICE.

The spike (tests/engine/rng/main.asm) counts one whole period on the C64 itself, and `make test`
checks its results. This script backs those figures from the other side:

  A. A Python model of the exact 6502 instruction sequence of rng_next (the two rotates through
     carry), and of the textbook form s ^= s << 7; s ^= s >> 9; s ^= s << 8. They must agree
     on all 65,536 states.
  B. Period: from state $0001 the model visits every non-zero state once before returning, so the
     period is 65,535 from ANY non-zero seed; state 0 maps to 0 and is reached from nowhere else
     (so the sequence can't get stuck at zero; rng_seed replaces seed 0/0).
  C. The 6502 routine in VICE against the model: for each of several seeds the state is written
     into zp_rng_lo/hi while the machine is stopped at rng_next, X and Y are set to marker
     values, and at rng_next_end A, the state, X and Y are read: --calls outputs per seed
     (default 600). Also the spike's own results (period, histogram, low-5 figures, ones per block
     for bits 0-4, the zero-seed state) against the model's for the spike's seed.
  D. Distribution of the low bits (Swarm masks to 5 bits), from the model, seed = the spike's:
     each of bits 0-4 over the period (ones, longest run), and for the low 1-5 bits the fewest /
     most times any value comes out in a block of 256 consecutive calls (255 blocks). Reported
     beside the same statistic for an ideal random source (Python's random, 20 trials), because
     the contract's first-guess limits for the low 5 bits (2-20) are tighter than randomness gives.

Run from the repo root (build first: make GAME=rng SRC_DIR=tests/engine/rng):

    uv run --package budget-runner python tests/engine/rng/check.py [--calls 600] [--prg build/rng/rng.prg]

About 20 s (600 warm-up frames: the spike's statistics take 450, measured, then one frame per call checked). Works on a release build
(make BUILD=release ...): it uses no DEBUG label. Exit code 1 on any failure.

    uv run --package budget-runner python tests/engine/rng/check.py --finish-frame

prints only the frame (counted from the program's entry, as the warm-up is) at which spike_done
becomes 1, and fails if that is not within WARMUP frames. About 15 s.
"""

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice
from vice_monitor import CPU_OP_EXEC, run_frames  # on sys.path once budget_runner.session is imported

REPO = Path(__file__).resolve().parents[3]
SPIKE_SEED = 0x1234
WARMUP = 600         # frames, as budget.json's warmup_frames
SEED_DEFAULT = 0x2A6D
SEEDS = [SPIKE_SEED, SEED_DEFAULT, 0x0001, 0x8000, 0xFFFF, 0x00FF, 0xFF00, 0xBEEF]


def step_6502(s: int) -> tuple[int, int]:
    """rng_next, instruction by instruction. Returns (new state, A)."""
    lo, hi = s & 0xFF, s >> 8
    a = hi                              # lda zp_rng_hi
    c, a = a & 1, a >> 1                # lsr
    a = lo                              # lda zp_rng_lo
    c, a = a & 1, (a >> 1) | (c << 7)   # ror
    a ^= hi                             # eor zp_rng_hi
    hi = a                              # sta zp_rng_hi
    c, a = a & 1, (a >> 1) | (c << 7)   # ror
    a ^= lo                             # eor zp_rng_lo
    lo = a                              # sta zp_rng_lo
    a ^= hi                             # eor zp_rng_hi
    hi = a                              # sta zp_rng_hi
    return (hi << 8) | lo, a


def step_ref(s: int) -> int:
    s ^= (s << 7) & 0xFFFF
    s ^= s >> 9
    s ^= (s << 8) & 0xFFFF
    return s


def block_minmax(out: list[int], bits: int) -> tuple[int, int]:
    m = (1 << bits) - 1
    lo, hi = 999, 0
    for b in range(len(out) // 256):
        c = Counter(v & m for v in out[b * 256:b * 256 + 256])
        lo = min(lo, min(c.get(i, 0) for i in range(m + 1)))
        hi = max(hi, max(c.values()))
    return lo, hi


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls", type=int, default=600)
    ap.add_argument("--prg", default=str(REPO / "build/rng/rng.prg"))
    ap.add_argument("--finish-frame", action="store_true",
                    help="only report the frame at which the spike's statistics finish")
    a = ap.parse_args()
    fails = []

    if a.finish_frame:
        v = Vice(Path(a.prg), 0)
        try:
            done, frame = v.symbols["spike_done"], 0
            while frame < WARMUP + 200 and v.mon.mem_get(done, done)[0] != 1:
                run_frames(v.mon, 1)
                frame += 1
            finished = v.mon.mem_get(done, done)[0] == 1
        finally:
            v.close()
        ok = finished and frame <= WARMUP
        print(f"[{'PASS' if ok else 'FAIL'}] spike_done = 1 " + (f"at frame {frame}" if finished else f"not reached in {frame} frames")
              + f" after the program's entry (warm-up {WARMUP})")
        return 0 if ok else 1

    def rep(name, ok, text):
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {text}")
        if not ok:
            fails.append(name)

    # A
    diff = [s for s in range(65536) if step_6502(s)[0] != step_ref(s) or step_6502(s)[1] != step_ref(s) >> 8]
    rep("A model = xorshift 7,9,8", not diff, f"6502 sequence and textbook form agree on {65536 - len(diff)} of 65,536 states; A = new high byte")

    # B
    seen, s, n = set(), 1, 0
    while True:
        s, _ = step_6502(s)
        seen.add(s)
        n += 1
        if s == 1 or n > 70000:
            break
    rep("B period", n == 65535 and len(seen) == 65535 and 0 not in seen and step_6502(0)[0] == 0,
        f"cycle from $0001 has {n} calls and {len(seen)} distinct states, zero not among them; "
        f"0 -> ${step_6502(0)[0]:04x}. One cycle holds every non-zero state, so the period is {n} from any seed")

    # Model outputs for the spike's seed, one period
    out, s = [], SPIKE_SEED
    for _ in range(65535):
        s, x = step_6502(s)
        out.append(x)
    hist = Counter(out)
    hmin, hmax = min(hist.get(i, 0) for i in range(256)), max(hist.values())
    l5 = block_minmax(out, 5)
    # Ones per block of 256 calls for each of bits 0-4 (255 blocks x 5 bits): spike_bit_min/max
    cells = [sum((x >> b) & 1 for x in out[k * 256:k * 256 + 256]) for k in range(255) for b in range(5)]
    bit_min, bit_max = min(cells), max(cells)

    # C
    v = Vice(Path(a.prg), WARMUP)
    try:
        mon, sym = v.mon, v.symbols

        def u(name, size=1):
            return int.from_bytes(mon.mem_get(sym[name], sym[name] + size - 1), "little")

        spike = {k: u(k, z) for k, z in [("spike_done", 1), ("spike_period", 2), ("spike_hist_min", 2),
                                         ("spike_hist_max", 2), ("spike_low5_min", 1), ("spike_low5_max", 1),
                                         ("spike_bit_min", 1), ("spike_bit_max", 1),
                                         ("spike_blocks", 1), ("spike_zero_ok", 1), ("spike_zero_state", 2)]}
        want = {"spike_done": 1, "spike_period": 65535, "spike_hist_min": hmin, "spike_hist_max": hmax,
                "spike_low5_min": l5[0], "spike_low5_max": l5[1], "spike_bit_min": bit_min, "spike_bit_max": bit_max,
                "spike_blocks": 255, "spike_zero_ok": 1,
                "spike_zero_state": SEED_DEFAULT}
        rep("C spike results = model", spike == want, f"C64 {spike}" + ("" if spike == want else f" model {want}"))

        cps = [mon.checkpoint_set(sym[n], sym[n], CPU_OP_EXEC) for n in ("rng_next", "rng_next_end")]

        def stop(label):
            mon.exit()
            if not mon.wait_stopped(STOP_TIMEOUT):
                mon.ping()
                raise MeasureError(f"{label} not reached: jam?")
            r = mon.registers()
            if r["PC"] != sym[label]:
                raise MeasureError(f"stopped at ${r['PC']:04x}, expected {label}")
            return r

        per = max(1, a.calls // len(SEEDS))
        total = bad = 0
        first_bad = None
        for seed in SEEDS:
            s = seed
            stop("rng_next")
            mon.mem_set(sym["zp_rng_lo"], bytes([seed & 0xFF]))
            mon.mem_set(sym["zp_rng_hi"], bytes([seed >> 8]))
            for i in range(per):
                if i:
                    stop("rng_next")
                mx, my = (0x5A + i) & 0xFF, (0xC3 - i) & 0xFF
                mon.set_register("X", mx)
                mon.set_register("Y", my)
                r = stop("rng_next_end")
                s, x = step_6502(s)
                got = (u("zp_rng_lo") | u("zp_rng_hi") << 8, r["A"], r["X"], r["Y"])
                total += 1
                if got != (s, x, mx, my):
                    bad += 1
                    first_bad = first_bad or (hex(seed), i, got, (s, x, mx, my))
        for c in cps:
            mon.checkpoint_delete(c.number)
    finally:
        v.close()
    rep("C 6502 = model", bad == 0 and total >= a.calls - len(SEEDS),
        f"{total} calls over {len(SEEDS)} seeds ({per} each: {', '.join(f'${x:04x}' for x in SEEDS)}): "
        f"{total - bad} match in A and state, with X and Y preserved" + (f"; first mismatch {first_bad}" if bad else ""))

    # D
    rep("D byte histogram, one period", (hmin, hmax) == (255, 256) and hist.get(0, 0) == 255,
        f"each value {hmin}-{hmax} times (value 0: {hist.get(0, 0)})")
    print("  D low bits, model, seed $1234, one period (65,535 calls; blocks = 255 x 256 calls):")
    for b in range(5):
        bits = [(x >> b) & 1 for x in out]
        run = best = 1
        for i in range(1, len(bits)):
            run = run + 1 if bits[i] == bits[i - 1] else 1
            best = max(best, run)
        ones = [sum(bits[k * 256:k * 256 + 256]) for k in range(255)]
        print(f"    bit {b}: ones {sum(bits)} of 65,535; longest run {best}; ones per block {min(ones)}-{max(ones)} (mean 128)")
        if not (32700 <= sum(bits) <= 32800 and 10 <= best <= 24):
            fails.append(f"D bit {b}")
    rnd = [list(random.Random(t).randbytes(65280)) for t in range(20)]
    print("    value counts per block of 256 calls, fewest-most over all blocks | ideal random, 20 trials")
    for k in range(1, 6):
        lo, hi = block_minmax(out, k)
        ref = [block_minmax(r, k) for r in rnd]
        print(f"    low {k} bit(s): mean {256 >> k:>3}, generator {lo}-{hi} | random: fewest "
              f"{min(r[0] for r in ref)}-{max(r[0] for r in ref)}, most {min(r[1] for r in ref)}-{max(r[1] for r in ref)}")
    lo, hi = l5
    ref = [block_minmax(r, 5) for r in rnd]
    in_ref = min(r[0] for r in ref) <= lo <= max(r[0] for r in ref) and min(r[1] for r in ref) <= hi <= max(r[1] for r in ref)
    rep("D low 5 bits behave as a random source", in_ref,
        f"fewest {lo}, most {hi} per block; contract's first-guess limits 2-20 are {'met' if lo >= 2 and hi <= 20 else 'NOT met'} "
        f"(random trials meeting 2-20: {sum(1 for r in ref if r[0] >= 2 and r[1] <= 20)} of 20)")
    for seed in SEEDS[1:]:
        o, s = [], seed
        for _ in range(65535):
            s, x = step_6502(s)
            o.append(x)
        print(f"    seed ${seed:04x}: low 5 bits {block_minmax(o, 5)}")

    print("\nFAILED: " + ", ".join(fails) if fails else "\nALL PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL (jam/hang): {e}")
        sys.exit(2)
