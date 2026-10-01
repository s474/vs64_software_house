# Random numbers: `engine/rng.asm`

Design contract for M4 (Technical Director, 2026-10-01). Status: **not implemented**. The
raster-engineer builds it in M4 stage 1 with the spike below. Conventions are
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
// Cost: estimate 36 CPU cycles + jsr/rts 12
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
| `rng_next` → `rng_next_end` (its `rts`) | **45** raster cycles, a lock once measured | *estimate*: a 16-bit xorshift is about 30–36 cycles in zero page, + `rts` 6. Measured in the border, so no DMA |
| `rng_seed` | not budgeted (called once a game) | |
| Size | 40 bytes | *estimate* |

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
| `rng_next` | `profile` | `rng_next` → `rng_next_end` | `max_cycles` 45 (then locked to the measured figure) | estimate |
| statistics finished | `memory` | `spike_done` | equals 1 | requirement |
| period | `memory` | `spike_period`, size 2 | equals 65535 | requirement |
| every byte value 255–257 times | `memory` ×2 | `spike_hist_min`, `spike_hist_max` | min 255; max 257 | requirement |
| low 5 bits spread in every 256 calls | `memory` ×2 | `spike_low5_min`, `spike_low5_max` | min 2; max 20 | estimate (the limits are a first guess: report the measured pair) |
| zero seed handled | `memory` | `spike_zero_ok` | equals 1 | requirement |
