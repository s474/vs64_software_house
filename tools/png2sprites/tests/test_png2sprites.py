import subprocess
import sys

import pytest
from PIL import Image

from png2sprites import SpriteError, convert, main

BLACK, WHITE, RED, CYAN, PURPLE, GREEN, BLUE = 0, 1, 2, 3, 4, 5, 6
RGB = {0: (0, 0, 0), 1: (255, 255, 255), 2: (0x68, 0x37, 0x2B), 3: (0x70, 0xA4, 0xB2),
       4: (0x6F, 0x3D, 0x86), 5: (0x58, 0x8D, 0x43), 6: (0x35, 0x28, 0x79), 7: (0xB8, 0xC7, 0x6F)}


def sheet(w, h, pixels):
    """pixels: {(x, y): colour index or (r, g, b, a)}; everything else transparent."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for xy, c in pixels.items():
        img.putpixel(xy, (*RGB[c], 255) if isinstance(c, int) else c)
    return img


def save(tmp_path, img, name="s.png"):
    p = tmp_path / name
    img.save(p)
    return p


def test_hires_byte_exact():
    # sprite 0: top-left pixel and bottom-right pixel; sprite 1 (right cell): whole row 3
    px = {(0, 0): WHITE, (23, 20): WHITE}
    px.update({(24 + x, 3): RED for x in range(24)})
    r = convert(sheet(48, 21, px), "t.png", "hires")
    assert r.count == 2 and len(r.data) == 128
    s0, s1 = r.data[:64], r.data[64:]
    assert s0[0] == 0x80 and s0[20 * 3 + 2] == 0x01 and s0[63] == 0
    assert sum(s0) == 0x81
    assert s1[9:12] == b"\xff\xff\xff" and sum(s1) == 3 * 255
    assert r.colours == [WHITE, RED]


def test_cells_are_row_major():
    px = {(0, 0): WHITE, (0, 21): RED, (24, 21): RED}
    r = convert(sheet(48, 42, px), "t.png", "hires")
    assert r.count == 4
    assert [d[0] for d in (r.data[i * 64:(i + 1) * 64] for i in range(4))] == [0x80, 0, 0x80, 0x80]


def test_multicolour_byte_exact():
    # row 0: mc1(cyan), own(red), mc2(purple), transparent, then repeat; 12 px = 3 bytes
    row = [CYAN, RED, PURPLE, None] * 3
    px = {(x, 0): c for x, c in enumerate(row) if c is not None}
    r = convert(sheet(12, 21, px), "t.png", "multicolour", mc1=CYAN, mc2=PURPLE)
    # 01 10 11 00 -> 0110 1100 = 0x6C, three times
    assert r.data[:3] == b"\x6c\x6c\x6c" and r.data[3:64] == bytes(61)
    assert (r.mc1, r.mc2, r.colours) == (CYAN, PURPLE, [RED])


def test_multicolour_infers_shared_and_orders_bits():
    # sprite 0 uses cyan+purple+red, sprite 1 cyan+purple+green: shared = cyan,purple
    a = {(0, 0): CYAN, (1, 0): PURPLE, (2, 0): RED}
    b = {(12, 0): CYAN, (13, 0): PURPLE, (14, 0): GREEN}
    r = convert(sheet(24, 21, {**a, **b}), "t.png", "multicolour")
    assert {r.mc1, r.mc2} == {CYAN, PURPLE}
    assert r.colours == [RED, GREEN]
    lut = {r.mc1: 1, r.mc2: 3}
    assert r.data[0] == (lut[CYAN] << 6) | (lut[PURPLE] << 4) | (2 << 2)  # own colour is %10
    assert r.data[64] == r.data[0]


def test_colodore_palette_accepted():
    img = sheet(24, 21, {(0, 0): (0x81, 0x33, 0x38, 255)})
    assert convert(img, "t.png", "hires").colours == [RED]


def test_alpha_zero_ignores_rgb():
    img = sheet(24, 21, {(5, 5): (12, 34, 56, 0), (0, 0): WHITE})
    assert convert(img, "t.png", "hires").data[0] == 0x80


# ---- constraint errors -------------------------------------------------------------------

def err(img, mode="hires", **kw):
    with pytest.raises(SpriteError) as e:
        convert(img, "bad.png", mode, **kw)
    return str(e.value)


def test_bad_dimensions_hires():
    m = err(sheet(25, 21, {}))
    assert "bad.png" in m and "25x21" in m and "24x21" in m


def test_bad_height():
    assert "multiple of 21" in err(sheet(24, 20, {}))


def test_bad_dimensions_multicolour():
    m = err(sheet(24, 22, {}), "multicolour")
    assert "12x21" in m and "22" in m


def test_multicolour_width_not_multiple_of_12():
    assert "12x21" in err(sheet(18, 21, {}), "multicolour")


def test_off_palette_colour_names_position():
    m = err(sheet(48, 21, {(30, 4): (1, 2, 3, 255)}))
    assert "bad.png" in m and "sprite 1" in m and "pixel (6,4)" in m
    assert "#010203" in m and "not in the C64 palette" in m


def test_semi_transparent():
    m = err(sheet(24, 21, {(2, 3): (255, 255, 255, 128)}))
    assert "semi-transparent" in m and "pixel (2,3)" in m


def test_hires_two_colours():
    m = err(sheet(24, 21, {(0, 0): WHITE, (7, 9): RED}))
    assert "sprite 0" in m and "pixel (7,9)" in m and "one colour" in m


def test_multicolour_four_colours():
    m = err(sheet(12, 21, {(0, 0): WHITE, (1, 0): RED, (2, 0): CYAN, (3, 5): PURPLE}),
            "multicolour")
    assert "4 colours" in m and "pixel (3,5)" in m and "limit is 3" in m


def test_shared_colours_inconsistent_across_sheet():
    # each sprite has 3 colours, but no pair of shared colours fits all three sprites
    s0 = {(0, 0): WHITE, (1, 0): RED, (2, 0): CYAN}
    s1 = {(12, 0): WHITE, (13, 0): GREEN, (14, 0): BLUE}
    s2 = {(24, 0): RED, (25, 0): GREEN, (26, 0): PURPLE}
    m = err(sheet(36, 21, {**s0, **s1, **s2}), "multicolour")
    assert "shared" in m and "sprite" in m and "ONE colour" in m


def test_fixed_shared_colours_violated():
    m = err(sheet(12, 21, {(0, 0): WHITE, (1, 0): RED, (2, 0): CYAN}), "multicolour",
            mc1=WHITE, mc2=BLUE)
    assert "fixed" in m and "sprite 0" in m and "pixel (2,0)" in m


def test_bad_mc_arguments():
    assert "0-15" in err(sheet(12, 21, {}), "multicolour", mc1=16)
    assert "different" in err(sheet(12, 21, {}), "multicolour", mc1=3, mc2=3)


# ---- CLI ----------------------------------------------------------------------------------

def test_cli_success_and_failure(tmp_path, capsys):
    good = save(tmp_path, sheet(24, 21, {(0, 0): WHITE}), "good.png")
    out = tmp_path / "o" / "g.bin"
    col = tmp_path / "g.col"
    assert main([str(good), "-o", str(out), "--colors", str(col)]) == 0
    assert out.stat().st_size == 64 and col.read_bytes() == b"\x01"
    printed = capsys.readouterr().out
    assert printed.count("\n") == 1 and "1 hires sprites" in printed

    bad = save(tmp_path, sheet(23, 21, {}), "bad.png")
    assert main([str(bad), "-o", str(tmp_path / "b.bin")]) == 1
    assert "bad.png" in capsys.readouterr().err
    assert not (tmp_path / "b.bin").exists()


def test_cli_inc_and_missing_file(tmp_path, capsys):
    p = save(tmp_path, sheet(12, 21, {(0, 0): CYAN, (1, 0): PURPLE}), "m.png")
    inc = tmp_path / "m.inc"
    assert main([str(p), "-m", "multicolour", "--mc1", "3", "--mc2", "4", "-o",
                 str(tmp_path / "m.bin"), "--inc", str(inc), "--prefix", "BALL"]) == 0
    assert inc.read_text().splitlines()[1:] == [".const BALL_COUNT = 1", ".const BALL_MC1 = 3",
                                                 ".const BALL_MC2 = 4"]
    assert main([str(tmp_path / "nope.png"), "-o", str(tmp_path / "x.bin")]) == 1


def test_module_entrypoint_exit_code(tmp_path):
    bad = save(tmp_path, sheet(23, 21, {}), "bad.png")
    r = subprocess.run([sys.executable, "-m", "png2sprites", str(bad), "-o", str(tmp_path / "x")],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "bad.png" in r.stderr
