"""Swarm tuning after the stage 4 playtest: the free period at a wave's start, and enemy fire.

Backs the figures in docs/games/swarm/design.md, "Tuning after the stage 4 playtest".
No emulator, no dependencies (stdlib only). Run from the repo root:

    uv run python tests/games/swarm/free_period.py | tee tests/games/swarm/free_period_results.txt

What it prints, for the tables BEFORE the tuning (as built in stage 4) and AFTER (the design now):

  1. The free period per wave: the wave frame (0 = Intro's frame 0) of the first launch (WindUp's
     frame t = 0), of the first enemy shot that can be fired, and of the first frame that shot can
     reach the ship, and of the first frame a diver can touch it. Exact, from the rules (Stage 4
     rules 2-3, the dive paths' fire steps).
  2. How many of the 18 a player can kill in that period: a model wave played by a bot that
     shoots the nearest column, lowest enemy first, and never has to dodge. Two bots:
       "best"      fires as fast as the game allows (cooldown 10), from frame 0;
       "competent" fires two thirds as fast (cooldown 15) and starts 15 frames late.
     Both are ASSUMPTIONS about a player, not measurements of one. The bots can't be hit, so
     they are an upper bound on kills: a real player also has to move out of the way.
  3. Enemy shots a second per wave with a formation that never dies (check_design.py's play
     simulation: the most the launcher can do), and the fire steps lost because all 3
     enemy-shot slots were in use.
  4. The same wave against the "competent" bot: how long the wave lasts and how many enemy
     shots are fired in it (the bot kills, so this is nearer what a player sees).

The model is this file's and check_design.py's transcription of the design, not the game:
design estimates, to be replaced by check.py / QA on the build.
"""
import random

import check_design as cd

OLD = dict(
    name="before (stage 4 as built)",
    interval=[[150, 120, 100, 80], [120, 100, 80, 64], [100, 80, 64, 50]],
    max_divers=[[1, 2, 2, 2], [2, 2, 3, 3], [2, 3, 3, 3]],
    shots_base=[1, 2, 2],
    intro=100, fight_delay=50, halve_alive=4,
)
# AFTER is whatever check_design.py holds: it is kept the same as the design doc's tables.
NEW = dict(
    name="after (the design now)",
    interval=cd.INTERVAL, max_divers=cd.MAX_DIVERS, shots_base=cd.SHOTS_BASE,
    intro=cd.INTRO_FRAMES, fight_delay=cd.FIGHT_LAUNCH_DELAY, halve_alive=cd.LAUNCH_HALVE_ALIVE,
)
ROW_FLIGHT = [18, 13, 8]            # frames from a player shot's spawn to its hit, by row (parked)
EXPLOSION = 16


def free_period(t, pattern, loop):
    """(first launch, first shot fired, first frame a shot can reach the ship, first frame a diver
    can touch it), wave frames: check_design.first_threat with t's shots a dive."""
    launch = t["intro"] + t["fight_delay"]
    keep, cd.SHOTS_BASE = cd.SHOTS_BASE, t["shots_base"]
    try:
        return (launch,) + cd.first_threat(launch, pattern, loop)
    finally:
        cd.SHOTS_BASE = keep


def bot_wave(t, pattern, loop, cooldown_frames, start_delay, seed, max_frames=6000):
    """One wave from Intro's frame 0 against a bot that can't be hit. Returns a dict of counts."""
    rng = random.Random(seed)
    L = min(loop, 3)
    fx, fdir = cd.DRIFT_MAX // 2, 1
    px, cooldown = 171, start_delay
    pshots = [None, None]                       # [x, y, target enemy index]
    eshots = [None, None, None]
    # state: X waiting, P parked, W wind-up, D dive, R return, E exploding, - dead
    en = [dict(st="X", x=0, y=0, row=e // 6, col=e % 6, t=0) for e in range(18)]
    timer, fight = 0, False
    launch_f, shot_f = None, None
    out = dict(kills_at_launch=None, kills_at_shot=None, launches=0, eshots=0, lost=0, frames=None)
    kills = 0

    def home_x(e, fx_):
        return cd.FORM_X0 + fx_ + cd.COL_DX * e["col"]

    def fx_after(n):
        f_, d_ = fx, fdir
        for k in range(1, n + 1):
            if (f + k) % cd.DRIFT_DIV[L] == 0:
                f_ += d_
                if f_ in (0, cd.DRIFT_MAX):
                    d_ = -d_
        return f_

    for f in range(max_frames):
        # wave phase
        if f < cd.INTRO_LAST_ENEMY_FRAME + 1 and f % 2 == 0 and f // 2 < 18:
            en[f // 2]["st"] = "P"
        if f == t["intro"]:
            fight, timer = True, t["fight_delay"] + 1
        # player shots move
        for s in pshots:
            if s:
                s[1] -= cd.PSHOT_SPEED
        pshots = [s if s and s[1] >= cd.PSHOT_KILL_Y else None for s in pshots]
        # drift, explosion timers
        if f % cd.DRIFT_DIV[L] == 0:
            fx += fdir
            if fx in (0, cd.DRIFT_MAX):
                fdir = -fdir
        for e in en:
            if e["st"] == "E":
                e["t"] -= 1
                if e["t"] == 0:
                    e["st"] = "-"
        # enemy shots move
        for s in eshots:
            if s:
                s[0] = max(cd.X_MIN, min(cd.X_MAX, s[0] + s[2]))
                s[1] += cd.ESHOT_DY[L]
        eshots = [s if s and s[1] <= cd.MUX_Y_MAX else None for s in eshots]
        # launcher
        if fight:
            if timer > 0:
                timer -= 1
            active = sum(1 for e in en if e["st"] in "WDR")
            if timer == 0 and active < t["max_divers"][pattern][L]:
                cand = [e for e in en if e["st"] == "P" and e["row"] in cd.ROWS[pattern]] \
                    or [e for e in en if e["st"] == "P"]
                if cand:
                    e = rng.choice(cand)
                    e.update(st="W", t=cd.WINDUP[L])
                    alive = sum(1 for q in en if q["st"] not in "-")
                    timer = t["interval"][pattern][L] // (2 if alive <= t["halve_alive"] else 1)
                    out["launches"] += 1
                    if launch_f is None:
                        launch_f, out["kills_at_launch"] = f, kills
        # enemies
        for e in en:
            hx, hy = home_x(e, fx), cd.ROW_Y[e["row"]]
            if e["st"] in "PW":
                e["x"], e["y"] = hx, hy
            if e["st"] == "W":
                e["t"] -= 1
                if e["t"] < 0:
                    p = cd.PATHS[cd.ROW_PATH[e["row"]]]
                    e.update(st="D", path=p, seg=0, left=p["segs"][0][2], step=0, mirror=px < e["x"],
                             shots=min(len(p["fire"]), t["shots_base"][pattern] + L))
            if e["st"] == "D":
                n = 2 if cd.EXTRA_STEP_EVERY[L] and f % cd.EXTRA_STEP_EVERY[L] == 0 else 1
                for _ in range(n):
                    if e["st"] != "D":
                        break
                    dx, dy, cnt = e["path"]["segs"][e["seg"]]
                    e["x"] = max(cd.X_MIN, min(cd.X_MAX, e["x"] + (-dx if e["mirror"] else dx)))
                    e["y"] += dy
                    e["step"] += 1
                    if e["step"] in e["path"]["fire"][:e["shots"]] and cd.VISIBLE_X[0] <= e["x"] <= cd.VISIBLE_X[1]:
                        if None in eshots:
                            d = px - e["x"]
                            eshots[eshots.index(None)] = [e["x"], e["y"], 0 if abs(d) <= 15 else (1 if d > 0 else -1)]
                            out["eshots"] += 1
                            if shot_f is None:
                                shot_f, out["kills_at_shot"] = f, kills
                        else:
                            out["lost"] += 1
                    if cnt == 0:
                        if e["x"] in (cd.X_MIN, cd.X_MAX):
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
        # collisions: player shots against enemies (boxes: design "Hit boxes")
        for i, s in enumerate(pshots):
            if not s:
                continue
            for e in en:
                if e["st"] in "PWDR" and -8 <= s[0] - e["x"] <= 8 and e["y"] + 3 - 7 <= s[1] <= e["y"] + 17:
                    e.update(st="E", t=EXPLOSION)
                    kills += 1
                    pshots[i] = None
                    break
        # the bot: nearest column with a parked (or winding-up), untargeted enemy; its lowest one;
        # lead the drift. With nothing parked it waits under the home of an enemy that is out
        cooldown = max(0, cooldown - 1)
        targeted = {s[2] for s in pshots if s}
        cands = [(i, e) for i, e in enumerate(en) if e["st"] in "PW" and i not in targeted]
        lowest = {}
        for i, e in cands:
            if e["col"] not in lowest or e["row"] > lowest[e["col"]][1]["row"]:
                lowest[e["col"]] = (i, e)
        aim, shoot = None, None
        if lowest:
            shoot, e = min(lowest.values(), key=lambda ie: abs(home_x(ie[1], fx) - px))
            aim = home_x(e, fx_after(ROW_FLIGHT[e["row"]]))
        else:
            out_ = [e for e in en if e["st"] in "DR"]
            if out_:
                aim = min((home_x(e, fx) for e in out_), key=lambda x: abs(x - px))
        if aim is not None:
            if abs(aim - px) >= 3:
                px = max(cd.PLAYER_XMIN, min(cd.PLAYER_XMAX, px + (3 if aim > px else -3)))
            if shoot is not None and abs(aim - px) <= 5 and cooldown == 0 and None in pshots:
                pshots[pshots.index(None)] = [px, cd.PSHOT_SPAWN_Y, shoot]
                cooldown = cooldown_frames
        if all(e["st"] == "-" for e in en):
            out["frames"] = f + 1
            break
    if out["kills_at_launch"] is None:
        out["kills_at_launch"] = kills
    if out["kills_at_shot"] is None:
        out["kills_at_shot"] = kills
    return out


def mean(xs):
    return sum(xs) / len(xs)


def bot_table(t, cooldown_frames, start_delay, seeds=40):
    rows = []
    for wave in range(1, 13):
        pattern, loop = (wave - 1) % 3, (wave - 1) // 3
        rs = [bot_wave(t, pattern, loop, cooldown_frames, start_delay, s) for s in range(seeds)]
        done = [r for r in rs if r["frames"]]
        rows.append((wave, mean([r["kills_at_launch"] for r in rs]), mean([r["kills_at_shot"] for r in rs]),
                     mean([r["frames"] for r in done]) if done else float("nan"),
                     mean([r["eshots"] for r in rs]), mean([r["launches"] for r in rs]), len(done)))
    return rows


def full_formation(t, frames=6000):
    """check_design.simulate with t's tables: shots a second, a formation that never dies."""
    keep = cd.INTERVAL, cd.MAX_DIVERS, cd.SHOTS_BASE
    cd.INTERVAL, cd.MAX_DIVERS, cd.SHOTS_BASE = t["interval"], t["max_divers"], t["shots_base"]
    try:
        out = []
        for wave in range(1, 13):
            pattern, loop = (wave - 1) % 3, (wave - 1) // 3
            s = cd.simulate(pattern, loop, frames, True)
            out.append((wave, s["launches"] / (frames / 50), s["eshots_fired"] / (frames / 50),
                        100 * s["drop_frames"] / frames, s["max_divers"], s["max_eshots"]))
        return out
    finally:
        cd.INTERVAL, cd.MAX_DIVERS, cd.SHOTS_BASE = keep


def main():
    for t in (OLD, NEW):
        print(f"\n===== {t['name']} =====")
        print(f"Intro {t['intro']} frames, launch timer at Fight {t['fight_delay']}, interval halved at "
              f"{t['halve_alive']} or fewer alive")
        print(f"intervals {t['interval']}, divers at once {t['max_divers']}, shots a dive at loop 0 {t['shots_base']}")
        print("\n1. The free period (wave frames; 50 = 1 s)")
        print("wave pattern loop | first launch | first enemy shot fired | first frame a shot can reach the ship "
              "| first frame a diver can touch the ship")
        for wave in range(1, 13):
            pattern, loop = (wave - 1) % 3, (wave - 1) // 3
            a, b, c, d = free_period(t, pattern, loop)
            print(f"  {wave:2d}  {pattern + 1}  {loop} | {a:3d} ({a / 50:.2f} s) | {b:3d} ({b / 50:.2f} s) | "
                  f"{c:3d} ({c / 50:.2f} s) | {d:3d} ({d / 50:.2f} s)")
        for label, cdn, delay in (("best (cooldown 10, from frame 0)", 10, 0),
                                  ("competent (cooldown 15, from frame 15)", 15, 15)):
            print(f"\n2/4. A wave against the bot: {label}; mean of 40 seeds")
            print("wave | kills before the first launch | kills before the first enemy shot | wave length, frames (s) "
                  "| enemy shots fired in the wave | launches | waves finished")
            for w, kl, ks, fr, es, la, n in bot_table(t, cdn, delay):
                print(f"  {w:2d} | {kl:4.1f} | {ks:4.1f} | {fr:5.0f} ({fr / 50:4.1f} s) | {es:4.1f} | {la:4.1f} | {n}/40")
        print("\n3. Full formation that never dies, 6000 frames (the most the launcher can do)")
        print("wave | launches a second | enemy shots a second | frames with a sprite dropped % | most divers, enemy shots at once")
        for w, la, es, drop, md, me in full_formation(t):
            print(f"  {w:2d} | {la:.2f} | {es:.2f} | {drop:5.2f}% | {md}, {me}")
            assert md <= 3 and me <= 3


if __name__ == "__main__":
    main()
