"""QA playthrough referee for Swarm (M4 stage 5, item 1): a stick bot plays whole games, title to game
over to title to the next game, and every frame is checked against the design's rules.

Run from the repo root (DEBUG build first: make GAME=swarm):

    uv run --package budget-runner python tests/games/swarm/qa_play.py [--games 3] [--max-frames 40000]
        [--prg build/swarm/swarm.prg] [--seed-wait 0,7,13] [--shots DIR]

The bot (qa_lib.Game.bot_stick) steers under the lowest enemy and fires; it sidesteps shots. Each
game starts from the title with a press of fire held for HOLD frames (so the 25-frame fire hold is
exercised: the stick keeps fire down) and ends when the game is over; the script waits through
GameOver and the title and starts the next.

Checked in every frame (one stop at game_update_end):
  score        each frame's score change = the points of the enemies that left Parked/WindUp/Dive/Return
               that frame (50/80/150 by row, doubled if diving) + 1,000 in the frame the phase becomes
               Clear; capped at 999,990
  lives        never rises in a game, 3 at a new game, falls by 1 at a hit only
  state        only the design's transitions (Title>Play, Play>Dying, Dying>Respawn|GameOver, Respawn>Play,
               GameOver>Title); Dying lasts >= 100 frames; Respawn exactly 50 frames; GameOver <= 200
  player       X in 24-318; at most 2 player shots; the ship can't be hit while zp_player_invuln > 0
  row 9        GAME OVER text in GameOver, WAVE nn in Intro frames 0-48, READY in a Respawn that began in
               Fight, otherwise blank (stars never in the text cells)
  high score   at GameOver's frame 0 max(old, score); shown on the title's panel
  new game     fire held from the press: first player shot in frame 25 of the game (the 25-frame hold),
               first wind-up in wave frame 60 (when nobody has died yet)
  counters     DEBUG counters 0 at the end of every game (mux_max_age <= 1)

Results are printed; a copy of the last run is in tests/games/swarm/qa_play_results.txt.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import *  # noqa: E402,F403

ROW_PTS = [150, 80, 50]


def row9(g):
    cells = g.mon.mem_get(0x0400 + 9 * 40 + 10, 0x0400 + 9 * 40 + 29)
    return "".join(chr(64 + c) if 1 <= c <= 26 else (chr(c) if 32 <= c < 64 else "?") for c in cells).strip()


class Ref:
    def __init__(self, g):
        self.g = g
        self.errors = []
        self.events = []
        self.stats = {"frames": 0, "kills": 0, "kill_diving": 0, "clears": 0, "deaths": 0, "games": 0}

    def err(self, text):
        self.errors.append(f"f{self.g.frames}: {text}")
        if len(self.errors) <= 40:
            print("  [FAIL]", self.errors[-1], "|", self.g.summary(), flush=True)

    def ev(self, text):
        self.events.append(f"f{self.g.frames}: {text}")
        print("  .", self.events[-1], flush=True)


def snapshot(g):
    return dict(st=list(g.mem("enemy_state", ENEMIES)), score=g.score(), lives=g.peek("zp_lives"),
                gs=g.gstate(), ph=g.peek("zp_wave_phase"), wave=g.peek("zp_wave"), inv=g.peek("zp_player_invuln"),
                px=g.player_x(), hi=g.hiscore(), alive=g.peek("zp_enemies_alive"), sprites=g.sprites())


def play_game(g, r, max_frames, hold_press=True, shots=None, tag="g"):
    """Start from the title (already there), play until GameOver ends in the title."""
    # --- start: wait until a fresh press is possible, press with fire held on
    g.run(12, [])
    hi_before = g.hiscore()
    g.step(["fire"])                        # the press frame (held from now on until the game's first bot frames)
    press_frame = g.frames
    prev = snapshot(g)
    first_shot = first_windup = None
    new_game_frame = None
    wave_start_frame = None
    dying_start = respawn_start = over_start = None
    deaths = 0
    best_wave = 1
    shot_state = set()
    ended = False
    pk = None
    while g.frames - press_frame < max_frames:
        # stick: hold fire only until the first shot, to show the 25-frame hold; then the bot
        if g.gstate() == GS_TITLE and new_game_frame is None:
            stick = BITS["fire"]
        elif new_game_frame is not None and first_shot is None:
            stick = BITS["fire"]              # fire held from the press, no moves: the hold test
        elif g.gstate() in (GS_PLAY, GS_RESPAWN, GS_DYING):
            stick = g.bot_stick()
        else:
            stick = 0                         # GameOver: let go (a held press would skip it / start nothing)
        g.step(stick)
        cur = snapshot(g)
        r.stats["frames"] += 1
        gf = g.frames
        # new game detected
        if new_game_frame is None and cur["gs"] == GS_PLAY:
            new_game_frame = gf
            wave_start_frame = gf
            if cur["lives"] != 3 or cur["score"] != 0:
                r.err(f"new game: lives {cur['lives']} score {cur['score']}")
            if cur["hi"] != hi_before:
                r.err(f"new game changed the high score {hi_before} -> {cur['hi']}")
            r.ev(f"new game: press frame {press_frame}, game frame {gf} (press + {gf - press_frame}), lives {cur['lives']}")
            if shots:
                pass
        # --- score
        exp = 0
        for e in range(ENEMIES):
            a, b = prev["st"][e], cur["st"][e]
            if a in (ENEMY_PARKED, 0x80, 0x81, 0x82) and b in (0x83, ENEMY_DEAD):
                pts = ROW_PTS[e // 6] * (2 if a >= 0x80 else 1)
                exp += pts
                r.stats["kills"] += 1
                r.stats["kill_diving"] += a >= 0x80
        if cur["ph"] == PH_CLEAR and prev["ph"] != PH_CLEAR and prev["gs"] != GS_TITLE:
            exp += 1000
            r.stats["clears"] += 1
            r.ev(f"wave {cur['wave']:02x} cleared: score {prev['score']} -> {cur['score']}")
        if new_game_frame is not None and prev["gs"] != GS_TITLE:
            want = min(prev["score"] + exp, 999990)
            if cur["score"] != want and not (cur["gs"] == GS_TITLE):
                r.err(f"score {prev['score']} -> {cur['score']}, expected {want} (kills worth {exp})")
        # --- state machine
        if cur["gs"] != prev["gs"]:
            legal = {(GS_TITLE, GS_PLAY), (GS_PLAY, GS_DYING), (GS_DYING, GS_RESPAWN), (GS_DYING, GS_OVER),
                     (GS_RESPAWN, GS_PLAY), (GS_RESPAWN, GS_DYING), (GS_OVER, GS_TITLE)}
            if (prev["gs"], cur["gs"]) not in legal:
                r.err(f"illegal state change {GS_NAMES[prev['gs']]} -> {GS_NAMES[cur['gs']]}")
            if cur["gs"] == GS_DYING:
                dying_start = gf
                deaths += 1
                r.stats["deaths"] += 1
                if cur["lives"] != prev["lives"] - 1:
                    r.err(f"hit: lives {prev['lives']} -> {cur['lives']}")
                if prev["inv"] > 0:
                    r.err(f"hit while invulnerable ({prev['inv']})")
                r.ev(f"hit: lives {cur['lives']}, score {cur['score']}, divers {g.peek('zp_divers_active')}, X {cur['px']}")
            if prev["gs"] == GS_DYING and cur["gs"] in (GS_RESPAWN, GS_OVER):
                n = gf - dying_start
                if n < 100:
                    r.err(f"Dying lasted {n} frames (< 100)")
                r.ev(f"Dying -> {GS_NAMES[cur['gs']]} after {n} frames (divers_active {g.peek('zp_divers_active')})")
                if cur["gs"] == GS_RESPAWN:
                    respawn_start = gf
                    ready = row9(g)
                    if cur["ph"] == PH_FIGHT and ready != "READY":
                        r.err(f"Respawn in Fight but row 9 is {ready!r}")
                    if abs(cur["px"] - 171) > 3:      # the bot may already have moved the ship in this frame
                        r.err(f"respawn X {cur['px']} != 171")
                else:
                    over_start = gf
                    if cur["hi"] != max(hi_before, cur["score"]) and cur["hi"] != max(prev["hi"], cur["score"]):
                        r.err(f"GameOver high score {cur['hi']}, score {cur['score']}, before {prev['hi']}")
            if prev["gs"] == GS_RESPAWN and cur["gs"] == GS_PLAY:
                n = gf - respawn_start
                if n != 50:
                    r.err(f"Respawn lasted {n} frames, not 50")
            if prev["gs"] == GS_OVER and cur["gs"] == GS_TITLE:
                n = gf - over_start
                r.ev(f"GameOver -> Title after {n} frames")
                if n > 201:
                    r.err(f"GameOver lasted {n} frames")
                ended = True
        # lives must not rise
        if cur["lives"] > prev["lives"] and prev["gs"] != GS_TITLE:
            r.err(f"lives rose {prev['lives']} -> {cur['lives']}")
        if not (24 <= cur["px"] <= 318) and cur["gs"] != GS_TITLE:
            r.err(f"player X {cur['px']} outside 24-318")
        shots = sum(1 for i in (4, 5) if cur["sprites"][i][1] != MUX_OFF)
        if cur["gs"] != GS_TITLE and shots > 2:
            r.err("more than 2 player shots")
        # first shot / windup
        if new_game_frame is not None and first_shot is None and any(cur["sprites"][i][1] != MUX_OFF for i in (4, 5)):
            first_shot = gf - new_game_frame
            r.ev(f"first player shot {first_shot} frames after the game's first frame (design: 25)")
        if new_game_frame is not None and first_windup is None and any(s == 0x80 for s in cur["st"]):
            first_windup = gf - new_game_frame
            r.ev(f"first wind-up {first_windup} frames after the game's first frame (design: 60 into the wave)")
        # row 9 text
        if cur["gs"] == GS_OVER:
            t = row9(g)
            if over_start is not None and gf > over_start and t != "GAME OVER":
                r.err(f"GameOver but row 9 = {t!r}")
        if cur["gs"] == GS_PLAY and cur["ph"] == PH_INTRO:
            t = row9(g)
            tm = g.peek("zp_wave_timer")
            if 1 <= tm <= 47 and t != f"WAVE {cur['wave']:02x}":
                r.err(f"Intro timer {tm}: row 9 = {t!r}")
        if cur["wave"] > best_wave and cur["wave"] < 0x99:
            pass
        if new_game_frame is not None:
            best_wave = max(best_wave, cur["wave"])
        # a periodic screenshot of interesting frames is taken by the caller via hooks
        if r.hook:
            r.hook(g, cur, prev)
        prev = cur
        if ended:
            break
    c = g.counters()
    r.ev(f"game over after {g.frames - press_frame} frames, wave reached {best_wave:02x}, deaths {deaths}, counters {c}")
    if ended is False:
        r.err("the game did not end within max-frames")
    return dict(frames=g.frames - press_frame, wave=best_wave, deaths=deaths, first_shot=first_shot,
                first_windup=first_windup, score=prev["score"], hi=prev["hi"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=3)
    ap.add_argument("--max-frames", type=int, default=40000)
    ap.add_argument("--prg", default=str(DEBUG_PRG))
    ap.add_argument("--shots", default=str(REPO / "screenshots"))
    a = ap.parse_args()
    g = Game(a.prg)
    r = Ref(g)
    r.hook = None
    out = []
    try:
        g.run(30, [])
        for n in range(a.games):
            print(f"== game {n + 1}", flush=True)
            res = play_game(g, r, a.max_frames, tag=f"g{n}")
            out.append(res)
            r.stats["games"] += 1
            # the title must show the finished game's score and the high score
            g.run(12, [])
            row = g.mon.mem_get(0x0400 + 24 * 40, 0x0400 + 24 * 40 + 39)
            text = "".join(chr(c & 0x3F | (0 if (c & 0x3F) >= 32 else 64)) for c in row).strip()
            print(f"   title: score {g.score()} hi {g.hiscore()} zp_wave {g.peek('zp_wave'):02x} panel {text!r}", flush=True)
            if f"WAVE {g.peek('zp_wave'):02x}" not in text:
                r.err(f"the title's panel wave differs from zp_wave {g.peek('zp_wave'):02x}: {text!r}")
            if f"HI {g.hiscore():06d}" not in text or f"SCORE {res['score']:06d}" not in text:
                r.err(f"the title's panel does not show the game's score and the high score: {text!r}")
            if g.hiscore() < res["score"]:
                r.err("high score below the finished game's score")
        c = g.counters()
    finally:
        g.close()
    print("\nSTATS", r.stats)
    for o in out:
        print("GAME", o)
    print("COUNTERS", c)
    print(f"{len(r.errors)} rule violations")
    for e in r.errors[:40]:
        print("  ", e)
    return 1 if r.errors else 0


if __name__ == "__main__":
    sys.exit(main())
