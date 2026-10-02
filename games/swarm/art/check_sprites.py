"""Check a Swarm sprite sheet against the design's art rules (design.md "Art rules" and "Hit boxes").

    uv run --package png2sprites python games/swarm/art/check_sprites.py [SHEET.hires.png]

Default sheet: games/swarm/src/sprites.hires.png. Works on any replacement art: it prints nothing
but a one-line summary on success, and every broken rule (shape index, name, rule) on failure, exit 1.
Shape order is in shapes.SHAPES / README.md. Also run by pytest: tools/png2sprites is not involved;
see test_art.py.
"""

import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from shapes import (ENEMY_ART, ENEMY_BOX, ESHOT_BOX, H, PLAYER_ART, PLAYER_BOX, PSHOT_BOX,  # noqa: E402
                    SHAPES, W)

from png2sprites.core import PALETTE  # noqa: E402

DEFAULT = Path(__file__).resolve().parents[1] / "src/sprites.hires.png"
BAD_COLOURS = {1: "white", 15: "light grey", 6: "blue"}  # rule 7


def cells(path):
    img = Image.open(path).convert("RGBA")
    problems = []
    if img.height != H or img.width != W * len(SHAPES):
        problems.append(f"sheet is {img.width}x{img.height}, expected {W * len(SHAPES)}x{H} "
                        f"({len(SHAPES)} cells of {W}x{H} in one row)")
        return None, problems
    out = []
    for n in range(len(SHAPES)):
        px, cols = set(), set()
        for y in range(H):
            for x in range(W):
                r, g, b, a = img.getpixel((n * W + x, y))
                if a == 0:
                    continue
                px.add((x, y))
                cols.add(PALETTE.get((r, g, b), (r, g, b)))
        out.append((px, cols))
    return out, problems


def bbox(px):
    xs, ys = [p[0] for p in px], [p[1] for p in px]
    return min(xs), max(xs), min(ys), max(ys)


def check(path):
    data, problems = cells(path)
    if data is None:
        return problems

    def bad(n, msg):
        problems.append(f"shape {n} ({SHAPES[n][0]}): {msg}")

    def inside(px, area):
        c0, c1, r0, r1 = area
        return all(c0 <= x <= c1 and r0 <= y <= r1 for x, y in px)

    def reaches(px, box):
        c0, c1, r0, r1 = box
        return {"left": any(x == c0 for x, y in px), "right": any(x == c1 for x, y in px),
                "top": any(y == r0 for x, y in px), "bottom": any(y == r1 for x, y in px)}

    for n, (px, cols) in enumerate(data):
        name = SHAPES[n][0]
        if not px:
            bad(n, "empty")
            continue
        if len(cols) != 1 or not all(isinstance(c, int) for c in cols):
            bad(n, f"needs exactly one C64 palette colour plus transparent, found {sorted(cols, key=str)}")
        for c in cols:
            if c in BAD_COLOURS:
                bad(n, f"colour is {BAD_COLOURS[c]} (rule 7: reserved or the panel's)")
        if name == "player":
            area, box = PLAYER_ART, PLAYER_BOX
        elif name.startswith("enemy_") and "shot" not in name:
            area, box = ENEMY_ART, ENEMY_BOX
        elif name == "player_shot" or name == "enemy_shot":
            box = PSHOT_BOX if name == "player_shot" else ESHOT_BOX
            want = {(x, y) for x in range(box[0], box[1] + 1) for y in range(box[2], box[3] + 1)}
            if px != want:
                bad(n, f"must be exactly columns {box[0]}-{box[1]}, rows {box[2]}-{box[3]}, every pixel "
                       f"set (extra {sorted(px - want)[:3]}, missing {sorted(want - px)[:3]})")
            continue
        else:
            continue  # explosions may use the whole cell
        if not inside(px, area):
            out = sorted(p for p in px if not (area[0] <= p[0] <= area[1] and area[2] <= p[1] <= area[3]))
            bad(n, f"pixel (col,row) {out[0]} is outside the art area columns {area[0]}-{area[1]}, "
                   f"rows {area[2]}-{area[3]}")
        for side, ok in reaches(px, box).items():
            if not ok:
                bad(n, f"does not reach the {side} edge of its hit box (columns {box[0]}-{box[1]}, "
                       f"rows {box[2]}-{box[3]})")
        x0, x1, y0, y1 = bbox(px)
        if abs((x0 + x1) / 2 - (box[0] + box[1]) / 2) > 1 or abs((y0 + y1) / 2 - (box[2] + box[3]) / 2) > 1:
            bad(n, f"outline columns {x0}-{x1}, rows {y0}-{y1} is not centred on its hit box (within 1 px)")
        if area is ENEMY_ART and any(y in (0, 20) for _, y in px):
            bad(n, "uses row 0 or row 20, which must stay empty for enemies (rule 3)")

    # rule 5: both frames of an enemy type have the same outline size and centre
    for a, b in [(3, 4), (5, 6), (7, 8)]:
        if data[a][0] and data[b][0] and bbox(data[a][0]) != bbox(data[b][0]):
            problems.append(f"shapes {a},{b} ({SHAPES[a][0]}, {SHAPES[b][0]}): frames differ in outline "
                            f"{bbox(data[a][0])} vs {bbox(data[b][0])} (rule 5)")
        if data[a][0] == data[b][0]:
            problems.append(f"shapes {a},{b}: the two frames are identical")
    return problems


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    problems = check(path)
    if problems:
        for p in problems:
            print(f"check_sprites: {path.name}: {p}", file=sys.stderr)
        sys.exit(1)
    print(f"check_sprites: {path.name}: {len(SHAPES)} shapes obey the art rules")


if __name__ == "__main__":
    main()
