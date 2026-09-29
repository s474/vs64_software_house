"""Regenerate the multiplexer spike's sprite sheet (the PNG is checked in; this is how it was drawn).

    uv run --package png2sprites python tests/engine/multiplexer/make_sprites.py

24 hires sprites, 8 x 3 cells of 24 x 21: a ring with the virtual sprite's number (00-23) inside,
so a screenshot shows which virtual sprite is where (and which one is missing). One colour
(white) in the PNG; the spike sets each sprite's colour at run time. make converts it with
tools/png2sprites to build/multiplexer/sprites.hires.bin.
"""

from pathlib import Path

from PIL import Image

OUT = Path(__file__).parent / "sprites.hires.png"
WHITE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)

# 3 x 5 digits
FONT = {
    "0": ["###", "#.#", "#.#", "#.#", "###"],
    "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["###", "..#", "###", "#..", "###"],
    "3": ["###", "..#", ".##", "..#", "###"],
    "4": ["#.#", "#.#", "###", "..#", "..#"],
    "5": ["###", "#..", "###", "..#", "###"],
    "6": ["###", "#..", "###", "#.#", "###"],
    "7": ["###", "..#", ".#.", ".#.", ".#."],
    "8": ["###", "#.#", "###", "#.#", "###"],
    "9": ["###", "#.#", "###", "..#", "###"],
}


def cell(n: int) -> list[list[bool]]:
    px = [[False] * 24 for _ in range(21)]
    for y in range(21):
        for x in range(24):
            dx, dy = x - 11.5, y - 10
            d = dx * dx / 132 + dy * dy / 110
            if 0.72 < d <= 1.0:
                px[y][x] = True
    # two digits, each 3x5 scaled x2 -> 6x10, 2 px apart, centred
    for i, ch in enumerate(f"{n:02d}"):
        ox, oy = 5 + i * 8, 5
        for gy, row in enumerate(FONT[ch]):
            for gx, c in enumerate(row):
                if c == "#":
                    for sy in range(2):
                        for sx in range(2):
                            px[oy + gy * 2 + sy][ox + gx * 2 + sx] = True
    return px


def main() -> None:
    img = Image.new("RGBA", (8 * 24, 3 * 21), CLEAR)
    for n in range(24):
        cx, cy = (n % 8) * 24, (n // 8) * 21
        for y, row in enumerate(cell(n)):
            for x, on in enumerate(row):
                if on:
                    img.putpixel((cx + x, cy + y), WHITE)
    img.save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
