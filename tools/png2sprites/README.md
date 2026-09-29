# png2sprites

Converts a PNG sprite sheet to C64 sprite data: **64 bytes per sprite** (63 data bytes + 1 pad),
in row-major cell order (left to right, then down). A member of the repo's uv workspace (root
`.venv` and `uv.lock`); the commands below work from this directory or the repo root.

```
cd tools/png2sprites
uv run png2sprites SHEET.png -o out.bin [-m hires|multicolour] [--mc1 N] [--mc2 N]
                            [--colors out.col] [--inc out.inc] [--prefix NAME]
uv run pytest -q          # tests (or: make test-tools from the repo root, which runs all tools' tests)
```

On success it prints one line and exits 0; on any rule violation it prints the file, sprite and
pixel to stderr, writes nothing, and exits 1.

```
png2sprites: demo.mc.png: 3 multicolour sprites -> build/spr_png/demo.mc.bin (192 bytes), mc1=3 (cyan) mc2=4 (purple)
png2sprites: error: bad.hires.png: sprite 0 (column 0, row 0), pixel (3,4) [sheet pixel (3,4)]: colour #010203 is not in the C64 palette ...
```

## Drawing the sheet

| | Hires | Multicolour |
|---|---|---|
| Cell size in the PNG | **24 x 21** | **12 x 21** (one PNG pixel = one double-wide multicolour pixel) |
| Colours per sprite | 1 + transparent | 3 + transparent |

- Transparent = alpha 0 (its RGB is ignored). Every other pixel must be fully opaque (alpha 255).
- Colours must match the C64 palette **exactly**. Accepted: Pepto's PAL values or Colodore's
  (`PALETTE` in `core.py`). Anything else, including anti-aliased pixels, is an error rather
  than "nearest colour".
- Multicolour bit pairs: `%00` transparent, `%01` shared colour 1 (`$D025`), `%10` the sprite's own
  colour (`$D027+`), `%11` shared colour 2 (`$D026`). The two shared colours must be the **same
  for the whole sheet**; each sprite adds at most one further colour of its own. They are inferred
  (first valid pair, lowest colour indices first) or pinned with `--mc1` / `--mc2`. Pin them when
  sheets that will be shown together must agree.
- A 24-wide multicolour drawing (pixels doubled) is **not** detected; it converts as two 12-wide sprites.

## Outputs

- `-o`: the sprite data. Sprite *n* is at offset *n* x 64, so with the data at `$2000` its pointer is
  `$80 + n` (VIC bank 0).
- `--colors`: one byte per sprite, its `$D027+` colour (hires: the sprite's colour; multicolour: the
  `%10` colour). A sprite with no such pixels gets 1.
- `--inc`: KickAssembler constants `PREFIX_COUNT` and, for multicolour, `PREFIX_MC1` / `PREFIX_MC2`
  (the values for `$D025` / `$D026`).

## In the build

`make` converts any `NAME.hires.png` / `NAME.mc.png` in the game's `SRC_DIR` to
`build/<game>/NAME.{hires,mc}.{bin,col,inc}` and rebuilds them when the PNG, the tool or the Makefile
changes. Constants are prefixed `NAME_HIRES_` / `NAME_MC_` (upper case, `-` becomes `_`).

```
#import "build/mygame/enemies.mc.inc"                 // ENEMIES_MC_COUNT, ENEMIES_MC_MC1, ENEMIES_MC_MC2
* = $2000 "Sprites"
        .import binary "build/mygame/enemies.mc.bin"  // path relative to the repo root (-libdir)
```

Working example: `tests/tools/png2sprites/` (`make GAME=spr_png SRC_DIR=tests/tools/png2sprites/src`).
