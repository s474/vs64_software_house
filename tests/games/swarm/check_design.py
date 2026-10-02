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
  5. The play-area text (design.md "Text cells and the star rule"): which text rows no parked
     enemy and no ship covers, at every drift position; what can pass over the message row and
     when; the title's sprites against the title's text; the star bands and the free cells.
  6. The difficulty curve: launches and enemy shots a minute per wave, counted in the play
     simulation of 3 (a formation that stays full: the most the launcher can do).

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
              max_divers=0, max_eshots=0, max_shown_range=0, max_moved=0,
              launches=0, eshots_fired=0)
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
                st["launches"] += 1
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
                        st["eshots_fired"] += 1
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


# ---- Text layout (design.md "Text cells and the star rule") ----
MSG_ROW = 9                         # READY, GAME OVER, WAVE nn
OLD_MSG_ROW = 12                    # where they were until stage 3 found the bug
# (screen, row, text): every text is centred, first column (40 - n) div 2, but the scores
TEXTS = [("Title", 5, "SWARM"), ("Title", 9, "150 PTS"), ("Title", 11, " 80 PTS"),
         ("Title", 13, " 50 PTS"), ("Title", 16, "DIVING SCORES DOUBLE"), ("Title", 19, "PRESS FIRE"),
         ("Game", MSG_ROW, "WAVE 01"), ("Game", MSG_ROW, "READY"), ("Game", MSG_ROW, "GAME OVER")]
TEXT_COL = {"150 PTS": 17, " 80 PTS": 17, " 50 PTS": 17}
BAND_COLS = (10, 29)
TITLE_SPRITES = [(120, 119), (120, 135), (120, 151)]
STARS = 48
ENEMY_ART = (2, 21, 1, 19)          # the enemy art area: columns 2-21, rows 1-19 of the cell
PSHOT_ART = (11, 12, 0, 7)
ESHOT_ART = (11, 12, 14, 20)
DYING_MIN, RESPAWN_FRAMES, CLEAR_PAUSE = 100, 50, 75


def row_lines(r):
    return 51 + 8 * r, 58 + 8 * r


def col_of(text):
    return TEXT_COL.get(text, (40 - len(text)) // 2)


def text_x(text):
    """The text's cells as sprite X coordinates (X 24 = the window's left edge), inclusive."""
    c = col_of(text)
    return 24 + 8 * c, 24 + 8 * (c + len(text)) - 1


def overlap(a, b):
    return a[0] <= b[1] and b[0] <= a[1]


def sprite_lines(y, art=(0, 23, 0, 20)):
    return y + 1 + art[2], y + 1 + art[3]


def diver_frames_over(name, loop, lines, phase, start_x, mirror):
    """One dive, launched in frame 0 (t = 0 of its wind-up): the frames, counted from the launch,
    in which the diver's 21 lines overlap the text lines. Wind-up, Dive, wrap and Return."""
    p = PATHS[name]
    home_y = ROW_Y[p["row"]]
    frames, f, x, y = [], 0, start_x, home_y
    for _ in range(WINDUP[loop]):
        if overlap(sprite_lines(y), lines):
            frames.append(f)
        f += 1
    steps = list(walk(name, start_x=start_x, mirror=mirror))
    i = 0
    while i < len(steps):
        n = 2 if EXTRA_STEP_EVERY[loop] and (f + phase) % EXTRA_STEP_EVERY[loop] == 0 else 1
        i = min(len(steps), i + n)
        y = steps[i - 1][2]
        if overlap(sprite_lines(y), lines):
            frames.append(f)
        f += 1
    if p["end"] == "wrap":
        y = 30
    while y != home_y:                                  # Return: 2 lines a frame
        y += max(-2, min(2, home_y - y))
        if overlap(sprite_lines(y), lines):
            frames.append(f)
        f += 1
    return frames, f


def layout_checks():
    print("\n== Text rows against the formation and the ship (a sprite at Y is on lines Y + 1 .. Y + 21) ==")
    form = [(y + 1, y + 21) for y in ROW_Y]
    ship = (PLAYER_Y + 1, PLAYER_Y + 21)
    print("formation rows on lines " + ", ".join(f"{a}-{b}" for a, b in form)
          + f"; the ship on {ship[0]}-{ship[1]}; text row r is lines 51 + 8r .. 58 + 8r")
    free = [r for r in range(24) if not any(overlap(row_lines(r), s) for s in form + [ship])]
    print(f"text rows no parked enemy and no ship covers, at any drift position (Y never changes): {free}")
    assert free == [4, 9, 14, 15, 16, 17, 18, 19, 20]
    lo, hi = row_lines(OLD_MSG_ROW)
    print(f"the old message row {OLD_MSG_ROW}: lines {lo}-{hi}, inside formation row 2's {form[2][0]}-{form[2][1]}: "
          f"covered: {overlap((lo, hi), form[2])}")
    assert overlap((lo, hi), form[2])
    lines = row_lines(MSG_ROW)
    gaps = [lines[0] - form[1][1] - 1, form[2][0] - lines[1] - 1]
    art_gaps = [lines[0] - (ROW_Y[1] + 1 + ENEMY_ART[3]) - 1, (ROW_Y[2] + 1 + ENEMY_ART[2]) - lines[1] - 1]
    print(f"the message row {MSG_ROW}: lines {lines[0]}-{lines[1]}: {gaps[0]} empty lines below row 1's cell, "
          f"{gaps[1]} above row 2's ({art_gaps[0]} and {art_gaps[1]} to the nearest line the enemy art may use); "
          f"{ship[0] - lines[1] - 1} lines above the ship")
    assert MSG_ROW in free

    # Every message cell against every parked or winding-up enemy, every drift position: by pixels
    worst = 0
    for _, row, text in TEXTS:
        if row != MSG_ROW:
            continue
        tx, tl = text_x(text), row_lines(row)
        for fx in range(DRIFT_MAX + 1):
            for wob in (-1, 0, 1):                       # the wind-up's 1 pixel either side of home
                for r in range(3):
                    for c in range(6):
                        ex = FORM_X0 + fx + COL_DX * c + wob
                        if overlap((ex, ex + 23), tx) and overlap(sprite_lines(ROW_Y[r]), tl):
                            worst += 1
    print(f"message cells covered by a parked or winding-up enemy's cell, over fx 0-{DRIFT_MAX} and the "
          f"wind-up's 1 pixel either side, 18 enemies, 3 messages: {worst}")
    assert worst == 0
    for _, row, text in TEXTS:
        if row == MSG_ROW and _ == "Game":
            c = col_of(text)
            print(f"   {text!r}: row {row}, columns {c}-{c + len(text) - 1} (was row {OLD_MSG_ROW}, the same columns)")
            assert BAND_COLS[0] <= c and c + len(text) - 1 <= BAND_COLS[1]

    print(f"\n== What can pass over the message row (lines {lines[0]}-{lines[1]}) ==")
    last_any = 0
    for name in PATHS:
        row = []
        for loop in range(4):
            last, longest = -1, 0
            for phase in range(4):
                for sx in (FORM_X0, 172, FORM_X0 + DRIFT_MAX + 5 * COL_DX):
                    for m in (False, True):
                        fr, total = diver_frames_over(name, loop, lines, phase, sx, m)
                        if fr:
                            last, longest = max(last, fr[-1]), max(longest, len(fr))
            row.append(f"loop {loop}: " + (f"{longest} frames, the last {last} after its launch" if last >= 0 else "never"))
            last_any = max(last_any, last)
        print(f"{name} (row {PATHS[name]['row']}), from its launch frame through Dive, wrap and Return: " + "; ".join(row))
    print(f"last frame after a launch in which any diver is over the row: {last_any}. GAME OVER is written "
          f"{DYING_MIN} frames after the hit and nothing launches from the hit's frame on: "
          f"{DYING_MIN - last_any - 1} frames to spare, so no diver ever crosses GAME OVER")
    assert last_any < DYING_MIN
    crossing = []
    for name, p in PATHS.items():
        at = {s: y for s, _, y in walk(name, start_x=172)}
        for s in p["fire"]:
            if s in at and at[s] + 1 + ESHOT_ART[2] <= lines[1]:
                crossing.append(f"{name} step {s} (Y {at[s]})")
    print("enemy shots that start above the row and fall through it: " + ", ".join(crossing))
    top_fire = min(y for name in PATHS for s, _, y in walk(name, start_x=172) if s in PATHS[name]["fire"])
    life = (MUX_Y_MAX - top_fire) // 2 + 2
    print(f"longest enemy shot life (fired at Y {top_fire}, 2 a frame, shown one frame at its spawn): {life} frames, "
          f"under the {CLEAR_PAUSE} empty frames before WAVE nn and the {DYING_MIN} before READY or GAME OVER "
          f"(shots are removed at the player's hit anyway)")
    assert life < CLEAR_PAUSE
    ys = [y for y in range(PSHOT_SPAWN_Y, PSHOT_KILL_Y - 1, -PSHOT_SPEED) if overlap(sprite_lines(y, PSHOT_ART), lines)]
    for text in ("WAVE 01", "READY"):
        tx = text_x(text)
        print(f"a player shot is over the row for {len(ys)} frames (Y {ys}), 2 pixels wide; over {text!r} only "
              f"when fired from ship X {tx[0] - PSHOT_ART[1]}-{tx[1] - PSHOT_ART[0]}")

    print("\n== Title: its three sprites against its text (no formation on screen) ==")
    hits = 0
    for sx, sy in TITLE_SPRITES:
        cols = ((sx - 24) // 8, (sx + 23 - 24) // 8)
        rows = ((sy + 1 - 51) // 8, (sy + 21 - 51) // 8)
        print(f"sprite at ({sx}, {sy}): lines {sy + 1}-{sy + 21}, text rows {rows[0]}-{rows[1]}, columns {cols[0]}-{cols[1]}")
        for scr, row, text in TEXTS:
            if scr == "Title" and overlap((sx, sx + 23), text_x(text)) and overlap(sprite_lines(sy), row_lines(row)):
                hits += 1
    print(f"title texts covered by a title sprite: {hits} (the nearest text starts at column 17). No title row moves")
    assert hits == 0

    print("\n== Star bands ==")
    bands = sorted({row for _, row, _ in TEXTS})
    for _, row, text in TEXTS:
        c = col_of(text)
        assert BAND_COLS[0] <= c and c + len(text) - 1 <= BAND_COLS[1], text
    width = BAND_COLS[1] - BAND_COLS[0] + 1
    cells = 24 * 40 - len(bands) * width
    print(f"text rows {bands}: {len(bands)} bands of {width} columns = {len(bands) * width} cells; "
          f"{cells} of 960 play-area cells free for {STARS} stars (was 7 bands, 820 free: row {OLD_MSG_ROW} "
          f"is no longer a text row and row {MSG_ROW} already was one)")
    assert bands == [5, 9, 11, 13, 16, 19] and cells == 840 and STARS <= cells


# ---- The difficulty curve ----
def difficulty(frames=6000):
    print(f"\n== Difficulty by wave (launches and shots counted over {frames} frames of the play simulation: "
          "a full formation that never dies, so the most the launcher can do) ==")
    print("wave pattern loop | interval, max divers, shots a dive (hook/sweep/plunge), wind-up, diver speed, "
          "shot dy | launches/min, enemy shots/min | Hook: launch to first lethal frame, s | "
          "shot from Y 164 to the ship, s")
    base = None
    for wave in range(1, 13):
        pattern, loop = (wave - 1) % 3, (wave - 1) // 3
        s = simulate(pattern, loop, frames, True)
        mins = frames / 3000
        shots = "/".join(str(min(len(PATHS[n]["fire"]), SHOTS_BASE[pattern] + loop)) if PATHS[n]["row"] in ROWS[pattern]
                         else "-" for n in ("hook", "sweep", "plunge"))
        speed = 1 + (1 / EXTRA_STEP_EVERY[loop] if EXTRA_STEP_EVERY[loop] else 0)
        hook = (WINDUP[loop] + -(-35 // speed)) / 50
        shot = -(-(ESHOT_HIT_Y - FIRE_MAX_Y) // ESHOT_DY[loop]) / 50
        lm, sm = s["launches"] / mins, s["eshots_fired"] / mins
        base = base or (lm, sm)
        print(f"  {wave:2d}  {pattern + 1}  {loop} | {INTERVAL[pattern][loop]:3d}, {MAX_DIVERS[pattern][loop]}, {shots}, "
              f"{WINDUP[loop]}, x{speed:.2f}, {ESHOT_DY[loop]} | {lm:5.1f}, {sm:5.1f} "
              f"(x{lm / base[0]:.1f}, x{sm / base[1]:.1f} of wave 1) | {hook:.2f} | {shot:.2f}")


if __name__ == "__main__":
    static_checks()
    explosion_checks()
    layout_checks()
    difficulty()
    play_checks()
