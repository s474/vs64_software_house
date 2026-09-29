# C64 memory map and banking

Two separate views of the same 64 KB of RAM matter:

- **The CPU's view** depends on the processor port at `$01`: ROMs and I/O can be switched in over RAM.
- **The VIC-II's view** is a 16 KB window chosen by CIA 2 (`$DD00`). It ignores `$01` completely.

## The CPU's view

| Range | Default contents | Notes |
|---|---|---|
| `$0000–$0001` | 6510 processor port | `$00` = data direction, `$01` = banking. Never use them for data |
| `$0002–$00FF` | Zero page | Fast and short addressing, and needed for `(zp),y` pointers. BASIC and KERNAL use most of it (see below) |
| `$0100–$01FF` | Stack | |
| `$0200–$03FF` | OS work area | Input buffer, KERNAL vectors (`$0314` IRQ, `$0316` BRK, `$0318` NMI), cassette buffer `$033C–$03FB` |
| `$0400–$07FF` | Default screen | 1000 screen codes; `$07F8–$07FF` = sprite pointers |
| `$0800–$9FFF` | BASIC program area | A PRG with `BasicUpstart2` loads at `$0801` |
| `$A000–$BFFF` | BASIC ROM | RAM underneath |
| `$C000–$CFFF` | RAM | Always RAM, never banked |
| `$D000–$DFFF` | I/O, character ROM, or RAM | See `$01` below |
| `$E000–$FFFF` | KERNAL ROM | RAM underneath. `$FFFA/$FFFC/$FFFE` = NMI/RESET/IRQ hardware vectors |

**Writes always go to RAM** when a ROM is switched in (you can write under BASIC and the KERNAL at
any time). Only reads see the ROM. When I/O is switched in, reads and writes in `$D000–$DFFF`
go to the chips.

### `$01` processor port (low 3 bits)

| `$01` | `$A000` | `$D000` | `$E000` | Typical use |
|---|---|---|---|---|
| `$37` | BASIC | I/O | KERNAL | Power-on default |
| `$36` | RAM | I/O | KERNAL | Game using KERNAL IRQ/loading but not BASIC |
| `$35` | RAM | I/O | RAM | **Most games:** all RAM plus I/O. You must supply the vectors at `$FFFA–$FFFF` |
| `$34` | RAM | RAM | RAM | All 64 KB RAM, no I/O. Use briefly (e.g. copying under I/O) with interrupts off |
| `$33` | BASIC | Char ROM | KERNAL | Reading the character ROM (interrupts off: no I/O) |

With the KERNAL switched out, IRQs go through `$FFFE/$FFFF` and NMIs through `$FFFA/$FFFB`
directly. **Always** point the NMI vector at an `RTI` when the KERNAL is out: RESTORE fires an NMI.

### Zero page use by the ROMs

- BASIC and KERNAL both in use: only `$FB–$FE` are reliably free.
- KERNAL in use, BASIC not: `$02–$8F` are free (BASIC's area). The KERNAL uses `$90–$FF`.
- KERNAL banked out (`$01=$35`): everything from `$02` is yours.

Games in this studio normally bank out BASIC and the KERNAL. Allocate zero page per the
[coding standards](../standards/coding-standards.md#zero-page).

## The VIC-II's view

### Bank selection (`$DD00` bits 0–1, inverted)

| `$DD00 & 3` | VIC bank | CPU addresses | Character ROM visible to VIC? |
|---|---|---|---|
| `%11` (default) | 0 | `$0000–$3FFF` | Yes, at `$1000–$1FFF` |
| `%10` | 1 | `$4000–$7FFF` | No |
| `%01` | 2 | `$8000–$BFFF` | Yes, at `$9000–$9FFF` |
| `%00` | 3 | `$C000–$FFFF` | No |

Set it with `lda $dd00 / and #%11111100 / ora #bank_bits / sta $dd00` so the other bits
(serial bus) are preserved.

- The VIC-II **always sees RAM** in its bank, except for the character ROM image in banks 0 and 2.
  It never sees BASIC, the KERNAL or I/O. So bank 3 gives the VIC the RAM *under* the I/O area and
  the KERNAL (`$D000–$FFFF`).
- In banks 0 and 2, `$1000–$1FFF` / `$9000–$9FFF` aren't usable for graphics (the VIC-II sees the
  ROM there), though the CPU can use that RAM for code or data.
- Banks 1 and 3 have 16 KB clear for graphics. Bank 3 is popular with the KERNAL banked out.

### Where things go inside the bank (`$D018`)

| Bits | Meaning | Step |
|---|---|---|
| 4–7 | Screen memory offset | × `$0400` (16 positions) |
| 1–3 | Character set offset (text modes) | × `$0800` (8 positions) |
| 3 | Bitmap offset (bitmap mode): `$0000` or `$2000` | |

Example: `$D018 = $18` in bank 0 = screen at `$0400`, charset at `$2000`.

- **Sprite pointers** are the last 8 bytes of the current screen (`screen + $3F8 … $3FF`).
  Sprite data address = bank base + pointer × 64. With double-buffered screens, each screen needs its own pointers.
- **Colour RAM** is fixed at `$D800–$DBFF`: 1000 nybbles, not banked, not movable, and not
  affected by `$01`'s I/O setting for the VIC-II. The CPU only reaches it while I/O is switched in.

## Typical game layout (one reasonable choice)

| What | Where |
|---|---|
| `$01` | `$35` (BASIC and KERNAL out, I/O in) |
| VIC bank | 3 (`$C000–$FFFF`) |
| Screens | `$C000` and `$C400` (double buffered) |
| Charset | `$C800` |
| Sprites | `$D000–$DFFF` (the RAM under I/O; the VIC sees it, the CPU writes it with `$01=$34`, **interrupts off**: with I/O out the raster IRQ can't be acknowledged. Do it at load or init time) and/or `$E000+` |
| Code, tables, music | `$0800–$BFFF` |
| Vectors | `$FFFA–$FFFF` point at our handlers (they're in the VIC bank, which is fine: a few bytes) |

Each game records its actual layout in `docs/games/<title>/memory-map.md`, using the
[template](../standards/memory-map-template.md).
