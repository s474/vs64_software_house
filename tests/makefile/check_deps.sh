#!/bin/bash
# Proof that a wrapper build rebuilds when a file it #imports from another directory changes
# (the Makefile's dependency file, build/<game>/<game>.d). Edits games/swarm/src/player.asm
# temporarily and restores it with a copy on exit; builds tests/games/swarm into build/swarm_budget.
# Run from anywhere:  bash tests/makefile/check_deps.sh        Exit 0 = every step behaved.
set -u
cd "$(dirname "$0")/../.."
FILE=games/swarm/src/player.asm
PRG=build/swarm_budget/swarm_budget.prg
BAK=$(mktemp)
cp "$FILE" "$BAK"
trap 'cp "$BAK" "$FILE"; rm -f "$BAK"' EXIT
fail=0
build() { make -s GAME=swarm_budget SRC_DIR=tests/games/swarm >/dev/null || { echo "build failed"; exit 1; }; }
sum() { md5 -q "$PRG" 2>/dev/null || md5sum "$PRG" | cut -d' ' -f1; }
mtime() { stat -f %m "$PRG" 2>/dev/null || stat -c %Y "$PRG"; }
expect() {  # name, rebuilt(yes/no), md5 (same/different)
    local t0 m0 t1 m1 rebuilt md
    build; t0=$(mtime); m0=$(sum)
    sleep 1.1; "$4"; build
    t1=$(mtime); m1=$(sum)
    [ "$t1" != "$t0" ] && rebuilt=yes || rebuilt=no
    [ "$m1" = "$m0" ] && md=same || md=different
    if [ "$rebuilt" = "$2" ] && [ "$md" = "$3" ]; then r=ok; else r=FAIL; fail=1; fi
    echo "$r  $1: rebuilt=$rebuilt (want $2), prg $md (want $3)"
    cp "$BAK" "$FILE"
}
nothing()  { :; }
comment()  { echo "// comment only" >> "$FILE"; }
touchit()  { touch "$FILE"; }
change()   { echo "        nop" >> "$FILE"; }
expect "nothing changed"            no  same      nothing
expect "comment line added"         yes same      comment
expect "file touched"               yes same      touchit
expect "code changed (nop added)"   yes different change
sleep 1.1; build   # leave a build that matches the restored source
exit $fail
