"""Generate Swarm's placeholder sprite sheet (the PNG is checked in; this is how it was drawn).

    uv run --package png2sprites python games/swarm/art/make_sprites.py            # write sprites.hires.png
    uv run --package png2sprites python games/swarm/art/make_sprites.py --preview  # also screenshots/swarm-placeholder-sprites.png

13 hires shapes in a row of 24x21 cells (312x21 px), in the order of shapes.SHAPES (see README.md).
Each shape is drawn in its colour from the design's colour table; the game sets the real colour per
sprite at run time. make converts the PNG with tools/png2sprites. Replace the PNG with real art
and run check_sprites.py to confirm it still obeys the art rules.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from shapes import H, SHAPES, W, shape  # noqa: E402

from png2sprites.core import PALETTE  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "games/swarm/src/sprites.hires.png"
PREVIEW = ROOT / "screenshots/swarm-placeholder-sprites.png"

# colour number -> RGB (first match = Pepto's values)
RGB = {}
for rgb, idx in PALETTE.items():
    RGB.setdefault(idx, rgb)


def sheet() -> Image.Image:
    img = Image.new("RGBA", (len(SHAPES) * W, H), (0, 0, 0, 0))
    for n, (_, col) in enumerate(SHAPES):
        for y, row in enumerate(shape(n)):
            for x, on in enumerate(row):
                if on:
                    img.putpixel((n * W + x, y), (*RGB[col], 255))
    return img


def preview(img: Image.Image, scale: int = 8) -> Image.Image:
    gap = 8
    w = len(SHAPES) * (W * scale + gap) + gap
    out = Image.new("RGB", (w, H * scale + 70), (0, 0, 0))
    d = ImageDraw.Draw(out)
    font = ImageFont.load_default(size=16)
    for n, (name, _) in enumerate(SHAPES):
        x0 = gap + n * (W * scale + gap)
        cell = img.crop((n * W, 0, (n + 1) * W, H)).resize((W * scale, H * scale), Image.NEAREST)
        d.rectangle([x0 - 1, 0, x0 + W * scale, H * scale], outline=(40, 40, 40))
        out.paste(cell, (x0, 0), cell)
        d.text((x0, H * scale + 6), f"{n}", fill=(255, 255, 255), font=font)
        d.text((x0, H * scale + 28), name.replace("_", " "), fill=(200, 200, 200), font=font)
    return out


def main() -> None:
    img = sheet()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(f"make_sprites: {len(SHAPES)} shapes -> {OUT.relative_to(ROOT)}")
    if "--preview" in sys.argv:
        PREVIEW.parent.mkdir(exist_ok=True)
        preview(img).save(PREVIEW)
        print(f"make_sprites: preview -> {PREVIEW.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
