// Swarm budget build (docs/games/swarm/memory-map.md#labels-the-game-must-provide): the game
// with AUTOPLAY defined, so it plays its worst case by itself for `make test`
// (tests/games/swarm/budget.json, spike "swarm_budget"; built into build/swarm_budget/).
// sprites.hires.png beside this file is a link to the game's sheet, so make converts it for this
// build too (the Makefile converts the PNGs of the source directory it is given).
//
// Build: make GAME=swarm_budget SRC_DIR=tests/games/swarm
// Test:  make test ARGS=swarm
#define AUTOPLAY
#import "games/swarm/src/main.asm"
