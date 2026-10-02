"""Worst raster cost of a SHORT main-loop routine that runs in the display (Swarm, M4 stage 3 budget).

Why: a routine of a few dozen to a few hundred CPU cycles doesn't lose "about 27%" to DMA. It
loses a fixed amount: a whole badline (43 cycles) if it meets one, plus the sprite fetches of every
line it touches. stars_update (57 CPU cycles) measured 129 raster cycles when it met badline 59 in
the first enemy row (tests/games/swarm/stage2b_costs.txt), not 57 x 1.27 = 72.

This is a COUNT, not a measurement: it lays the measured steals of docs/reference/vic-ii-timing.md
on a raster line and finds, over every start cycle, the longest raster time a run of `cpu` CPU
cycles can take:

  badline            43 cycles, VICE cycles 12-54        (tests/timing/badline; trace_badline.py)
  n sprites a line   2 n + 3 cycles (one group): 8 -> 19, the fetches of sprites 3-7 on cycles
                     0-10 and of 0-2 on 55-62             (tests/timing/sprites)
  badlines           every 8th line

Instruction boundaries are ignored (a real instruction can't use one lone free cycle), so a
measurement can be a cycle or two either side. The model gives the WORST start cycle; a sampled
maximum is at or below it. Measured points that check it (printed first):

  stars_update, 57 CPU, badline 51, no sprites:        measured 100 (make test ARGS=swarm, 300
                                                       passes, stage 2 part B build)
  stars_update, 57 CPU, badline 59, 6 enemy sprites:   measured 129 over 600 passes
                                                       (stage2b_costs.txt): the badline and two
                                                       lines' fetches, 57 + 43 + 2 x 15 - 1. The
                                                       model's 145 is a third line's fetch more,
                                                       a start cycle those 600 passes didn't hit
  bls_blk, 126 CPU, sprites 0-7, a badline:            measured 126 + 119 = 245 (vic-ii-timing.md,
                                                       "Badline and sprites on the same line")
  spr_blk, 126 CPU, sprites 0-7, no badline:           measured 183 (vic-ii-timing.md, "Sprite DMA")

Run from the repo root (instant, no emulator):

    python3 tests/games/swarm/short_routine_dma.py

Results of the last run: tests/games/swarm/short_routine_dma.txt (the memory map's rows 3, 4, 5, 7
and 10 and its "Short routines" method quote them). Not for long routines: no routine of a
thousand cycles has 8 sprites on every line it crosses; those keep the measured x 1.23-1.36.
"""

LINE, BADLINE_EVERY = 63, 8
BADLINE_CYCLES = range(12, 55)          # 43 cycles


def stolen(sprites, badlines=True):
    """One badline period (8 lines) as a list of booleans: True = the VIC-II has the bus."""
    d = 2 * sprites + 3 if sprites else 0
    head = min(d, 11)                   # sprites 3-7: cycles 0-10
    tail = d - head                     # sprites 0-2: the end of the line
    out = []
    for line in range(BADLINE_EVERY):
        for c in range(LINE):
            s = c < head or c >= LINE - tail
            if badlines and line == 0 and c in BADLINE_CYCLES:
                s = True
            out.append(s)
    return out


def worst(cpu, sprites, badlines=True):
    """Longest raster time for `cpu` CPU cycles, over every start cycle of the 8-line period."""
    mask = stolen(sprites, badlines)
    n, best = len(mask), 0
    for start in range(n):
        if mask[start]:
            continue                    # a routine starts on a cycle the CPU has
        got, t = 0, start
        while got < cpu:
            if not mask[t % n]:
                got += 1
            t += 1
        best = max(best, t - start)
    return best


def main():
    print("# python3 tests/games/swarm/short_routine_dma.py   (a count from the measured steals of")
    print("# docs/reference/vic-ii-timing.md; no emulator)")
    print("Model against measurements:")
    for name, cpu, spr, bl, meas in (("stars_update, badline 51, no sprites", 57, 0, True, "100"),
                                     ("stars_update, badline 59, 6 enemy sprites", 57, 6, True,
                                      "129 max over 600 passes (two lines' fetches: 57 + 43 + 30)"),
                                     ("bls_blk, badline, sprites 0-7", 126, 8, True, "245"),
                                     ("spr_blk, no badline, sprites 0-7", 126, 8, False, "183")):
        print(f"  {name}: {cpu} CPU -> model {worst(cpu, spr, bl)}, measured {meas}")
    print("Worst raster cycles for a routine of N CPU cycles (rows) with S sprites on every line")
    print("it touches (columns), meeting a badline; and x 1.27 for comparison:")
    cols = (0, 3, 6, 8)
    print("  CPU    " + "".join(f"S={s:<6}" for s in cols) + "x1.27")
    for cpu in (43, 57, 100, 122, 150, 200, 300):
        print(f"  {cpu:<6} " + "".join(f"{worst(cpu, s):<8}" for s in cols) + f"{round(cpu * 1.27)}")
    print("The same in the border above line 51 (no badline), S sprites of wrapped or rising divers:")
    cols = (0, 1, 3)
    print("  CPU    " + "".join(f"S={s:<6}" for s in cols))
    for cpu in (43, 57, 150, 231, 627):
        print(f"  {cpu:<6} " + "".join(f"{worst(cpu, s, False):<8}" for s in cols))


if __name__ == "__main__":
    main()
