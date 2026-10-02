#!/bin/sh
# Item 3 soak, every scenario of qa_soak.py in parallel (one VICE each, DEBUG build).
# Run from the repo root after: make GAME=swarm
#   sh tests/games/swarm/qa_soak_all.sh
# Output: tests/games/swarm/qa_results/soak_<scenario>.txt
R=tests/games/swarm/qa_results
P="uv run --package budget-runner python tests/games/swarm/qa_soak.py"
for s in wave3-passive wave3-play wave12-passive wave12-play; do $P $s --frames 12000 --seed 3 > $R/soak_$s.txt 2>&1 & done
for s in thin12 thin30; do for k in 5 6 7 8; do $P $s --frames 6000 --seed $k > $R/soak_${s}_s$k.txt 2>&1 & done; done
$P death3 --frames 12000 --seed 7 > $R/soak_death3.txt 2>&1 &
$P cycles --frames 60000 --seed 9 > $R/soak_cycles.txt 2>&1 &
$P clear --frames 60000 --seed 11 > $R/soak_clear.txt 2>&1 &
$P fifth > $R/soak_fifth.txt 2>&1 &
wait
for k in 21 22 23 24; do $P fuzz --frames 40000 --seed $k > $R/soak_fuzz_s$k.txt 2>&1 & done
wait
