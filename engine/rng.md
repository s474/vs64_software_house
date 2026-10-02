# Random numbers: `engine/rng.asm`

Design contract for M4 (Technical Director, 2026-10-01). Status: **implemented and measured**
(raster-engineer, M4 stage 1, 2026-10-02): `engine/rng.asm`, a 16-bit xorshift (shifts 7, 9, 8)
returning the new high byte; spike `tests/engine/rng/`, 9 checks in `make test`, and the model
check `tests/engine/rng/check.py`. **One point is open for the Technical Director: the first-guess
limits for the low 5 bits (2–20) are not met, measured 0–21** ([Results](#results-raster-engineer-2026-10-02)). Conventions are
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
// Cost: measured 30 raster cycles to its rts (no DMA) + jsr/rts 12 = 42
rng_next:
```

Requirements (the algorithm is the raster-engineer's choice; a 16-bit xorshift or Galois LFSR
stepped a whole byte meets them):

| # | Requirement |
|---|---|
| 1 | 16 bits of state; the sequence repeats only after **65,535** calls, from any accepted seed |
| 2 | Over one whole period every byte value comes out 255–257 times |
| 3 | The low 1, 2, 3, 4 and 5 bits each take all their values about equally over any 256 consecutive calls (no bit that just alternates): Swarm masks to 5 bits |
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

| Routine | Budget | Basis |
|---|---|---|
| `rng_next` → `rng_next_end` (its `rts`) | **30** raster cycles, locked (`min_cycles` = `max_cycles`) | **measured** 30 in every pass (`make test`, and `vice_profile` over 50 passes, 2026-10-02), equal to the instruction count; no branches, so requirement 5 holds exactly. The estimate was 45 including the `rts`; like for like it is 36. Called on line 18 (top border, no DMA). With `jsr` and `rts`: 42 |
| `rng_seed` | not budgeted (called once a game) | 13 + `rts` 6 (22 + 6 for seed 0/0), counted |
| Size | 37 bytes (`rng_seed` 17, `rng_next` 20) | **measured** (estimate was 40) |

Swarm's use is inside the diver row of its
[frame budget](../docs/games/swarm/memory-map.md#frame-budget).

## Spike: `tests/engine/rng/`

No display work. The spike seeds, then in its main loop calls `rng_next` and keeps statistics in
RAM. Chain: entry 0 only (so the budget runner has its IRQ labels). It must demonstrate:

1. **Period**: after seeding, count calls until the state returns to the seed:
   `spike_period` (2 bytes) = 65,535, and `spike_done` = 1 when the count has finished.
2. **Distribution**: a 256-entry histogram of one whole period: `spike_hist_min` ≥ 255,
   `spike_hist_max` ≤ 257.
3. **Low bits**: over each block of 256 calls in the period, the count of each 5-bit value (it
   should be about 8): `spike_low5_min` and `spike_low5_max` over all blocks, reported and limited
   to 2–20.
4. **Zero seed**: `rng_seed` with A = X = 0, then 256 calls that aren't all the same value:
   `spike_zero_ok` = 1.
5. The measured cost of `rng_next`.

A whole period is 65,535 calls: about 3.2 million cycles at 48 a call, 160 frames or so. The
statistics run to completion once, then the spike keeps calling `rng_next` once a frame so the
profile check has passes to measure.

`tests/engine/rng/budget.json` (`warmup_frames` 400, so the statistics are finished):

| Check | Kind | Labels | Limit | Basis |
|---|---|---|---|---|
| `rng_next` | `profile` | `rng_next` → `rng_next_end` | `min_cycles` = `max_cycles` = 30 (the estimate was 45) | measured |
| statistics finished | `memory` | `spike_done` | equals 1 | requirement |
| period | `memory` | `spike_period`, size 2 | equals 65535 | requirement |
| every byte value 255–257 times | `memory` ×2 | `spike_hist_min`, `spike_hist_max` | min 255; max 257 | requirement |
| low 5 bits spread in every 256 calls | `memory` ×2 | `spike_low5_min`, `spike_low5_max` | min 2; max 20 | estimate (the limits are a first guess: report the measured pair) |
| zero seed handled | `memory` | `spike_zero_ok` | equals 1 | requirement |

As built, `budget.json` has two more things than the table: a `no late chain entries` check, and the
two low-5-bit checks are `equals` 0 and `equals` 21 (the measured pair, basis `measured`) instead of
min 2 and max 20, which the generator does not meet. See below: this needs the Technical Director's
re-baseline.

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
does now), or replace the statistic with one a good generator passes and a bad one fails (for
example ones per block for each bit within 96–160, measured 103–157).
