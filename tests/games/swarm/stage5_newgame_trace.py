"""Two loose ends from stage 4 part B, traced (Swarm, M4 stage 5). Technical Director, 2026-10-02.

1. THE NEW GAME'S FRAME GREW BY 103 CYCLES in part B (game_update 2,190 -> 2,293) where one sound
   request (36) was expected. This prints, for the frame game_new runs in, every routine's raster
   cost (IRQ time excluded) and the raster line and cycle it starts and ends on, so the growth can
   be laid against the code that was added and the badlines the frame crosses. Run it on the
   part A build too (below) and compare line by line.

2. THE $D012 READ AT THE TITLE'S PRESS: "line 27 at all of 8 presses" (stage4_costs.txt) against
   "line 26" (check.py's title-press case). title.asm's lda $d012 starts 21 cycles before its
   jsr rng_seed reaches rng_seed (lda $d012 4, eor 3, tax 2, lda 3, eor 3, jsr 6) and the read
   itself is the lda's fourth cycle, 18 before: the line and cycle at rng_seed, less 18, place the
   read. Printed for presses in several title frames, with the value that was read (X at rng_seed
   is the line read ^ zp_rng_hi, which still holds the stepped state there).

On the game's DEBUG build (build/swarm), the stick through the monitor's joyport.
Run from the repo root (seconds):

    uv run --package budget-runner python tests/games/swarm/stage5_newgame_trace.py | tee tests/games/swarm/stage5_newgame_trace.txt

The same on the stage 4 part A build (commit 7f9e937, no sound), appended to the results:

    git worktree add /tmp/swarm_4a 7f9e937 && make -C /tmp/swarm_4a GAME=swarm
    uv run --package budget-runner python tests/games/swarm/stage5_newgame_trace.py \
        --prg /tmp/swarm_4a/build/swarm/swarm.prg | tee -a tests/games/swarm/stage5_newgame_trace.txt
    git worktree remove --force /tmp/swarm_4a

Results of the last runs: tests/games/swarm/stage5_newgame_trace.txt.
"""

import sys
from pathlib import Path

from budget_runner.evaluate import profile_costs
from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice, build_program
from vice_monitor import CPU_OP_EXEC

GS_OVER, GS_TITLE = 3, 4
JOYPORT_IO_SIMULATION, PORT2 = 37, 1
PRESS_FRAMES = (8, 9, 12, 23, 40, 77, 130, 142, 200)
READ_TO_SEED = 18                   # cycles from the read (the 4th cycle of lda $d012) to rng_seed's first instruction
SPANS = ("game_update", "input_read", "panel_update", "stars_update", "title_update", "formation_update",
         "diver_update", "collide_update", "player_update")
ENDS = {"game_update": "game_update_end", "input_read": None, "title_update": None}


def main() -> int:
    prg = Path(sys.argv[2]) if len(sys.argv) == 3 and sys.argv[1] == "--prg" else build_program("swarm")
    shown = prg.resolve().relative_to(Path.cwd()) if prg.resolve().is_relative_to(Path.cwd()) else prg
    print(f"# uv run --package budget-runner python tests/games/swarm/stage5_newgame_trace.py   ({shown}, VICE 3.10 x64sc PAL, DEBUG)")
    v = Vice(prg, 60)
    try:
        mon, sym = v.mon, v.symbols
        end = sym["game_update_end"]
        mon.resource_set("JoyPort2Device", JOYPORT_IO_SIMULATION)
        mon.joyport_set(PORT2, 0x1F)

        def frame(n=1):
            for _ in range(n):
                cp = mon.checkpoint_set(end, end, CPU_OP_EXEC)
                mon.exit()
                if not mon.wait_stopped(STOP_TIMEOUT):
                    mon.ping()
                    raise MeasureError("game_update_end not reached")
                mon.checkpoint_delete(cp.number)

        def poke(label, data):
            mon.mem_set(sym[label], bytes(data))

        def peek(label, n=1):
            return mon.mem_get(sym[label], sym[label] + n - 1)

        def to_title():
            frame()
            if peek("zp_game_state")[0] != GS_TITLE:
                poke("zp_game_state", [GS_OVER])
                poke("zp_state_timer", [199])
                frame()

        d, r = v.addr("irq_dispatch"), v.addr("irq_exit_rti")
        pairs = {a: (sym[a], sym[ENDS.get(a) or a + "_end"]) for a in SPANS if a in sym and (ENDS.get(a) or a + "_end") in sym}
        seed = sym["rng_seed"]
        reads = []
        for i, f in enumerate(PRESS_FRAMES):
            to_title()
            while peek("zp_state_timer")[0] + 1 < f:
                frame()
            f = peek("zp_state_timer")[0] + 1           # the title frame the press is in (the first is later than
                                                        # asked: the power-on title has already run)
            mon.joyport_set(PORT2, 0x0F)                # fire down in the title's frame f
            ev = v.trace([seed], lambda e: len(e) >= 1, "rng_seed at the press")
            regs = mon.registers()
            t = ev[0].line * 63 + ev[0].cycle - READ_TO_SEED
            reads.append((f, t // 63, t % 63, ev[0].line, ev[0].cycle, regs["X"] ^ peek("zp_rng_hi")[0]))
            mon.joyport_set(PORT2, 0x1F)
            frame()                                     # the press's frame, to its end
            if i:
                frame(7)                                # past the erase frames, into the new game
                continue
            # the first press only: the new game's frame, 6 frames after the press's
            frame(5)
            addrs = sorted({x for p in pairs.values() for x in p} | {d, r})
            gu, gue = pairs["game_update"]
            ev = v.trace(addrs, lambda e: sum(1 for x in e if x.pc == gue) >= 1 and any(x.pc == gu for x in e), "the new game's frame")
            first = [k for k, x in enumerate(ev) if x.pc == gu][0]
            seg = ev[first:]
            print(f"the new game's frame (the title's press was in its frame {f}), routine: raster cycles, IRQ time excluded; "
                  f"line.cycle it starts and ends on:")
            for name, (a, b) in pairs.items():
                if any(x.pc == a for x in seg) and any(x.pc == b for x in seg):
                    s = [x for x in seg if x.pc == a][-1]
                    e = [x for x in seg if x.pc == b][-1]
                    print(f"  {name:<17} {profile_costs(seg, a, b, d, r)[-1]:>5}   {s.line}.{s.cycle:02d} -> {e.line}.{e.cycle:02d}")
            print(f"  wave phase {peek('zp_wave_phase')[0]}, wave timer {peek('zp_wave_timer')[0]}, game state {peek('zp_game_state')[0]} "
                  f"(Intro's frame 0 of a new game: 1, 0, 0)")
        print("the $D012 read at the press (title frame: line.cycle of the read, by rng_seed's line.cycle less 18; the "
              "value read, from X at rng_seed ^ the stepped zp_rng_hi):")
        for f, line, cyc, sl, sc, x in reads:
            print(f"  frame {f:>3}: read at {line}.{cyc:02d} (rng_seed at {sl}.{sc:02d}): value {x}")
        print(f"  values read: {sorted({x for _, _, _, _, _, x in reads})}")
        return 0
    finally:
        v.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL: {e}")
        sys.exit(2)
