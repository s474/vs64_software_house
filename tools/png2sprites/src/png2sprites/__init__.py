"""png2sprites: convert a PNG sprite sheet to C64 sprite data (64 bytes per sprite)."""

from png2sprites.core import (  # noqa: F401
    PALETTE,
    Result,
    SpriteError,
    convert,
    convert_file,
)
from png2sprites.cli import main  # noqa: F401
