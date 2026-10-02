#!/bin/bash
# ASSET_DIR: a build whose source directory has no PNG converts the sheets of another directory
# into its own build directory, and the source finds them with no build-specific path.
# Builds tests/makefile/assets_wrapper as GAME=assetprobe with ASSET_DIR=games/swarm/src and checks the
# converted files match the game's own (build/swarm). Run: bash tests/makefile/check_assets.sh
set -eu
cd "$(dirname "$0")/../.."
rm -rf build/assetprobe
make -s GAME=swarm >/dev/null
make -s GAME=assetprobe SRC_DIR=tests/makefile/assets_wrapper ASSET_DIR=games/swarm/src >/dev/null
for f in sprites.hires.bin sprites.hires.col sprites.hires.inc; do
    cmp build/swarm/$f build/assetprobe/$f
done
echo "ok  ASSET_DIR converted games/swarm/src/sprites.hires.png into build/assetprobe, identical to build/swarm"
