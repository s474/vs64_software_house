"""Model check of engine/collision.asm: the 6502 routines against a Python model of the boxes.

The model is the plain definition: two boxes overlap when neither is wholly left of, right of,
above or below the other, with the design's hit boxes (docs/games/swarm/design.md#hit-boxes) typed
here once more; a hidden sprite (Y = MUX_OFF) overlaps nothing. It shares no arithmetic with the
module (which uses one subtraction and one unsigned compare per axis).

Parts (PASS/FAIL each, exit code 1 on any failure):

  T  tables   The spike's box table (spike_boxes) is the design's, and its col_pairs rows are the
              ColPair encoding of them: (ax0 - bx1) & $FF, 256 - range_x, (ay1 - by0) & $FF, range_y.
  D  demo     The spike's own frames (engine/collision.md, spike item 1): the machine is stopped at
              spike_frame_done in each of --frames frames (default 2,000), the 24 positions and the
              module's hit arrays are read, and every one of the frame's 42 pairs is compared with
              the model: no false hit, no missed hit. Also spike_mismatch_count (the spike's 6502
              reference test) = 0 and spike_overrun_count = 0 at the end.
  Scenes, through the spike's harness (spike_scene): the script writes all 24 positions into the
  multiplexer's arrays, and the C64 runs collision_begin(a, pair), collision_one on every target,
  then collision_range(last, first) and collision_next until it reports no more. Compared: each
  collision_one carry (targets other than A), the list of targets the range returned and its
  order (highest index first, A itself left out), X and Y preserved by collision_begin, X
  preserved by collision_one.
  E  edges    For each pair and each of 15 positions of A (X on both sides of 255/256 and at
              both ends of 0-511; Y at MUX_Y_MIN, MUX_Y_MAX and between), B at EVERY offset from 3
              pixels outside the overlap rectangle to 3 pixels outside the other side, in X and
              in Y: so each of the four edges is crossed with every alignment of the other axis.
              Counted separately: B touching by exactly one pixel on each side (must hit) and
              one pixel apart on each side (must miss). 23 targets a scene, A's index rotating,
              range 23..0 (so A is inside its own range, and collision_next walks many hits).
  X  far      A and B at the same Y with X over the whole 9-bit range (0, 1, 23, 24, 254-258,
              487, 488, 510, 511 and more), every combination: no hit from 9-bit wrap-round.
  H  hidden   B hidden (MUX_OFF) at an X that would hit, for A at every Y in MUX_Y_MIN-MUX_Y_MAX;
              A hidden, for B at every Y and hidden; nothing may be reported.
  N  next     Scenes built to have 2-6 overlapping targets inside the range, some hidden ones and
              A in the middle: collision_next returns the second, third, ... in order.
  R  random   --random scenes (default 400, seed 20261002): random pair, A, range and positions
              (clustered round A so that about a quarter overlap; one in ten hidden; X anywhere in
              0-511 for the rest): 23 pairs a scene.

Run from the repo root (build first: make GAME=collision SRC_DIR=tests/engine/collision):

    uv run --package budget-runner python tests/engine/collision/check.py [--prg build/collision/collision.prg]
                                                                           [--frames 2000] [--random 400]

About 8 s. Works on a release build too (make BUILD=release ...): it uses no DEBUG label.
`make test` runs it as the spike's last check (kind "script").
"""

import argparse
import random
import sys
from pathlib import Path

from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice
from vice_monitor import CPU_OP_EXEC  # on sys.path once budget_runner.session is imported

REPO = Path(__file__).resolve().parents[3]
MUX_COUNT, MUX_OFF, MUX_Y_MIN, MUX_Y_MAX = 24, 0xFF, 30, 221
SEED = 20261002

# docs/games/swarm/design.md#hit-boxes: columns x0-x1, rows y0-y1, inclusive
PLAYER, ENEMY, PSHOT, ESHOT = (6, 17, 6, 20), (4, 19, 3, 17), (11, 12, 0, 7), (11, 12, 14, 20)
PAIRS = [(PSHOT, ENEMY), (PLAYER, ESHOT), (PLAYER, ENEMY)]  # engine/collision.md#data-the-game-provides
PAIR_NAMES = ["player shot / enemy", "player / enemy shot", "player / enemy"]


def overlap(pair: int, a: tuple[int, int], b: tuple[int, int]) -> bool:
    """The model. a, b = (x, y) sprite positions."""
    (ax0, ax1, ay0, ay1), (bx0, bx1, by0, by1) = PAIRS[pair]
    (ax, ay), (bx, by) = a, b
    if ay == MUX_OFF or by == MUX_OFF:
        return False
    return not (ax + ax1 < bx + bx0 or bx + bx1 < ax + ax0 or ay + ay1 < by + by0 or by + by1 < ay + ay0)


def window(pair: int) -> tuple[int, int, int, int]:
    """B - A offsets that overlap: dx0..dx1, dy0..dy1."""
    (ax0, ax1, ay0, ay1), (bx0, bx1, by0, by1) = PAIRS[pair]
    return ax0 - bx1, ax1 - bx0, ay0 - by1, ay1 - by0


class Scene:
    def __init__(self, pair, a, first, last, pos, tag=None):
        self.pair, self.a, self.first, self.last, self.pos, self.tag = pair, a, first, last, pos, tag or {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prg", default=str(REPO / "build/collision/collision.prg"))
    ap.add_argument("--frames", type=int, default=2000)
    ap.add_argument("--random", type=int, default=400)
    a = ap.parse_args()
    fails = []

    def rep(name, ok, text):
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {text}")
        if not ok:
            fails.append(name)

    v = Vice(Path(a.prg), 20)
    try:
        mon, sym = v.mon, v.symbols

        def mem(name, size=1):
            return mon.mem_get(sym[name], sym[name] + size - 1)

        def run_to(label):
            mon.exit()
            if not mon.wait_stopped(STOP_TIMEOUT):
                mon.ping()
                raise MeasureError(f"{label} not reached: jam?")

        # ---- T
        boxes = list(mem("spike_boxes", 24))
        want_boxes = [n for pa, pb in PAIRS for n in pa + pb]
        rows = list(mem("col_pairs", 12))
        want_rows = []
        for pa, pb in PAIRS:
            rx = (pa[1] - pa[0]) + (pb[1] - pb[0]) + 1
            ry = (pa[3] - pa[2]) + (pb[3] - pb[2]) + 1
            want_rows += [(pa[0] - pb[1]) & 0xFF, 256 - rx, (pa[3] - pb[2]) & 0xFF, ry]
        rep("T tables", boxes == want_boxes and rows == want_rows,
            f"spike_boxes = the design's 3 pairs; col_pairs = {' '.join(f'{x:02x}' for x in rows)}"
            + ("" if rows == want_rows else f", expected {' '.join(f'{x:02x}' for x in want_rows)}"))

        # ---- D
        cp = mon.checkpoint_set(sym["spike_frame_done"], sym["spike_frame_done"], CPU_OP_EXEC)
        pairs_d = hits_d = bad_d = 0
        first_bad = None
        phases = {"M": 0, "W": 0, "B": 0}
        frames_hit = 0
        for f in range(a.frames):
            run_to("spike_frame_done")
            arr = mem("mux_x_lo", 73)       # mux_x_lo 24, mux_x_hi 24, mux_y 25
            pos = [(arr[i] | (arr[24 + i] & 1) << 8, arr[48 + i]) for i in range(24)]
            got = mem("spike_hits0", 72)    # hits0, hits1, hitsp
            h0, h1, hp, ptgt = list(got[0:24]), list(got[24:48]), list(got[48:72]), list(mem("spike_ptgt", 3))
            t = mem("spike_t")[0]
            phases["M" if t < 224 else "W" if t < 240 else "B"] += 1
            w0, w1, wp = [0] * 24, [0] * 24, [0] * 24
            for b in range(6, 24):
                w0[b] = int(overlap(0, pos[4], pos[b]))
                w1[b] = int(overlap(0, pos[5], pos[b]))
            for b in range(1, 4):
                wp[b] = int(overlap(1, pos[0], pos[b]))
            for b in ptgt:
                wp[b] = int(overlap(2, pos[0], pos[b]))
            n = sum(w0) + sum(w1) + sum(wp)
            wp[4], wp[5] = int(any(w0)), int(any(w1))
            wp[0] = int(any(wp[1:4]) or any(wp[b] for b in ptgt))
            pairs_d += 42
            hits_d += n
            frames_hit += bool(n)
            if (h0, h1, hp) != (w0, w1, wp):
                bad_d += 1
                first_bad = first_bad or (f, t, pos, (h0, h1, hp), (w0, w1, wp))
        mon.checkpoint_delete(cp.number)
        mism, over = mem("spike_mismatch_count")[0], mem("spike_overrun_count")[0]
        bbad = mem("spike_border_bad")[0]
        runs = int.from_bytes(mem("spike_border_runs", 2), "little")
        skips = int.from_bytes(mem("spike_border_skips", 2), "little")
        rep("D demo", bad_d == 0 and hits_d > 0 and a.frames >= 2000,
            f"{a.frames} frames ({phases['M']} moving, {phases['W']} worst mix, {phases['B']} border), "
            f"{pairs_d} pairs, {hits_d} overlaps in {frames_hit} frames: {a.frames - bad_d} frames match the model"
            + (f"; first mismatch (frame, spike_t, positions, got, want) {first_bad}" if bad_d else "")
            + ("" if a.frames >= 2000 else " (fewer than the contract's 2,000 frames)"))
        rep("D spike counters", mism == 0 and over == 0 and bbad == 0 and runs > 0 and skips == 0,
            f"spike_mismatch_count {mism}, spike_overrun_count {over}, spike_border_bad {bbad}, "
            f"border passes run in {runs} frames, skipped in {skips}")

        # ---- scenes
        cp = mon.checkpoint_set(sym["spike_frame"], sym["spike_frame"], CPU_OP_EXEC)
        run_to("spike_frame")
        mon.checkpoint_delete(cp.number)
        cp = mon.checkpoint_set(sym["spike_scene_done"], sym["spike_scene_done"], CPU_OP_EXEC)

        def run_scene(s: Scene):
            xs = [p[0] for p in s.pos]
            mon.mem_set(sym["mux_x_lo"], bytes([x & 0xFF for x in xs] + [x >> 8 for x in xs] + [p[1] for p in s.pos]))
            mon.mem_set(sym["spike_cmd"], bytes([1, s.a, s.pair, s.first, s.last]))
            run_to("spike_scene_done")
            out = mem("spike_sc_flags", 2 + 25 + 24)
            flags, n, lst, one = out[0], out[1], list(out[2:27]), list(out[27:51])
            return flags, lst[:min(n, 25)], one

        def check(scenes: list[Scene]):
            """Returns (scenes, pair tests, model overlaps, mismatches, first mismatch, range hits returned)."""
            tests = hits = bad = rhits = 0
            first = None
            for s in scenes:
                flags, lst, one = run_scene(s)
                want_one = [int(overlap(s.pair, s.pos[s.a], s.pos[t])) for t in range(24)]
                want_lst = [t for t in range(s.last, s.first - 1, -1) if t != s.a and want_one[t]]
                ok = flags == 0 and lst == want_lst and all(
                    one[t] == want_one[t] for t in range(24) if t != s.a) and all(o & 0x80 == 0 for o in one)
                tests += 23
                hits += sum(want_one[t] for t in range(24) if t != s.a)
                rhits += len(want_lst)
                if not ok:
                    bad += 1
                    first = first or dict(pair=s.pair, a=s.a, first=s.first, last=s.last, pos=s.pos, flags=flags,
                                          got_list=lst, want_list=want_lst, got_one=one, want_one=want_one)
            return len(scenes), tests, hits, bad, first, rhits

        def pack(pair, apos, bpos_list, rot, tags=None):
            """Scenes of 23 targets each from a list of B positions; A's index rotates from `rot`."""
            out = []
            for i in range(0, len(bpos_list), 23):
                chunk = bpos_list[i:i + 23]
                ai = (rot + len(out)) % 24
                pos = [(0, MUX_OFF)] * 24
                pos[ai] = apos
                slots = [t for t in range(24) if t != ai]
                for t, b in zip(slots, chunk):
                    pos[t] = b
                out.append(Scene(pair, ai, 0, 23, pos))
            return out

        # ---- E
        anchors = [(100, 120), (250, 120), (255, 120), (256, 120), (262, 120), (300, 120), (24, 120), (0, 120),
                   (488, 120), (511, 120), (250, MUX_Y_MIN), (250, MUX_Y_MAX), (256, MUX_Y_MIN + 14),
                   (255, MUX_Y_MAX - 14), (171, MUX_Y_MAX)]
        e_scenes, edge = [], {k: 0 for k in ("touch left", "touch right", "touch top", "touch bottom",
                                             "apart left", "apart right", "apart top", "apart bottom")}
        e_points = e_skipped = 0
        across = set()
        for pair in range(3):
            dx0, dx1, dy0, dy1 = window(pair)
            for ax, ay in anchors:
                pts = []
                for dy in range(dy0 - 3, dy1 + 4):
                    for dx in range(dx0 - 3, dx1 + 4):
                        bx, by = ax + dx, ay + dy
                        if not (0 <= bx <= 511 and MUX_Y_MIN <= by <= MUX_Y_MAX):
                            e_skipped += 1
                            continue
                        pts.append((bx, by))
                        inx, iny = dx0 <= dx <= dx1, dy0 <= dy <= dy1
                        if iny:
                            edge["touch left"] += dx == dx0
                            edge["touch right"] += dx == dx1
                            edge["apart left"] += dx == dx0 - 1
                            edge["apart right"] += dx == dx1 + 1
                            if (ax < 256) != (bx < 256):
                                across.add((pair, dx))
                        if inx:
                            edge["touch top"] += dy == dy0
                            edge["touch bottom"] += dy == dy1
                            edge["apart top"] += dy == dy0 - 1
                            edge["apart bottom"] += dy == dy1 + 1
                e_points += len(pts)
                e_scenes += pack(pair, (ax, ay), pts, len(e_scenes))
        n, tests, hits, bad, first, rh = check(e_scenes)
        rep("E edges", bad == 0 and all(edge.values()),
            f"{n} scenes, {e_points} positions of B round {len(anchors)} positions of A x 3 pairs "
            f"({e_skipped} outside X 0-511 or Y {MUX_Y_MIN}-{MUX_Y_MAX} left out): {hits} overlap, {e_points - hits} don't; "
            f"{n - bad} scenes match. One-pixel cases: " + ", ".join(f"{k} {c}" for k, c in edge.items())
            + f"; {len(across)} (pair, X offset) cases with A and B on opposite sides of X 255/256"
            + (f"; first mismatch {first}" if bad else ""))

        # ---- X
        xs = [0, 1, 2, 23, 24, 100, 232, 233, 254, 255, 256, 257, 258, 279, 280, 300, 487, 488, 489, 510, 511]
        x_scenes, x_pts = [], 0
        for pair in range(3):
            dy = window(pair)[2]            # B's lowest line that still overlaps: one line shared
            for ax in xs:
                pts = [(bx, 120 + dy) for bx in xs] + [(bx, 120) for bx in xs]
                x_pts += len(pts)
                x_scenes += pack(pair, (ax, 120), pts, len(x_scenes))
        n, tests, hits, bad, first, rh = check(x_scenes)
        rep("X far", bad == 0, f"{n} scenes, {x_pts} pairs with X of A and of B from {xs}: {hits} overlap, "
            f"{x_pts - hits} don't; {n - bad} scenes match" + (f"; first mismatch {first}" if bad else ""))

        # ---- H
        h_scenes, h_pairs = [], 0
        ys = list(range(MUX_Y_MIN, MUX_Y_MAX + 1))
        for pair in range(3):
            dx0, dx1, dy0, dy1 = window(pair)
            for ay in ys:                       # B hidden: A at every Y, 23 hidden targets at overlapping X
                ai = ay % 24
                pos = [(250 + dx0 + (t % (dx1 - dx0 + 1)), MUX_OFF) for t in range(24)]
                pos[ai] = (250, ay)
                h_scenes.append(Scene(pair, ai, 0, 23, pos))
                h_pairs += 23
            for i in range(0, len(ys) + 1, 23):  # A hidden: B at every Y (and hidden), X overlapping
                chunk = ys[i:i + 23] + [MUX_OFF]
                pts = [(250 + (dx0 + dx1) // 2, y) for y in chunk]
                sc = pack(pair, (250, MUX_OFF), pts, len(h_scenes))
                h_scenes += sc
                h_pairs += len(pts)
        n, tests, hits, bad, first, rh = check(h_scenes)
        rep("H hidden", bad == 0 and hits == 0 and rh == 0,
            f"{n} scenes, {h_pairs} pairs with A or B (or both) at MUX_OFF, X overlapping, the other at every Y "
            f"{MUX_Y_MIN}-{MUX_Y_MAX}: {hits} overlaps in the model, {rh} reported; {n - bad} scenes match"
            + (f"; first mismatch {first}" if bad else ""))

        # ---- N
        rnd = random.Random(SEED)
        n_scenes, multi = [], {}
        for i in range(120):
            pair = i % 3
            dx0, dx1, dy0, dy1 = window(pair)
            ai = rnd.randrange(24)
            apos = (rnd.choice([120, 250, 256, 300]), rnd.randrange(MUX_Y_MIN + 25, MUX_Y_MAX - 24))
            pos = []
            for t in range(24):
                r = rnd.random()
                if r < 0.3:
                    pos.append((apos[0] + rnd.randint(dx0, dx1), apos[1] + rnd.randint(dy0, dy1)))   # overlaps
                elif r < 0.45:
                    pos.append((apos[0] + rnd.randint(dx0, dx1), MUX_OFF))
                else:
                    pos.append((apos[0] + rnd.choice([dx0 - 1, dx1 + 1, 0]), apos[1] + rnd.choice([dy0 - 1, dy1 + 1])))
            pos[ai] = apos
            first = rnd.randrange(0, 12)
            last = rnd.randrange(first, 24)
            if i % 2 == 0:
                first, last = min(first, ai), max(last, ai)       # A inside its own range
            s = Scene(pair, ai, first, last, pos)
            k = sum(1 for t in range(first, last + 1) if t != ai and overlap(pair, apos, pos[t]))
            multi[k] = multi.get(k, 0) + 1
            n_scenes.append(s)
        n, tests, hits, bad, first, rh = check(n_scenes)
        many = sum(c for k, c in multi.items() if k >= 3)
        rep("N next", bad == 0 and many >= 20,
            f"{n} scenes, {rh} hits returned by collision_range + collision_next, all in order; hits per scan: "
            + ", ".join(f"{k}: {multi[k]}" for k in sorted(multi)) + f" scenes ({many} with 3 or more; A inside the "
            f"range in {n // 2}); {n - bad} scenes match" + (f"; first mismatch {first}" if bad else ""))

        # ---- R
        r_scenes = []
        for i in range(a.random):
            pair = rnd.randrange(3)
            dx0, dx1, dy0, dy1 = window(pair)
            ai = rnd.randrange(24)
            apos = (rnd.randrange(512), rnd.randrange(MUX_Y_MIN, MUX_Y_MAX + 1))
            pos = []
            for t in range(24):
                r = rnd.random()
                if r < 0.1:
                    pos.append((rnd.randrange(512), MUX_OFF))
                elif r < 0.65:
                    x = min(511, max(0, apos[0] + rnd.randint(dx0 - 12, dx1 + 12)))
                    y = min(MUX_Y_MAX, max(MUX_Y_MIN, apos[1] + rnd.randint(dy0 - 12, dy1 + 12)))
                    pos.append((x, y))
                else:
                    pos.append((rnd.randrange(512), rnd.randrange(MUX_Y_MIN, MUX_Y_MAX + 1)))
            pos[ai] = apos
            first = rnd.randrange(24)
            last = rnd.randrange(first, 24)
            r_scenes.append(Scene(pair, ai, first, last, pos))
        n, tests, hits, bad, first, rh = check(r_scenes)
        rep("R random", bad == 0 and tests >= 2000,
            f"{n} scenes (seed {SEED}), {tests} pairs: {hits} overlap, {tests - hits} don't; {rh} hits returned by "
            f"ranges; {n - bad} scenes match" + (f"; first mismatch {first}" if bad else ""))
        total = (len(e_scenes) + len(x_scenes) + len(h_scenes) + len(n_scenes) + len(r_scenes)) * 23
        mon.checkpoint_delete(cp.number)
    finally:
        v.close()

    print(("\nFAILED: " + ", ".join(fails)) if fails else
          f"\nALL PASS: {pairs_d} pairs in {a.frames} demo frames and {total} target tests in scenes match the model")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL (jam/hang): {e}")
        sys.exit(2)
