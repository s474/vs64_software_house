#!/bin/sh
# size_guard_check.sh: evidence for the zone code's size lock in engine/multiplexer.asm (M3 follow-up
# F4; MUX_ZONE_BLOCK_BYTES and friends, engine/README.md#slot-write-deadline).
#
#   1. The guard adds no bytes: the multiplexer and multiplexer_edge spikes are built from the
#      commit given (default HEAD~1; give the last commit WITHOUT the guard, f913ad0, for the
#      original proof) in a temporary git worktree, and from the working tree, in DEBUG and
#      release, and the PRGs' md5s are compared.
#   2. The guard works: one `nop` is added in turn to a zone block, to its next-slot test and to
#      the dispatch, and each build must fail with the guard's message. engine/multiplexer.asm is
#      restored from a copy afterwards (and on any exit).
#
# Run from the repo root:   sh tests/engine/multiplexer_edge/size_guard_check.sh [commit]
# Exit 0 = every md5 identical and every deliberate change stopped the build. It uses build/ only
# for the worktree and the spikes' normal outputs, and leaves the spikes built in DEBUG.
# Result (2026-10-01, against f913ad0): results-size-guard.txt beside this file.
set -u
BASE=${1:-HEAD~1}
ROOT=$(git rev-parse --show-toplevel) || exit 2
cd "$ROOT" || exit 2
ASM=engine/multiplexer.asm
WT=build/head-check
KEEP=$(mktemp) || exit 2
cp "$ASM" "$KEEP"
restore() { cp "$KEEP" "$ROOT/$ASM"; rm -f "$KEEP"; git -C "$ROOT" worktree remove --force "$WT" 2>/dev/null; }
trap restore EXIT
fail=0

build() {   # dir, spike, build -> prints the PRG's md5, or FAILED
    (cd "$1" && make -s GAME="$2" SRC_DIR=tests/engine/"$2" BUILD="$3" >/dev/null 2>&1 \
        && md5 -q build/"$2"/"$2".prg) || echo FAILED
}

echo "1. PRG md5, $(git rev-parse --short "$BASE") against the working tree"
git worktree remove --force "$WT" 2>/dev/null
git worktree add "$WT" "$BASE" >/dev/null 2>&1 || { echo "can't make the worktree"; exit 2; }
for spike in multiplexer multiplexer_edge; do
    for b in debug release; do
        old=$(build "$WT" "$spike" "$b")
        new=$(build . "$spike" "$b")
        [ "$old" = "$new" ] && [ "$old" != FAILED ] && verdict=identical || { verdict=DIFFERENT; fail=1; }
        printf '   %-17s %-8s before %s  after %s  %s\n' "$spike" "$b" "$old" "$new" "$verdict"
    done
done
git worktree remove --force "$WT"

echo "2. One nop added: the build must stop with the guard's message"
try() {     # what, the line to add the nop after (exact text, once in the file)
    cp "$KEEP" "$ASM"
    python3 - "$ASM" "$2" <<'EOF'
import sys
path, line = sys.argv[1], sys.argv[2]
src = open(path).read()
assert src.count(line) == 1, f"'{line}' is in the file {src.count(line)} times"
open(path, "w").write(src.replace(line, line + "\n        nop"))
EOF
    for b in debug release; do
        out=$(make -s GAME=multiplexer SRC_DIR=tests/engine/multiplexer BUILD="$b" 2>&1)
        rc=$?
        msg=$(printf '%s\n' "$out" | grep '^Error: ' | head -1)
        case "$rc:$msg" in
            0:*) verdict="BUILT (the guard missed it)"; fail=1 ;;
            *"size is locked"*"engine/README.md#slot-write-deadline"*"edge.py"*) verdict="stopped" ;;
            *) verdict="failed, but not with the guard's message"; fail=1 ;;
        esac
        printf '   %-28s %-8s make exit %s: %s\n      %s\n' "$1" "$b" "$rc" "$verdict" "$msg"
    done
}
try "nop in a block's writes"   "        sta MUX_VIC_XMSB                // 4  = 40 writes (uniform)"
try "nop in the next-slot test" "n6:     jmp mux_zone_rearm"
try "nop in the dispatch"       "        sta mux_zone_jmp + 2            // 4"
cp "$KEEP" "$ASM"
for spike in multiplexer multiplexer_edge; do build . "$spike" debug >/dev/null; done
[ "$fail" = 0 ] && echo "RESULT: PASS" || echo "RESULT: FAIL"
exit "$fail"
