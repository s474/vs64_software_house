"""F3: the M3 positions check and the --slack measurement, run on the SWARM GAME (not the engine
spike), under the game's extended colour mode panel, in DEBUG and release (M4 deliverable 6).

It reuses the engine's Checker class (tests/engine/multiplexer/positions.py, unedited) for every
register comparison, and replaces only its driver:
  * the game is started from the title by stick and then PLAYED by a bot (qa_lib.Game.bot_stick,
    stick set at game_update_end each frame); nothing is perturbed (the spike's HIRES / MC / MIXED
    phases write random colours, pointers and multicolour bits into the mux arrays: the game owns
    those, and uses all hires). When a game ends and the title comes up the script presses fire
    again, so one run covers Intro, Fight, Clear, Respawn, Dying, GameOver and Title;
  * the zone block layout differs per build (DEBUG: block 81 bytes, `inx` at +45; release: 66 and
    +30), found here from the build's own labels and verified by opcode (inx = $E8, lda abs,x = $BD);
  * the "late" counters are read only in DEBUG (a release build has none);
  * `--wave N` places the game in wave N after the title's Intro the way check.py does (stores
    poked, Clear at its last frame), so a run can cover waves the bot would not reach;
  * `--slack` mode stops at game_update_end (to drive the stick; one stop a frame) and at each zone
    slot's `inx`, and reports the same histogram as positions.py --slack.

Run from the repo root (build first: make GAME=swarm; make BUILD=release GAME=swarm):

    uv run --package budget-runner python tests/games/swarm/qa_positions.py --frames 1500 [--wave 3]
        [--seed-wait 0] [--bot-seed 1] [--prg build/swarm/swarm.prg | build/swarm-release/swarm.prg]
    uv run --package budget-runner python tests/games/swarm/qa_positions.py --slack --frames 3000 ...

--hostile: at every game_update_end (after the game's own update, before mux_update) the 24 virtual
sprites' X, Y, pointer and colour are overwritten with the engine's hostile layouts (edge.py's
staircases, steps of 2-4 or 2-6 lines, three rows of 8, base lines chosen so slot Y lines fall on
badlines; and dense random layouts that overflow and flicker), a new layout every 20 frames, and
the game's own values are put back at mux_build_end. The game runs normally around it (extended
colour mode, panel, sound tick, state machine), only what the multiplexer is asked to show is
hostile. Natural play never gets near the engine's 17 / 39 cycle margins (its sprites are 40 lines
apart); this is what does.

--frames counts GAME frames (game_update_end stops). Exit 0 = pass, 1 = a mismatch / slack <= 0,
2 = jam. A positions run is ~35 monitor stops a frame: run several in parallel (qa_positions_all.sh).
"""

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine" / "multiplexer"))
from qa_lib import *  # noqa: E402,F403
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine" / "multiplexer_edge"))
from positions import Checker, DMA_CYCLE, N  # noqa: E402  (the engine's, unedited)
from edge import staircase  # noqa: E402  (the engine's hostile layouts, unedited)

LAYOUT = {True: (45, 81), False: (30, 66)}   # DEBUG, release: (inx offset in a uniform block, block size)


def zone_layout(g):
    off, size = LAYOUT[g.debug]
    sym, mon = g.sym, g.mon
    z0 = sym["mux_zone_0"]
    if sym["mux_zone_1"] - z0 != size:
        raise MeasureError(f"zone block size {sym['mux_zone_1'] - z0}, expected {size}: update LAYOUT")
    inxs = {}
    for j in range(8):
        ad = z0 + size * j + off
        if mon.mem_get(ad, ad)[0] != 0xE8:
            raise MeasureError(f"no inx at ${ad:04x}")
        if mon.mem_get(z0 + size * j, z0 + size * j)[0] != 0xBD:
            raise MeasureError("zone block stride changed")
        inxs[ad] = j
    entries = {z0 + size * j: j for j in range(8)}
    return entries, inxs


def place_wave(g, n):
    """Wave n from Intro's frame 0 by the game's own path (check.py's start_wave): stores one wave
    back, Clear at its last frame, the sky emptied."""
    g.poke("enemy_state", [0] * ENEMIES)
    g.poke("mux_y", [MUX_OFF] * ENEMIES, ENEMY0)
    g.poke("explosion_enemy", [0xFF] * 4)
    g.poke("zp_enemies_alive", [0])
    g.poke("zp_wave_phase", [PH_CLEAR])
    g.poke("zp_wave_timer", [75 - 1])
    bcd = lambda v: (v // 10) * 16 + v % 10
    if n == 1:
        g.poke("zp_wave", [0]); g.poke("zp_pattern", [2]); g.poke("zp_loop", [0])
    else:
        g.poke("zp_wave", [bcd(n - 1)]); g.poke("zp_pattern", [(n - 2) % 3]); g.poke("zp_loop", [min((n - 2) // 3, 3)])


class Driver:
    """Called at every game_update_end stop: starts games, sets the stick, counts what was covered."""

    def __init__(self, g, wave, seed_wait, bot_seed, hostile=False):
        self.g, self.wave, self.seed_wait = g, wave, seed_wait
        self.hostile, self.saved, self.layout_left, self.layouts = hostile, None, 0, Counter()
        self.hrng = random.Random(bot_seed * 7919 + 1)
        self.rng = random.Random(bot_seed)
        self.title_frames = 0
        self.placed = False
        self.cover = Counter()
        self.divers = Counter()
        self.games = 0
        self.noise = 0

    def frame(self):
        g = self.g
        gs = g.gstate()
        self.cover[GS_NAMES[gs]] += 1
        self.cover["phase" + str(g.peek("zp_wave_phase"))] += 1
        self.divers[g.peek("zp_divers_active")] += 1
        if gs == GS_TITLE:
            self.title_frames += 1
            # 12 + seed_wait frames at the title, then press (a new press: up the frame before)
            t = self.title_frames
            w = 12 + self.seed_wait
            stick = BITS["fire"] if t == w else 0
            if t == w:
                self.games += 1
                self.placed = False
            g.mon.joyport_set(PORT2, ~stick & 0x1F)
            return
        self.title_frames = 0
        if self.wave > 1 and not self.placed and gs == GS_PLAY and g.peek("zp_wave_phase") == PH_INTRO and g.peek("zp_wave_timer") >= 1:
            place_wave(g, self.wave)
            self.placed = True
        # the bot, with some noise so the ship doesn't only chase: 1 frame in 6 a random stick
        stick = g.bot_stick()
        if self.rng.random() < 0.05:
            stick = self.rng.choice([0, 4, 8, 0x14, 0x18, 0x10, 5, 9])
        g.mon.joyport_set(PORT2, ~stick & 0x1F)

    def hostile_in(self):
        """At game_update_end: save the game's mux arrays, put this frame's hostile layout in."""
        g, r = self.g, self.hrng
        self.saved = {k: bytes(g.mem(k, 24)) for k in ("mux_x_lo", "mux_x_hi", "mux_y", "mux_ptr", "mux_col")}
        if self.layout_left <= 0:
            self.layout_left = 20
            kind = r.random()
            if kind < 0.5:
                self.layouts["staircase 2-4"] += 1
                ys = staircase(r.randint(40, 75), [r.choice((2, 3, 4)) for _ in range(21)])
            elif kind < 0.75:
                self.layouts["staircase 2-6 wide"] += 1
                ys = staircase(r.randint(32, 110), [r.choice((2, 3, 4, 5, 6)) for _ in range(21)])
            else:
                self.layouts["dense random"] += 1
                n = r.randint(12, 24)
                ys = [r.randint(30, 120) for _ in range(n)] + [MUX_OFF] * (24 - n)
                r.shuffle(ys)
            ys = [y if y == MUX_OFF or y <= 221 else MUX_OFF for y in ys]
            xs = [r.randint(24, 343) for _ in range(24)]
            self.cur = dict(
                mux_y=bytes(ys),
                mux_x_lo=bytes(x & 255 for x in xs),
                mux_x_hi=bytes(x >> 8 for x in xs),
                mux_ptr=bytes(0xC0 + r.randint(0, 12) for _ in range(24)),
                mux_col=bytes(r.randint(1, 15) for _ in range(24)))
        self.layout_left -= 1
        for k, v in self.cur.items():
            g.poke(k, v)

    def hostile_out(self):
        """At mux_build_end: the game's own values back (the game keeps its state in these arrays)."""
        if self.saved:
            for k, v in self.saved.items():
                self.g.poke(k, v)
            self.saved = None


def get_late(g):
    if not g.debug:
        return None, None
    return g.peek("mux_late_count"), g.peek("irq_late_count")


def positions_main(a):
    g = Game(a.prg)
    sym, mon = g.sym, g.mon
    ck = Checker(g.v, sym)
    drv = Driver(g, a.wave, a.seed_wait, a.bot_seed, a.hostile)
    entries, inxs = zone_layout(g)
    top_entry = sym["mux_irq_top"]
    top_txa = top_entry + 234
    if mon.mem_get(top_txa, top_txa)[0] != 0x8A:
        raise MeasureError("no txa at mux_irq_top+234")
    gue = sym["game_update_end"]
    # the Game class already set a checkpoint at game_update_end
    addrs = [top_entry, top_txa, sym["mux_build_end"], *entries, *inxs]
    for ad in addrs:
        mon.checkpoint_set(ad, ad, CPU_OP_EXEC)
    gframes = 0
    stops = 0
    ok = True
    try:
        while gframes < a.frames:
            mon.exit()
            if not mon.wait_stopped(STOP_TIMEOUT):
                mon.ping()
                raise MeasureError(f"no checkpoint within {STOP_TIMEOUT}s at game frame {gframes}: jam? jammed_pc={mon.state.jammed_pc}")
            stops += 1
            r = mon.registers()
            pc, lin, x = r["PC"], r["LIN"], r["X"]
            if pc == gue:
                gframes += 1
                g.frames += 1
                drv.frame()
                if drv.hostile and g.gstate() != GS_TITLE:
                    drv.hostile_in()
                if gframes % 250 == 0:
                    print(f"  ...{gframes} game frames, {ck.frame} mux frames, {stops} stops, {drv.cover.get('Play', 0)} in Play", flush=True)
            elif pc == top_entry:
                ck.on_top_entry()
            elif pc == top_txa:
                ck.on_top_txa()
            elif pc == sym["mux_build_end"]:
                ck.on_build_end(None)
                drv.hostile_out()
            elif pc in entries:
                ck.on_zone_entry(lin, x)
            elif pc in inxs:
                ck.on_zone_inx(lin, r["CYC"], x)
            else:
                ck.fail(f"stopped at unexpected PC ${pc:04x}")
        late, ilate = get_late(g)
        counters = g.counters()
    finally:
        g.close()
    print(f"\n{a.prg}: {gframes} game frames, {ck.frame} multiplexer frames, {stops} monitor stops, wave placed {a.wave}, seed-wait {a.seed_wait}")
    print("coverage (game frames):", dict(drv.cover), "games started:", drv.games, "hostile layouts:", dict(drv.layouts))
    print("divers active (frames):", dict(sorted(drv.divers.items())))
    print(f"builds {ck.counts['builds']}, slow (flicker) builds {ck.counts['slow_frames']} "
          f"({100.0 * ck.counts['slow_frames'] / max(1, ck.counts['builds']):.2f}%), kept sprite-frames {ck.counts['kept_sprite_frames']}, "
          f"with X > 255: {ck.counts['x_gt_255_sprite_frames']}")
    print(f"hardware slot checks {ck.counts['slot_checks']}: X bit 8 set in {ck.counts['hw_x_hi_set']}, multicolour bit set in {ck.counts['hw_mc_set']}")
    print(f"zone slots finished ON line Y: {ck.counts['finished_on_line_y']}, latest cycle seen {ck.counts['max_cyc_on_line_y']}")
    print(f"mux_late_count {late}, irq_late_count {ilate}, DEBUG counters {counters}\n")
    print(f"{'attribute':<14}{'checked':>9}{'mismatch':>10}")
    fails = []
    from positions import ATTRS
    for attr in ATTRS + ["before_y_line", "free_before_write", "d015_top", "park_d015", "park_mask"]:
        c, b = ck.checked[attr], ck.bad[attr]
        print(f"{attr:<14}{c:>9}{b:>10}  {'PASS' if c and not b else 'FAIL'}")
        if b or not c:
            fails.append(attr)
        for e in ck.examples.get(attr, []):
            print("    " + e)
    for o in ck.other[:20]:
        print("[FAIL] " + o)
    if ck.other:
        fails.append(f"{len(ck.other)} structural/timing failures")
    if late or ilate:
        fails.append("late counters")
    print("\nFAILED: " + ", ".join(fails) if fails else "\nALL PASS")
    return 1 if fails else 0


def slack_main(a):
    g = Game(a.prg)
    sym, mon = g.sym, g.mon
    entries, inxs = zone_layout(g)
    for ad in inxs:
        mon.checkpoint_set(ad, ad, CPU_OP_EXEC)
    drv = Driver(g, a.wave, a.seed_wait, a.bot_seed, a.hostile)
    gue = sym["game_update_end"]
    bend = sym["mux_build_end"]
    if a.hostile:
        mon.checkpoint_set(bend, bend, CPU_OP_EXEC)
    sy = sym["mux_s_y"]
    cats = ("all", "Y badline", "Y 1-3 below badline", "other")
    n = Counter(); on_y = Counter(); max_cyc = Counter(); min_slack = {}; lines_before = Counter()
    slack_hist = Counter()
    worst = []
    gframes = 0
    try:
        while gframes < a.frames:
            mon.exit()
            if not mon.wait_stopped(STOP_TIMEOUT):
                mon.ping()
                raise MeasureError(f"no checkpoint within {STOP_TIMEOUT}s at game frame {gframes}: jam?")
            r = mon.registers()
            if r["PC"] == gue:
                gframes += 1
                g.frames += 1
                drv.frame()
                if drv.hostile and g.gstate() != GS_TITLE:
                    drv.hostile_in()
                if gframes % 1000 == 0:
                    print(f"  ...{gframes} game frames, {n['all']} slots", flush=True)
                continue
            if r["PC"] == bend:
                drv.hostile_out()
                continue
            lin, cyc, x = r["LIN"], r["CYC"], r["X"]
            y = mon.mem_get(sy + x, sy + x)[0]
            slack = (y - lin) * 63 + (DMA_CYCLE - cyc)
            if 51 <= y <= 243 and y % 8 == 3:
                cat = "Y badline"
            elif 51 <= y <= 243 + 3 and y % 8 in (4, 5, 6):
                cat = "Y 1-3 below badline"
            else:
                cat = "other"
            for c in ("all", cat):
                n[c] += 1
                min_slack[c] = min(min_slack.get(c, slack), slack)
                if lin == y:
                    on_y[c] += 1
                    max_cyc[c] = max(max_cyc[c], cyc)
            lines_before[min(max(y - lin, -1), 6)] += 1
            slack_hist[min(slack, 200) // 10 * 10] += 1
            if slack <= 0:
                worst.append((slack, y, lin, cyc, x, cat))
        late, ilate = get_late(g)
        counters = g.counters()
    finally:
        g.close()
    print(f"\n{a.prg}: {gframes} game frames, {n['all']} consecutive zone slots, deadline line Y cycle {DMA_CYCLE}, mux_late_count {late}, irq_late_count {ilate}")
    print("coverage (game frames):", dict(drv.cover), "games started:", drv.games, "hostile layouts:", dict(drv.layouts))
    print("divers active (frames):", dict(sorted(drv.divers.items())))
    print("lines from the slot's last write to its line Y (-1 = past Y, 6 = 6 or more):", sorted(lines_before.items()))
    print("slack histogram (cycles, 10-wide bins, 200 = 200 or more):", sorted(slack_hist.items()))
    print(f"{'class':<22}{'slots':>8}{'on line Y':>11}{'latest cyc':>12}{'min slack':>11}")
    for c in cats:
        if n[c]:
            print(f"{c:<22}{n[c]:>8}{on_y[c]:>11}{(max_cyc[c] if on_y[c] else '-'):>12}{min_slack[c]:>11}")
    print("DEBUG counters:", counters)
    for w in worst[:20]:
        print(f"[FAIL] write at/after deadline: slack {w[0]} Y {w[1]} line {w[2]} cycle {w[3]} slot X={w[4]} ({w[5]})")
    print("\nFAILED: writes at or after the deadline" if worst else "\nALL PASS (every last write before line Y cycle 55)")
    return 1 if worst or late or ilate else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=1000)
    ap.add_argument("--slack", action="store_true")
    ap.add_argument("--wave", type=int, default=1)
    ap.add_argument("--hostile", action="store_true", help="overwrite the mux arrays with the engine's hostile layouts")
    ap.add_argument("--seed-wait", type=int, default=0)
    ap.add_argument("--bot-seed", type=int, default=1)
    ap.add_argument("--prg", default=str(DEBUG_PRG))
    a = ap.parse_args()
    return slack_main(a) if a.slack else positions_main(a)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL (jam/hang/layout): {e}")
        sys.exit(2)
