# Random numbers: `engine/rng.asm`

Design contract for M4 (Technical Director, 2026-10-01). Status: **implemented and measured**
(raster-engineer, M4 stage 1, 2026-10-02): `engine/rng.asm`, a 16-bit xorshift (shifts 7, 9, 8)
returning the new high byte; spike `tests/engine/rng/` at its stage 2 (commit 9e6c11e), **11 checks
in `make test`, all passing** (`make test ARGS=rng`, 2026-10-02), and the model check
`tests/engine/rng/check.py`. The first-guess limits for the low 5 bits (2–20) were wrong and
are **replaced** (Technical Director, 2026-10-02) by a ones-per-block test the spike now reports:
**measured 103–157**, equal to the model: see [Low-bit limits](#low-bit-limits). Conventions are
[engine/README.md](README.md)'s.

## Purpose

An 8-bit pseudo-random number, cheap enough to call a few times a frame, repeatable from a seed.
Swarm uses it to choose which parked enemy dives (about once every 50–150 frames); `AUTOPLAY`
budget runs and QA scripts need the same sequence every run.

Out of scope for M4: ranges (`0..n−1` without bias), 16-bit results, more than one generator.
A game that needs a number below n masks to the next power of two and retries.

## API

```
// Seed the generator. Any value is accepted; a seed that would stop the generator (all zero for
// an LFSR or xorshift) is replaced by a fixed non-zero one.
// In: A = seed low, X = seed high   Out: nothing   Uses: A
rng_seed:

// Next random byte. Main loop only.
// In:  nothing
// Out: A = 0-255
// Uses: A only (X and Y are preserved, so it can be called inside an indexed loop)
// Cost: the whole call is 42 cycles (measured, no DMA): the caller's jsr 6 + 30 from rng_next to
//       rng_next_end + rts 6. The profile check's span is the 30
rng_next:
```

Requirements (the algorithm is the raster-engineer's choice; a 16-bit xorshift or Galois LFSR
stepped a whole byte meets them):

| # | Requirement |
|---|---|
| 1 | 16 bits of state; the sequence repeats only after **65,535** calls, from any accepted seed |
| 2 | Over one whole period every byte value comes out 255–257 times |
| 3 | Each of bits 0–4 behaves like a fair coin over any 256 consecutive calls: not stuck, not biased, and not too regular (no bit that just alternates). Swarm masks to 5 bits. The test and its limits: [Low-bit limits](#low-bit-limits) |
| 4 | The same seed gives the same sequence in DEBUG and release |
| 5 | Constant time: no data-dependent path longer than another by more than 2 cycles |

Not for anything that needs unpredictability beyond a game's. Seeding is the game's job: Swarm
seeds from `zp_irq_frame` and `$D012` when fire starts a game (reading `$D012` is allowed; only
writing it is the IRQ framework's), and with a constant under `AUTOPLAY`.

## Data the game provides

None.

## Zero page

| Label | Bytes | Owner | Purpose |
|---|---|---|---|
| `zp_rng_lo`, `zp_rng_hi` | 2 | Main loop | Generator state |

Not IRQ-safe: an IRQ handler that needs random numbers gets them from the main loop.

## Cycle budget

Two spans, as everywhere in the engine ([README](README.md#which-span-a-figure-is)): the **profile
span** is what `make test` measures, from the routine's label to its `_end` label, which is on the
`rts`, so the `rts` isn't in it; the **whole call** adds the caller's `jsr` (6) and the `rts` (6),
and is the figure a game puts in its frame budget.

| Routine | Profile span | Whole call | Basis |
|---|---|---|---|
| `rng_next` → `rng_next_end` | **30** raster cycles, locked (`min_cycles` = `max_cycles`) | **42** | **measured** 30 in every pass (`make test`, and `vice_profile` over 50 passes, 2026-10-02), equal to the instruction count; no branches, so requirement 5 holds exactly. Called on line 18 (top border, no DMA). The design estimate was 45 for the whole call |
| `rng_seed` | not budgeted (called once a game) | 13 + `rts` 6 + `jsr` 6 = 25 (34 for seed 0/0) | counted |
| Size | 37 bytes (`rng_seed` 17, `rng_next` 20) | **measured** (estimate was 40) |

42 is with no DMA. A call made while the display and sprites are on costs more raster time (× 1.27
on average with 24 sprites, **measured** share, [vic-ii-timing.md](../docs/reference/vic-ii-timing.md#frame-budget-worked-example-pal):
about 54). Swarm's use is inside the diver row of its
[frame budget](../docs/games/swarm/memory-map.md#frame-budget).

## Spike: `tests/engine/rng/`

No display work. The spike seeds, then in its main loop calls `rng_next` and keeps statistics in
RAM. Chain: entry 0 only (so the budget runner has its IRQ labels). It must demonstrate:

1. **Period**: after seeding, count calls until the state returns to the seed:
   `spike_period` (2 bytes) = 65,535, and `spike_done` = 1 when the count has finished.
2. **Distribution**: a 256-entry histogram of one whole period: `spike_hist_min` ≥ 255,
   `spike_hist_max` ≤ 257.
3. **Low bits**: over each complete block of 256 calls in the period (255 blocks), for each of
   bits 0–4, the number of calls in which the bit is 1 (it should be about 128): `spike_bit_min`
   and `spike_bit_max` over all 1,275 cells, limited as in [Low-bit limits](#low-bit-limits).
   (First built with the count of each 5-bit value instead, `spike_low5_min` / `spike_low5_max`,
   which stay as reported figures.)
4. **Zero seed**: `rng_seed` with A = X = 0, then 256 calls that aren't all the same value:
   `spike_zero_ok` = 1.
5. The measured cost of `rng_next`.

A whole period is 65,535 calls: the statistics finish (`spike_done` = 1) at **frame 450** after
the program's entry (**measured**: `check.py --finish-frame`; about 300 before the five bit counters
were added). They run to completion once, then the spike keeps calling `rng_next` once a frame so
the profile check has passes to measure.

`tests/engine/rng/budget.json` (`warmup_frames` 600, so the statistics are finished; `stage` 2:
the spike reports the two `spike_bit_*` labels). 11 checks:

| Check | Kind | Labels | Limit | Basis |
|---|---|---|---|---|
| `rng_next` | `profile` | `rng_next` → `rng_next_end` | `min_cycles` = `max_cycles` = 30 (the estimate was 45) | measured |
| statistics finished | `memory` | `spike_done` | equals 1 | requirement |
| period | `memory` | `spike_period`, size 2 | equals 65535 | requirement |
| every byte value 255–257 times | `memory` ×2 | `spike_hist_min`, `spike_hist_max` | min 255; max 257 | requirement |
| ones per block for bits 0–4, not too uneven | `memory` ×2, `from_stage` 2 | `spike_bit_min`, `spike_bit_max` | min 92; max 164 (**measured** 103, 157) | requirement ([model](#low-bit-limits)) |
| ones per block for bits 0–4, not too even | `memory` ×2, `from_stage` 2 | `spike_bit_min`, `spike_bit_max` | max 116; min 140 | requirement ([model](#low-bit-limits)) |
| no late chain entries | `memory` | `irq_late_count` | equals 0 after 100 frames | requirement |
| zero seed handled | `memory` | `spike_zero_ok` | equals 1 | requirement |

The two interim locks on the count of each 5-bit value (`spike_low5_min` equals 0, `spike_low5_max`
equals 21) were **removed** on 2026-10-02, when the four ones-per-block checks first ran and
passed. The spike still reports both labels, and `check.py` still compares them with the model, so
a change to the sequence is still caught there.

### Low-bit limits

Technical Director, 2026-10-02. Model: [tests/engine/rng/limits_model.py](../tests/engine/rng/limits_model.py)
(`python3 tests/engine/rng/limits_model.py`, about 2 s, no VICE); every probability below is its
output.

**The first guess was wrong, not the generator.** "Each value of the low 5 bits 2–20 times in every
256 calls" asks for something *more even* than chance. With 32 values and 256 calls the mean count
is 8, and a period has 32 × 255 = 8,160 value-block cells. For a fair source a given value is absent
from a given block with probability (31/32)^256 = **0.030%**, so 2.4 empty cells are expected in a
period and at least one turns up in about **91%** of periods; a count of 21 or more turns up in
about **42%**. The chance a fair source meets 2–20 is about 1 in 10 billion. Measured 0–21 is what
a fair source does. Those limits are withdrawn.

**The replacement statistic** (the raster-engineer's suggestion, with the limits set from the
model): for each of bits 0–4 and each complete block of 256 consecutive calls, the number of calls
in which the bit is 1. One period gives 255 × 5 = **1,275 cells**; a fair bit's count is binomial
(n = 256, p = ½): mean 128, standard deviation 8.

| Limit | Value | A fair source fails it | What fails it |
|---|---|---|---|
| Not too uneven: every cell within | **92–164** (± 4.5 sd) | **0.56%** of periods (one cell outside: 4.4 in a million, × 1,275) | A stuck bit (0 or 256), a bit that is 1 with probability 0.6 or more (most: 174) |
| Not too even: the fewest is at most, the most is at least | **116**, **140** (the extremes at least 1.5 sd out) | never (5 × 10⁻⁴⁴) | A counter, an 8-bit LCG, anything whose low bits have a short period: 128 in every cell |
| All four together | | **0.56%**: 1 fair source in 180 | |

- **Why not 96–160**, the suggested range (± 4 sd): a fair source has a cell outside it in **5.5%**
  of periods (model; 64 of 1,000 trials of Python's `random`). One good generator in 18 would fail,
  which is a limit that invites being edited to pass. 92–164 costs almost nothing in power: the bad
  generators above miss it by 10 or more.
- **Why the "too even" pair.** A range alone is passed by a generator that alternates or counts
  (exactly 128 every time), which is the fault requirement 3 names. A fair source's fewest is
  91–108 and its most 148–166 (1,000 trials), so 116 and 140 are far from anything chance does.
- **The generator**: **103–157 measured** on the C64 from the spike's seed (`spike_bit_min` 103,
  `spike_bit_max` 157, `make test ARGS=rng`, stage 2), equal to the model's figures; 102–158 over
  the eight seeds `check.py` uses (*model*: the Python model that `check.py` proves equal to the
  6502 routine). Inside the outer limits by 6 or more.
- **What this statistic can't see**, and what covers it: one bit that is too even while the other
  four are fine (the fewest and most are taken over all five bits), and bits that copy each other
  (an LFSR stepped one bit a call passes). `check.py` part D covers the first (longest run of each
  bit 10–24, measured 16) and requirements 1 and 2 with the model comparison cover the second for
  this algorithm. `make test` is a regression guard, not a randomness test suite.
- The sequence is deterministic, so there is no run-to-run noise: the limits matter when the
  algorithm or the spike's seed changes, and a change that fails them is reported, not re-baselined.

**What the spike adds at its stage 2** (raster-engineer, done in commit 9e6c11e; this is the
specification it was built to):

| Label | Size | Starts | Meaning when `spike_done` = 1 |
|---|---|---|---|
| `spike_bit_min` | 1 byte | `$FF` | Over the same 255 complete blocks as `spike_low5_*`, and bits 0–4 of the byte `rng_next` returned: the fewest calls in a block in which a bit was 1 |
| `spike_bit_max` | 1 byte | `0` | The most |

- Five 1-byte counters, cleared at each block end after folding into the two results (as
  `spike_block_end` does for `spike_low5`). A bit that is 1 in all 256 calls wraps its counter to
  0, which fails the min 92 check: no 16-bit count is needed.
- From seed `$1234`: **103** and **157**, the model's figures and the **measured** ones. Both are
  on the spike's screen.
- `check.py` compares the two labels with the model's figures; its warm-up is 600 frames, as
  `budget.json`'s (the statistics finish at frame 450, **measured**).
- `"stage"` is 2 in `budget.json`, and the two interim `spike_low5` locks are removed.

**Does a game need to care that a 5-bit value can be absent for 256 calls? No, with one rule.**
It is what dice do: any particular value misses a whole block of 256 calls once in about 3,400
blocks. Swarm asks for a number about once every 50–150 frames, so 256 calls is 4 to 13 minutes of
play, and "enemy 7 didn't dive for a while" is not something a player can see. The rule: **never
write code that depends on a value turning up within some number of calls** (a loop that waits for
a particular value, "every enemy has had a turn after 32 picks"). A game that needs every item
chosen once before any repeats uses a shuffled list, not this module's raw output. And a
mask-and-retry loop (a number below n) is bounded by the caller: Swarm's launcher makes at most 2
calls a frame ([memory map](../docs/games/swarm/memory-map.md#frame-budget)).

### Results (raster-engineer, 2026-10-02)

Spike figures from `make test ARGS=rng` (seed `$1234`); the rest from
`uv run --package budget-runner python tests/engine/rng/check.py` (about 15 s; all pass, DEBUG and
release).

| Requirement | Result | How |
|---|---|---|
| 1 Period 65,535 from any seed | **Met.** `spike_period` = 65,535 counted on the C64. In the model the cycle from `$0001` holds all 65,535 non-zero states, so every seed is on it; state 0 maps only to itself and nothing else reaches it | spike; `check.py` A, B |
| 2 Each byte value 255–257 times | **Met.** 255 (value 0) to 256 | spike; `check.py` D |
| 3 Low bits spread over any 256 calls | **Met as worded, but not the 2–20 limits.** No bit alternates: each of bits 0–4 is 1 in 32,768 of 65,535 calls, longest run 16, 103–157 ones per block. Per block of 256, any value of the low 5 bits comes out **0–21** times (mean 8); low 4 bits 4–31 (mean 16); low 3 bits 14–50; low 2 bits 43–86; low 1 bit 99–157 | spike (`spike_low5_min` 0, `spike_low5_max` 21, 255 blocks); `check.py` D |
| 4 Same sequence in DEBUG and release | **Met.** No `#if` in the module; `check.py` passes on both builds | `check.py --prg` |
| 5 Constant time | **Met.** No branches; 30 every pass | `make test` |
| X and Y preserved, A = result | **Met.** 600 calls over 8 seeds with marker values in X and Y, A and the state equal to the model's | `check.py` C |
| Zero seed | **Met.** Seed 0/0 becomes `RNG_SEED_DEFAULT` = `$2A6D`; `spike_zero_ok` = 1 | spike; `check.py` C |

**The 2–20 limits can't be met by a generator that behaves randomly.** With a mean of 8 per value
the count in a block is close to Poisson: a value is absent from a block with probability about
0.03%, and there are 8,160 value-block cells in a period, so about 3 empty cells are expected.
`check.py` runs the same statistic on Python's `random`: over 20 trials the fewest was 0–1 and the
most 19–22, and none of the 20 met 2–20. Other seeds of this generator give 0 and 20–22. A
generator that did meet 2–20 would be *less* random (too even). For Swarm this means: in some
stretch of 256 calls a particular 5-bit value won't appear at all, which is what dice do.
Options for the Technical Director: keep the measured pair as a regression lock (what `budget.json`
did at the time), or replace the statistic with one a good generator passes and a bad one fails (for
example ones per block for each bit within 96–160, measured 103–157).

**Decided** (Technical Director, 2026-10-02): the second, with limits 92–164 and a "not too even"
pair: [Low-bit limits](#low-bit-limits). The measured pair was kept as an interim lock until the
spike reported the new statistic, and is now removed.
