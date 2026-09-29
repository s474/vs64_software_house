"""Conversion and C64 constraint validation. No file output here, so it is easy to test."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from PIL import Image

SPRITE_H = 21
CELL_W = {"hires": 24, "multicolour": 12}

# RGB -> C64 colour index. Two widely used palettes are accepted, exact match only:
# Pepto's PAL palette and Colodore's. A sheet may use either (not needed to be consistent
# with anything else); a colour matching neither is an error, so an anti-aliased or
# off-palette pixel never converts to a "close enough" colour silently.
_PEPTO = ["000000", "FFFFFF", "68372B", "70A4B2", "6F3D86", "588D43", "352879", "B8C76F",
          "6F4F25", "433900", "9A6759", "444444", "6C6C6C", "9AD284", "6C5EB5", "959595"]
_COLODORE = ["000000", "FFFFFF", "813338", "75CEC8", "8E3C97", "56AC4D", "2E2C9B", "EDF171",
             "8E5029", "553800", "C46C71", "4A4A4A", "7B7B7B", "A9FF9F", "706DEB", "B2B2B2"]
PALETTE: dict[tuple[int, int, int], int] = {}
for _table in (_PEPTO, _COLODORE):
    for _i, _hex in enumerate(_table):
        PALETTE[(int(_hex[0:2], 16), int(_hex[2:4], 16), int(_hex[4:6], 16))] = _i

COLOUR_NAMES = ["black", "white", "red", "cyan", "purple", "green", "blue", "yellow",
                "orange", "brown", "light red", "dark grey", "grey", "light green",
                "light blue", "light grey"]


class SpriteError(Exception):
    """A C64 rule was broken. The message names the file, sprite and pixel."""


@dataclass
class Result:
    data: bytes                      # 64 bytes per sprite
    count: int
    mode: str
    colours: list[int]               # per sprite: individual (hires: the) colour
    mc1: int | None = None           # multicolour shared colours (%01 and %11)
    mc2: int | None = None
    warnings: list[str] = field(default_factory=list)


def _cn(i: int) -> str:
    return f"{i} ({COLOUR_NAMES[i]})"


def convert(img: Image.Image, name: str = "<image>", mode: str = "hires",
            mc1: int | None = None, mc2: int | None = None) -> Result:
    if mode not in CELL_W:
        raise ValueError(f"mode must be 'hires' or 'multicolour', not {mode!r}")
    multi = mode == "multicolour"
    cw = CELL_W[mode]
    img = img.convert("RGBA")
    w, h = img.size
    if w % cw or h % SPRITE_H or w == 0 or h == 0:
        raise SpriteError(
            f"{name}: image is {w}x{h}, but a {mode} sprite sheet must be a whole number of "
            f"{cw}x{SPRITE_H} cells (width a multiple of {cw}, height a multiple of {SPRITE_H})"
            + (". In multicolour one PNG pixel is one multicolour (double-wide) pixel, so "
               "draw at 12 pixels wide per sprite" if multi else ""))
    cols, rows = w // cw, h // SPRITE_H
    px = img.load()

    # Pass 1: read every pixel into a colour index (None = transparent), checking palette.
    sprites: list[list[list[int | None]]] = []
    for n in range(cols * rows):
        c0, r0 = (n % cols) * cw, (n // cols) * SPRITE_H
        grid = []
        for y in range(SPRITE_H):
            line = []
            for x in range(cw):
                r, g, b, a = px[c0 + x, r0 + y]
                where = _where(name, n, cols, x, y, c0 + x, r0 + y)
                if a == 0:
                    line.append(None)
                    continue
                if a != 255:
                    raise SpriteError(
                        f"{where}: semi-transparent pixel (alpha {a}). Sprites are either "
                        f"opaque or fully transparent; remove anti-aliasing/feathering")
                idx = PALETTE.get((r, g, b))
                if idx is None:
                    raise SpriteError(
                        f"{where}: colour #{r:02X}{g:02X}{b:02X} is not in the C64 palette "
                        f"(Pepto or Colodore values). Recolour the pixel to a palette colour")
                line.append(idx)
            grid.append(line)
        sprites.append(grid)

    used = [sorted({c for line in g for c in line if c is not None}) for g in sprites]

    out = bytearray()
    colours: list[int] = []
    warnings: list[str] = []

    if not multi:
        for n, g in enumerate(sprites):
            if len(used[n]) > 1:
                x, y, c = _first_not(g, used[n][0])
                raise SpriteError(
                    f"{_where(name, n, cols, x, y, (n % cols) * cw + x, (n // cols) * SPRITE_H + y)}: "
                    f"hires sprite uses {len(used[n])} colours "
                    f"({', '.join(_cn(u) for u in used[n])}); a hires sprite has one colour "
                    f"plus transparent. This pixel is colour {_cn(c)} but the sprite's first "
                    f"colour is {_cn(used[n][0])}")
            colours.append(used[n][0] if used[n] else 1)
            for line in g:
                bits = "".join("0" if c is None else "1" for c in line)
                out += int(bits, 2).to_bytes(3, "big")
            out.append(0)
        return Result(bytes(out), len(sprites), mode, colours, warnings=warnings)

    # Multicolour: at most 3 colours per sprite, and the same two shared colours everywhere.
    for n, g in enumerate(sprites):
        if len(used[n]) > 3:
            x, y, c = _first_not(g, *used[n][:3])
            raise SpriteError(
                f"{_where(name, n, cols, x, y, (n % cols) * cw + x, (n // cols) * SPRITE_H + y)}: "
                f"multicolour sprite uses {len(used[n])} colours "
                f"({', '.join(_cn(u) for u in used[n])}); the limit is 3 plus transparent. "
                f"This pixel is colour {_cn(c)}")
    m1, m2 = _pick_shared(name, sprites, used, cols, cw, mc1, mc2)
    for n, g in enumerate(sprites):
        own = [c for c in used[n] if c not in (m1, m2)]
        colours.append(own[0] if own else 1)
        lut = {None: 0, m1: 1, m2: 3}
        if own:
            lut[own[0]] = 2
        for line in g:
            bits = "".join(f"{lut[c]:02b}" for c in line)
            out += int(bits, 2).to_bytes(3, "big")
        out.append(0)
    return Result(bytes(out), len(sprites), mode, colours, m1, m2, warnings)


def _where(name, n, cols, x, y, sx, sy) -> str:
    return (f"{name}: sprite {n} (column {n % cols}, row {n // cols}), pixel ({x},{y}) "
            f"[sheet pixel ({sx},{sy})]")


def _first_not(grid, *ok):
    for y, line in enumerate(grid):
        for x, c in enumerate(line):
            if c is not None and c not in ok:
                return x, y, c
    raise AssertionError("no offending pixel")


def _pick_shared(name, sprites, used, cols, cw, mc1, mc2):
    """Choose the two sheet-wide shared colours so every sprite has <= 1 other colour."""
    for v, label in ((mc1, "mc1"), (mc2, "mc2")):
        if v is not None and not 0 <= v <= 15:
            raise SpriteError(f"{name}: --{label} {v} is not a C64 colour index (0-15)")
    if mc1 is not None and mc1 == mc2:
        raise SpriteError(f"{name}: mc1 and mc2 must be different colours (both {_cn(mc1)})")
    fixed = {m for m in (mc1, mc2) if m is not None}
    everything = sorted({c for u in used for c in u})

    def bad(pair):
        return [n for n, u in enumerate(used) if len([c for c in u if c not in pair]) > 1]

    pool = sorted(set(everything) | fixed)
    pool += [c for c in range(16) if c not in pool][: max(0, 2 - len(pool))]
    if mc1 is not None and mc2 is not None:
        candidates = [(mc1, mc2)]
    elif mc1 is not None:
        candidates = [(mc1, c) for c in pool if c != mc1]
    elif mc2 is not None:
        candidates = [(c, mc2) for c in pool if c != mc2]
    else:
        candidates = list(combinations(pool, 2))
    best = min(candidates, key=lambda p: (len(bad(p)), candidates.index(p)))
    b = bad(best)
    if b:
        n = b[0]
        own = [c for c in used[n] if c not in best]
        # locate the pixel of the second 'own' colour
        x, y, c = _first_not(sprites[n], *best, own[0])
        how = (f"the shared colours are fixed at {_cn(best[0])} and {_cn(best[1])}"
               if mc1 is not None and mc2 is not None
               else f"no choice of two shared colours works for the whole sheet (best choice "
                    f"{_cn(best[0])} and {_cn(best[1])} still breaks {len(b)} sprite(s))")
        raise SpriteError(
            f"{_where(name, n, cols, x, y, (n % cols) * cw + x, (n // cols) * SPRITE_H + y)}: "
            f"sprite colours {', '.join(_cn(u) for u in used[n])} do not fit the sheet's shared "
            f"multicolour colours: {how}. Each sprite may add only ONE colour beyond the two "
            f"shared ones (this pixel is {_cn(c)}, a second non-shared colour)")
    return best


def convert_file(path: str, mode: str = "hires", mc1: int | None = None,
                 mc2: int | None = None) -> Result:
    try:
        img = Image.open(path)
        img.load()
    except (OSError, ValueError) as e:
        raise SpriteError(f"{path}: cannot read PNG: {e}") from e
    return convert(img, path, mode, mc1, mc2)
