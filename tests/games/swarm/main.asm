// Swarm budget build (docs/games/swarm/memory-map.md#labels-the-game-must-provide): the game
// with AUTOPLAY defined, so it plays its worst case by itself for `make test`
// (tests/games/swarm/budget.json, spike "swarm_budget"; built into build/swarm_budget/).
// The game's sprite sheet is converted for this build too: budget.json's "asset_dir" (make's
// ASSET_DIR) names games/swarm/src, and build/swarm_budget/ is on the include path.
//
// Build: make GAME=swarm_budget SRC_DIR=tests/games/swarm ASSET_DIR=games/swarm/src
// Test:  make test ARGS=swarm
#define AUTOPLAY
#import "games/swarm/src/main.asm"
