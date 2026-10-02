"""pytest: the checked-in sheet passes the art rules, the generator reproduces it, and the checker
catches broken art.   uv run --package png2sprites pytest games/swarm/art -q"""

import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import check_sprites as cs  # noqa: E402
import make_sprites as ms  # noqa: E402
from shapes import W  # noqa: E402


def test_checked_in_sheet_passes():
    assert cs.check(cs.DEFAULT) == []


def test_generator_matches_checked_in_png():
    assert ms.sheet().tobytes() == Image.open(cs.DEFAULT).convert("RGBA").tobytes()


def _broken(tmp_path, edit):
    img = Image.open(cs.DEFAULT).convert("RGBA")
    edit(img)
    p = tmp_path / "bad.hires.png"
    img.save(p)
    return cs.check(p)


def test_pixel_outside_art_area(tmp_path):
    probs = _broken(tmp_path, lambda i: i.putpixel((3 * W + 0, 10), (112, 61, 156, 255)))
    assert any("shape 3" in p and "outside" in p for p in probs)


def test_enemy_row_20_rejected(tmp_path):
    probs = _broken(tmp_path, lambda i: i.putpixel((5 * W + 10, 20), (205, 197, 106, 255)))
    assert any("shape 5" in p for p in probs)


def test_shot_must_be_full(tmp_path):
    probs = _broken(tmp_path, lambda i: i.putpixel((1 * W + 11, 3), (0, 0, 0, 0)))
    assert any("shape 1" in p and "every pixel" in p for p in probs)


def test_white_rejected(tmp_path):
    def edit(i):
        for y in range(21):
            for x in range(W):
                if i.getpixel((x, y))[3]:
                    i.putpixel((x, y), (255, 255, 255, 255))
    assert any("white" in p for p in _broken(tmp_path, edit))
