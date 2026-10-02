"""Checks the numbers in docs/games/swarm/design.md. No emulator, no dependencies (stdlib only).

Run from the repo root:

    uv run python tests/games/swarm/check_design.py | tee tests/games/swarm/check_design_results.txt

What it does:
  1. Static checks: formation and drift stay on screen, the player's crossing time, each dive
     path's length, end point, lowest point, lethal steps and firing heights.
  2. The smallest row spacing at which three parked rows of 6 are all shown, by the multiplexer's
     own selection rule (engine/README.md, "Scheduling, and the minimum vertical separation").
  3. A worst-case play simulation of every wave pattern at every speed loop: nothing ever dies
     (the formation stays full), the player sweeps the screen firing at the maximum rate, and
     divers and enemy shots follow the design's rules. Each frame goes through a Python model of
     the multiplexer's selection (fit rule, fair flicker, pinned sprites: engine/README.md,
     "Overflow: fair flicker" and "Pinned sprites"), which reports who was dropped.
  4. How many enemy explosions can run at once (design.md "Explosions at once"): a bound from
     the shot rules, and a schedule that reaches it, replayed against the two-slot rule.
     Explosions are NOT in the play simulation, and don't need to be: an explosion is drawn in
     the dead enemy's own virtual sprite, where it is, and the simulation's enemies never die,
     so every enemy sprite is already counted in every frame.

The multiplexer model is a transcription of the README's pseudocode, not the engine: its
figures are design estimates until QA's positions.py runs on the real game (M4 deliverable 6).
The data tables below are the same as the design doc's. If one changes, change both.
"""
import random

# ---- Engine constants (engine/README.md) ----
MUX_Y_MIN, MUX_Y_MAX = 30, 221
FREE_AFTER, IRQ_LINES, WRITE_LINES = 22, 1, 2
WIN_UP, WIN_DOWN = 38, 25          # the exact guarantee's window: Y-38 .. Y+25
OFF = 255

# ---- Design data (docs/games/swarm/design.md) ----
ROW_Y = [56, 96, 136]
FORM_X0, COL_DX, DRIFT_MAX = 34, 36, 96
PLAYER_Y, PLAYER_XMIN, PLAYER_XMAX, PLAYER_SPEED = 221, 24, 318, 3
PSHOT_SPEED, PSHOT_SPAWN_Y, PSHOT_KILL_Y, PSHOT_COOLDOWN = 8, 213, 46, 10
X_MIN, X_MAX = 0, 344              # diver and shot X clamp: both ends are off screen
VISIBLE_X = (24, 320)
FIRE_MAX_Y = 164                   # a diver below this doesn't fire
LETHAL_Y = 210                     # an enemy at Y >= this overlaps the player's hit box
ESHOT_HIT_Y = 207

# (dx, dy, steps); steps 0 = repeat until X leaves the screen. Authored heading right.
PATHS = {
    "hook":   dict(row=2, end="return", fire=[8, 16],
                   segs=[(1, 1, 8), (2, 2, 12), (1, 3, 12), (0, 2, 6), (-2, 0, 12), (-1, -2, 8)]),
    "sweep":  dict(row=1, end="wrap", fire=[24, 38, 62, 86],
                   segs=[(-1, 1, 8), (1, 2, 16), (2, 2, 14), (2, 0, 0)]),
    "plunge": dict(row=0, end="wrap", fire=[26, 36, 46],
                   segs=[(0, -1, 6), (1, 2, 20), (2, 3, 20), (1, 3, 16), (0, 2, 9),
                         (2, -1, 24), (2, 0, 0)]),
}
ROW_PATH = ["plunge", "sweep", "hook"]

# Per wave pattern (0-2), per loop (0, 1, 2, 3+)
INTERVAL = [[150, 120, 100, 80], [120, 100, 80, 64], [100, 80, 64, 50]]
MAX_DIVERS = [[1, 2, 2, 2], [2, 2, 3, 3], [2, 3, 3, 3]]
ROWS = [{2}, {1, 2}, {0, 1, 2}]
SHOTS_BASE = [1, 2, 2]
# Per loop
ESHOT_DY = [2, 2, 3, 3]
EXTRA_STEP_EVERY = [0, 4, 2, 2]    # a diver takes a second path step every Nth frame
WINDUP = [24, 20, 16, 12]
DRIFT_DIV = [2, 2, 1, 1]

# Virtual sprite allocation
V_PLAYER, V_ESHOT, V_PSHOT, V_ENEMY = 0, 1, 4, 6


# ---- Multiplexer selection model ----
def all_fit(ys):
    done = []
    for k, y in enumerate(ys):
        if k < 8:
            d = 18 + k                                   # README: slots 0-7 need Y >= 18 + slot
        else:
            d = max(ys[k - 8] + FREE_AFTER + IRQ_LINES, done[k - 1]) + WRITE_LINES
        if d > y:
            return False
        done.append(d)
    return True


def select(order, y, age, pinned):
    """Returns the set of virtual sprites shown this frame, and updates age."""
    kept, evictions = [], 0

    def youngest(lst):
        cand = [k for k in lst[-8:] if k not in pinned]
        if not cand:
            return None
        return min(cand, key=lambda k: (age[k], -lst.index(k)))

    for v in order:
        if not MUX_Y_MIN <= y[v] <= MUX_Y_MAX:
            continue
        if all_fit([y[k] for k in kept] + [y[v]]):
            kept.append(v)
        elif v in pinned:
            while evictions < 8 and not all_fit([y[k] for k in kept] + [y[v]]):
                w = youngest(kept)
                if w is None:
                    break
                kept.remove(w)
                evictions += 1
            if all_fit([y[k] for k in kept] + [y[v]]):
                kept.append(v)
        else:
            w = youngest(kept)
            if w is not None and age[v] > age[w]:
                trial = [k for k in kept if k != w]
                if all_fit([y[k] for k in trial] + [y[v]]):
                    kept = trial + [v]
    shown = set(kept)
    for v in range(24):
        if MUX_Y_MIN <= y[v] <= MUX_Y_MAX and v not in shown:
            age[v] += 1
        else:
            age[v] = 0
    return shown


# ---- Static checks ----
def walk(path, x=0, y=None, mirror=False, start_x=0):
    """Yields (step, x, y) for each step of a path, offsets from the start unless start_x given."""
    p = PATHS[path]
    y = ROW_Y[p["row"]] if y is None else y
    x, step = start_x, 0
    for dx, dy, n in p["segs"]:
        if mirror:
            dx = -dx
        count = 0
        while (count < n) if n else (X_MIN < x < X_MAX):
            x = max(X_MIN, min(X_MAX, x + dx))
            y += dy
            step += 1
            count += 1
            yield step, x, y


def static_checks():
    print("== Formation ==")
    left, right = FORM_X0, FORM_X0 + DRIFT_MAX + 5 * COL_DX
    print(f"sprite X of the formation over the drift: {left} .. {right} "
          f"(fully visible is {VISIBLE_X[0]} .. {VISIBLE_X[1]})")
    assert VISIBLE_X[0] <= left and right <= VISIBLE_X[1]
    print(f"rows Y {ROW_Y}: displayed lines "
          + ", ".join(f"{y + 1}-{y + 21}" for y in ROW_Y))
    for div in (2, 1):
        print(f"drift 1 px every {div} frame(s): one sweep {DRIFT_MAX * div} frames, "
              f"there and back {2 * DRIFT_MAX * div} frames")

    print("\n== Player ==")
    steps = (PLAYER_XMAX - PLAYER_XMIN) / PLAYER_SPEED
    print(f"crossing {PLAYER_XMIN} -> {PLAYER_XMAX} at {PLAYER_SPEED} px/frame: {steps:.0f} frames "
          f"= {steps / 50:.2f} s")
    n = 0
    y = PSHOT_SPAWN_Y
    while y >= PSHOT_KILL_Y:
        y -= PSHOT_SPEED
        n += 1
    print(f"player shot lifetime with no hit: {n} frames; to the bottom row (Y {ROW_Y[2]}): "
          f"{-(-(PSHOT_SPAWN_Y - ROW_Y[2] - 17) // PSHOT_SPEED)} frames")

    print("\n== Minimum row spacing, three parked rows of 6 (selection model) ==")
    for s in range(24, 42):
        ys = sorted([56 + s * r for r in range(3) for _ in range(6)])
        if all_fit(ys):
            print(f"smallest spacing with every sprite kept: {s} lines "
                  f"(the brief says 24; the README's guarantee needs 39; the design uses "
                  f"{ROW_Y[1] - ROW_Y[0]})")
            break

    print("\n== Dive paths (authored heading right, offsets from the launch position) ==")
    for name, p in PATHS.items():
        pts = list(walk(name, start_x=172))            # 172: a start that can't clamp early
        fixed = sum(n for _, _, n in p["segs"])
        at = {s: (x - 172, y) for s, x, y in pts}
        lethal = [s for s, x, y in pts if y >= LETHAL_Y]
        fires = [(s, at[s][1]) for s in p["fire"] if s in at]
        print(f"{name}: row {p['row']}, {fixed} fixed steps, ends '{p['end']}', "
              f"offset after the fixed steps {at[fixed]}, lowest Y {max(y for _, _, y in pts)}, "
              f"highest Y {min(y for _, _, y in pts)}")
        print(f"   lethal steps (Y >= {LETHAL_Y}): {len(lethal)}"
              + (f" (steps {lethal[0]}-{lethal[-1]})" if lethal else ""))
        print("   fire steps and the diver's Y there: " + ", ".join(f"{s}: Y {yy}" for s, yy in fires))
        assert all(yy <= FIRE_MAX_Y for _, yy in fires) and max(y for _, _, y in pts) <= MUX_Y_MAX
        if p["end"] == "wrap":
            worst = max(len(list(walk(name, start_x=sx, mirror=m)))
                        for sx in range(FORM_X0, FORM_X0 + DRIFT_MAX + 5 * COL_DX + 1)
                        for m in (False, True))
            print(f"   longest dive before it leaves the screen, any start and direction: {worst} steps")
        else:
            print(f"   return climb from the end: {(at[fixed][1] - ROW_Y[p['row']] + 1) // 2} frames")
    for dy in (2, 3):
        print(f"enemy shot fired at Y {FIRE_MAX_Y}, {dy} px/frame: "
              f"{-(-(ESHOT_HIT_Y - FIRE_MAX_Y) // dy)} frames to the player's hit box")
    print(f"wrap re-entry from Y 30 at 2 px/frame: "
          + ", ".join(f"row {r}: {(ROW_Y[r] - 30) // 2} frames" for r in (0, 1)))


# ---- Worst-case play simulation ----
KINDS = ["player", "enemy shot", "player shot", "parked enemy", "diver"]


def simulate(pattern, loop, frames, pin_shots, seed=1):
    rng = random.Random(seed)
    L = min(loop, 3)
    fx, fdir = DRIFT_MAX // 2, 1
    px, pdir, cooldown = 172, 1, 0
    pshots = [None, None]                      # [x, y]
    eshots = [None, None, None]                # [x, y, dx]
    # enemy: state P/W/D/R, x, y, plus dive bookkeeping
    en = [dict(st="P", x=0, y=0, row=e // 6, col=e % 6) for e in range(18)]
    timer = INTERVAL[pattern][L]
    order = list(range(24))
    age = [0] * 24
    pinned = {V_PLAYER} | ({1, 2, 3} if pin_shots else set())
    st = dict(max_window=0, drop_frames=0, max_run={k: 0 for k in KINDS},
              missing={k: 0 for k in KINDS}, shown_frames={k: 0 for k in KINDS},
              max_divers=0, max_eshots=0, max_shown_range=0, max_moved=0)
    prev_y = None

    for f in range(frames):
        # formation drift
        if f % DRIFT_DIV[L] == 0:
            fx += fdir
            if fx in (0, DRIFT_MAX):
                fdir = -fdir
        # player: sweep and fire at the maximum rate
        px += pdir * PLAYER_SPEED
        if px >= PLAYER_XMAX or px <= PLAYER_XMIN:
            px = max(PLAYER_XMIN, min(PLAYER_XMAX, px))
            pdir = -pdir
        cooldown = max(0, cooldown - 1)
        for s in pshots:
            if s:
                s[1] -= PSHOT_SPEED
        pshots = [s if s and s[1] >= PSHOT_KILL_Y else None for s in pshots]
        if cooldown == 0 and None in pshots:
            pshots[pshots.index(None)] = [px, PSHOT_SPAWN_Y]
            cooldown = PSHOT_COOLDOWN
        # enemy shots
        for s in eshots:
            if s:
                s[0] = max(X_MIN, min(X_MAX, s[0] + s[2]))
                s[1] += ESHOT_DY[L]
        eshots = [s if s and s[1] <= MUX_Y_MAX else None for s in eshots]
        # launches
        active = [e for e in en if e["st"] != "P"]
        if timer > 0:
            timer -= 1
        if timer == 0 and len(active) < MAX_DIVERS[pattern][L]:
            cand = [e for e in en if e["st"] == "P" and e["row"] in ROWS[pattern]]
            if cand:
                e = rng.choice(cand)
                e.update(st="W", t=WINDUP[L])
                timer = INTERVAL[pattern][L]
        # enemies
        for e in en:
            hx, hy = FORM_X0 + fx + COL_DX * e["col"], ROW_Y[e["row"]]
            if e["st"] in "PW":
                e["x"], e["y"] = hx, hy
            if e["st"] == "W":
                e["t"] -= 1
                if e["t"] == 0:
                    p = PATHS[ROW_PATH[e["row"]]]
                    e.update(st="D", path=p, seg=0, left=p["segs"][0][2], step=0,
                             mirror=px < e["x"], shots=min(len(p["fire"]), SHOTS_BASE[pattern] + L))
            elif e["st"] == "D":
                n = 2 if EXTRA_STEP_EVERY[L] and f % EXTRA_STEP_EVERY[L] == 0 else 1
                for _ in range(n):
                    if e["st"] != "D":
                        break
                    dx, dy, cnt = e["path"]["segs"][e["seg"]]
                    e["x"] = max(X_MIN, min(X_MAX, e["x"] + (-dx if e["mirror"] else dx)))
                    e["y"] += dy
                    e["step"] += 1
                    if (e["step"] in e["path"]["fire"][:e["shots"]] and e["y"] <= FIRE_MAX_Y
                            and VISIBLE_X[0] <= e["x"] <= VISIBLE_X[1] and None in eshots):
                        d = px - e["x"]
                        eshots[eshots.index(None)] = [e["x"], e["y"], 0 if abs(d) < 16 else (1 if d > 0 else -1)]
                    if cnt == 0:
                        if e["x"] in (X_MIN, X_MAX):           # off screen: wrap to the top
                            e.update(st="R", x=hx, y=30)
                    else:
                        e["left"] -= 1
                        if e["left"] == 0:
                            e["seg"] += 1
                            if e["seg"] == len(e["path"]["segs"]):
                                e["st"] = "R"
                            else:
                                e["left"] = e["path"]["segs"][e["seg"]][2]
            elif e["st"] == "R":
                e["x"] += max(-2, min(2, hx - e["x"]))
                e["y"] += max(-2, min(2, hy - e["y"]))
                if (e["x"], e["y"]) == (hx, hy):
                    e["st"] = "P"

        # the frame's virtual sprites
        y = [OFF] * 24
        kind = [None] * 24
        y[V_PLAYER], kind[V_PLAYER] = PLAYER_Y, "player"
        for i, s in enumerate(eshots):
            kind[V_ESHOT + i] = "enemy shot"
            if s:
                y[V_ESHOT + i] = s[1]
        for i, s in enumerate(pshots):
            kind[V_PSHOT + i] = "player shot"
            if s:
                y[V_PSHOT + i] = s[1]
        for i, e in enumerate(en):
            y[V_ENEMY + i] = e["y"]
            kind[V_ENEMY + i] = "parked enemy" if e["st"] in "PW" else "diver"

        order.sort(key=lambda v: y[v])                    # stable, like the persistent insertion sort
        shown = select(order, y, age, pinned)
        in_range = [v for v in range(24) if MUX_Y_MIN <= y[v] <= MUX_Y_MAX]
        for v in in_range:
            st["max_window"] = max(st["max_window"],
                                   sum(1 for w in in_range if y[v] - WIN_UP <= y[w] <= y[v] + WIN_DOWN))
            st["shown_frames"][kind[v]] += 1
            if v not in shown:
                st["missing"][kind[v]] += 1
            st["max_run"][kind[v]] = max(st["max_run"][kind[v]], age[v])
        if len(shown) < len(in_range):
            st["drop_frames"] += 1
        if prev_y:
            st["max_moved"] = max(st["max_moved"],
                                  sum(1 for v in range(24) if abs(y[v] - prev_y[v]) > 8))
        prev_y = y
        st["max_divers"] = max(st["max_divers"], sum(1 for e in en if e["st"] in "DR"))
        st["max_eshots"] = max(st["max_eshots"], sum(1 for s in eshots if s))
        st["max_shown_range"] = max(st["max_shown_range"], len(in_range))
    return st


def play_checks(frames=6000):
    for pin_shots, label in ((True, "player + 3 enemy shots pinned (the design)"),
                             (False, "player only pinned (the alternative)")):
        print(f"\n== Worst-case play, {frames} frames each, {label} ==")
        print("wave loop | max in window | frames with a drop | missing sprite-frames % "
              "(longest run) per kind: player, enemy shot, player shot, parked enemy, diver "
              "| max divers, enemy shots, sprites in range, sprites moving > 8 lines in a frame")
        for loop in range(4):
            for pattern in range(3):
                s = simulate(pattern, loop, frames, pin_shots)
                cells = []
                for k in KINDS:
                    n = s["shown_frames"][k]
                    pct = 100 * s["missing"][k] / n if n else 0
                    cells.append(f"{pct:.2f}% ({s['max_run'][k]})")
                print(f"  {pattern + 1}    {loop}   | {s['max_window']:2d} | "
                      f"{100 * s['drop_frames'] / frames:5.2f}% | " + ", ".join(cells)
                      + f" | {s['max_divers']}, {s['max_eshots']}, {s['max_shown_range']}, {s['max_moved']}")
                assert s["missing"]["player"] == 0
                if pin_shots:
                    assert s["missing"]["enemy shot"] == 0

    print("\n== Full formation, player and player shots, before the first launch ==")
    s = simulate(0, 0, 100, True)        # no launch in the first 100 frames (interval 150)
    print(f"frames with a drop before the first launch: {s['drop_frames']} of 100")
    assert s["drop_frames"] == 0


# ---- Explosions at once ----
EXPLOSION_FRAMES = 16               # the hit's frame and the 15 after it
PSHOT_MISS_FRAMES = 21              # a shot that hits nothing: spawn frame + 20, gone in the 21st


def hits_bound(flights):
    """Most player-shot hits in any EXPLOSION_FRAMES frames. Shot i spawns at s_i >= s_1 +
    10 (i - 1) and hits at s_i + flight, so k hits span at least 10 (k - 1) - (longest flight -
    shortest flight) frames, and all k explosions overlap only if that span is <= 15."""
    k = 1
    while PSHOT_COOLDOWN * k - (max(flights) - min(flights)) <= EXPLOSION_FRAMES - 1:
        k += 1
    return k


def replay(schedule):
    """schedule: (spawn frame, flight) per shot. Checks the cooldown and the two slots (a slot
    freed by a hit in frame h can fire in frame h: Stage 1 rule 3c). Returns the hit frames."""
    for i, (s, _) in enumerate(schedule):
        if i:
            assert s - schedule[i - 1][0] >= PSHOT_COOLDOWN
        assert sum(1 for s2, f2 in schedule[:i] if s2 <= s < s2 + f2) <= 1, "no free slot"
    hits = sorted(s + f for s, f in schedule)
    assert hits[-1] - hits[0] <= EXPLOSION_FRAMES - 1
    return hits


def explosion_checks():
    print("\n== Explosions at once (16 frames each; shots 10 frames apart, 2 slots) ==")
    parked = [-(-(PSHOT_SPAWN_Y - y - 17) // PSHOT_SPEED) for y in ROW_Y]      # 18, 13, 8
    anyf = list(range(1, PSHOT_MISS_FRAMES))                                   # 1 .. 20
    for label, flights, sched in (
            ("every target parked", parked, [(0, 18), (10, 13), (20, 8)]),
            ("divers too (stage 3)", anyf, [(0, 20), (10, 6), (20, 11), (30, 1)])):
        b = hits_bound(flights)
        hits = replay(sched)
        assert len(sched) == b and all(f in flights for _, f in sched)
        print(f"{label}: flights {min(flights)}-{max(flights)} frames: at most {b} hits in any "
              f"{EXPLOSION_FRAMES} frames; reached by (spawn, flight) {sched}: hits in frames {hits}")
    print("plus one enemy ramming the player in the same 16 frames: 5 enemy explosions wanted, "
          "4 slots: the 5th dies without one")


if __name__ == "__main__":
    static_checks()
    explosion_checks()
    play_checks()
