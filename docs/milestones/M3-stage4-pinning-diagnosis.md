# M3 stage 4: pinning and the free-CPU promise

A record of the raster-engineer's diagnosis (2026-10-01) and the decision taken on it. It explains
why the stage 4 budgets differ from stage 3's, and what multiplexer v2 has to fix.

**Reproduce the numbers:** `tests/engine/multiplexer/idle_breakdown.py` (the header says how to run
it; 6,000 frames takes about a minute) and `tests/engine/multiplexer/measure_pin.py`.

## Summary

- Pinning works as designed. Over 20,000 frames `mux_pin_drop_count`, `mux_pin_excess_count`,
  `mux_late_count`, `irq_late_count` and `spike_overrun_count` are all 0, and `mux_max_age` is 4
  (its limit).
- Normal frames are unaffected: `mux_update` averages 4,254 raster cycles in the frames without
  overflow (limit 5,000).
- The **free-CPU promise** ([M3 brief](M3-engine-basics.md), rule 3: `spike_idle_min` × 16 ≥ 5,300)
  **fails**, but only in frames where two things coincide: a pinned sprite inside a crowd, and the
  spike's deliberate sort-reversal stress at minimum row spacing.
- `mux_update`'s maximum is also over its 11,400 limit on long runs. `make test` doesn't see it,
  because it samples 600 passes.

## Free CPU, same stage 4 motion

6,000 frames after 100 warm-up frames, unless stated. The three 6,000-frame runs were paired
frame for frame, with identical motion state.

| Build | `spike_idle_min` × 16 | Frames < 5,300 | Worst non-stress frame | `mux_update` max |
|---|---|---|---|---|
| Stage 3 engine, stage 4 spike unchanged (it ignores flag bit 7) | 5,440 | 0 | 5,792 | 11,228 |
| Stage 4 engine, pin flags cleared | 6,192 | 0 | 6,672 | 10,391 |
| Stage 4 engine, 4 pinned | **4,736** (misses by 564) | 3 | 5,840 | 11,856 |
| Stage 4 engine, 4 pinned, 20,000 frames | **4,496** (misses by 804) | 8 | not measured | 12,330 |

- The worst case keeps falling with run length: 5,328 over 900 frames, 4,736 over 6,000, 4,496
  over 20,000. Nothing longer has been run.
- With nothing pinned, stage 4's slow path is faster than stage 3's: 752 more cycles free in the worst frame.
- Every miss is a stress frame: 3 of 3 over 6,000 frames and 8 of 8 over 20,000, all at row
  spacing 11–15 on the reversal step. 260 of the 6,000 frames are stress frames, so 3 of those 260 miss.
- Outside the stress, the worst frame with pinning keeps 5,840: a margin of 540.

## The worst frame (frame 2529 of the 6,000-frame run)

Row spacing 11, the reversal step, player Y 31. Raster cycles. The segments add up to the frame.

| Segment | 4 pinned | Same frame, pins cleared | Difference |
|---|---|---|---|
| Spike motion (`spike_move`) | 2,267 | 2,268 | −1 |
| `mux_sort` (plus 15 head) | 2,211 | 2,211 | 0 |
| `mux_select` fast walk | 1,171 | 1,171 | 0 |
| Slow setup (`mux_fill_kept`) | 244 | 252 | −8 |
| **Pinned pass** | 325 | 0 | +325 |
| Slow walk and unpinned fail decisions | 3,620 | 3,325 | +295 |
| **Pinned fail decision** | 244 | 0 | +244 |
| Fair evictions (8 against 7) | 2,652 | 1,925 | +727 |
| **Pinned eviction** (1) | 302 | 0 | +302 |
| `mux_build` before rebuild | 33 | 33 | 0 |
| **Restore saved ages** | 103 | 9 | +94 |
| Rebuild and build tail | 878 | 642 | +236 |
| Tail (`rts`, spike statistics) | 57 | 62 | −5 |
| IRQ time | 763 | 763 | 0 |
| Idle raster span | 4,795 | 6,985 | −2,190 |
| **Free (iterations × 16)** | **4,736** | **6,768** | **−2,032** |

`mux_update` totals 11,783 in this frame.

**Where the shortfall comes from:**

- **Pinning: 2,190 raster cycles.** 974 is pinning's own code (the pass, the fail decision, the
  eviction, the restore). The other 1,258 is knock-on: one extra fair eviction, a longer slow walk,
  and a rebuild that starts earlier.
- **Sort stress: about 1,600.** The sort took 2,196 against a median of 591.
- **Other motion: about 190.** `spike_move` took 2,267 against a median of 2,073.
- Of the two excesses, pinning is about 58% and the stress about 42%. Removing either clears the
  miss: no pinning gives 6,768, and a normal sort gives about 6,340.

## Options considered (estimates, none implemented)

| Option | Estimated saving in the worst frame | Catch |
|---|---|---|
| Cap all evictions per `mux_update` at about 5, not only the pinned ones | 1,000–1,300 | The only engine change that covers the 804 alone. Overloaded rows flicker more, and `mux_max_age` is already at its limit of 4 |
| Keep the pinned list between frames, rebuilding it only when flags change | 200–230 | Not enough alone |
| Rebuild only changed slots, or cheapen the per-slot shift and re-simulation in a removal | 200–400 | Not enough alone, and touches the slow path's core |
| Scope the promise to non-stress frames | About 1,600 | Changes the test, not the engine. Rule 3 already lets the worst case stay expensive |

## Decision (Simon, 2026-10-01): accept for v1

- **v1's promise is scoped:** ≥ 5,300 cycles free in every frame **except** a mass sort reversal with
  pinned sprites in a crowd, where free CPU can drop to about 4,500. The effect of a miss is one
  repeated frame of sprites (a one-frame stutter), never corruption.
- **Why not fix it in v1:** the fix that covers it (capping evictions) makes overloaded rows flicker
  more, which is more visible than a rare one-frame stutter, and it is work on code that v2 replaces.
- **Follow-ups:**
  - Technical Director: scope the free-CPU check to non-stress frames, with a lower floor for stress
    frames so a regression still shows; re-baseline `mux_update`'s maximum from the 20,000-frame run;
    record the scoped promise in `engine/README.md`.
  - Raster-engineer: finish stage 4 (stage bump, `make test` and `--strict`, screenshots, commit).
- **Multiplexer v2 requirement** (added to the [M3 brief](M3-engine-basics.md), rule 3): the free-CPU
  promise holds in **every** frame, including a mass sort reversal with 4 pinned sprites in a crowd,
  over a 20,000-frame run.

## Technical Director's re-baseline (2026-10-01): longer runs

Long traces on the stage 4 engine, up to 919,800 frames. They correct two statements above.

| Figure | 20,000 frames | 300,000 frames | 919,800 frames |
|---|---|---|---|
| Free CPU, stress frames | 4,496 | 4,496 | 4,480 |
| Free CPU, non-stress frames | 5,728 | not recorded | **5,344** (0 frames below 5,300) |

- **The worst case levels off:** it doesn't keep falling. It's 4,496 to 300,000 frames and 4,480 at 919,800.
- **The worst non-stress frame is lower than first measured:** 5,840 over 6,000 frames, 5,728 over
  20,000, and 5,344 over 919,800. So the scoped promise holds in the longest run by **44 cycles**.
  The two lowest non-stress frames are where pinned sprite 1 jumps 219 lines as its sweep turns,
  inside a crowd.
- **How often a stress frame misses 5,300:** 451 of 919,800 frames, about 1 in 2,040.
  `spike_overrun_count` stayed 0.
- **"Stress frame" defined:** `spike_move` left `spike_damp` = 1 and `spike_amp` = 2, 3, 4 or 5: the
  4 frames in every 48 that re-sort after each reversal.
- **Checks from stage 4:** `spike_idle_min_normal` × 16 ≥ 5,300 and `spike_idle_min_stress` × 16 ≥ 4,250
  (4,480 less 5%). The single `spike_idle_min` check is retired.
- **Limits re-baselined** from a 20,000-pass trace (max + ~5%): `mux_update` 13,000 (was 11,400),
  `mux_select` 9,400, `mux_build` 3,100, `mux_irq_zone` 2,950, all IRQ time per frame 4,000.

The long-run scripts behind these figures were not kept in the repo, so the 300,000- and
919,800-frame figures can't be reproduced as they stand. `make test-long` at ×34 covers about
800,000 frames for the free-CPU checks.

## Sign-off long run (2026-10-01): `make test-long`, ×34

The reproducible long run, on the committed stage 4 engine (2b7aed5 plus the README tidy-up):
**34/34 checks pass** across all four spikes.

| Check | Reading | Requirement |
|---|---|---|
| Free CPU, non-stress frames (`spike_idle_min_normal` × 16) | **5,328** | ≥ 5,300 (margin 28) |
| Free CPU, stress frames (`spike_idle_min_stress` × 16) | **4,448** | ≥ 4,250 (the Technical Director expected ≥ 4,464: one idle iteration lower) |
| `mux_update`, all frames | max 12,339 | ≤ 13,000 |
| `mux_update` fast path, frames with no overflow | max 6,945, average 4,281 | ≤ 7,400, average ≤ 5,000 |
| `mux_select` / `mux_build` / `mux_sort` | max 8,281 / 2,567 / 2,957 | ≤ 9,400 / 3,100 / 3,550 |
| All IRQ time per frame | max 3,725 | ≤ 4,000 |
| `mux_max_age` | 4 | ≤ 4 |
| `mux_pin_drop_count`, `mux_pin_excess_count`, `mux_late_count`, `irq_late_count`, `spike_overrun_count` | 0 | 0 |
| IRQ framework locks (`irq_chain`), `mux_irq_top` 381 and 393, `mux_irq_park` 80 | unchanged | locked |

QA (2026-10-01): the 10,000-frame soak (`tests/engine/multiplexer/soak.py`) and the position and
attribute check (`tests/engine/multiplexer/positions.py`: 21,714 sprite-frames, 0 mismatches,
4,908 of them at X > 255) both pass.

## A debug counter changed meaning

`mux_pin_excess_count` now counts only frames that overflowed with more than 4 sprites flagged as
pinned. Frames where everything fits never count. Counting in every frame would cost about 170
cycles in DEBUG builds and move the fast-path figures. It's documented in `engine/README.md`
("Pinned sprites", "Debug counters") and in the counter's comment. The QA soak step still works,
because about 65% of the spike's frames overflow (12,984 of 20,000).
