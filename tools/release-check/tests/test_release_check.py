"""Unit tests (no VICE): directory parsing, screen codes, and the file checks."""
import pytest

from release_check.cli import CheckError, check_prgs, parse_directory, screen_codes

LISTING = '0 "SWARM           " 01 2a\n57   "SWARM"             prg\n607 blocks free.\n'


def test_parse_directory():
    name, files = parse_directory(LISTING)
    assert name.strip() == "SWARM" and files == [(57, "SWARM", "prg")]


def test_screen_codes():
    assert screen_codes("press 1!") == bytes([16, 18, 5, 19, 19, 32, 49, 33])


def test_check_prgs(tmp_path):
    raw, sfx = tmp_path / "a.prg", tmp_path / "a-sfx.prg"
    raw.write_bytes(b"\x01\x08" + bytes(100))
    sfx.write_bytes(b"\x01\x08\x0b\x08\x00\x00\x9e2061" + bytes(20))
    assert check_prgs(raw, sfx) == (102, 31)
    sfx.write_bytes(b"\x01\x08\x0b\x08\x00\x00\x9e2061" + bytes(200))
    with pytest.raises(CheckError, match="not smaller"):
        check_prgs(raw, sfx)
