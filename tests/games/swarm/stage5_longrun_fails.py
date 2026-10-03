"""Why the stage 5 long run failed player_update (377 / 365) and stars_update (61 / 60), reproduced
(Swarm, M4 stage 5 sign-off; the build of commit 2d6cf3f). Technical Director, 2026-10-03.

`make test-long ARGS=swarm_budget` (every count x 34, Simon, 2026-10-03) read player_update at 377
against 365 and stars_update at 61 against 60; every other check passed. This script runs the same
AUTOPLAY budget build (build/swarm_budget, DEBUG) and traces the two routines pass by pass, with
the budget runner's own measure (raster cycles, IRQ time excluded: budget_runner.evaluate.
profile_costs), and prints for each pass that is dearer than the row's count what was going on.

  stars N        N passes of stars_update. For each: its cost and the raster line and cycle it
                 started on. A pass over 57 prints zp_game_frame mod 64 and the hardware sprites'
                 Y registers. FINDING: every such pass starts on line 30 in a frame whose
                 zp_game_frame is a multiple of 64 (autoplay_update's three sound requests, AUTOPLAY
                 only, run before panel_update and push the border work ~2 lines later), with a
                 wrapped diver at Y 30 in hardware sprite 0: one sprite's fetch, 2 + 3 = 5 cycles.
  player N       N passes of player_update, with the zone IRQs nested in each. Prints the number
                 of passes and the maximum by number of nested IRQs, and every pass over 358 (the
                 row's count with no IRQ) with its start, the IRQ's dispatch and rti, its end.
                 FINDING: every pass over 358 has one zone IRQ nested in it, which splits the
                 routine in two, and each part meets a badline (two badlines, not one).
  border N       N frames: the raster lines the five border routines start and end on, and the
                 first IRQ of each frame after mux_irq_top (line 16). Checks the premise of rows 4,
                 5, 7, 9 and 10 that no IRQ can land in the border work (so no IRQ can split it).
  --replace      (player) at the start of every pass, set voice 1's pending request to the enemy
                 shot (sfx_request + 0 = 2), so that a firing pass takes sfx_play's dearest path
                 (a pending request of equal priority replaced: 49 as a whole call): player_update's
                 dearest CPU path, 201, in every firing frame. The places it lands are AUTOPLAY's own.
  --check        (stars) exit 1 if any pass starts on line 30 or later: the premise of row 10
                 (no sprite fetch can reach stars_update) checked directly. budget.json runs this.

The build is deterministic: the 377 is pass 34,215 of `player` (from the end of the 400 warm-up
frames), the frame Simon's long run met as its pass 13,815 (game_update's 20,400 passes run first).

Run from the repo root (it builds nothing: run `make GAME=swarm_budget SRC_DIR=tests/games/swarm
ASSET_DIR=games/swarm/src` first, or `make test ARGS=swarm_budget`, which builds it):

    uv run --package budget-runner python tests/games/swarm/stage5_longrun_fails.py stars 60000
    uv run --package budget-runner python tests/games/swarm/stage5_longrun_fails.py player 150000
    uv run --package budget-runner python tests/games/swarm/stage5_longrun_fails.py player 120000 --replace
    uv run --package budget-runner python tests/games/swarm/stage5_longrun_fails.py border 20000

About 2.6 ms a pass for stars, 2.7 for player (VICE warp, the checkpoint stops). Results of the
runs quoted in docs/games/swarm/memory-map.md ("Stage 5 review", "The long run"):
tests/games/swarm/stage5_longrun_fails.txt.
"""

import sys
import time
from pathlib import Path

from budget_runner.evaluate import CYCLES_PER_LINE, FRAME, Event, profile_costs
from budget_runner.session import REPO, MeasureError, Vice
from vice_monitor import CPU_OP_EXEC

PLAYER_COUNT = 358          # row 3's count with no IRQ (memory-map.md row 3, short_routine_dma.py)
STARS_CPU = 57              # stars_update's CPU count, its cost with no DMA
STARS_LAST_LINE = 29        # row 10's premise: it starts on line 29 at the latest


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    prg_flag = [a for a in flags if a.startswith("--prg=")]
    if len(args) != 2 or args[0] not in ("stars", "player", "border"):
        print(__doc__)
        return 2
    mode, n = args[0], int(args[1])
    prg = Path(prg_flag[0][6:]) if prg_flag else REPO / "build" / "swarm_budget" / "swarm_budget.prg"
    if not prg.exists():
        raise MeasureError(f"{prg} not built (make GAME=swarm_budget SRC_DIR=tests/games/swarm ASSET_DIR=games/swarm/src)")
    print(f"# uv run --package budget-runner python tests/games/swarm/stage5_longrun_fails.py "
          f"{' '.join(sys.argv[1:])}   ({prg.relative_to(REPO) if prg.is_relative_to(REPO) else prg}, "
          f"VICE 3.10 x64sc PAL, DEBUG, 400 warm-up frames; raster cycles, IRQ time excluded)")
    v = Vice(prg, 400)
    t0 = time.time()
    try:
        mon, sym = v.mon, v.symbols

        def stop():
            mon.exit()
            if not mon.wait_stopped(5.0):
                mon.ping()
                raise MeasureError("checkpoint not reached")
            return mon.registers()

        def vic_ys():
            vic = mon.mem_get(0xD000, 0xD01F)
            return f"$D015 ${vic[0x15]:02x}, sprite Y {[vic[1 + 2 * k] for k in range(8)]}"

        if mode == "border":
            names = ("panel_update", "stars_update", "pshot_update", "eshot_update", "formation_update")
            where = {}
            for nm in names:
                where[sym[nm]] = (nm, 0)
                where[sym[nm + "_end"]] = (nm, 1)
            d = sym["irq_dispatch"]
            for addr in [*where, d]:
                mon.checkpoint_set(addr, addr, CPU_OP_EXEC)
            seen = {nm: ({}, {}) for nm in names}
            irq_lines, frames, first_irq = {}, 0, None
            while frames < n:
                r = stop()
                if r["PC"] == d:
                    if 16 < r["LIN"] < 100 and first_irq is None:
                        first_irq = r["LIN"]
                        irq_lines[first_irq] = irq_lines.get(first_irq, 0) + 1
                    continue
                nm, k = where[r["PC"]]
                h = seen[nm][k]
                h[r["LIN"]] = h.get(r["LIN"], 0) + 1
                if nm == "formation_update" and k == 1:
                    frames += 1
                    first_irq = None
            for nm in names:
                st, en = seen[nm]
                print(f"{nm}: starts on lines {sorted(st.items())}, ends on lines {sorted(en.items())}")
            print(f"first IRQ after mux_irq_top (line 16) and before line 100, by line: {sorted(irq_lines.items())}"
                  f"   ({n} frames, {time.time() - t0:.0f} s)")
            return 0

        if mode == "stars":
            a, b = sym["stars_update"], sym["stars_update_end"]
            mon.checkpoint_set(a, a, CPU_OP_EXEC)
            mon.checkpoint_set(b, b, CPU_OP_EXEC)
            hist, lines, late = {}, {}, 0
            for i in range(n):
                r = stop()
                s, sl = r["LIN"] * CYCLES_PER_LINE + r["CYC"], (r["LIN"], r["CYC"])
                r = stop()
                c = r["LIN"] * CYCLES_PER_LINE + r["CYC"] - s     # no IRQ is due on lines 23-31
                hist[c] = hist.get(c, 0) + 1
                lines[sl[0]] = lines.get(sl[0], 0) + 1
                late += sl[0] > STARS_LAST_LINE
                if c > STARS_CPU:
                    fr = mon.mem_get(sym["zp_game_frame"], sym["zp_game_frame"])[0]
                    print(f"pass {i}: {c} cycles, line {sl[0]} cycle {sl[1]} to line {r['LIN']} cycle "
                          f"{r['CYC']}, zp_game_frame mod 64 = {fr & 63}, {vic_ys()}")
            print(f"{n} passes: cost -> passes {sorted(hist.items())}")
            print(f"start line -> passes {sorted(lines.items())}")
            print(f"passes starting after line {STARS_LAST_LINE}: {late}   ({time.time() - t0:.0f} s)")
            if "--check" in flags and late:
                print(f"FAIL: row 10's premise (stars_update starts on line {STARS_LAST_LINE} at the latest) "
                      f"does not hold in {late} of {n} passes")
                return 1
            return 0

        a, b = sym["player_update"], sym["player_update_end"]
        d, x = sym["irq_dispatch"], sym["irq_exit_rti"]
        req = sym["sfx_request"]
        mon.checkpoint_set(a, a, CPU_OP_EXEC)
        mon.checkpoint_set(b, b, CPU_OP_EXEC)
        hist, by_irqs = {}, {}
        for i in range(n):
            r = stop()
            if "--replace" in flags:
                mon.mem_set(req, bytes([2]))          # SFX_ENEMY_SHOT + 1 pending on voice 1
            evs = [Event(a, r["LIN"] * CYCLES_PER_LINE + r["CYC"], r["LIN"], r["CYC"])]
            c1, c2 = mon.checkpoint_set(d, d, CPU_OP_EXEC), mon.checkpoint_set(x, x, CPU_OP_EXEC)
            while True:
                r = stop()
                t = r["LIN"] * CYCLES_PER_LINE + r["CYC"]
                if t < evs[-1].t:
                    t += FRAME
                evs.append(Event(r["PC"], t, r["LIN"], r["CYC"]))
                if r["PC"] == b:
                    break
            mon.checkpoint_delete(c1.number)
            mon.checkpoint_delete(c2.number)
            c = profile_costs(evs, a, b, d, x)[0]
            k = sum(1 for e in evs if e.pc == d)
            hist[c] = hist.get(c, 0) + 1
            cnt, mx = by_irqs.get(k, (0, 0))
            by_irqs[k] = (cnt + 1, max(mx, c))
            if c > PLAYER_COUNT:
                names = {a: "start", b: "end", d: "irq_dispatch", x: "irq_exit_rti"}
                trail = ", ".join(f"{names[e.pc]} {e.line}/{e.cycle}" for e in evs)
                print(f"pass {i}: {c} (raw {evs[-1].t - evs[0].t}): {trail}; {vic_ys()}", flush=True)
        print(f"{n} passes: nested IRQs -> (passes, max) {sorted(by_irqs.items())}")
        print(f"the 12 dearest: {sorted(hist.items())[-12:]}   ({time.time() - t0:.0f} s)")
        return 0
    finally:
        v.close()


if __name__ == "__main__":
    sys.exit(main())
