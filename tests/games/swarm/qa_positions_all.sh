#!/bin/sh
# F3 driver: positions and slack on the game, DEBUG and release, in parallel (one VICE each).
# Run from the repo root after: make GAME=swarm; make BUILD=release GAME=swarm
#   sh tests/games/swarm/qa_positions_all.sh [frames-per-run (default 3000)]
# Output: tests/games/swarm/qa_results/positions_<build>_wave<N>.txt and slack_<build>_wave<N>.txt
F=${1:-3000}
R=tests/games/swarm/qa_results
P="uv run --package budget-runner python tests/games/swarm/qa_positions.py"
for b in debug release; do
  prg=build/swarm/swarm.prg; [ $b = release ] && prg=build/swarm-release/swarm.prg
  for w in 1 3 12 20; do
    $P --frames $F --wave $w --seed-wait $w --bot-seed $w --prg $prg > $R/positions_${b}_wave$w.txt 2>&1 &
  done
done
wait
for b in debug release; do
  prg=build/swarm/swarm.prg; [ $b = release ] && prg=build/swarm-release/swarm.prg
  for w in 1 3 12 20; do
    $P --slack --frames $F --wave $w --seed-wait $w --bot-seed $((w+10)) --prg $prg > $R/slack_${b}_wave$w.txt 2>&1 &
  done
done
wait
