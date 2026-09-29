"""Regenerate the source sheets for this test (run: cd tools/png2sprites && uv run python
../../tests/tools/png2sprites/make_pngs.py). The PNGs are checked in; this is how they were drawn."""
from pathlib import Path
from PIL import Image

out = Path(__file__).parent / "src"
T = (0, 0, 0, 0)
RGB = {"w": (255, 255, 255, 255), "r": (0x68, 0x37, 0x2B, 255), "c": (0x70, 0xA4, 0xB2, 255),
       "p": (0x6F, 0x3D, 0x86, 255), "y": (0xB8, 0xC7, 0x6F, 255), "g": (0x58, 0x8D, 0x43, 255),
       "b": (0x35, 0x28, 0x79, 255)}




# hires: a ring with an X, and a right-pointing arrow. One colour each (white, yellow).
ring = []
for y in range(21):
    row = ""
    for x in range(24):
        dx, dy = x - 11.5, y - 10
        d = (dx * dx / 132 + dy * dy / 100)
        on = 0.55 < d < 1.0 or abs(x - 11.5) - abs(y - 10) in (0.5, -0.5, 1.5) and d < 0.55
        row += "#" if on else "."
    ring.append(row)
arrow = []
for y in range(21):
    row = ""
    for x in range(24):
        half = abs(y - 10)
        shaft = half <= 2 and x < 14
        head = x >= 12 and half <= (23 - x)
        row += "#" if shaft or head else "."
    arrow.append(row)
img = Image.new("RGBA", (48, 21), T)
for i, (rows, col) in enumerate(((ring, RGB["w"]), (arrow, RGB["y"]))):
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == "#":
                img.putpixel((i * 24 + x, y), col)
img.save(out / "demo.hires.png")

# multicolour: 3 sprites 12x21 sharing cyan (mc1) and purple (mc2); own colours red/green/blue-ish.
mc = Image.new("RGBA", (36, 21), T)
own = [RGB["r"], RGB["g"], RGB["y"]]
for i in range(3):
    for y in range(21):
        for x in range(12):
            dx, dy = x - 5.5, y - 10
            d = dx * dx / 30 + dy * dy / 100
            if d > 1:
                continue
            band = int(d * 4) if i != 1 else (x + y) % 4 // 1
            col = [own[i], RGB["c"], RGB["p"], RGB["c"]][band % 4]
            mc.putpixel((i * 12 + x, y), col)
mc.save(out / "demo.mc.png")
