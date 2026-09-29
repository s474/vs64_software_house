# Engine

Shared modules that every game in the studio builds on. This page is the **design contract**
for M3 ([brief](../docs/milestones/M3-engine-basics.md)): the APIs, zero page, raster timeline
and cycle budgets that the raster-engineer implements and `make test` enforces. The Technical
Director owns it. If the design can't be met, report with numbers and change this page before
the code, not after.

| Module | File | Status |
|---|---|---|
| IRQ framework | `engine/irq.asm` | **Implemented** (M3 stage 1). Costs measured in `tests/engine/irq_chain` |
| Sprite multiplexer v1 | `engine/multiplexer.asm` | Designed (this page). Not implemented |

**How to read the numbers.** Every figure is marked:

- **measured**: from a probe, with the reference doc that records it.
- *estimate*: a design figure nobody has measured yet. The full list, and who measures what,
  is in [Estimates to measure in M3](#estimates-to-measure-in-m3). When a figure is measured,
  replace it here, in the routine header, and in the spike's `budget.json`.

---

## Using the engine in a game

```
BasicUpstart2(start)
#import "zp.asm"                        // the game's zero page, including the engine's bytes
.const MUX_SCREEN = $0400               // only if you use the multiplexer (see below)
.const MUX_Y_MAX  = $f9
#import "engine/irq.asm"
#import "engine/multiplexer.asm"        // optional

        IrqChainBegin()
        IrqNormal(MUX_TOP_LINE, mux_irq_top)    // entry 0: the frame entry
        IrqNormal($fb, game_irq_bottom)         // entry 1
        IrqChainEnd()

start:  jsr mux_init                    // before irq_init: entry 0 may fire straight away
        jsr irq_init                    // machine setup; returns with the chain running
main:   jsr irq_wait_frame
        jsr game_update                 // writes mux_x_lo / mux_y / ... for this frame
        jsr mux_update
        jmp main
```

What a game must provide:

| Item | Where | Needed by |
|---|---|---|
| The engine's zero-page labels (`zp_irq_*`, `zp_mux_*`) and `zp_tmp0`–`zp_tmp3` | `games/<title>/src/zp.asm` | [Zero page](#zero-page) |
| A chain: `IrqChainBegin()`, 1–16 entries, `IrqChainEnd()` | Game source | IRQ framework |
| Handlers that end in `IrqDone()` | Game source | IRQ framework |
| `MUX_SCREEN`: the screen whose last 8 bytes are the sprite pointers | `.const` before the import | Multiplexer |
| `MUX_Y_MAX`: largest sprite Y the multiplexer shows (≤ `$F9`) | `.const` before the import | Multiplexer |
| Entry 0 of the chain is `mux_irq_top` at `MUX_TOP_LINE` | Chain | Multiplexer |

Engine modules emit their code and tables where they're imported, so the game places them
with `* = ... "Engine"` like any other block and records them in its memory map.

---

## IRQ framework: `engine/irq.asm`

### Ownership

Only this module writes `$FFFE/$FFFF`, `$FFFA/$FFFB`, `$D012`, `$D019`, `$D01A`, `$DC0D`,
`$DD0D`, and bit 7 of `$D011` (raster compare bit 8). Game code and other engine modules
ask for IRQ time through the chain and the macros below, never by touching these
([coding standards](../docs/standards/coding-standards.md#irq-ownership)).

Rules this imposes on the rest of the game:

- **Chain lines are 0–255.** The compare bit 8 is always 0, so every game write to `$D011`
  (YSCROLL, DEN, bitmap mode) keeps **bit 7 clear**: `and #$7f` before `sta $d011`. Lines
  256–311 (the bottom of the lower border) can still be *run through*, just not triggered on.
- **`$01` stays `$35` whenever interrupts are enabled.** The handlers assume I/O is in and
  don't save `$01` (it would cost 12 cycles per IRQ). Anything that needs `$01=$34`
  (writing RAM under I/O) runs with interrupts off, at init time or with no IRQ due.
- **No long `sei` sections** in the main loop. Every cycle with `I` set delays whichever IRQ
  is due; the multiplexer's zone IRQs have only a few lines of slack.
- The main loop may use decimal mode (BCD scores): the dispatcher clears `D`.

### Machine setup: `irq_init`

```
// Set up the machine and start the raster chain at entry 0.
// In:  nothing (the chain is declared with IrqChainBegin/IrqChainEnd)
// Out: interrupts enabled, chain running
// Uses: A, X
irq_init:
```

It replaces the setup every program has copied from `hello`: `sei`; CIA 1 and CIA 2
interrupts off (`$7F` to `$DC0D`/`$DD0D`, then read both to clear anything pending);
`$01=$35`; `$FFFA/$FFFB` → `irq_nmi` (an `rti`); `$FFFE/$FFFF` → `irq_dispatch`; `$D011`
bit 7 cleared; `$D012` and the dispatch target set for entry 0; `$D01A=$01` (raster only);
all VIC IRQ latches acknowledged (`$FF` to `$D019`); `cli`. It doesn't touch the stack pointer,
the VIC bank, `$D018` or anything else on the screen.

### Declaring the chain

```
        IrqChainBegin()
        IrqNormal(line, handler)        // handler starts on `line`, within the normal jitter
        IrqStable(line, handler)        // handler starts on `line` at the SAME cycle every frame
        ...
        IrqChainEnd()
```

- 1–16 entries (`IRQ_MAX_ENTRIES = 16`), in **ascending line order**, run in order every frame.
  After the last, the chain wraps to entry 0.
- **Entry 0 is the frame entry**: the framework increments `zp_irq_frame` just before its
  handler runs. `irq_wait_frame` returns just after that.
- The macros emit, where `IrqChainEnd()` is: the RAM table `irq_lines` (one byte per entry,
  the trigger line: `line − 2` for a stable entry), `irq_next` (the following entry's index),
  the dispatch-target tables `irq_target_lo`/`irq_target_hi`, the handler tables
  `irq_handler_lo`/`irq_handler_hi` (read by the stable stage 2), all sized to the chain
  (6 bytes per entry, kept in one page), and the entry-0 tick stub. The double-IRQ stages are
  common code in `irq.asm`.
  They assemble-time check (`.errorif`) that there are 1–16 entries, lines are ascending and
  in 0–255, and a stable entry's line is at least 2.
- `irq_lines` may be rewritten from the main loop (one byte, atomic) to move an entry. The
  new line takes effect the next time the chain programs that entry, and must keep the
  lines ascending with enough room for each handler. Handlers can't be changed at run time
  (use `IrqRearm` for dynamic work).

### Dispatch model

`$FFFE/$FFFF` point at `irq_dispatch` permanently (except inside a stable entry's double IRQ).
The per-entry "vector switching" is the dispatcher's self-modified `jmp` target, set from
`irq_target_lo/hi` by the exit code. This costs 3 cycles more than switching `$FFFE` itself,
and buys two things: every IRQ enters through **one address**, which lets the budget runner
exclude IRQ time when it measures main-loop code, and the vector can never be left pointing
at a half-written address.

```mermaid
flowchart LR
    V["IRQ taken<br/>7-cycle sequence<br/>via $FFFE"] --> D["irq_dispatch<br/>save A, X, Y (self-mod)<br/>cld, jmp target"]
    D --> H["handler work"]
    D -.->|"entry 0"| T["tick stub<br/>inc zp_irq_frame"]
    T --> H
    D -.->|"stable entry"| S["stable stub<br/>double IRQ"]
    S --> H
    H -->|"IrqDone()"| E["irq_exit<br/>next entry: $D012, target<br/>ack $D019, late check"]
    H -->|"IrqRearm(handler)<br/>A = line"| R["irq_rearm<br/>$D012 = A, target = handler<br/>ack $D019, late check"]
    E --> X["irq_exit_rti<br/>restore A, X, Y; rti"]
    R --> X
    E -.->|"already past the line"| L["run that handler now<br/>(no rti, no re-save)"]
    R -.->|"already past the line"| L
```

### Handler conventions

On entry to a handler:

| State | Guarantee |
|---|---|
| A, X, Y | Free to use. The framework saved them and restores them |
| `D` flag | Clear |
| `I` flag | Set. **Never `cli`** in a handler (only the framework's stable stage does) |
| `$01` | `$35` (given the rule above) |
| Stack | Free to use; the IRQ itself uses 3 bytes (6 during a stable entry) |
| `$D019` | Not yet acknowledged. **Don't touch it**: the exit does it |

A handler ends with exactly one of:

| Macro | Expands to | Effect |
|---|---|---|
| `IrqDone()` | `jmp irq_exit` | Advance to the next chain entry, acknowledge, restore, `rti` |
| `IrqRearm(handler)` | `ldx #<handler / ldy #>handler / jmp irq_rearm` | With the line in **A**: fire `handler` at that line, *without* advancing the chain. The multiplexer uses this for its zone IRQs |

`irq_exit` and `irq_rearm` write `$D012` and the target **first**, then acknowledge `$D019`,
then do the **late check**: if the raster is already on or past the new line, the IRQ would
not fire until next frame, so they acknowledge again (clearing a latch that may have happened
between the first ack and the check) and jump straight to the next handler with the registers
still saved. The next handler runs late, but it runs exactly once, and the chain stays in step.
The wrap to entry 0 is exempt from the check. Each late run increments `irq_late_count`
(1 byte, saturating at 255, DEBUG builds only), and `make test` requires it to stay 0 in every
spike: a late run means a budget was blown.

The last entry's handler must finish before line 311 ends, or entry 0 misses a frame (not
detected in v1).

### Stable handlers

`IrqStable(line, handler)` makes `handler`'s first instruction run on `line` at the same
raster cycle every frame: `IRQ_STABLE_CYCLE` = **cycle 6** (**measured**: `irq_chain` spike,
1,000 of 1,000 frames on cycle 6, with stage 1 arriving on 8 different cycles and stage 2 on
2, via `tests/engine/irq_chain/measure.py`). It uses the double IRQ from
[raster-interrupts.md](../docs/reference/raster-interrupts.md#jitter-and-stable-rasters): the chain
triggers at `line − 2`; the stable stub (label `irq_stable_begin`, common code) points
`$FFFE` at stage 2, sets `$D012` to the next line, acknowledges, `cli`s and runs `NOP`s;
stage 2 arrives with at most 1 cycle of jitter, discards its own 3-byte interrupt frame,
restores `$FFFE` to `irq_dispatch`, and removes the last cycle with a `$D012` compare
across the line change. Then it jumps to the handler, which exits normally.

Implementation notes (as built):

- Stage 1 and stage 2 switch only the **low byte** of `$FFFE`: `irq_dispatch` and
  `irq_stable_stage2` are assembled into one page (asserted). Stage 2 finds the handler
  through `irq_handler_lo/hi` indexed by `zp_irq_idx`, in the time it has to burn anyway.
- Stage 2 doesn't acknowledge its own latch: `I` is set until the handler's `irq_exit`, which
  acknowledges after writing `$D012`.
- Stage 2's wait (`IRQ_STABLE_DELAY`, `IRQ_STABLE_PAD` in `irq.asm`) was set by measurement.
  Changing any instruction in stage 2 needs the spread re-measured.
- If stage 2's IRQ never arrives (stage 1 started too late, e.g. after a long `sei` in the main
  loop), stage 1's `NOP` slide falls through to a fallback that runs the handler at once,
  unstable, and counts a late run. Stage 1 reaches `cli` 22 cycles after it starts, so it must
  start by about cycle 40 of `line − 2` (*counted*; it measured 26–33 with the worst main loop).

Constraints:

- Lines `line − 2` to `line` must **not be badlines** (the `NOP` slide needs the bus), and the
  sprite DMA on them must be the same every frame. Put stable entries in the border or in a
  gap between badlines ($AF–$B1 is fine with the default YSCROLL=3: badlines are at 51 + 8n,
  measured, [vic-ii-timing.md](../docs/reference/vic-ii-timing.md#badlines)), and never inside
  the multiplexer's region.
- Its exit may run into a badline: that only lengthens the entry's span
  ([DMA inside an IRQ](#dma-inside-an-irq)), it doesn't affect stability.
- Cost: 99–106 cycles more than a normal entry (**measured**, see [Costs](#irq-framework-costs)).
- An NMI (RESTORE key) during the stage costs one frame of stability. Accepted.

### Jitter guarantee

A normal handler starts on its line within **7 cycles** of its earliest possible start
(**measured**: spread exactly 7 on every entry of the `irq_chain` spike over 1,000 frames, with a
worst-case main loop that includes taken branches right before 7-cycle `inc abs,x`; the IRQ
sequence starts on cycle 2 of the trigger line at the earliest, so a normal handler's first
instruction runs on cycle **26–33**, entry 0's on **34–41**;
[raster-interrupts.md](../docs/reference/raster-interrupts.md#jitter-and-stable-rasters)), **provided no
badline or sprite DMA falls between the trigger and the handler**. DMA delays it by up to the
DMA on that line: 43 cycles for a badline, 81 for a badline with sprites 0–7 active around it
(**measured**, [vic-ii-timing.md](../docs/reference/vic-ii-timing.md#badline-and-sprites-on-the-same-line)).
Trigger normal entries on non-badlines when their start time matters.

### DMA inside an IRQ

The framework costs below are raster time on lines with no DMA. A badline (43 cycles,
**measured**) or sprite DMA anywhere in an IRQ's span, from the trigger to the `rti`, lengthens
that span by the cycles stolen. A normal handler starts on cycle 26–33, so with W cycles of work
its `irq_exit` starts at about cycle 36 + W and, for any small handler, runs into the next line
(**measured**: `irq_exit` 102–103 when the next lines were badlines 107 and 179, the `irq_chain`
spike's first layout at $6A and $B2, against 60 everywhere else).

What that does and doesn't cost:

- **No CPU time.** The VIC takes those cycles whatever code is running: if the IRQ didn't span
  the badline, the main loop would lose the same 43. The [frame budget](#frame-budget) counts every
  badline and sprite DMA once in its DMA rows, so an IRQ spanning DMA costs the frame nothing
  extra. (Its IRQ rows are raster time, so that DMA is counted twice, on purpose, as margin.)
- **Latency.** Whatever follows the IRQ happens later: the next chain entry can't start before
  this one's `rti`, and the main loop resumes later. This matters where IRQs are packed
  closely, which in practice means the multiplexer's zone IRQs.
- **Measurement.** A `profile` check's max includes any DMA inside the span.

Rules:

1. **Spikes that lock a framework path to its measured cost** (`irq_chain`) place each entry so
   no badline or sprite DMA falls between its trigger and its `rti`. For a small handler that's
   the trigger line and the next one: that's why the spike uses $69 and $B1.
2. **Games don't have to.** Put fixed entries where the effect needs them and budget each
   entry's **raster span**: framework overhead + work + the DMA on the lines it covers (43 per
   badline, up to 81 for a badline with sprites 0–7, **measured**,
   [vic-ii-timing.md](../docs/reference/vic-ii-timing.md#badline-and-sprites-on-the-same-line)).
   A game that scrolls vertically moves its badlines with YSCROLL and couldn't keep them clear
   anyway. Keep DMA out of an entry's span only when its *timing* matters: another entry close
   behind it, or a register write that must land by a given cycle.
3. **Stable entries** keep their hard rule (lines `line − 2` to `line` free of badlines, same
   sprite DMA every frame). Their exit may cross a badline.
4. **Multiplexer budgets** are raster spans in the display area, DMA included by design. Zone IRQs
   can't avoid badlines, and their budgets and scheduling constants must allow for them.

### Frame sync

```
// Wait for the next frame tick (entry 0 has just started).
// In: nothing   Out: A = new zp_irq_frame   Uses: A
irq_wait_frame:
```

`zp_irq_frame` is a free-running 8-bit counter. A game that needs to detect a missed frame
compares it with the value it saw last time (a difference of more than 1 = an overrun).

### IRQ framework costs

**Measured** in the `irq_chain` spike (VICE 3.10 x64sc PAL, 2026-09-29), with
`tests/engine/irq_chain/measure.py` over 1,000 frames and confirmed with `vice_profile`. Raster
cycles, no DMA on the lines involved.

| Part | Cycles | Basis |
|---|---|---|
| IRQ sequence starts (earliest) | cycle 2 of the trigger line | **measured** (lines 32, 105, 175, 250; line 0 not measured) |
| Interrupt sequence | 7 | [6502-timing.md](../docs/reference/6502-timing.md) (standard figure) |
| Jitter: finishing the interrupted instruction | 0–7 | **measured**, worst-case main loop, all 8 values seen on every entry |
| `irq_dispatch`: 3 self-mod saves (12), `cld` (2), `jmp` (3) | 17 | **measured** (`vice_profile irq_dispatch → spike_h1`: 17 every pass) |
| **Handler starts** after the IRQ is taken | **24** | **measured** (dispatch hit + 17) |
| Frame tick stub, entry 0 only | +8 | **measured** (h0 starts 25 after dispatch) |
| `irq_exit` → `irq_exit_rti` (advance, `$D012`, target, ack, late check, restore) | **60** (58 on the wrap) | **measured**, every pass; equals the instruction count. The budget is locked to it |
| `irq_rearm` → `irq_exit_rti` (`$D012`, target, ack, late check, restore) | 41 | *counted*: 35 to its `jmp irq_restore` + 6 restore. (Was given as 35, which left out the restore.) Measured in M3 stage 2 |
| `rti` + the handler's `jmp irq_exit` | 9 | [6502-timing.md](../docs/reference/6502-timing.md) |
| **Total per normal entry, excluding its work** | **93** (+8 on entry 0) | **measured** parts |
| Stable entry, extra: `irq_stable_begin` → handler | **99–106** (1.7 lines) | **measured** |
| **Total per stable entry, excluding its work** | **192–199** | **measured** parts |
| Total per re-armed IRQ (`IrqRearm`, e.g. a zone IRQ), excluding its work | 78: 7 + 17 + 7 (macro) + 41 + 6 | measured parts + *counted* 41 |
| All four `irq_chain` entries, per frame (runner's IRQ-span definition) | **501–508** | **measured**, 1,000 frames: h0 107 + h1 99 + h2 198–205 + h3 97 |

**Budgets for these are locks, not allowances.** Each path is straight-line code measured
where no DMA touches it, so the figure is exact and repeatable, and
`tests/engine/irq_chain/budget.json` sets each budget *equal* to it. Headroom there could only
hide a regression, and every framework cycle is paid by every IRQ (up to 18 a frame in a
multiplexer game). A change to `irq.asm` that moves one of these figures is re-measured and
re-baselined on purpose. Games get their headroom from the [frame budget](#frame-budget).

**Why `irq_exit` stays at 60.** Reviewed after stage 1: the only removable parts are the raster
bit 8 check (6: it catches a handler overrunning into lines 256–311) and the dispatch-target
write (16: the price of the single-entry dispatcher, a design decision). Both are worth what they
cost. At most one `irq_exit` runs per chain entry; zone IRQs use `irq_rearm` (41).

The exit's 60 cycles: `irq_next` table (10 for index advance), `$D012` (8), target (16), ack (6),
late check against the line (8) and raster bit 8 (6, so a handler that overruns into lines
256–311 is caught too), restore (6).

For comparison, `hello`'s hand-written handlers cost about 50 cycles each with no register
save beyond A, no table and no late check.

### Labels exported for tests

`irq_dispatch`, `irq_exit`, `irq_rearm`, `irq_exit_rti` (the `rti` itself), `irq_stable_begin`,
`irq_nmi`, `irq_late_count`, `irq_lines`. The budget runner depends on these names. Also
emitted: `irq_stable_stage2`, `irq_next`, `irq_target_lo/hi`, `irq_handler_lo/hi`, `irq_tick`,
`IRQ_COUNT`, and the constant `IRQ_STABLE_CYCLE`.

---

## Sprite multiplexer v1: `engine/multiplexer.asm`

24 virtual sprites on the 8 hardware sprites, sorted by Y each frame, with fair flicker
when too many share a row. Decisions from the brief: 24 sprites, flicker rather than drop.

### Constants

| Constant | Value | Set by | Meaning |
|---|---|---|---|
| `MUX_COUNT` | 24 | Engine | Virtual sprites |
| `MUX_OFF` | `$FF` | Engine | Y value that hides a virtual sprite |
| `MUX_TOP_LINE` | `$10` (16) | Engine | Line of `mux_irq_top` (chain entry 0) |
| `MUX_Y_MIN` | `$1E` (30) | Engine | Smallest Y shown. Y=29 is displayed on lines 30–50, all border |
| `MUX_Y_MAX` | ≤ `$F9` (249) | **Game** | Largest Y shown. Y=249 is the last with a visible line (250) |
| `MUX_SCREEN` | e.g. `$0400` | **Game** | Screen whose `+$3F8…$3FF` get the sprite pointers |
| `MUX_FREE_AFTER` | 22 | Engine | A hardware sprite is free to rewrite on line `Y_old + 22`. *Estimate*: display on Y+1 to Y+21 is unmeasured |
| `MUX_IRQ_LINES` | 1 | Engine | Lines from a zone IRQ's trigger to its first write. *Estimate* |
| `MUX_WRITE_LINES` | 1 | Engine | Lines to write one slot, allowing for DMA. *Estimate* |
| `MUX_MAX_PINNED` | 4 | Engine | Most sprites honoured as pinned in one frame (decision, not a measurement) |
| `MUX_PIN_EVICT_MAX` | 8 | Engine | Most evictions pinned sprites may make in one `mux_update`. Bounds the worst case. *Estimate*: set from cost, revisit once measured |

Sprites with Y outside `MUX_Y_MIN`–`MUX_Y_MAX` (including `MUX_OFF`) are not shown and cost
nothing.

### Per-frame data the game writes

Structure of arrays, indexed by virtual sprite 0–23. Written **by the main loop only**, before
it calls `mux_update` in the same frame; nothing reads them until then, so there's no race.

| Array | Bytes | Contents |
|---|---|---|
| `mux_x_lo` | 24 | X bits 0–7 |
| `mux_x_hi` | 24 | X bit 8 in bit 0; other bits 0 |
| `mux_y` | 24 | Y (as the VIC-II register). `MUX_OFF` to hide |
| `mux_ptr` | 24 | Sprite pointer: data at VIC bank base + ptr × 64 |
| `mux_col` | 24 | Colour, bits 0–3 |
| `mux_flags` | 24 | Bit 0: multicolour. Bit 7: **pinned**, never evicted by flicker (at most 4: see [Pinned sprites](#pinned-sprites)). Bits 1–6 reserved, write 0 |

Registers the multiplexer owns (nothing else writes them): `$D000–$D010`, `$D015`, `$D01C`,
`$D027–$D02E`, and `MUX_SCREEN+$3F8…$3FF`. The game owns the shared multicolours
`$D025/$D026` and priority `$D01B`. `$D017` and `$D01D` (Y and X expansion) must be 0: v1
assumes 21-line sprites.

### API

```
// Hide all virtual sprites and reset the multiplexer. Call once, before irq_init.
// In: nothing   Out: nothing   Uses: A, X
mux_init:

// Sort, select and build the next frame's sprites into the back buffer. Main loop, once per
// frame, after writing the arrays above. Doesn't block.
// In:  nothing
// Out: C=0 queued for the next mux_irq_top; C=1 skipped (the previous build hasn't been shown yet)
// Uses: A, X, Y, zp_tmp0-zp_tmp3
// Cost: <= 5,600 cycles (estimate; budget in tests/engine/multiplexer/budget.json)
mux_update:

// Chain entry 0 (IrqNormal(MUX_TOP_LINE, mux_irq_top)). Internal: mux_irq_zone.
mux_irq_top:
```

### Frame flow and double buffering

The IRQs never read what the main loop is writing. `mux_update` writes a **back buffer** of
slot arrays; `mux_irq_top` swaps it in at the top of the next frame, before any sprite is
displayed. Each slot array is 64 bytes: buffer 0 uses indices 0–23 and buffer 1 uses 32–55,
so `zp_mux_front` (0 or 32) is just a base added to the slot index, and the IRQs pay nothing
for the double buffer.

```mermaid
sequenceDiagram
    participant T as mux_irq_top (line $10)
    participant Z as mux_irq_zone (re-armed)
    participant M as Main loop
    T->>T: zp_irq_frame += 1 (framework)
    T-->>M: irq_wait_frame returns
    T->>T: write slots 0-7 of the front buffer
    T->>Z: IrqRearm at slot 8's free line
    M->>M: game logic writes mux_x_lo, mux_y, ...
    Z->>Z: write slots 8+ as each hardware sprite frees
    M->>M: mux_update: sort, select, build back buffer
    M->>T: zp_mux_ready = 1
    Z->>Z: last slot written: IrqDone()
    Note over T,M: next frame
    T->>T: ready? front ^= 32, copy end index, ready = 0
```

- **Latency:** positions written in frame N are on screen in frame N+1, provided the main
  loop (game logic + `mux_update`) finishes within the frame. If it doesn't, the previous
  frame's sprites are shown again (no tearing, no garbage) and `mux_update` returns C=1 if
  called again before the swap.
- The slot arrays (all 64 bytes, `.align $40` so indexed reads never cross a page):
  `mux_s_y`, `mux_s_xlo`, `mux_s_ptr`, `mux_s_col`, `mux_s_d010`, `mux_s_d01c`
  (the cumulative `$D010`/`$D01C` value after this slot is written), `mux_s_free`
  (the line on which the slot's hardware sprite is free: `mux_s_y[k−8] + MUX_FREE_AFTER`).
  Plus `mux_s_count` (the back buffer's end index, copied to `zp_mux_end` on the swap).

### Sort

Insertion sort of an index list, `mux_order`, by `mux_y`. `mux_order` persists between
frames, so it's nearly sorted and each frame costs about one compare per sprite plus one
shift per pair that swapped places. Hidden sprites sort as Y = `$FF` (to the end) and are cut
off there.

Worst case (list fully reversed, e.g. after many sprites teleport) is 276 shifts: about 6,000
cycles (*estimate*). That's a main-loop cost, so the effect is one repeated frame, not a
display glitch. Spawn code should place new sprites with a sensible Y (not all at 0).

### Hardware sprite assignment

Kept sprites, in Y order, become slots 0, 1, 2…; **slot k uses hardware sprite k mod 8**
(round robin). The sprites active on any one line are then a consecutive run mod 8, which is at
most two DMA groups: the cheap case per the measured DMA costs
([vic-ii-timing.md](../docs/reference/vic-ii-timing.md#sprite-dma): 2 cycles per sprite + 3 per group).
The run can wrap (7 → 0), which costs one extra group (3 cycles a line) against starting
again at 0; accepted, because restarting at 0 would need an idle hardware sprite.

### Scheduling, and the minimum vertical separation

Slot k (k ≥ 8) can't be written until slot k−8, on the same hardware sprite, has finished
displaying (line `y[k−8] + MUX_FREE_AFTER`), and must be written before its own Y line. The
selection pass **simulates the zone IRQs** in raster lines with the three constants above, so
it only keeps sprites the IRQs can actually write in time:

```
done[-1] = 0
free_k  = (k < 8) ? MUX_TOP_LINE : y[k-8] + MUX_FREE_AFTER
start_k = max(free_k + MUX_IRQ_LINES, done[k-1])     // new IRQ, or carry on in the current one
done_k  = start_k + MUX_WRITE_LINES
slot k fits  <=>  done_k <= y[k]
```

What that gives, with the *estimated* constants (22 / 1 / 1):

| Layout | Minimum Y gap to the sprite 8 places earlier in Y order |
|---|---|
| One sprite reusing a hardware sprite | **24 lines** (22 + 1 + 1) |
| A full row of 8 directly below another full row | **31 lines** (22 + 1 + 8) |
| Slots 0–7 (written by `mux_irq_top` from line 16) | Y ≥ 18 + slot, always met since Y ≥ `MUX_Y_MIN` (30) |

So "at most 8 on a row" means, for this multiplexer, at most 8 sprites within any 24-line
window (more for back-to-back full rows), not 8 on one raster line. The QA soak test's
"≤ 8 on a row" should be read that way.

The IRQ side doesn't need a plan: `mux_irq_zone` writes slot k, then carries on with slot k+1
if `mux_s_free[k+1]` ≤ the current raster line, re-arms at `mux_s_free[k+1]` if not, and calls
`IrqDone()` after the last slot. It writes `$D010`/`$D01C` from the cumulative slot values.
In DEBUG builds it also checks, before each slot, that the raster hasn't reached the slot's Y
line; if it has, it increments `mux_late_count` (saturating). **That counter is how the
estimated constants get validated**: the spike must run with it at 0, and if it doesn't, the
constants are raised until it does.

### Overflow: fair flicker

When a sprite doesn't fit, something must be dropped for this frame. Simon's decision is that
nothing vanishes permanently, so the choice rotates. Each virtual sprite has an age,
`mux_age` (frames since it was last shown, saturating at 255). Selection walks the sprites in
Y order:

```
pinned[v] = flags bit 7, for the first MUX_MAX_PINNED such sprites in virtual order 0-23
pin_evictions = 0
for each shown-range sprite v in mux_order:
    if v fits after the kept list: keep v
    elif pinned[v]:                                        // see "Pinned sprites"
        while v doesn't fit and pin_evictions < MUX_PIN_EVICT_MAX
              and an unpinned sprite is among the last 8 kept:
            remove the youngest unpinned of the last 8 kept; pin_evictions += 1
        keep v if it fits now, else drop v (mux_pin_drop_count += 1)
    else:
        w = the youngest UNPINNED of the last 8 kept (lowest age; on a tie, the later one)
        if w exists and age[v] > age[w] and v fits once w is removed:
            remove w (shift up to 7 kept entries, re-simulate them), keep v
        else: drop v
age[v] = 0 if kept, else age[v] + 1
```

Removing a kept sprite never breaks the ones after it (their "8 places earlier" sprite moves
up the screen, which only gives them more time), so one pass is enough. The effect: a sprite
dropped last frame beats one that was shown, so crowded sprites take turns. Worked through
by hand, with nothing pinned: 9 on a row, the two extras alternate (each missing at most 1
frame in 2); 24 on one row, three sets of 8 rotate (each missing 2 frames in 3).

**Flicker target for unpinned sprites.** With P pinned sprites in a crowded window, the
unpinned ones share 8 − P hardware sprites, so n unpinned sprites competing in one window
should each be missing for at most **⌈n / (8 − P)⌉ − 1 consecutive frames**:

| Pinned in the window (P) | Unpinned competing (n) | Longest run missing |
|---|---|---|
| 0 | up to 24 | 2 |
| 1 | up to 21 | 2 |
| 1 | 23 | 3 |
| 4 | up to 12 | 2 |
| 4 | 20 | 4 |

That's a design target, not a proof. `mux_max_age` (the DEBUG high-water mark) covers
**unpinned sprites only**; pinned sprites have their own counter. A pinned sprite's forced
evictions take the youngest unpinned sprite first, the same choice the age rule makes, so
they don't break the rotation. They just take capacity from it.

With ≤ 8 sprites in every window, nothing is ever dropped and nothing flickers, pinned or not.
So the QA soak criterion from the brief (no sprite missing more than 2 frames when ≤ 8 are on
a row) is unaffected by pinning.

### Pinned sprites

Decision (Simon): the player's sprite must not flicker. A virtual sprite with `mux_flags`
bit 7 set is **pinned**: it's never chosen for eviction, and when it doesn't fit it evicts
unpinned sprites until it does.

- **Selection.** A pinned sprite that fits is kept like any other. One that doesn't evicts
  the youngest unpinned sprite among the last 8 kept, and repeats (each removal brings an
  earlier kept sprite into the last 8) until it fits. It ignores ages: a pinned sprite beats
  any unpinned one. Unpinned sprites never evict a pinned one.
- **At most 4.** The first 4 sprites with bit 7 set, in virtual order 0–23, are pinned; any
  more are treated as unpinned that frame and flicker normally. So the game should pin its
  most important sprites at the lowest indices (the player at 0). Each frame with more than 4
  pinned increments `mux_pin_excess_count` (DEBUG).
- **Why 4 is always schedulable.** With the estimated constants, 4 pinned sprites never fill
  a hardware-sprite window (8), and a row of 4 needs 22 + 1 + 4 = 27 clear lines above it once
  the unpinned sprites there are evicted, which eviction provides. So **with ≤ 4 pinned sprites
  in the shown range, every one is shown every frame**, unless the eviction cap runs out.
- **The cap.** `MUX_PIN_EVICT_MAX` (8, *estimate*) bounds the evictions pinned sprites may
  make in one `mux_update`, so the worst case stays about 8 × 350 = 2,800 cycles
  (*estimate*) above normal selection. Reaching it needs several pinned sprites inside dense
  crowds in the same frame. If a pinned sprite still doesn't fit, it's **dropped for that frame**
  (never shown in the wrong place, never left half-written) and `mux_pin_drop_count` increments
  (DEBUG, saturating). Its age still counts, and next frame it evicts as before.
- **Off-screen.** A pinned sprite with Y outside `MUX_Y_MIN`–`MUX_Y_MAX` is hidden, as any
  sprite is. That isn't a drop and isn't counted.
- **Effect on the other sprites.** Every pinned eviction is an unpinned sprite
  dropped, so pinning a sprite that sits in a crowd makes the others flicker more (see the
  table above). That's the trade Simon chose.

### Multiplexer costs

All *estimates* until measured in the `multiplexer` spike (DEBUG build, which is what
`make test` runs; release is cheaper by the late checks).

| Routine | Budget (cycles) | Where it runs | Basis |
|---|---|---|---|
| `mux_sort` → `mux_sort_end` | 1,500 | Main loop | *estimate*: ~24 × 25 compares + shifts for 24 bouncing sprites |
| `mux_select` → `mux_select_end` | 2,200 | Main loop | *estimate*: ~24 × 45, + ~150 for the pinned pre-pass, + evictions at ~350 each (shift 3 kept arrays ≤ 7 entries, re-simulate ≤ 7), allowing ~2 per frame in the spike |
| `mux_build` → `mux_build_end` | 1,800 | Main loop | *estimate*: ~24 × 75 (4 copies, 2 cumulative bytes, free line) |
| `mux_update` → `mux_update_end` (all three) | 5,600 | Main loop | Sum + call overhead |
| Worst case, not budgeted | + ~2,800 on select | Main loop | *estimate*: `MUX_PIN_EVICT_MAX` (8) pinned evictions × ~350. Costs at most a repeated frame, as the sort's worst case does |
| `mux_irq_top` → `irq_exit_rti` | 600 | IRQ, line 16 | *estimate*: swap + 8 slots × ~60 + `$D015`/`$D010`/`$D01C` + re-arm |
| `mux_irq_zone` → `irq_exit_rti`, one IRQ | 550 | IRQ | *estimate*: up to 8 slots × ~60 + re-arm |
| All IRQ time in one frame | 3,300 | IRQ | *estimate*: see the frame budget. Framework overhead per zone IRQ is 78 (was assumed ≈ 95) |

### Debug counters (DEBUG builds)

| Label | Meaning | Spike requires |
|---|---|---|
| `mux_late_count` | Slots the zone IRQ reached on or after their Y line | 0 |
| `mux_max_age` | Highest `mux_age` ever reached by an **unpinned** sprite | ≤ 4 (the target for 4 pinned + 20 unpinned; see the flicker table) |
| `mux_pin_drop_count` | Times a pinned sprite in the shown range was dropped (saturating) | 0 |
| `mux_pin_excess_count` | Frames with more than `MUX_MAX_PINNED` sprites flagged pinned (saturating) | 0 in the budget run; the soak test forces it on purpose |
| `mux_drop_count` | Sprites dropped in the last `mux_update` | (reported only) |

---

## Zero page

The engine doesn't pick addresses. Each game's `zp.asm` defines these labels (any free
zero-page bytes, in any order), and the engine modules use them by name. A missing label
is an assembly error ("unknown symbol"); each module also checks
`.errorif <label> > $ff, "<label> must be in zero page"` for its own labels.

| Label | Bytes | Owner | Purpose |
|---|---|---|---|
| `zp_irq_idx` | 1 | IRQ | Index of the chain entry now running |
| `zp_irq_frame` | 1 | **Shared**: IRQ writes, main reads | Frame counter, +1 at entry 0. One byte, so reads are atomic |
| `zp_mux_front` | 1 | **Shared**: IRQ writes on the swap; main reads only while `zp_mux_ready`=0 | Front buffer base, 0 or 32 |
| `zp_mux_ready` | 1 | **Shared**: main sets 1, IRQ clears to 0 on the swap | Back buffer is built and waiting |
| `zp_mux_slot` | 1 | IRQ | Next slot `mux_irq_zone` writes (includes the base) |
| `zp_mux_end` | 1 | IRQ | End index of the front buffer (includes the base) |
| `zp_tmp0`–`zp_tmp3` | (4) | Main loop (the game's scratch) | Used by `mux_update`; the caller mustn't hold them across the call |

6 bytes of the engine's own, plus 4 of the game's scratch. The register saves in
`irq_dispatch` are self-modified operands, not zero page. A game without the multiplexer
defines only the two `zp_irq_*` labels.

Suggested block for `zp.asm`, after the scratch registers:

```
// Engine (engine/README.md#zero-page)
.label zp_irq_idx   = $0a   // IRQ: current chain entry
.label zp_irq_frame = $0b   // shared: IRQ +1 at entry 0, main loop reads
.label zp_mux_front = $0c   // shared: IRQ writes on swap, main reads while ready = 0
.label zp_mux_ready = $0d   // shared: main sets 1, IRQ clears on swap
.label zp_mux_slot  = $0e   // IRQ: next slot the zone IRQ writes
.label zp_mux_end   = $0f   // IRQ: end of the front buffer
```

Non-zero-page engine RAM (in the engine block): the IRQ chain tables (6 bytes per entry, ≤ 96),
the six virtual arrays (144), `mux_order` and `mux_age` (48), the selection's kept list
(about 72), and the slot buffers (7 × 64 = 448, aligned). About 760 bytes, plus code
(IRQ framework **as built**: 310 bytes of code and data, plus 6 per entry and the 8-byte
tick stub; multiplexer *estimate* ~1.5 KB).

---

## Raster timeline

A game using the multiplexer, PAL, default YSCROLL=3 (badlines on 51 + 8n up to 243, measured).

```mermaid
flowchart TB
    A["Line $10 (16), top border<br/>Entry 0: mux_irq_top<br/>frame tick, buffer swap, slots 0-7,<br/>$D015 / $D010 / $D01C"]
    B["Lines ≈ $34-$F9 (52-249), display<br/>mux_irq_zone, re-armed as hardware sprites free<br/>up to 16 IRQs, slots 8-23"]
    C["Line $FB (251), lower border<br/>Entry 1: game handler (optional)<br/>no badlines; music goes here later"]
    D["Lines 252-311 and 0-15<br/>no IRQs"]
    M["Main loop, whenever no IRQ runs<br/>irq_wait_frame, game logic, mux_update"]
    A --> B --> C --> D -->|"next frame"| A
    A -.->|"irq_wait_frame returns"| M
    M -.->|"zp_mux_ready = 1"| A
```

| Line | Handler | Job | Budget (cycles) |
|---|---|---|---|
| `$10` (16) | `mux_irq_top` (entry 0) | Frame tick, swap, slots 0–7 | 600 (*estimate*) + 32 framework before the handler (**measured**: 7 + 17 + 8) + 6 `rti` |
| ≈ 52–249, dynamic | `mux_irq_zone` | Slots 8–23 as hardware sprites free | 550 per IRQ (*estimate*, raster span, DMA included) + 30 framework (7 + 17 + 6); ≤ 16 IRQs |
| `$FB` (251) | Game entry 1 (optional) | Anything that must run at a fixed time: music (later), colour splits in the border | Its own; lines 251–311 are free of other IRQs |

Rules for other chain entries in a multiplexer game:

- None between `MUX_TOP_LINE` and `MUX_Y_MAX + 2`. The zone IRQs' lines are dynamic and must
  not interleave with fixed entries.
- Entries at `MUX_Y_MAX + 2` or later, up to 255. The last zone IRQ writes its slots before
  the slot's Y (≤ `MUX_Y_MAX`) by construction, so it's done by then.
- **With DMA, + 2 isn't always enough.** After the last write, the last zone IRQ reaches
  `irq_exit`'s late check 47 cycles later (3 + 44, *counted*), plus any DMA in between: up to
  81 on a badline with 8 sprites (**measured**), 128 in all, which is just over 2 lines (126). If
  that happens, the fixed entry runs late (it still runs, and `irq_late_count` counts it). With
  the default `MUX_Y_MAX` = `$F9` there are no badlines after 243, so + 2 holds. A bottom panel
  that puts `MUX_Y_MAX` inside the badline region (≤ 243, the last badline with YSCROLL=3) uses **`MUX_Y_MAX + 3`**, unless
  stage 2 measures the last zone IRQ's end and shows + 2 is enough.

**Status panels: only at the bottom in v1.** A game gets a bottom panel by lowering
`MUX_Y_MAX` so no sprite reaches the panel, and adding a fixed chain entry at the panel's
first line (≥ `MUX_Y_MAX + 2`) for its colour or mode change. Note that a sprite at Y is
displayed on lines Y+1 to Y+21 (*estimate*), so for no sprite pixels over a panel starting on
line P, `MUX_Y_MAX` = P − 22. A **top panel is not supported**: `MUX_Y_MIN` is fixed by the
engine, and no fixed entry may sit between `MUX_TOP_LINE` and `MUX_Y_MAX + 2`. Nor are
splits anywhere in the play area. Either would need a future extension (a configurable
`MUX_Y_MIN`, or zone scheduling that works around fixed splits), which isn't designed.
- Nothing before `MUX_TOP_LINE`: lines 0–15 are where the previous frame's lowest sprites
  finish (a sprite at Y=249 is displayed until line 270, *estimate*) and `mux_irq_top` needs
  them finished.

The `irq_chain` spike's timeline is in [Spikes](#spikes).

---

## Frame budget

PAL, screen on, 24 virtual sprites, DEBUG build.

| Item | Cycles per frame | Basis |
|---|---|---|
| Whole frame | 19,656 | **Measured** ([vic-ii-timing.md](../docs/reference/vic-ii-timing.md#frame-geometry)) |
| Badlines | −1,075 | 25 × **measured** 43 ([vic-ii-timing.md](../docs/reference/vic-ii-timing.md#badlines)) |
| Sprite DMA, 24 sprites | −2,448 | 24 × 21 lines × **measured** 2 = 1,008, plus ≤ 240 lines × 2 groups × **measured** 3 = 1,440 ([vic-ii-timing.md](../docs/reference/vic-ii-timing.md#sprite-dma)). The 21 lines per sprite and the 240 lines are *estimates* |
| All IRQs: framework, `mux_irq_top`, ≤ 16 zone IRQs, one game entry | −3,300 | *estimate*: ≈ 640 + 16 × (78 overhead, measured parts + counted re-arm, + ≈ 60 per slot) + ≈ 100 ≈ 2,950, leaving ≈ 350 for the unmeasured per-slot cost and DMA inside the IRQs |
| `mux_update` (main loop) | −5,600 | *estimate*, including pinned evictions |
| **Left for game logic, music and everything else** | **≈ 7,200** (37%) | |

The IRQ and `mux_update` figures are raster time, so they include DMA that lands on them;
that DMA is also in the DMA row. The table double-counts it on purpose, as margin.

What this means for a game: about 7,200 cycles a frame for a 50 Hz game with 24 sprites.
Music (M3 doesn't include it; a typical player's cost is *unmeasured*) comes out of that.

---

## Budget files

Each spike has `tests/engine/<spike>/budget.json`. The Technical Director writes the budgets;
the tools-engineer's runner (`make test`, see [Running it](#running-it)) builds the spike, runs it
in VICE through `mcp/vice/vice_monitor.py`, runs every check, prints one line per check, and exits
non-zero if any fails.

```json
{
  "spike": "multiplexer",
  "src_dir": "tests/engine/multiplexer",
  "warmup_frames": 100,
  "checks": [
    {"name": "...", "kind": "profile", "routine": ["start_label", "end_label"],
     "max_cycles": 1500, "samples": 50, "basis": "estimate", "source": "engine/README.md#..."}
  ]
}
```

| Field | Meaning |
|---|---|
| `spike`, `src_dir` | Build with `make GAME=<spike> SRC_DIR=<src_dir>` (DEBUG build) |
| `warmup_frames` | Frames to run after boot before any check |
| `checks[].name` | Shown in the output line |
| `checks[].basis` | `"measured"` (budget derived from a measured figure), `"estimate"` (not yet measured), or `"requirement"` (an acceptance criterion or invariant, e.g. jitter ≤ 7, a counter = 0). Printed, so an estimate-based pass is visible as such |
| `checks[].source` | Where the budget comes from |

Check kinds (`kind` defaults to `profile`, so the brief's single-object example is a valid check):

| `kind` | Fields | Measures | Passes if |
|---|---|---|---|
| `profile` | `routine: [start, end]`, `max_cycles`, `samples` (default 50) | Raster cycles from executing `start` to executing `end`, as `vice_profile` (includes DMA and anything that interrupts it) | max ≤ `max_cycles` |
| `profile_excl_irq` | as `profile` | As `profile`, minus time spent in IRQs inside the span. An IRQ spans from its `irq_dispatch` hit − 7 cycles to its `irq_exit_rti` hit + 6 | max ≤ `max_cycles` |
| `start_cycle` | `label`, `line`, `frames` (default 100), `max_spread`, optional `max_cycle` | Raster line and cycle each time `label` is about to execute, over consecutive frames (`vice_run_until` reports the same) | Every hit on `line`, max − min cycle ≤ `max_spread`, and max ≤ `max_cycle` if given |
| `irq_time_per_frame` | `max_cycles`, `frames` | Sum of IRQ spans (as above) per frame | max over the frames ≤ `max_cycles` |
| `memory` | `address` (label), `size` (1 or 2, little-endian), `after_frames`, one of `equals` / `max` / `min`, optional `scale` | Value after running `after_frames` more frames, times `scale` | Comparison holds |

Output, one line per check (`spike  name  figures  PASS|FAIL  (basis)`); a failing check adds
indented lines saying what is over or under, what was measured, and the check's `source`:

```
irq_chain  h1 start (normal, line $69)           spread 7 / budget 7; max cycle 33 / budget 33  PASS  (measured)
irq_chain  irq_exit overhead                     max 60 / budget 60  PASS  (measured)
irq_chain  no late handlers                      irq_late_count 0 (required == 0)  PASS  (requirement)
multiplexer  SKIP  tests/engine/multiplexer/main.asm does not exist yet (14 checks not run)
budget-runner: 9/9 checks passed (1 spike run, 1 skipped: no source yet)
```

```
irq_chain  irq_exit overhead                     max 60 / budget 50  FAIL  (measured)
    max: 60 is over the budget of 50 by 10
    measured: min 58, avg 59.5, 50 passes
    budget source: engine/README.md#irq-framework-costs: measured 60 every pass ...
```

### Running it

```
make test                    # every tests/**/budget.json
make test ARGS=irq_chain     # one spike (a name, or a path to any budget.json, e.g. a scratch copy)
uv run budget-runner --no-build irq_chain   # reuse the existing build
uv run budget-runner --strict               # a missing main.asm is a failure, not a skip
```

Exit status: 0 all checks passed; 1 a check failed, could not be measured, or a build failed;
2 a budget file is malformed or the selection matched nothing. Code: `tools/budget-runner`
(parsing and comparison in `spec.py` / `evaluate.py`, tested by pytest without VICE; the VICE
driving in `session.py`, on `mcp/vice/vice_monitor.py`). One headless x64sc runs per spike, and
its checks run one after another in file order, so a `memory` check sees the frames the earlier
checks already ran.

How the runner reads the schema, where the text above left room:

- `warmup_frames` counts from the program's entry (the BASIC `SYS` target), in whole frames.
- Every hit is a stop at an execution checkpoint, so raster figures are exact. Time is raster
  line x 63 + cycle, unwrapped across frames; two watched hits more than a frame apart cannot be
  timed, and a watched address not reached within 5 s of wall time fails that check as
  "timed out".
- `profile`: the cost of a pass is the time from a hit on `start` to the next hit on `end`; a
  second `start` before `end` restarts the pass. Passes stop after `samples`.
- `profile_excl_irq` and `irq_time_per_frame` watch the framework labels `irq_dispatch` and
  `irq_exit_rti`, which the test program must therefore export. Nested IRQs are counted once.
  Only IRQs **nested inside the pass** (dispatched after `start`, returned before `end`) are
  subtracted, so a routine that itself runs inside a handler is not reduced to nothing.
- `irq_time_per_frame` assigns each IRQ span to the frame (raster line 0 to line 0) its start falls
  in, discards the partial first frame, and takes the max over the next `frames` frames.
- `start_cycle`: **every** hit of `label` must be on `line` (a hit on another line fails, since it
  means the IRQ moved), the cycle spread over `frames` hits must be at most `max_spread`, and the
  max cycle at most `max_cycle` when given. (Decided with Simon, 2026-09-29: a hit elsewhere fails
  rather than being ignored.)
- `memory`: `address` is a label (or `$hex`); the value is read little-endian after
  `after_frames` more frames, multiplied by `scale`, then compared.
- `notes` is allowed at the top level and on a check and is ignored. An unknown field, an unknown
  `kind`, or a missing required field is a budget-file error naming the file and check.
- A spike whose `src_dir/main.asm` does not exist yet (its budget was written first, as with
  `multiplexer`) is reported as SKIP and does not fail the run. Use `--strict` to fail on it;
  M3 sign-off runs with `--strict`.

---

## Spikes

Both live in `tests/engine/<spike>/main.asm`, built with
`make GAME=<spike> SRC_DIR=tests/engine/<spike>`. Labels named here are what `budget.json` uses.

### `irq_chain`

Four entries changing the border colour, screen on (badlines active), no sprites.

| Entry | Line | Kind | Label (first instruction) | Why this line |
|---|---|---|---|---|
| 0 | `$20` (32) | Normal | `spike_h0` | Top border, frame entry |
| 1 | `$69` (105) | Normal | `spike_h1` | Display area; 105 and 106 (where its exit ends) are not badlines |
| 2 | `$B1` (177) | **Stable** | `spike_h2` | Stage lines 175–177 and 178 (its exit) are not badlines (171, 179 are) |
| 3 | `$FA` (250) | Normal | `spike_h3` | Last display line, below the last badline (243) |

- Entries 1 and 2 were first designed at `$6A` and `$B2`. Their exits then ran into badlines
  107 and 179, and `irq_exit` measured 102–103 instead of 60, so both moved up one line. That's a
  rule for spikes that lock costs, not for games ([DMA inside an IRQ](#dma-inside-an-irq)).
- The **main loop must generate worst-case jitter**: a loop mixing 7-cycle instructions
  (`inc abs,x`) with 2- and 3-cycle ones, not `jmp *`. Otherwise the normal handlers show 3
  cycles of spread and the stable one proves nothing. **A fixed-length loop isn't enough**
  (**measured**): the IRQs' own durations feed back into the loop's phase, and a 25-cycle loop
  locked into 5 phases at h0 over 1,000 frames. The spike's loop takes a 30- or 37-cycle path
  chosen by an LFSR, which reached all 8 jitter values on every entry.
- `spike_h2` writes the border colour as its first store, so a screenshot with `area="full"`
  shows the colour change at the same x position on every frame.
- Screenshot: `screenshots/irq-chain-bands.png`.
- Frame-by-frame figures: `uv run python tests/engine/irq_chain/measure.py 1000` (from the repo root or `mcp/vice`).

```mermaid
flowchart LR
    H0["$20 spike_h0<br/>frame tick, colour 1"] --> H1["$69 spike_h1<br/>colour 2"]
    H1 --> H2["$AF trigger, $B1 start<br/>spike_h2 stable, colour 3"]
    H2 --> H3["$FA spike_h3<br/>colour 4"]
    H3 -->|"next frame"| H0
```

### `multiplexer`

24 virtual sprites bouncing around the screen with different speeds, so rows form, cross and
overload. Sprite data from a PNG through `tools/png2sprites`, wired into `make`.

- Memory: VIC bank 0, screen `$0400` (`MUX_SCREEN`), sprite data from `$2000` (pointers
  `$80`+; `$1000–$1FFF` is the character ROM for the VIC in bank 0, per
  [memory-map.md](../docs/reference/memory-map.md#bank-selection-dd00-bits-01-inverted)).
- Chain: entry 0 `mux_irq_top` at `$10`, entry 1 `spike_bottom` at `$FB` (sets nothing but
  proves a fixed entry coexists with the zone IRQs).
- The main loop is the real pattern: `irq_wait_frame`, move the sprites, `mux_update`, then an
  **idle loop** that counts iterations until the next frame tick. It keeps
  `spike_idle_min` (16-bit, the fewest iterations seen in a frame, after warm-up) and
  `spike_overrun_count` (frames where the work didn't finish before the next tick). The idle
  loop's cost per iteration is counted and written in its header (budget.json assumes 16).
- **Pinned sprites: 0–3 are pinned** (the maximum, so capacity is tested at its worst).
  Sprite 0 is the "player": it sweeps the whole shown range from top to bottom and back, so
  it passes through every crowd the bouncing sprites form. Sprite 1 tracks sprite 0's Y at a
  different X for part of each sweep, so two pinned sprites regularly share a row inside a
  crowd. Sprites 2 and 3 bounce like the others. Sprites 4–23 are unpinned.
- `budget.json` requires `mux_pin_drop_count` = 0 and `mux_pin_excess_count` = 0 over 3,000
  frames, and `mux_max_age` ≤ 4 (the flicker target for 4 pinned + 20 unpinned).
- Screenshots: `screenshots/multiplexer-24-sprites.png`, one with an overloaded row
  (`screenshots/multiplexer-overload.png`), and one with the player inside that row
  (`screenshots/multiplexer-pinned-in-crowd.png`).

**QA soak test (10,000 frames)**, in addition to the brief's no-crash / no-jam /
≤ 2-missing-frames checks:

- The player never drops out: `mux_pin_drop_count` = 0 at the end, and, sampled every frame
  (or every few frames if that's too slow through the MCP), `mux_age[0]` = 0 whenever sprite 0's
  Y is in the shown range.
- Excess pins are handled: set bit 7 of `mux_flags+4` with `vice_write_memory`, run 100 frames,
  and check `mux_pin_excess_count` > 0, sprites 0–3 still never dropped, sprite 4 flickers but
  its missing runs stay within the unpinned target, and nothing crashes. Then clear the bit.

---

## Estimates to measure in M3

The raster-engineer measures these with probes (`tests/timing/<name>/`) or in the spikes,
records them in the reference docs as measured, and updates this page and the budget files.

| # | Figure | Design value | Used for | How |
|---|---|---|---|---|
| 1 | Raster IRQ trigger cycle within the line (and whether line 0 differs) | **Measured**: IRQ sequence starts on cycle 2 at the earliest (lines 32, 105, 175, 250). Line 0 still unmeasured | Handler start cycle, `max_cycle` checks | `vice_run_until` on a handler after a `jmp *` loop |
| 2 | Writing `$D012` with the current line: does the IRQ latch immediately? | Assumed "maybe": the late check handles both | Late-check correctness | Probe |
| 3 | Framework costs: dispatch, exit, re-arm, tick, stable extra | **Measured** 17 / 60 / (41 counted) / 8 / 99–106. Re-arm to be measured in stage 2: an `IrqRearm` entry in `irq_chain` on DMA-free lines | Every IRQ budget | `irq_chain` spike, `vice_profile` |
| 4 | `IRQ_STABLE_CYCLE`: the stable handler's start cycle | **Measured**: 6 | Stable handler users | `irq_chain` spike, `start_cycle` |
| 5 | Maximum normal jitter with the worst main loop | **Measured**: 7 (8 never seen in 4,000 IRQs, taken branches included) | Acceptance | `irq_chain` spike, `start_cycle` |
| 6 | Sprite DMA lines per sprite (display on Y+1 … Y+21) | 21 | DMA budget, `MUX_FREE_AFTER` | Extend `tests/timing/sprites` |
| 7 | Latest cycle on line Y at which writing the sprite's Y still shows it from Y+1 | Before ~cycle 55 | Scheduling, `MUX_WRITE_LINES` | Probe |
| 8 | Earliest line/cycle to rewrite X, pointer and colour without marking the previous occupant's last line | Line Y_old + 22 | `MUX_FREE_AFTER` | Probe with screenshots |
| 9 | Zone IRQ trigger-to-first-write, and per-slot write time, under worst DMA | 1 line / 1 line | `MUX_IRQ_LINES`, `MUX_WRITE_LINES` | Spike, with `mux_late_count` = 0 as the test |
| 10 | Sort, select, build and IRQ costs | See the tables | Budgets | `multiplexer` spike |
| 11 | Badline steal when the badline starts during IRQ entry (3 consecutive writes) | 40 | Only for cycle-exact code across a badline | Listed as unmeasured in vic-ii-timing.md |
| 12 | Cost of one eviction (remove, shift, re-simulate) | ~350 | Select budget, `MUX_PIN_EVICT_MAX` | `multiplexer` spike: profile an eviction path |
| 13 | Pinned pre-pass (effective pinned set, excess count) | ~150 | Select budget | `multiplexer` spike |
| 14 | Whether `MUX_PIN_EVICT_MAX` = 8 is ever reached in the spike and soak | Not reached | The pinned guarantee | Soak: `mux_pin_drop_count` = 0; if not, raise the cap and re-cost it |
| 15 | Flicker targets in the table in [Overflow](#overflow-fair-flicker) | ⌈n / (8 − P)⌉ − 1 | `mux_max_age` checks | Spike and soak |

---

## v1 limits

Deliberately out of v1, so they don't get assumed:

- Chain lines ≥ 256; more than 16 chain entries; changing handlers at run time.
- Sprite X/Y expansion (a decision: see below), per-sprite background priority, and
  double-buffered screens (sprite pointers go to one `MUX_SCREEN`).
- Fixed chain entries inside the multiplexer's region, so no top panel and no splits in the
  play area; a bottom panel only ([Raster timeline](#raster-timeline)).
- More than 4 pinned sprites.
- `BRK` goes through the IRQ vector like an IRQ and will put the chain out of step. A stray
  `BRK` means a crash anyway; a DEBUG trap for it is possible later (about 10 cycles per IRQ).
- NTSC (out of scope for M3).

## Decisions

Simon's answers to the design's open questions (2026-09-29):

| Question | Decision |
|---|---|
| Splits inside the sprite area | Not in v1. A **bottom panel** is enough for now (`MUX_Y_MAX` plus a fixed entry below it). A top panel or play-area splits need a future extension, not designed yet |
| Should the player's sprite flicker? | **No**: "player sprite flickering is bad." Pinned sprites are in v1: `mux_flags` bit 7, at most 4 ([Pinned sprites](#pinned-sprites)) |
| Expanded (double-size) sprites | **Not needed for now.** Unsupported in v1: `$D017` and `$D01D` must be 0 |
