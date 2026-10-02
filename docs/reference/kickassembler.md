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
#define AUTOPLAY                        // a symbol defined here is seen by every file imported after it
                                        // (checked with 5.25, 2026-10-01: a main.asm of "#define X" then
                                        // "#import" of a file testing "#if X"). So a test build can wrap
                                        // a game: tests/games/<title>/main.asm defines, then imports the game

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

### Traps

**An anonymous label inside a loop steals the loop's branch.** `!-` is the nearest `!:` above,
whatever it was meant for. Stage 1 of Swarm had this (M4, 2026-10-02):

```
        ldx #23
!:      lda #0                  // meant as the loop head
        cpx #4
        bcs !+
        lda #$80
!:      sta mux_flags,x         // the skip target: also a "!:"
        dex
        bpl !-                  // binds to the line above, not to the loop head
```

It assembles, and loops over the store alone, so A is never reloaded: every flag was left 0 and the
player wasn't pinned. No build message and no budget check sees it; a behaviour script did.
**Rule: when a loop's body contains another anonymous label, name the loop's**
(`!loop:` … `bpl !loop-`). A bare `!:` / `!-` pair is for loops with no label inside.

**An underscore in `.encoding "screencode_upper"` text is a graphic character**, not a space or a
line at the bottom of the cell (found in the same stage). Screen text takes capitals, digits and
the punctuation of screen codes 32–63 only.

**A `.const` can't be used before the line that defines it; a `.label` can** (checked with 5.25,
M4 stage 4). `lda #SFX_START` above the effect data fails with "Reference to not yet defined
symbol" if `SFX_START` is a `.const`, and assembles if it is a `.label`. So numbers that code
imported earlier needs (effect numbers, table sizes) are `.label`s.

**A macro can't define a symbol whose name is one of its arguments; a function can return the
value for a `.label`.** `engine/sfx.asm` does this: `.label SFX_START = SfxEffect(0, 3, $09, $00, 4)`,
where `SfxEffect` is a `.function` that adds the effect to assembly-time lists (`.eval list.add(…)`
works inside a function, as inside a macro) and returns its index. `.error "text"` works inside a
function (`.errorif` is for macros and the top level). The function runs once: the lists come out
right with forward references elsewhere in the program.

**`#import "engine/x.asm"` looks beside the importing file and in the working directory before
the `-libdir`s.** A `-libdir` put first does not override a file that exists relative to where
the assembler was started. `tests/engine/sfx/mutate.py` wanted to swap one engine file for a
modified copy and got the original until it copied the importing files beside the copy and ran
the assembler there.

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
