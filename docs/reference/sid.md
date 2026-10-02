# SID: what the sound-effects module relies on

The SID facts behind [engine/sfx.asm](../../engine/sfx.asm) ([contract](../../engine/sfx.md)).
Every fact is marked one of:

- **measured**: read back from the chip's two readable registers by a probe, in VICE;
- *standard figure, unverified*: what the data sheet and common lore say, not checked here;
- **by ear: Simon only**: anything about how something *sounds*. No tool here can hear.

**What "measured" means on this page.** A program can read back two things from the SID: `$D41B`
(the top 8 bits of voice 3's waveform output) and `$D41C` (voice 3's envelope). So only voice 3
can be measured, and voices 1 and 2 are assumed to behave the same. And a measurement in VICE is
a measurement of VICE's SID emulation (**reSID, emulating an 8580**: fact 14), which is a model of
the chip. What the chip in Simon's machine does is known only by listening.

Measured 2026-10-02, VICE 3.10 (x64sc, PAL), by one probe:

| Probe | Measures |
|---|---|
| [tests/timing/sid_readback](../../tests/timing/sid_readback/main.asm) + [measure.py](../../tests/timing/sid_readback/measure.py) | Everything marked **measured** below. The run behind this page: [results.txt](../../tests/timing/sid_readback/results.txt), sections 1–9 |
| [tests/engine/sfx/check.py](../../tests/engine/sfx/check.py) | Fact 3 again, in use: the monitor's read of `$D400–$D418` against a model, every frame of 14,289 |

```
make GAME=sid_readback SRC_DIR=tests/timing/sid_readback
uv run --package budget-runner python tests/timing/sid_readback/measure.py | tee tests/timing/sid_readback/results.txt
```

## The facts, in short

| # | Fact | Status |
|---|---|---|
| 1 | [Register map](#1-register-map): 7 registers a voice from `$D400`, `$D407`, `$D40E`; control bits; `$D415–$D418` | *Standard figure*; the parts facts 5–9 use are **measured** for voice 3 |
| 2 | [A program can't read `$D400–$D418`](#2-and-3-reading-the-registers): a read returns the last byte written to *any* SID register | **Measured** |
| 3 | [The VICE monitor can](#2-and-3-reading-the-registers): it returns the last value written to each register, in every harness | **Measured** |
| 4 | [`$D41B` and `$D41C` do **not** read live under the test harness](#4-the-harness-and-the-sid) (`-sounddev dummy`). They do under `-sounddev dump -soundarg /dev/null` | **Measured** |
| 5 | [Frequency](#5-frequency): a 24-bit count + the 16-bit value every cycle. Value = Hz × 17.0284 on PAL | The accumulator: **measured**. Hz and the note table: *computed* from it and the clock figure (itself *unmeasured*); pitch **by ear** |
| 6 | [Envelope](#6-envelope): sustain level = nibble × 17; attack 0 reaches the top in 2.33 ms, attack 1 in 8.30 ms; the envelope of each of Swarm's six value pairs, tick by tick | **Measured** for Swarm's values. The 16-entry time tables: *standard figure* |
| 7 | [Re-triggering](#7-re-triggering): (a) a control write with the gate already set doesn't restart the attack; (b) gate off then on 48–63 cycles apart does, from the level the envelope was at; (c) a one-tick gate-off step does too, **but the envelope has not moved in that tick** | **Measured**. (b) and (c) are prompt only under fact 15's conditions |
| 8 | [Pulse width](#8-pulse-width): high register n, low register 0: the output is low for exactly n/16 of the period | **Measured** |
| 9 | [Noise](#9-noise): control `$81`; the value changes once every 2^20 ÷ frequency value cycles | The rate: **measured**. "Never combine noise with another waveform or the test bit": *standard caution, unverified* |
| 10 | [`$D418` = `$0F`, `$D417` = 0](#10-and-11-volume-filter-reset): full volume, no filter, voice 3 not muted. A write to `$D418` clicks on a 6581 | *Standard figures*. The click: **by ear** |
| 11 | [Register state after reset](#10-and-11-volume-filter-reset) | Not measured, not relied on: `sfx_init` writes all 25 |
| 12 | [The tick](#12-the-tick): once a frame = 19,656 cycles; 50.125 a second, 19.95 ms | 19,656: **measured** ([vic-ii-timing.md](vic-ii-timing.md)). The rate follows from the clock figure, *unmeasured* |
| 13 | Voices 1 and 2 behave as voice 3 | Assumed: no read-back. **By ear** |
| 14 | [Which chip](#14-which-chip): VICE emulates an **8580** by default, here and in Simon's own settings | The VICE resource: **measured**. The C64 Ultimate: ask Simon. The differences: *standard lore* |
| 15 | [A start can be up to 33 ms late](#15-late-starts-the-envelopes-rate-counter), the voice holding the level it had: **seen for Swarm's values** | **Measured** (it was listed as lore to check). Whether it can be heard: **by ear** |

## 1 Register map

*Standard figure*, except where a later section measured it on voice 3.

| Offset in a voice | Voice 1 / 2 / 3 | Register |
|---|---|---|
| 0, 1 | `$D400` / `$D407` / `$D40E`, +1 | Frequency, low and high |
| 2, 3 | `$D402` / `$D409` / `$D410`, +1 | Pulse width, low 8 bits and high 4 bits (12 bits in all) |
| 4 | `$D404` / `$D40B` / `$D412` | Control: gate `$01`, sync `$02`, ring modulation `$04`, test `$08`, triangle `$10`, sawtooth `$20`, pulse `$40`, noise `$80` |
| 5 | `$D405` / `$D40C` / `$D413` | Attack (high nibble), decay (low nibble) |
| 6 | `$D406` / `$D40D` / `$D414` | Sustain level (high nibble), release (low nibble) |

| Register | |
|---|---|
| `$D415`, `$D416` | Filter cutoff |
| `$D417` | Filter resonance (high nibble); which voices go through the filter (bits 0–2) |
| `$D418` | Volume (low nibble); filter mode (bits 4–6); bit 7 mutes voice 3 |
| `$D419`, `$D41A` | Paddles (read) |
| `$D41B` | Voice 3's waveform output, top 8 bits (read) |
| `$D41C` | Voice 3's envelope (read) |

**Measured** on voice 3: the frequency registers (fact 5), the pulse width's high register (8),
the gate, test, sawtooth, pulse and noise bits (5–9), both envelope registers (6). Not exercised:
sync, ring modulation, triangle's shape, the pulse width's low register, everything from `$D415`.

## 2 and 3 Reading the registers

**Measured** ([results.txt](../../tests/timing/sid_readback/results.txt), section 2: the probe
writes `$A5` eor n to register n of `$D400–$D418`, then reads).

| Read | Returns |
|---|---|
| By the program, 4 cycles after writing that register | The value just written |
| By the program, a frame later | The same byte from **every** write-only register: the last byte written to the chip (`$BD`, the value written to `$D418`, the last write) |
| By the program, after `$5A` is written to `$D401` | `$5A` from all 25 |
| By the program, `$D419`/`$D41A` | `$FF` (no paddles) |
| By the **monitor** (`vice_read_memory`, the budget runner's `mem_get`; no side effects) | **The last value written to each register**: all 25 as written |
| By the monitor with side effects on | As the program's read: the last byte written to the chip |

- So the module reads no SID register, and a program that wants to know what it wrote keeps its
  own copy: `sfx_shadow`, in DEBUG builds.
- And a test script doesn't need the shadow: the monitor's plain read gives the registers, in
  DEBUG and release builds alike, under every way of starting VICE that section 1 of the results
  tried (the test harness included). `check.py` compares all 25 every frame, and the shadow as
  well when the build has one. Also seen through the MCP server: `vice_read_memory $d400` and
  `sfx_shadow` on the running spike gave the same 25 bytes.
- How long the last byte "stays on the bus" on a real chip isn't measured: in VICE it was still
  there a frame later.

## 4 The harness and the SID

**Measured** ([results.txt](../../tests/timing/sid_readback/results.txt), section 1). The budget
runner and the MCP server start VICE through the same `start_vice` (`mcp/vice/vice_monitor.py`):
`x64sc -default -pal -sounddev dummy`, with `-warp` by default.

| How VICE is started | `$D41B`, `$D41C` | Monitor read of `$D400–$D418` |
|---|---|---|
| Budget runner, MCP server: `-sounddev dummy`, warp | **Not live**: `$D41B` reads `$55` every time, `$D41C` stays 0 | The values written |
| The same without warp | **Not live**, the same | The values written |
| `-sounddev dump -soundarg /dev/null`, warp or not (**the probe's own settings**) | Live | The values written |
| VICE's defaults, the Mac's sound device, warp or not | Live | The values written |
| Simon's own settings, as `make run` starts VICE | Live | The values written |
| Sound off (`+sound`) | **Not the SID**: a counter (`3b 4b 5b 6b…`) | The values written |

- **Warp makes no difference; the sound device does.** With the dummy device (or sound off)
  the emulated chip is not clocked for reads.
- So nothing in `make test` or under the MCP tools can use `$D41B`/`$D41C`, and nothing has to:
  the module reads neither. Only the probe needs them, and its script starts its own VICE with
  the `dump` device writing to `/dev/null` (silent; nothing else is changed).
- A game that used `$D41B` as a random-number source would get a constant under the test harness.
  `engine/rng.asm` doesn't.
- Resources, the same in every row: `SidEngine` 1 (reSID), `SidModel` 1 (8580), `Sound` 1 (0 in
  the last row), `SoundSampleRate` 48000, `SidResidSampling` 2.

## 5 Frequency

**Measured** (section 3): sawtooth on voice 3, the test bit held and then cleared, 256 reads of
`$D41B` exactly 16 cycles apart (the spacing itself measured at the probe's labels). For frequency
values `$1000`, `$1D45` and `$F123`, **all 256 reads equal floor(F × t ÷ 65,536) mod 256**, with
t = 3 + 16 i cycles: the oscillator is a 24-bit count that adds the 16-bit frequency value once a
cycle, starting the cycle after the test bit is cleared, and `$D41B` is its top 8 bits. With
F = 1, all 256 reads are 0.

*Computed* from that and the PAL clock figure (985,248 cycles a second: *unmeasured*,
[vic-ii-timing.md](vic-ii-timing.md)):

```
Hz = F × 985,248 ÷ 16,777,216        F = Hz × 17.0284        (SfxHz(hz) in engine/sfx.asm)
```

| Note | Hz | F | | Note | Hz | F |
|---|---|---|---|---|---|---|
| C4 | 261.63 | `$1167` | | C5 | 523.25 | `$22CE` |
| D4 | 293.66 | `$1389` | | D5 | 587.33 | `$2711` |
| E4 | 329.63 | `$15ED` | | E5 | 659.26 | `$2BDA` |
| F4 | 349.23 | `$173B` | | F5 | 698.46 | `$2E76` |
| G4 | 392.00 | `$1A13` | | G5 | 783.99 | `$3426` |
| A4 | 440.00 | `$1D45` | | A5 | 880.00 | `$3A89` |
| B4 | 493.88 | `$20DA` | | B5 | 987.77 | `$41B4` |
| | | | | C6 | 1046.50 | `$459C` |

An octave up doubles F. Whether a note is in tune is **by ear**: the table rests on an unmeasured
clock figure, and nobody has listened to it yet.

## 6 Envelope

The model (*standard figure*): gate on, the envelope rises to `$FF` at the attack rate, then falls
to the sustain level at the decay rate; gate off, it falls to 0 at the release rate. Nominal times,
from the data sheet (*unverified* beyond the values below):

| Rate | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Attack, ms | 2 | 8 | 16 | 24 | 38 | 56 | 68 | 80 | 100 | 250 | 500 | 800 | 1,000 | 3,000 | 5,000 | 8,000 |
| Decay, release, ms | 6 | 24 | 48 | 72 | 114 | 168 | 204 | 240 | 300 | 750 | 1,500 | 2,400 | 3,000 | 9,000 | 15,000 | 24,000 |

**Measured** through `$D41C` (section 4), once a tick at line 251, for every attack/decay and
sustain/release pair in [Swarm's first effect data](../../tests/engine/sfx/swarm_sfx.asm). Tick 0
is the start; G is the tick the gate is cleared; each value is read just before that tick's write.

| Effect | AD, SR | What `$D41C` read |
|---|---|---|
| Player shot | `$00`, `$A0` | `$AA` from tick 1 to G = 8; 0 at G + 1 |
| Enemy shot | `$00`, `$F0` | `$FF` from tick 1 to G = 6; 0 at G + 1 |
| Dive | `$10`, `$80` | `$88` from tick 1 to G = 30; 0 at G + 1 |
| Enemy explosion | `$08`, `$00` | `D4 A1 6F 4D 35 29 1C 15 0F 0C 08 06 04 03 01` at ticks 1–15, 0 from tick 16 (= G) |
| Player hit, game over | `$0A`, `$00` | `F7 ED E3 D8 CE C4 BA B0 A6 9C…`, `$60` at tick 16, `$4B` at 20, `$27` at 30, `$14` at 40, `$0B` at 50, `$06` at G = 60; 0 at G + 2 |
| Wave start, wave clear, start (one note) | `$09`, `$00` | `EE DA C6 B2 9D 89 75 61 55` at ticks 1–9 (= G), `$55` still at G + 1, 0 at G + 2 |

- **The sustain level is the nibble × 17**: `$A` gives `$AA`, `$8` gives `$88`, `$F` gives `$FF`.
- **Attack**, read every 22 or 42 cycles from silence: rate 0 reaches `$FF` 2,295 cycles
  (2.33 ms) after the gate-on write, rate 1 after 8,177 (8.30 ms). Both are over within one tick,
  which is why the table shows no rise.
- The slow decays are not straight lines: fast at the top, slower lower down (the explosion is at
  a third of its level after 4 ticks and near silence after 12).
- **"0 at G + 2", not G + 1,** for the effects with a slow decay: gate off does not act at once
  on them. That is fact 15.
- Loudness against each other, and whether these shapes sound like the design's descriptions:
  **by ear**.

## 7 Re-triggering

**Measured** (section 5), on voice 3 with the module's own order of writes and spacing.

| | What was done | Result |
|---|---|---|
| (a) | A control write with the gate already set (`$41` again, or `$21`: another waveform) at tick 5 | **No restart.** `$D41C` read every 132 cycles for 33,800 cycles: never a rise. A step change inside an effect does not disturb its envelope |
| (b) | A start on a sounding voice: control 0, then the gate again 63 cycles later (the module's DEBUG spacing; 53 and 48 also tried, release is 51) | **A new attack, from about the level the envelope was at** (not from 0: the 63 cycles of release take off a step or two). With every rate 0 (`$00`/`$A0`): first rise 161 cycles after the gate, the top after about 700. With a slow decay (`$0A`/`$00`): the same, **but 32,100–32,600 cycles late** (fact 15) |
| (c) | A one-tick gate-off step between two notes (`$09`/`$00`, gate off at tick 9, on at tick 10) | **A new attack, but no silence between the notes.** The envelope reads `$55` when the gate is cleared and still `$55` a tick later: the release has not begun (fact 15). The new attack starts about 12,500 cycles (12.7 ms) into the next note, from `$55` |
| (c) | The same with the gate off for **two** ticks | The envelope is at 0 when the gate is set again, and the attack is as prompt as a start from silence: at once in most phases (fact 15's "now and then" row) |

So the start sequence's control-0 write does what the contract wants (a new attack whatever was
playing), and a note sequence's one-frame gate-off re-attacks each note: late, and without a gap.

## 8 Pulse width

**Measured** (section 6): pulse on voice 3 at F = `$1000`, 256 reads of `$D41B` 16 cycles apart,
which is exactly one period. With n in the high register (`$D411`) and 0 in the low one, every
read is `$00` or `$FF`, and **exactly 16 × n of the 256 are `$00`**, for every n from 0 to 15: the
output is low while the top 12 bits of the accumulator are below the width, so it is low for n/16
of the period and high for the rest.

- n = 8 is a square wave. n and 16 − n are the same wave upside down, and should sound the same
  (**by ear**).
- **n = 0 is a constant `$FF`: no sound.** `sfx_pw` = 0 is allowed by the macros but silences a
  pulse effect.

## 9 Noise

**Measured** (section 7): control `$81` after the test bit, 256 reads of `$D41B` 16 cycles apart.
The value changes 4, 16, 64 and 253 times in 4,080 cycles for F = `$0400`, `$1000`, `$4000` and
`$FFFF`: **once every 2^20 ÷ F cycles**. So a noise effect's frequency value sets how coarse the
noise is, and a slide changes it as it does a tone's pitch.

- About 1,300 cycles of the test bit did not reset the noise register: two identical runs read
  different values.
- *Standard caution, unverified*: noise combined with another waveform bit can lock the noise
  register at 0 until the test bit is used. The module's macros refuse any control byte that
  isn't one waveform, with or without the gate.

## 10 and 11 Volume, filter, reset

*Standard figures*: `$D418` = `$0F` is volume 15, no filter mode, voice 3 audible (bit 7 clear);
`$D417` = 0 sends no voice through the filter. `sfx_init` writes 0 to all 25 registers and then
`$0F` to `$D418`, so the state after reset doesn't matter (not measured).

On a 6581 a write to `$D418` makes a click (the trick behind sample playback): *standard lore*,
and **by ear**. The module never writes `$D415–$D418` after `sfx_init`: **measured** by
`check.py` (store checkpoints on all 25 registers, 14,289 frames, no write to them).

## 12 The tick

`sfx_update` runs once a frame. A frame is 19,656 cycles (**measured**,
[vic-ii-timing.md](vic-ii-timing.md)); at the *unmeasured* clock figure that is 50.125 ticks a
second, 19.95 ms each. An effect of n frames holds its voice for n × 19.95 ms.

## 14 Which chip

**Measured**: `SidModel` = 1 and `SidEngine` = 1 in every way of starting VICE that was tried,
**including Simon's own settings** (no `-default`, as `make run` does). `x64sc -help` gives the
numbering: `-sidenginemodel` 256 = reSID 6581, 257 = reSID 8580, 258 = reSID 8580 + digi boost. So
**VICE plays these effects on an emulated 8580** unless told otherwise
(`x64sc -sidenginemodel 256` for a 6581).

**Open: which SID is in Simon's C64 Ultimate** (a real chip in a socket, of either kind, or the
board's own emulation)? That decides what "sounds right" is being judged on.

*Standard lore, unverified*, on what differs that this module could meet: the `$D418` click is a
6581 thing (much weaker on an 8580); a 6581 is somewhat louder and dirtier, an 8580 cleaner; the
filter and combined waveforms differ most, and the module uses neither.

## 15 Late starts: the envelope's rate counter

The contract listed this as lore to check ("after a quick release and re-trigger the attack can
start late by some tens of milliseconds"). **Measured: it happens, with Swarm's values, and not
only after a quick release** (sections 5, 8 and 9).

**What is seen.** After the gate-on write of a start, `$D41C` stays where it was for up to
**32,900 cycles (33.4 ms, 1.67 ticks)** and only then rises. A prompt start rises within 161 cycles
(the probe reads every 132).
The voice is not silent meanwhile: it holds the level the old effect had reached, with the new
effect's waveform and frequency.

**Why** (the standard account, which the measurements fit): the envelope steps when a counter
that counts up once a cycle equals the period of the rate in force. If a write makes the period
*smaller* than the count, the counter must run on to 32,768 and wrap before it can match.

**When**, for Swarm's effects, each case run in 9 phases (45 from silence):

| Start of | On a voice that | Late |
|---|---|---|
| Either shot, the dive | is silent, or is playing a shot or a dive | **Never** (0 of 135 from silence; 0 of 153 on top of each other). All their rates are 0, or the decay is no slower than the attack |
| The explosion, a note, the hit, game over (slow decay, attack 0) | is silent, two ticks or more after its last effect ended | **Now and then**: 8, 1 and 0 of 45 for the three in the committed run, different from run to run (the probe doesn't control which phase the counter is in; nor does a game). The gate-on write puts the decay period in force for a moment before the attack period |
| Anything | is still playing an explosion, a note, the hit or game over (slow decay), or ended one less than two ticks ago | **Always**, by 31,800–32,900 cycles; 12,300–13,000 if the old effect ended one tick before |
| A note or game over | is playing a shot or a dive | **Always** (the new effect's own slow decay, met with a count above the attack's period) |
| A note inside a sequence | (its own one-tick gate-off step) | Always, by about 12,500 cycles: fact 7 (c) |
| *Not Swarm's data:* anything | was left idle after a **release above 0** (tried: `$85`) | **Nearly always, however long ago** the effect ended (150 ticks tried) |

**What follows for effect data** (and why Swarm's first versions are as they are):

- **Release 0 on every effect.** A voice left with a slower release makes the next start on it
  late, for ever after. With release 0 a voice is clean again two ticks after an effect ends.
- Effects that must be prompt and can be cut off (shots) use **rate 0 throughout**.
- A fade by slow decay (explosion, hit, notes) costs up to 33 ms at the next start on that voice
  while it sounds, and sometimes at its own. In Swarm that is: an explosion on top of an
  explosion, the player hit on top of an explosion, each note of the jingles.
- A two-tick gate-off between notes gives a clean gap and (mostly) a prompt attack; one tick gives
  neither.

**A change to the start sequence that removes the "now and then" row** was measured for the
Technical Director (section 9; it is *not* what the module does, whose seven writes are the
contract's): write attack/decay with decay 0 where it is written now, and the real value again
after the gate-on write (8 writes, 12 to 14 cycles more a start in DEBUG). From silence, five effects
45 times each: **0 late of 225**, against 1 of 225 for the module's order in the same section
(and 9 of the 135 slow-decay starts in section 8), and the envelope tick by tick is unchanged. It does nothing for the "always"
rows: those need the old effect out of the way two ticks earlier, which an effect that starts on
an event can't have.

Whether 33 ms of an explosion's tail before the next explosion begins can be heard at all is
**by ear**. It is also VICE's model of the chip: the real one is said to do the same (*lore*).

## By ear: Simon

The only check of how it sounds. Play the spike ([tests/engine/sfx](../../tests/engine/sfx/main.asm):
`make run GAME=sfx SRC_DIR=tests/engine/sfx`, stick in port 2, up/down to choose, fire to play),
in VICE and from the same PRG on the C64 Ultimate. **Not yet done.**

| Question | VICE | C64 Ultimate |
|---|---|---|
| Is each of the ten effects recognisably the design's description: pitch direction and range, length, character (pulse, sawtooth, noise)? | | |
| Loudness of the effects against each other | | |
| Clicks: at a start, when one effect cuts another off (fire twice quickly on the player shot), at an end | | |
| Is anything left sounding after an effect ends? | | |
| Late starts (fact 15): fire the explosion twice, half a second apart and then quickly. Is the second one audibly late? Do the jingles' notes sound separate? | | |
| Do VICE and the real machine agree closely enough to tune the sounds in VICE? | | |
| Which SID does the Ultimate have (6581, 8580, or its own emulation)? | n/a | |
