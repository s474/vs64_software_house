"""Model behind the low-bit limits in tests/engine/rng/budget.json (Technical Director, 2026-10-02).

Question: which statistic, with which limits, does a good 8-bit generator pass and a bad one
fail? The contract's first guess (each value of the low 5 bits 2-20 times in every block of 256
calls) is not met by any random-like source. This script gives the numbers for its replacement:

  STATISTIC   For each of bits 0-4 of the output and each complete block of 256 consecutive calls
              in one period (255 blocks x 5 bits = 1,275 cells), the number of calls in which the
              bit is 1. spike_bit_min / spike_bit_max = the fewest / most over all cells.
  LIMITS      Not too uneven:  spike_bit_min >= LO_FLOOR  and  spike_bit_max <= HI_CEIL
              Not too even:    spike_bit_min <= LO_CEIL   and  spike_bit_max >= HI_FLOOR

What it prints:
  1. Exact binomial model (n = 256, p = 1/2, cells independent): the chance one cell, and any of
     the 1,275, falls outside a range; the same for the candidate 96-160; the chance a fair
     source passes all four limits.
  2. The same four limits on Python's random (TRIALS periods): how many pass. Checks the model.
  3. engine/rng.asm's sequence (xorshift 7,9,8, new high byte) from 8 seeds: must pass.
  4. Bad generators: which fail, and the two kinds this statistic can't see (one bit that is too
     even while the others are fine; bits that copy each other). check.py's run-length figures
     and its model-against-6502 comparison cover those.
  5. The old statistic, for the record: the chance a 5-bit value is absent from a block.

Run from the repo root (standard library only, about 2 s, no VICE, no build needed):

    python3 tests/engine/rng/limits_model.py

Exit code 1 if the chosen limits don't do their job (a fair source fails too often, the engine's
generator fails, or a bad generator that should fail passes). Results: engine/rng.md#low-bit-limits.
"""

import random
import sys
from math import comb

N = 256                 # calls in a block
BLOCKS = 255            # complete blocks in a period of 65,535
BITS = 5
CELLS = BLOCKS * BITS   # 1,275

# The limits in budget.json (ones per cell).
LO_FLOOR, HI_CEIL = 92, 164     # not too uneven: +/- 36 = 4.5 standard deviations (sd = 8)
LO_CEIL, HI_FLOOR = 116, 140    # not too even: the extremes must be at least 12 = 1.5 sd out

TRIALS = 1000
SEEDS = [0x1234, 0x2A6D, 0x0001, 0x8000, 0xFFFF, 0x00FF, 0xFF00, 0xBEEF]

PMF = [comb(N, k) / 2 ** N for k in range(N + 1)]


def p_outside(lo: int, hi: int) -> float:
    """P(a fair cell's count is < lo or > hi)."""
    return sum(PMF[:lo]) + sum(PMF[hi + 1:])


def p_all_inside(lo: int, hi: int) -> float:
    return (1 - p_outside(lo, hi)) ** CELLS


def p_fair_passes() -> float:
    """P(all four limits hold) for 1,275 independent fair cells, by inclusion-exclusion.

    A = all cells in [LO_FLOOR, HI_CEIL]. Too even on the low side = no cell <= LO_CEIL; on the
    high side = no cell >= HI_FLOOR. Pass = A and not (too even low) and not (too even high).
    """
    a = p_all_inside(LO_FLOOR, HI_CEIL)
    no_low = p_all_inside(LO_CEIL + 1, HI_CEIL)
    no_high = p_all_inside(LO_FLOOR, HI_FLOOR - 1)
    neither = p_all_inside(LO_CEIL + 1, HI_FLOOR - 1)
    return a - no_low - no_high + neither


def stat(out: list[int]) -> tuple[int, int]:
    """Fewest and most ones per (block, bit) cell over the complete blocks of out."""
    lo, hi = N, 0
    for b in range(len(out) // N):
        block = out[b * N:(b + 1) * N]
        for bit in range(BITS):
            ones = sum((v >> bit) & 1 for v in block)
            lo, hi = min(lo, ones), max(hi, ones)
    return lo, hi


def passes(s: tuple[int, int]) -> bool:
    return LO_FLOOR <= s[0] <= LO_CEIL and HI_FLOOR <= s[1] <= HI_CEIL


def xorshift798(seed: int, calls: int = 65535) -> list[int]:
    """engine/rng.asm: s ^= s << 7; s ^= s >> 9; s ^= s << 8; output the new high byte."""
    out, s = [], seed
    for _ in range(calls):
        s ^= (s << 7) & 0xFFFF
        s ^= s >> 9
        s ^= (s << 8) & 0xFFFF
        out.append(s >> 8)
    return out


def bad_generators() -> list:
    """(name, one period of output, expected: True must fail, False known to pass, None borderline)."""
    n = BLOCKS * N
    r = random.Random(1)
    fair = [r.getrandbits(8) for _ in range(n)]
    gens = [("counter (0, 1, 2, ...)", [i & 0xFF for i in range(n)], True)]
    x, lcg = 1, []
    for _ in range(n):
        x = (x * 5 + 1) & 0xFF
        lcg.append(x)
    gens.append(("8-bit LCG x = 5x + 1, whole byte (low bits have periods 2-32)", lcg, True))
    gens.append(("fair, but bit 0 alternates", [(v & 0xFE) | (i & 1) for i, v in enumerate(fair)], False))
    gens.append(("fair, but bit 3 stuck at 0", [v & 0xF7 for v in fair], True))
    for p in (0.55, 0.60, 0.65):
        gens.append((f"fair, but bit 2 is 1 with probability {p}",
                     [(v & 0xFB) | (4 if r.random() < p else 0) for v in fair], True if p >= 0.60 else None))
    s, lfsr = 0x1234, []
    for _ in range(n):                      # 16-bit Galois LFSR stepped ONE bit a call, low byte out
        s = (s >> 1) ^ (0xB400 if s & 1 else 0)
        lfsr.append(s & 0xFF)
    gens.append(("16-bit LFSR stepped one bit a call (each bit is its neighbour, one call late)", lfsr, False))
    return gens


def main() -> int:
    fails = []
    print(f"1. Binomial model: ones in {N} calls, p = 1/2 (mean 128, sd 8); {CELLS} cells = {BLOCKS} blocks x {BITS} bits")
    print("   range      P(one cell outside)   P(any of the cells outside) = P(a fair source fails)")
    for lo, hi in [(104, 152), (100, 156), (96, 160), (94, 162), (LO_FLOOR, HI_CEIL), (88, 168)]:
        mark = "  <- candidate (raster-engineer)" if (lo, hi) == (96, 160) else "  <- chosen" if (lo, hi) == (LO_FLOOR, HI_CEIL) else ""
        print(f"   {lo:>3}-{hi:<3}    {p_outside(lo, hi):.2e}              {1 - p_all_inside(lo, hi):.4%}{mark}")
    even_lo = p_all_inside(LO_CEIL + 1, N)
    even_hi = p_all_inside(0, HI_FLOOR - 1)
    print(f"   too even: P(no cell <= {LO_CEIL}) = {even_lo:.1e}; P(no cell >= {HI_FLOOR}) = {even_hi:.1e}")
    p_pass = p_fair_passes()
    print(f"   all four limits ({LO_FLOOR} <= min <= {LO_CEIL}, {HI_FLOOR} <= max <= {HI_CEIL}): "
          f"a fair source passes with probability {p_pass:.4%} (fails 1 time in {1 / (1 - p_pass):,.0f})")
    if p_pass < 0.99:
        fails.append("a fair source fails more than 1% of the time")

    print(f"\n2. Python's random, {TRIALS} periods of {CELLS} cells:")
    r = random.Random(2026)
    mins, maxs, ok, ok_candidate = [], [], 0, 0
    for _ in range(TRIALS):
        cells = [bin(r.getrandbits(N)).count("1") for _ in range(CELLS)]
        s = (min(cells), max(cells))
        mins.append(s[0])
        maxs.append(s[1])
        ok += passes(s)
        ok_candidate += s[0] >= 96 and s[1] <= 160
    mins.sort()
    maxs.sort()
    print(f"   fewest: {mins[0]}-{mins[-1]} (median {mins[TRIALS // 2]}); most: {maxs[0]}-{maxs[-1]} (median {maxs[TRIALS // 2]})")
    print(f"   pass the chosen limits: {ok} of {TRIALS}; would pass 96-160: {ok_candidate} of {TRIALS} "
          f"(model: {p_all_inside(96, 160):.1%})")
    if ok < 0.98 * TRIALS:
        fails.append("random trials disagree with the model")

    print("\n3. engine/rng.asm (xorshift 7,9,8, high byte), one period from each seed:")
    for seed in SEEDS:
        s = stat(xorshift798(seed))
        print(f"   seed ${seed:04x}: ones per cell {s[0]}-{s[1]}  {'pass' if passes(s) else 'FAIL'}")
        if not passes(s):
            fails.append(f"engine generator, seed ${seed:04x}")

    print("\n4. Bad generators:")
    for name, out, must_fail in bad_generators():
        s = stat(out)
        verdict = "pass" if passes(s) else "fail"
        note = {True: "", None: "  (borderline: 0.55 moves the mean by 1.6 sd; may go either way)",
                False: "  (blind spot of this statistic: covered by check.py, see engine/rng.md)"}[must_fail]
        if must_fail is False and verdict == "fail":
            note = "  (was expected to pass)"
        print(f"   {name}: {s[0]}-{s[1]}  {verdict}{note}")
        if must_fail and verdict == "pass":
            fails.append(name)

    print("\n5. The old statistic (count of each 5-bit value in a block: 32 values x 255 blocks = 8,160 cells, mean 8):")
    p0 = (31 / 32) ** N
    print(f"   P(a given value is absent from a given block) = (31/32)^256 = {p0:.3%}; "
          f"expected empty cells in a period {8160 * p0:.1f}; P(at least one) about {1 - (1 - p0) ** 8160:.0%}")
    def p_cell(lo: int, hi: int) -> float:
        return sum(comb(N, j) * (1 / 32) ** j * (31 / 32) ** (N - j) for j in range(lo, hi + 1))

    for k in (20, 21, 22, 23):
        print(f"   P(a cell >= {k}) = {p_cell(k, N):.2e}; expected cells in a period {8160 * p_cell(k, N):.2f}")
    print(f"   The first-guess limits 2-20, cells taken as independent: P(a fair source has fewest >= 2) = "
          f"{(1 - p_cell(0, 1)) ** 8160:.1e}; P(most <= 20) = {(1 - p_cell(21, N)) ** 8160:.0%}. Not a usable limit.")

    print("\nFAILED: " + "; ".join(fails) if fails else "\nLIMITS OK")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
