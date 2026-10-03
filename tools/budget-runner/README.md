# budget-runner

Builds every `tests/**/budget.json` spike, runs it in headless VICE and checks measured cycle counts
against the budgets. The full schema, check kinds and output are in
[engine/README.md](../../engine/README.md#budget-files); this page covers use and the premise report.

```
make test                                  # every spike (make test ARGS=swarm_budget for one)
uv run budget-runner --no-build -v swarm_budget   # -v / --premise: show each profile check's premise
make test-tools                            # the unit tests (no VICE)
```

## The premise of a profile check

A profile limit is only true *where on the screen the routine runs* (badlines, sprite fetches) and
with *no IRQ inside it* (an IRQ splits the routine into two pieces, each meeting a badline). For every
pass of a `profile` / `profile_excl_irq` check the runner records the raster line and cycle the pass
started and ended on, and the number of IRQs dispatched inside it (hits on `irq_dispatch` between the
start and the end; a build without that label gets no IRQ count for a plain `profile`).

With `-v`, one line under each profile result:

```
swarm_budget  stars_update  max 57 / budget 60  PASS  (measured)
    premise: start L27 c49 .. L28 c8; end L28 c42 .. L29 c1; IRQs inside a pass: 0: 300 (max 57)
swarm_budget  player_update  max 302 / budget 440  PASS  (estimate)
    premise: start L42 c35 .. L77 c26; end L44 c1 .. L85 c38; IRQs inside a pass: 0: 589 (max 302), 1: 11 (max 229)
```

`start L27 c49 .. L28 c8` is the earliest and latest start seen; `1: 11 (max 229)` means 11 passes had
one IRQ inside and the dearest of them cost 229. Optional limits in a check enforce a premise (whole
numbers; each is its own part of the result and fails like `max_cycles`):

| Field | Fails if |
|---|---|
| `start_line_min` / `start_line_max` | any pass starts on a line below / above it |
| `end_line_max` | any pass ends on a line above it |
| `irqs_inside_max` | any pass has more IRQs inside it (needs `irq_dispatch` in the build) |

A check that sets a limit prints its premise line without `-v`, so an enforced premise is always
visible. Fixture showing all of it on the swarm spike (not part of `make test`):
`uv run budget-runner --no-build -v tools/budget-runner/tests/fixtures/swarm_premise.json`.
The passes are traced one checkpoint stop at a time, the method of
`tests/games/swarm/stage5_longrun_fails.py`.

Cost: the `profile_excl_irq` checks already stop at every IRQ dispatch, so they cost nothing more
(only bookkeeping). A plain `profile` check now also stops at each `irq_dispatch`. Measured on
`make test ARGS=swarm_budget` (2 plain checks of 600 samples, the rest unchanged): 166 s before,
175 s after, about 5%.
