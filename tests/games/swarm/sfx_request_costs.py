"""What Swarm's sound requests cost where they are made (M4 stage 4 part B budget decisions).

A COUNT, not a measurement: the measured costs of engine/sfx.asm's sfx_play (tests/engine/sfx,
locked in its budget.json: whole call 34 nothing pending, 49 a pending request replaced, 37 a
pending higher one kept) laid on a raster line with the measured DMA steals, by the model of
tests/games/swarm/short_routine_dma.py (a badline 43 cycles, n sprites 2n + 3 a line). It prints
every figure docs/games/swarm/memory-map.md "Stage 4 part B: sound requests" quotes.

A request is `lda #SFX_x` (2) + `jsr sfx_play` (the whole call), + 6 for each register the caller
has to keep (stx/ldx or sty/ldy through a zero-page byte: sfx_play uses A, X, Y and no zero page).

The model is checked against the spike's display measurement first (tests/engine/sfx/
measure_results.txt, DISPLAY: whole calls 77, 92 and 80 at worst with a badline and no sprites).

The stage 4 part A measurements it adds the requests to are the gameplay-engineer's:
tests/games/swarm/stage4_costs.txt and stage4a_collide_worst.txt.

Run from the repo root (instant, no emulator):

    python3 tests/games/swarm/sfx_request_costs.py | tee tests/games/swarm/sfx_request_costs.txt
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from short_routine_dma import worst  # noqa: E402

TAKE, REPLACE, KEEP = 34, 49, 37        # jsr sfx_play, whole call, CPU (locks, tests/engine/sfx)
LDA, SAVE = 2, 6                        # lda #effect; one register kept through a zero-page byte
FLAG_SET, FLAG_TEST = 6, 8              # lda # / sta abs;  lsr abs / bcc (not taken)


def pct5(x):
    return round(x * 1.05)


def main():
    print("# python3 tests/games/swarm/sfx_request_costs.py   (a count: sfx_play's measured whole calls")
    print("# on the measured DMA steals; no emulator)")
    print("Model against the spike's measurement (sfx_play in the display, a badline, no sprites):")
    for name, cpu, meas in (("take", TAKE, 77), ("replace", REPLACE, 92), ("keep", KEEP, 80)):
        print(f"  {name}: {cpu} CPU -> model {worst(cpu, 0)}, measured {meas}")

    print("One request (lda # + jsr sfx_play), raster cycles at worst:")
    print("  path      CPU   border   border, 3 wrapped divers   display, no sprites   6 sprites   8 sprites")
    for name, call in (("take", TAKE), ("replace", REPLACE), ("keep", KEEP)):
        c = call + LDA
        print(f"  {name:<9} {c:<5} {c:<8} {worst(c, 3, False):<26} {worst(c, 0):<21} {worst(c, 6):<11} {worst(c, 8)}")

    print("Row 3, player_update (display, 8 sprites a line; 150 CPU without sound, stage 3):")
    c = 150 + LDA + REPLACE
    print(f"  150 + the shot's request (replace: an enemy shot may be pending on voice 1) = {c} CPU -> {worst(c, 8)} (limit 365)")

    print("Row 5, formation_update in Clear's first frame (border, no sprite DMA: no diver exists):")
    c = LDA + TAKE + 2 * SAVE
    print(f"  measured 650-670 + the wave-clear request {c} CPU (take, X and Y kept) = {650 + c}-{670 + c} (limit 750);")
    print(f"  it ended on lines 37-38: {c} cycles more is under one line (63)")

    print("Row 6, diver_update (border into the first enemy row; measured 994 max in AUTOPLAY, + 5% = "
          f"{pct5(994)}):")
    direct3 = 3 * (LDA + 2 * SAVE) + TAKE + 2 * REPLACE
    direct21 = 2 * (LDA + 2 * SAVE) + TAKE + REPLACE + (LDA + TAKE + 2 * SAVE)
    once3 = 3 * FLAG_SET + FLAG_TEST + LDA + TAKE
    once21 = 2 * FLAG_SET + FLAG_TEST + LDA + TAKE + (LDA + TAKE + 2 * SAVE)
    for name, c in (("a request for each of 3 enemy shots", direct3),
                    ("a request for each of 2 shots, and the dive", direct21),
                    ("ONE enemy-shot request a frame (a flag), 3 shots", once3),
                    ("ONE enemy-shot request a frame, 2 shots, and the dive", once21)):
        w = worst(c, 8)
        print(f"  {name}: {c} CPU -> {w} at worst; {pct5(994)} + {w} = {pct5(994) + w} (limit 1350)")

    print("Row 8, collide_update (display; frame C measured 2471, + 5% = " f"{pct5(2471)}):")
    cases = (
        ("frame C as it is (2 shot hits' flags, the ram: hit A take, hit B take; no explosion request)",
         FLAG_SET + 2 * FLAG_SET + 2 * (LDA + TAKE)),
        ("the upper bound: the same with hit B replacing a dive or wave-clear request",
         FLAG_SET + 2 * FLAG_SET + (LDA + TAKE) + (LDA + REPLACE)),
        ("the upper bound if the explosion were also asked for in the hit's frame (kept)",
         FLAG_SET + 2 * FLAG_SET + (LDA + TAKE) + (LDA + REPLACE) + FLAG_TEST - 2 + LDA + KEEP),
        ("a frame with no player hit: 2 flags, the test, the explosion (take)",
         FLAG_SET + 2 * FLAG_SET + FLAG_TEST - 2 + LDA + TAKE),
    )
    for name, c in cases:
        print(f"  {name}: {c} CPU -> {worst(c, 6)} with 6 sprites a line, {worst(c, 8)} with 8; "
              f"{pct5(2471)} + {worst(c, 8)} = {pct5(2471) + worst(c, 8)} (limit 2825)")

    print("Row 1, game_state_update and the title (border, lines 23-45):")
    c = LDA + TAKE
    print(f"  wave start, game over, start: {c} CPU each (take), one a frame; with 3 wrapped divers' fetches "
          f"(GameOver's frame 0) {worst(c, 3, False)}")
    print("AUTOPLAY's three priority-3 requests every 64 frames (border, line 23-24, no DMA): "
          f"{3 * (LDA + TAKE)} in game_update")

    print("Row 12, the sound tick (IRQ, lines 251-259, no DMA: raster = CPU):")
    print("  game_irq_bottom -> rti: jsr 6 + span 417 + rts 6 + jmp 3 + irq_exit 66 = "
          f"{6 + 417 + 6 + 3 + 66} (the spike's 511 less its 13 of call-site choice)")
    print(f"  on top of the entry's 93 of framework (which has irq_exit at 60): 429 + 6 = {429 + 6}")
    print(f"  with an eighth write in a start (14 a start, + 1 a voice if the first branch becomes a jump): "
          f"{429 + 6 + 3 * 15}")


if __name__ == "__main__":
    main()
