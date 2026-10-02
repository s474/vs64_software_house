"""QA of the RELEASE build against DEBUG (M4 stage 5, item 4), headless.

Run from the repo root (build first: make GAME=swarm; make BUILD=release GAME=swarm):

    uv run --package budget-runner python tests/games/swarm/qa_release.py

Both builds are driven with the same stick script (title, a press at the same frame, a bot) and compared:
  * the game's own state frame by frame (score, ship X, enemies alive, lives, state, phase, every
    sprite's X and Y from the mux_* arrays) for 1,500 frames: identical = the release plays the same game
    as the build that was tested (the DEBUG build's extra code doesn't change what the game does)
  * screenshots of the title, the Intro, play, READY, GAME OVER, written to screenshots/ as
    swarm-qa-{debug,release}-<what>.png, and the number of pixels that differ between the two builds
    (a sprite or star one frame apart shows as a few pixels; a real difference as many)
  * the border and background colour registers ($D020, $D021): a store checkpoint on each over 3,000
    frames of play in the release build lists every write (a debug border flash would show as writes
    to $D020 after init); the DEBUG build is run the same way for comparison
  * the release labels (zp_game_state, game_score, zp_lives) read through the monitor
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_lib import *  # noqa: E402,F403
from vice_monitor import CPU_OP_STORE  # noqa: E402

SHOTS = REPO / "screenshots"


def run_script(prg, tag, frames=1500):
    g = Game(prg)
    rec = []
    shots = {}
    try:
        g.run(20, [])
        g.screenshot(SHOTS / f"swarm-qa-{tag}-title.png")
        g.step(["fire"])
        g.step([])
        got_game = False
        for k in range(frames):
            if g.gstate() == GS_PLAY and not got_game:
                got_game = True
            stick = g.bot_stick() if got_game else 0
            g.step(stick)
            sp = g.sprites()
            rec.append((g.gstate(), g.peek("zp_lives"), g.score(), g.player_x(), g.peek("zp_enemies_alive"), g.peek("zp_wave_phase"), tuple(sp)))
            if k == 40:
                g.screenshot(SHOTS / f"swarm-qa-{tag}-intro.png")
            if k == 300:
                g.screenshot(SHOTS / f"swarm-qa-{tag}-play.png")
            if g.gstate() == GS_RESPAWN and "ready" not in shots and g.peek("zp_state_timer") > 5:
                g.screenshot(SHOTS / f"swarm-qa-{tag}-ready.png"); shots["ready"] = k
            if g.gstate() == GS_OVER and "over" not in shots and g.peek("zp_state_timer") > 5:
                g.screenshot(SHOTS / f"swarm-qa-{tag}-gameover.png"); shots["over"] = k
        end = g.summary()
    finally:
        g.close()
    return rec, shots, end


def pixel_diff(a, b):
    import zlib, struct
    def load(p):
        d = Path(p).read_bytes()
        pos, idat, w, h = 8, b"", 0, 0
        while pos < len(d):
            n = struct.unpack(">I", d[pos:pos + 4])[0]
            t = d[pos + 4:pos + 8]
            if t == b"IHDR":
                w, h = struct.unpack(">II", d[pos + 8:pos + 16])
            if t == b"IDAT":
                idat += d[pos + 8:pos + 8 + n]
            pos += 12 + n
        return w, h, zlib.decompress(idat)
    wa, ha, ra = load(a)
    wb, hb, rb = load(b)
    if (wa, ha) != (wb, hb):
        return None
    stride = 1 + 3 * wa
    diff = 0
    for y in range(ha):
        la, lb = ra[y * stride + 1:(y + 1) * stride], rb[y * stride + 1:(y + 1) * stride]
        if la != lb:
            diff += sum(1 for x in range(wa) if la[3 * x:3 * x + 3] != lb[3 * x:3 * x + 3])
    return diff


def border_writes(prg, tag, frames=3000):
    g = Game(prg)
    mon, sym = g.mon, g.sym
    hits = {}
    control = [0]
    try:
        cps = []
        for a in (0xD020, 0xD021, 0xD015):          # $D015 is the positive control: the multiplexer stores it every frame
            cps.append(mon.checkpoint_set(a, a, CPU_OP_STORE))
        g.run(20, [])
        g.step(["fire"])
        n = 0
        # run frame by frame; the monitor stops at game_update_end and at any $D020/$D021 store
        games = 1
        while n < frames:
            mon.exit()
            if not mon.wait_stopped(STOP_TIMEOUT):
                mon.ping()
                raise MeasureError("jam")
            r = mon.registers()
            if r["PC"] == sym["game_update_end"]:
                n += 1
                g.frames += 1
                stick = g.bot_stick() if g.gstate() != GS_TITLE else (BITS["fire"] if n % 40 == 0 else 0)
                g.mon.joyport_set(PORT2, ~stick & 0x1F)
            else:
                a = r["PC"]
                # which register was stored: the checkpoint that fired is not reported, so read the opcode's operand
                op = mon.mem_get(a - 3, a - 1)            # the 3-byte store just executed (sta abs)
                reg = op[1] + 256 * op[2] if op[0] in (0x8D, 0x8E, 0x8C) else None
                if reg == 0xD015:
                    control[0] += 1
                else:
                    hits[a] = hits.get(a, 0) + 1
        for c in cps:
            mon.checkpoint_delete(c.number)
        final = (g.mon.mem_get(0xD020, 0xD020)[0] & 15, g.mon.mem_get(0xD021, 0xD021)[0] & 15)
    finally:
        g.close()
    print(f"  ({prg.parent.name} control: {control[0]} stores to $D015 seen in the same run)")
    return hits, final


def main():
    ok = True
    dbg, dshots, dend = run_script(DEBUG_PRG, "debug")
    rel, rshots, rend = run_script(RELEASE_PRG, "release")
    n = min(len(dbg), len(rel))
    first = next((i for i in range(n) if dbg[i] != rel[i]), None)
    print(f"state per frame, {n} frames, DEBUG vs release: {'IDENTICAL' if first is None else f'first difference at frame {first}'}")
    if first is not None:
        a, b = dbg[first], rel[first]
        print("  DEBUG  ", a[:6])
        print("  release", b[:6])
        ok = False
    print("  DEBUG end:", dend)
    print("  release end:", rend)
    print("  screenshots with the game state:", dshots, rshots)
    for what in ("title", "intro", "play", "ready", "gameover"):
        a, b = SHOTS / f"swarm-qa-debug-{what}.png", SHOTS / f"swarm-qa-release-{what}.png"
        if a.exists() and b.exists():
            print(f"  screenshot {what}: differing pixels {pixel_diff(a, b)}")
        else:
            print(f"  screenshot {what}: missing in one build (debug {a.exists()}, release {b.exists()})")
    for name, prg in (("release", RELEASE_PRG), ("debug", DEBUG_PRG)):
        hits, final = border_writes(prg, name)
        sym_lines = {k: v for k, v in hits.items()}
        print(f"stores to $D020/$D021 over 3,000 frames in {name}: {sum(hits.values())} from PCs {[hex(k) for k in sym_lines]}; final border/background {final}")
        if name == "release" and hits:
            ok = False
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
