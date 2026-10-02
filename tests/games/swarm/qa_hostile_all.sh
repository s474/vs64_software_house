#!/bin/sh
# F3, hostile layouts (--hostile): positions and slack on the game, DEBUG and release, in parallel.
# Run from the repo root after: make GAME=swarm; make BUILD=release GAME=swarm
#   sh tests/games/swarm/qa_hostile_all.sh [frames-per-run (default 3000)]
# Output: tests/games/swarm/qa_results/hostile_{positions,slack}_<build>_<n>.txt
F=${1:-3000}
R=tests/games/swarm/qa_results
P="uv run --package budget-runner python tests/games/swarm/qa_positions.py"
for b in debug release; do
  prg=build/swarm/swarm.prg; [ $b = release ] && prg=build/swarm-release/swarm.prg
  for n in 1 2 3 4; do
    $P --hostile --frames $F --wave $((n*4-3)) --seed-wait $n --bot-seed $((n+20)) --prg $prg > $R/hostile_positions_${b}_$n.txt 2>&1 &
  done
done
wait
for b in debug release; do
  prg=build/swarm/swarm.prg; [ $b = release ] && prg=build/swarm-release/swarm.prg
  for n in 1 2 3 4; do
    $P --slack --hostile --frames $F --wave $((n*4-3)) --seed-wait $n --bot-seed $((n+30)) --prg $prg > $R/hostile_slack_${b}_$n.txt 2>&1 &
  done
done
wait
