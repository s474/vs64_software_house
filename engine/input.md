# Joystick input: `engine/input.asm`

Design contract for M4 (Technical Director, 2026-10-01). Status: **implemented and measured**
(raster-engineer, M4 stage 1, 2026-10-02): `engine/input.asm`, spike `tests/engine/input/`, 3 checks
in `make test`, 17 joystick cases in `tests/engine/input/check.py` (all pass, DEBUG and release).
The costs below are measured; the API is as designed. Conventions (figures marked **measured** / *estimate*, budget
files, spikes) are [engine/README.md](README.md)'s.

## Purpose

Read the joystick in **port 2** once a frame and give the game the stick's state and which
buttons and directions were newly pressed this frame. Swarm needs: left, right and fire held
(movement, auto-fire), and fire newly pressed (start a game, skip the game-over screen, so a held
button doesn't carry from one screen into the next).

Out of scope for M4: port 1, the keyboard, paddles, a second player.

## API

```
// Set up CIA 1 for reading port 2 and clear the state. Call once, before irq_init or after.
// In: nothing   Out: zp_joy = zp_joy_pressed = 0   Uses: A
input_init:

// Sample the joystick. Main loop, once per frame, first thing after irq_wait_frame.
// In:  nothing
// Out: zp_joy = the stick now; zp_joy_pressed = bits that are 1 now and were 0 at the last call;
//      A = zp_joy
// Uses: A
// Cost: the whole call is 40 cycles (measured, no DMA): the caller's jsr 6 + 28 from input_read
//       to input_read_end + rts 6. The profile check's span is the 28
input_read:
```

Bits, **active high** (1 = pressed), in both bytes:

| Constant | Value | |
|---|---|---|
| `JOY_UP` | `$01` | |
| `JOY_DOWN` | `$02` | |
| `JOY_LEFT` | `$04` | |
| `JOY_RIGHT` | `$08` | |
| `JOY_FIRE` | `$10` | |

Bits 5–7 are always 0. The order is the port's own (and `vice_joystick`'s), so the routine is an
invert and a mask.

- **Debounce: none.** The port is sampled once per frame (20 ms), and a state has to be seen in
  one sample to count. That a real switch's bounce is shorter than a frame is *unverified* (no real
  hardware in M4); in VICE there is no bounce.
- **Edge detection** is `zp_joy_pressed`. A game that polls less than once a frame, or calls
  `input_read` twice in a frame, loses edges: once a frame, always.
- Left and right together (impossible on a real stick, possible in an emulator) are reported as
  they are; the game decides.

**Rules for a game** (from the implementation, raster-engineer's report, M4 stage 1):

1. Call `input_read` **exactly once a frame, straight after `irq_wait_frame`**. Twice in a frame
   loses edges; later in the frame adds up to a frame of lag and moves the call into the display's DMA.
2. **No IRQ handler reads `zp_joy_pressed`** (or writes either byte). Inside `input_read` it holds
   scratch, not the edges, for 15 cycles (*counted* by the raster-engineer from the routine), and an
   IRQ can land there. A handler that needs the stick gets it from the main loop.
3. **Nothing else writes `$DC00` or `$DC02`.**
4. **The keyboard can't be scanned after `input_init`** (`$DC02` = `$00`). A game that wants keys
   as well needs a new contract, not a second write to `$DC02`.

## Hardware it owns

`$DC00` (CIA 1 port A, read) and `$DC02` (its direction register), which `input_init` sets to
`$00` (all inputs) so the keyboard-scan value left in the port can't mask the stick. That this is
enough is **measured** (`tests/engine/input/check.py`, the `ddr` cases, 2026-10-02): with `$DC02=$00`
an output latch of `$00` changes nothing. That it's needed is conditional, also **measured**: with
`$DC02=$FF` and the latch `$00` an idle stick reads `$1F`, but with the latch at `$7F` (what the
KERNAL's scan leaves at rest, and what a program started with `RUN` inherits) the stick reads
correctly even without the write. So the write protects against a latch with a 0 in bits 0–4,
not against a normal BASIC start. With `$DC02=$00` the keyboard can't be scanned. Nothing else may write `$DC00`
or `$DC02`. The module never touches `$DC0D` (the IRQ framework's).

## Data the game provides

None.

## Zero page

| Label | Bytes | Owner | Purpose |
|---|---|---|---|
| `zp_joy` | 1 | Main loop | The stick this frame |
| `zp_joy_pressed` | 1 | Main loop | Newly pressed this frame |

Not read or written by any IRQ. `input.asm` checks both labels are in zero page (`.errorif`).

## Cycle budget

Two spans, as everywhere in the engine ([README](README.md#which-span-a-figure-is)): the **profile
span** is what `make test` measures, from the routine's label to its `_end` label, which is on the
`rts`, so the `rts` isn't in it; the **whole call** adds the caller's `jsr` (6) and the `rts` (6),
and is the figure a game puts in its frame budget.

| Routine | Profile span | Whole call | Basis |
|---|---|---|---|
| `input_read` → `input_read_end` | **28** raster cycles, locked (`min_cycles` = `max_cycles`) | **40** | **measured** 28 in every pass (`make test`, and `vice_profile` over 50 passes, 2026-10-02), equal to the instruction count. The spike calls it on lines 17–18 (top border, no DMA, the frame's IRQ already over). The design estimate was 40 for the routine with its `rts` (measured like for like: 34) |
| `input_init` | not budgeted (called once) | 16 + `rts` 6 + `jsr` 6 = 28 | counted |

Size: 32 bytes (`input_init` 10, `input_read` 22), **measured** (estimate was 60).

In Swarm's frame budget the row is **40**, the whole call with no DMA allowance: called straight
after `irq_wait_frame` it runs in the top border before any sprite's DMA
([memory-map.md](../docs/games/swarm/memory-map.md#frame-budget)).

## Spike: `tests/engine/input/`

A screen showing the five bits as characters, a counter of fire presses, and a sprite or
character that moves with the stick. Chain: entry 0 only, in the top border (no multiplexer).
The main loop calls `input_read` straight after `irq_wait_frame`.

It must demonstrate:

1. Each of the five inputs, driven with `vice_joystick` on port 2, sets its own bit and no other;
   releasing clears it. Port 1 input changes nothing.
2. `zp_joy_pressed` has a bit set for **exactly one frame** per press, however long the button is
   held: hold fire for 50 frames, `spike_fire_presses` = 1; press 10 times, 10.
3. It works after `irq_init` (`$01=$35`, CIA interrupts off) and after a normal BASIC start (the
   KERNAL's keyboard scan has run).
4. The measured cost of `input_read`, in the routine header and here.

A driver script (`tests/engine/input/check.py`, in the style of `tests/engine/multiplexer/soak.py`)
does 1–3 through the VICE monitor's joystick control and prints PASS/FAIL per case: `make test`
can't press buttons, so those are run by hand and by QA.

`tests/engine/input/budget.json` (the raster-engineer creates it with these limits; the Technical
Director re-baselines after measurement):

| Check | Kind | Labels | Limit | Basis |
|---|---|---|---|---|
| `input_read` | `profile` | `input_read` → `input_read_end` | `min_cycles` = `max_cycles` = 28 (the estimate was 40) | measured |
| no late chain entries | `memory` | `irq_late_count` | equals 0 after 500 frames | requirement |
| idle stick reads as nothing pressed | `memory` | `zp_joy` | equals 0 after 0 frames | requirement |

### Results (raster-engineer, 2026-10-02)

`uv run --package budget-runner python tests/engine/input/check.py` (about 2 s; the script's header
lists the cases). All 17 pass in the DEBUG and the release build:

| Spike item | Cases | Result |
|---|---|---|
| 1 | `single` ×5, `combos` (13, with left+right, up+down and all five), `port1`, `idle` | Each input sets its own bit and no other; release clears it; port 1 changes nothing. Idle raw `$DC00` is `$1F` under VICE's I/O simulation device (bits 5–7 low), so the mask is exercised |
| 2 | `hold-50`, `press-10`, `edge-add` | Fire held 50 frames: one edge, `spike_fire_presses` +1. Ten one-frame presses: +10. Left added while fire is held: `zp_joy_pressed` = left only |
| 3 | `start`, `ddr` ×4 | Started with `RUN`, then `irq_init` (`$01=$35`): works. The `$DC02` findings are under [Hardware it owns](#hardware-it-owns) |
| 4 | `make test ARGS=input` | `input_read` 28, every pass |

Two joystick devices are in play: `check.py` and the MCP server's `vice_joystick` attach VICE's I/O
simulation device (idle raw `$DC00` = `$1F`), while `make test` starts VICE with the default
joystick device (idle raw `$7F`, raster-engineer's report). `input_read` masks bits 5–7, so
`zp_joy` is 0 in both.

Not covered: `input_init` called *after* `irq_init` (the spike calls it before; the routine touches
nothing `irq_init` does), and switch bounce on real hardware.
