# 6502/6510 instruction timing

Cycle counts for writing and checking timing-critical code. These are CPU cycles only.
Add what the VIC-II steals ([vic-ii-timing.md](vic-ii-timing.md)) to get raster time.

## By addressing mode

| Mode | Example | Read (LDA, ADC, CMP, AND…) | Write (STA, STX, STY) | Read-modify-write (INC, DEC, ASL, LSR, ROL, ROR) |
|---|---|---|---|---|
| Immediate | `lda #$00` | 2 | — | — |
| Zero page | `lda $fb` | 3 | 3 | 5 |
| Zero page,X / ,Y | `lda $fb,x` | 4 | 4 | 6 |
| Absolute | `lda $c000` | 4 | 4 | 6 |
| Absolute,X / ,Y | `lda $c000,x` | 4, **+1 if the index crosses a page** | 5 (always) | 7 (always) |
| (Indirect,X) | `lda ($fb,x)` | 6 | 6 | — |
| (Indirect),Y | `lda ($fb),y` | 5, **+1 if the index crosses a page** | 6 (always) | — |
| Accumulator | `asl` | — | — | 2 |

A page crossing happens when base + index lands in a different 256-byte page from the base
(e.g. `lda $c0f0,x` with X=$20). **Page-align tables** read in timing-critical loops
(`.align $100` in KickAssembler), so the count is constant.

## Everything else

| Instruction | Cycles |
|---|---|
| Implied: `tax`, `inx`, `clc`, `sei`, `nop`… | 2 |
| Branch not taken | 2 |
| Branch taken, same page | 3 |
| Branch taken, to another page | 4 |
| `jmp abs` | 3 |
| `jmp (ind)` | 5 (bug: a pointer at `$xxFF` reads its high byte from `$xx00`) |
| `jsr` | 6 |
| `rts` | 6 |
| `rti` | 6 |
| `pha`, `php` | 3 |
| `pla`, `plp` | 4 |
| `brk` | 7 |
| **Interrupt entry (IRQ/NMI)** | **7**, after the current instruction finishes |
| `bit zp` / `bit abs` | 3 / 4 |

Common idioms:

| Code | Cycles | Use |
|---|---|---|
| `jsr` + `rts` | 12 | Call overhead: inline or unroll hot paths instead |
| `lda $d012 / cmp #n / bne *-5` | 4 + 2 + 3 per loop | Busy-wait for a line (resolution: the loop's 9 cycles) |
| `bit $ea` | 3 | 3-cycle delay (a harmless zero-page read, but it changes the N, V and Z flags) |
| `nop` | 2 | 2-cycle delay |
| `inc $d020` / `dec $d020` | 6 each | Border-colour timing markers while debugging |

## Illegal opcodes

Stable on all C64s, and widely used in demos. Allowed in engine code, with a comment naming the opcode:

| Opcode | Does | Typical use |
|---|---|---|
| `LAX` | `LDA` + `LDX` in one | Loading both from a table |
| `SAX` | Store A AND X | Masked writes |
| `DCP` | `DEC` memory, then `CMP` | Counters |
| `ISC` (`ISB`) | `INC` memory, then `SBC` | |
| `SLO`, `RLA`, `SRE`, `RRA` | Shift/rotate memory, then `ORA`/`AND`/`EOR`/`ADC` | Speedcode |
| `ANC`, `ALR` (`ASR`), `ARR`, `SBX` (`AXS`) | Immediate-mode combinations | Speedcode |

Read-modify-write illegals take the same cycles as `INC` in the same mode, plus
(Indirect,X) and (Indirect),Y forms at 8 cycles and Absolute,Y at 7.

**Don't use** the unstable ones (`ANE`/`XAA` `$8B`, `LXA` `$AB`, `SHA`, `SHX`, `SHY`, `TAS`):
their results vary between chips and temperatures, or depend on DMA timing. `JAM` (`KIL`) opcodes halt the CPU. VICE and
`vice_run_frames` report a jam.

## Counting cycles in code

Timing-critical code carries a cycle count on each line or per block, and blocks list their total:

```
        lda (ptr),y             // 5 (6 if page crossed: table is page-aligned, so never)
        sta $d021               // 4
        dex                     // 2
        bne loop                // 3 taken / 2 last
                                // loop body: 14 cycles
```

Then prove it: `vice_profile(start, end)` in a border area with no sprites should match your count exactly.
