// Fixture for tests/makefile/check_assets.sh: a program with no sprite sheet of its own, built with
// ASSET_DIR=games/swarm/src. build/<game>/ is on the include path, so no build-specific path.
#import "sprites.hires.inc"
        * = $0801
        .byte SPRITES_HIRES_COUNT
        .fill 64, LoadBinary("sprites.hires.bin").get(i)
