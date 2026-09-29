# KickAssembler in this studio

KickAssembler 5.25 (`/Applications/KickAssembler/KickAss.jar`). Full manual:
<https://theweb.dk/KickAssembler/>. This page covers how we use it.

## Building

- **Command line (agents):** `make GAME=<title>` builds `games/<title>/src/main.asm` into `build/<title>/`.
  For programs elsewhere, add `SRC_DIR=`, e.g. `make GAME=badline SRC_DIR=tests/timing/badline`.
- **IDE (humans):** VS64 builds whatever `project-config.json` points `"main"` at, into `build/`.
- One entry file per program: `main.asm` imports everything else. KickAssembler takes one
  source file, and VS64 ignores extra ones.
- Debug builds define `DEBUG` (both the Makefile and VS64). `make BUILD=release` leaves it out.

Build outputs in `build/<title>/`:

| File | What it's for |
|---|---|
| `<title>.prg` | The program |
| `main.vs` | Labels for VICE. `vice_load` reads it, so tools accept label names |
| `main.sym` | KickAssembler symbol file |
| `main.dump` | **Every source line with its address and bytes.** Use it to map an address from VICE back to source |

`-showmem` prints the memory map at the end of every build: check it for overlaps.

## Syntax we rely on

```
BasicUpstart2(start)                    // BASIC "SYS" line at $0801, then code

.const SCREEN = $0400                   // constant
.label zp_ptr = $fb                     // label for an address you don't assemble (zero page, I/O)
.var count = 0                          // assembly-time variable (scripts, loops)

#import "engine/irq.asm"                // include another source: relative to this file, or to the repo
                                        // root (make and VS64 both pass the root as -libdir)
#if DEBUG
        inc $d020                       // debug-only code
#endif

* = $1000 "Music"                       // set the program counter; the name shows in -showmem
.align $100                             // next byte on a page boundary (constant-time table reads)

.byte 1, 2, 3
.word irq_top                           // little-endian 16-bit
.text "HELLO"                           // uses .encoding (e.g. .encoding "screencode_upper")
.fill 40, i * 2                         // generated table: 40 bytes, i = 0..39
.fill 63, NOP                           // 63 NOP opcodes (speedcode, delays)

!loop:  dex                             // multi-label: reuse the name freely
        bne !loop-                      // nearest !loop backwards (!loop+ = forwards)

player: {                               // scoped labels: player.update from outside
update: rts
}

.macro SetBorder(colour) {              // macro: expands inline
        lda #colour
        sta $d020
}
        SetBorder(RED)

.for (var i = 0; i < 8; i++) {          // assembly-time loop: unrolled code or tables
        lda sprite_y + i
        sta $d001 + i * 2
}

.assert "table fits in a page", >table_end, >table
.errorif (* > $cfff), "code overran $cfff"
```

Built-in constants include the colours (`BLACK`, `WHITE`, `RED`, …, `LIGHT_BLUE`) and the
opcodes (`NOP`, `RTS`, …) as byte values.

## Assets at build time

KickAssembler scripts can import data directly, so converters aren't always needed:

```
.var music = LoadSid("assets/title/tune.sid")
* = music.location "Music"
.fill music.size, music.getData(i)

.var pic = LoadPicture("assets/title/logo.png", List().add($000000, $ffffff, $68372b, $70a4b2))
.var bin = LoadBinary("assets/title/charset.bin")
.fill bin.getSize(), bin.get(i)
```

For anything with C64 constraints to check (colour limits per cell, sprite sizes), the Tools
Engineer writes a Python converter in `tools/` that validates and emits `.bin` files, and the
source loads those. Sprite sheets: [`tools/png2sprites`](../../tools/png2sprites/README.md); `make`
converts `NAME.hires.png` / `NAME.mc.png` in a game's source directory automatically.

## Conventions

See [coding standards](../standards/coding-standards.md): naming, zero-page allocation,
cycle-count comments, IRQ ownership.
