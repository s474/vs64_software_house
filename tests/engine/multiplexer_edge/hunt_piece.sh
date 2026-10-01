#!/bin/sh
# hunt_piece.sh: one piece of edge.py --hunt in the DEBUG and the release build side by side (two
# VICEs), each appended to its results file beside this script. The M3 follow-up hunts (F1, F2,
# 2026-10-01) were run as the pieces listed below, because one command had to finish inside 10
# minutes; a piece of 750 staircases takes about 4.5 minutes, one of 400 flicker layouts about 6.
#
# Run from the repo root:
#   sh tests/engine/multiplexer_edge/hunt_piece.sh <name> <layouts> <seed> [edge.py options]
# appends to results-hunt-debug-<name>.txt and results-hunt-release-<name>.txt. It builds the probe
# in release and then DEBUG first (copies in build/edge-release and build/edge-debug), so make
# test's DEBUG build is back afterwards. Exit 0 = both hunts passed.
#
# The pieces behind the results files (delete the files first to reproduce them from scratch):
#   hunt_piece.sh uniform    750 1 --hunt-mode uniform
#   hunt_piece.sh uniform    750 2 --hunt-mode uniform
#   hunt_piece.sh mixed-wide 750 1 --hunt-mode mixed --hunt-space wide
#   hunt_piece.sh mixed-wide 750 2 --hunt-mode mixed --hunt-space wide
#   hunt_piece.sh flicker    400 1 --hunt-mode flicker
#   hunt_piece.sh flicker    400 2 --hunt-mode flicker
#   hunt_piece.sh flicker    400 3 --hunt-mode flicker
# and, DEBUG only, appended by hand to results-hunt-debug-mixed-wide.txt (a longer climb from the
# cycle-51 layout that mixed-wide piece 1 found; seeds 11 and 12):
#   edge.py --hunt 1 --seed 11 --climb 450 --hunt-mode mixed --hunt-space wide \
#           --hunt-start 89,5,2,2,4,2,2,2,2,2,2,6,2,3,5,4,2,4,4,2,4,2
# (results-hunt-debug.txt and results-hunt-release.txt are the original mixed hunt:
#  edge.py --hunt 1500, one run a build.)
set -u
[ $# -ge 3 ] || { echo "usage: $0 <name> <layouts> <seed> [edge.py options]"; exit 2; }
NAME=$1; N=$2; SEED=$3; shift 3
ROOT=$(git rev-parse --show-toplevel) || exit 2
cd "$ROOT" || exit 2
R=tests/engine/multiplexer_edge
for b in release debug; do
    make -s GAME=multiplexer_edge SRC_DIR=$R BUILD=$b >/dev/null 2>&1 || { echo "$b build failed"; exit 2; }
    mkdir -p build/edge-$b
    cp build/multiplexer_edge/multiplexer_edge.prg build/multiplexer_edge/main.vs build/edge-$b/
done
for b in debug release; do
    (
        tmp=$(mktemp)
        uv run --package budget-runner python $R/edge.py --prg build/edge-$b/multiplexer_edge.prg \
            --hunt "$N" --seed "$SEED" "$@" > "$tmp" 2>&1
        echo "exit $?" >> "$tmp"
        { echo "==== hunt_piece.sh $NAME $N $SEED $*"; cat "$tmp"; echo; } >> $R/results-hunt-$b-$NAME.txt
        rm -f "$tmp"
    ) &
done
wait
rc=0
for b in debug release; do
    tail -4 $R/results-hunt-$b-$NAME.txt | grep -q '^exit 0' || rc=1
    grep -E '^hunt: (closest|[0-9])|^hunt RESULT|^exit' $R/results-hunt-$b-$NAME.txt | tail -6 | cut -c1-230
done
exit $rc
