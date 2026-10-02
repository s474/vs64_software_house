"""QA probe: is any ship position safer than the others? (M4 stage 5, tester's question after the MCP playthrough,
where a ship parked at the right edge survived 400 frames in wave 1 and one in the middle died within 100.)

Run from the repo root (DEBUG build first):

    uv run --package budget-runner python tests/games/swarm/qa_camp.py X [--frames 4000] [--waves 1,3,12]

The ship walks to X (24-318, in steps of 3), then stands still with fire held (so the formation is shot at
the same way), no dodging. Each wave is held (every Clear puts the stores back, so the same wave comes round
again), the ship is vulnerable, and a game over starts a new game by itself. Counts the hits (entries into
PlayerDying) in --frames game frames per wave; the figure to compare is hits per 1,000 frames of Play.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import *  # noqa: E402,F403
from qa_soak import Soak  # noqa: E402


def run(x, wave, frames):
    s = Soak(f"camp{x}-w{wave}", wave=wave, safe=False)
    g = s.g
    s.start_game()
    hits = play = 0
    prev = GS_PLAY
    for _ in range(frames):
        gs = g.gstate()
        if gs == GS_TITLE:
            s.frame(0); s.frame(0)
            s.frame(BITS["fire"])
            s.placed = False
            prev = GS_PLAY
            continue
        px = g.player_x()
        stick = BITS["fire"]
        if px < x - 2:
            stick |= BITS["right"]
        elif px > x + 2:
            stick |= BITS["left"]
        s.frame(stick)
        ngs = g.gstate()
        play += ngs == GS_PLAY
        if ngs == GS_DYING and prev != GS_DYING:
            hits += 1
        prev = ngs
    s.g.close()
    return hits, play


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("x", type=int)
    ap.add_argument("--frames", type=int, default=4000)
    ap.add_argument("--waves", default="1,3,12")
    a = ap.parse_args()
    for w in (int(v) for v in a.waves.split(",")):
        hits, play = run(a.x, w, a.frames)
        print(f"X {a.x:3d} wave {w:2d}: {hits} hits in {play} frames of Play = {1000.0 * hits / max(1, play):.2f} per 1,000 frames", flush=True)


if __name__ == "__main__":
    main()
