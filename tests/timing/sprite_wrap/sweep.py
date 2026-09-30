"""Sweep sprite_wrap.prg: per-line sprite DMA and displayed rows, for several sprite Y settings.

For each configuration it pokes the probe's RAM, then:
- DMA: for every probed line L it runs the 62-cycle block started on L (main.asm) for `passes`
  passes (the probe's 32 start phases) and keeps the passes that start on line L at cycle 11-36:
  their raster time - 62 is exactly the DMA that feeds display line L + 1 (main.asm says why).
  Line 0 is probed through the probe's "line 312" path.
- Display: with the screen on (DEN=1) and the borders open, it reads VICE's frame buffer and lists
  the raster lines on which sprite 0's column shows its colour. Rows are mapped to raster lines by
  a reference: a reversed space in text row 0 (column 39), whose first row is raster line 51, the
  measured first badline (tests/timing/badline). VICE renders raster lines 16-287 only.
- It checks that the display lines equal the DMA lines + 1 wherever VICE renders them.

    cd mcp/vice && uv run python ../../tests/timing/sprite_wrap/sweep.py [passes]

Needs a build first: make GAME=sprite_wrap SRC_DIR=tests/timing/sprite_wrap
Measured 2026-09-30, VICE 3.10 x64sc PAL, passes = 32 (DMA lines are block start lines L):
  Y=55:  DMA 55-75 and 311, 0-19 (21 + 21 lines), 5 cycles each; shown 56-76 and 16-20 (0-20)
  Y=56:  DMA 56-76 only; shown 57-77. Nothing after line 255, nothing at the top.
  Y=35:  DMA 35-55 and 291-311; Y=0: DMA 0-20 and 256-276; Y=10: 10-30 and 266-286
  Y=55 Y-expanded: DMA 55-96 (42) and 311, 0-40 (42)
  Y=55 screen on: the same wrap DMA (in the border, no badlines); sprites 0-7 at Y=55: 19 a line
  Shown lines == DMA lines + 1 on every rendered, probed line, in every single-sprite configuration.
See docs/reference/vic-ii-timing.md#sprite-y-and-the-frame-wrap.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "mcp" / "vice"))

from vice_monitor import CPU_OP_EXEC, ViceMonitor, free_port, load_symbols, run_frames  # noqa: E402

CYCLES_PER_LINE = 63  # measured: tests/timing/rasterline
FRAME = 312 * CYCLES_PER_LINE
BLOCK = 62            # 31 NOPs
START_MIN, START_MAX = 11, 36  # usable pass start cycles on line L
MIN_KEPT = 8          # usable passes needed per line
ALL_LINES = list(range(0, 101)) + list(range(256, 312))

REF_CHAR = 0x0427     # screen row 0, column 39: the raster-51 reference (clear of the sprites)
REF_COLOUR = 7
REF_LINE = 51         # first badline, measured: tests/timing/badline
HALF = list(range(0, 25)) + list(range(300, 312))

# name, $D011 for the DMA sweep ($0B: DEN off, no badlines), $D015, $D017, sprite Ys, lines to probe
CONFIGS = [
    ("sprite 0, Y=55", 0x0B, 0x01, 0x00, [55] * 8, ALL_LINES),
    ("sprite 0, Y=56", 0x0B, 0x01, 0x00, [56] * 8, ALL_LINES),
    ("sprite 0, Y=35", 0x0B, 0x01, 0x00, [35] * 8, ALL_LINES),
    ("sprite 0, Y=10", 0x0B, 0x01, 0x00, [10] * 8, ALL_LINES),
    ("sprite 0, Y=0", 0x0B, 0x01, 0x00, [0] * 8, ALL_LINES),
    ("sprite 0, Y=55, Y-expanded", 0x0B, 0x01, 0x01, [55] * 8, ALL_LINES),
    ("sprite 0, Y=55, screen on (DEN=1)", 0x1B, 0x01, 0x00, [55] * 8, HALF),
    ("sprites 0-7, Y=55", 0x0B, 0xFF, 0x00, [55] * 8, HALF),
]


def ranges(items: list[tuple[int, str]]) -> str:
    """[(line, tag)] sorted -> 'a-b tag, c tag' with runs of consecutive lines and equal tags."""
    out, run = [], []
    for line, tag in items:
        if run and line == run[-1][0] + 1 and tag == run[-1][1]:
            run.append((line, tag))
        else:
            if run:
                out.append(run)
            run = [(line, tag)]
    if run:
        out.append(run)
    return ", ".join(f"{r[0][0]}-{r[-1][0]} ({len(r)}) {r[0][1]}" if len(r) > 1 else f"{r[0][0]} {r[0][1]}"
                     for r in out) or "none"


def main() -> None:
    passes = int(sys.argv[1]) if len(sys.argv) > 1 else 32
    prg = REPO / "build" / "sprite_wrap" / "sprite_wrap.prg"
    sym = load_symbols(prg)
    port = free_port()
    proc = subprocess.Popen(
        ["x64sc", "-default", "-pal", "-sounddev", "dummy", "-warp", "-minimized",
         "-binarymonitor", "-binarymonitoraddress", f"ip4://127.0.0.1:{port}", "-autostartprgmode", "1"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    mon = ViceMonitor(port=port)
    mon.connect()
    mon.drain_events(0.3)

    def profile(a: int, b: int) -> list[tuple[int, int, int]]:
        """(start line, start cycle, raster cycles) of `passes` passes of a -> b."""
        cp = mon.checkpoint_set(a, a, CPU_OP_EXEC)
        cp2 = mon.checkpoint_set(b, b, CPU_OP_EXEC)
        costs, t0 = [], None
        try:
            while len(costs) < passes:
                mon.exit()
                if not mon.wait_stopped(5):
                    raise RuntimeError("block not reached")
                r = mon.registers()
                t = r["LIN"] * CYCLES_PER_LINE + r["CYC"]
                if r["PC"] == a:
                    t0, start = t, (r["LIN"], r["CYC"])
                elif t0 is not None:
                    costs.append((*start, (t - t0) % FRAME))
                    t0 = None
        finally:
            mon.checkpoint_delete(cp.number)
            mon.checkpoint_delete(cp2.number)
        return costs

    def shown_lines(x: int, colour: int) -> tuple[list[int], range]:
        """Raster lines where column x (sprite X) shows `colour`, and the raster lines rendered."""
        d = mon.display_get()
        px = d.pixels.ljust(d.width * d.height, b"\x00")
        ref_col = d.offset_x + 39 * 8 + 4
        ref = [y for y in range(d.height) if px[y * d.width + ref_col] == REF_COLOUR]
        if len(ref) != 8:
            raise RuntimeError(f"reference character not found (rows {ref})")
        shift = REF_LINE - ref[0]                   # raster line = buffer row + shift
        col = d.offset_x + (x - 24) + 12            # middle of the 24-pixel sprite
        drawn = [y for y in range(d.height) if px[y * d.width + col] != 0]  # 0 = black, not rendered
        return ([y + shift for y in range(d.height) if px[y * d.width + col] == colour],
                range(drawn[0] + shift, drawn[-1] + shift + 1))

    try:
        mon.autostart(str(prg), run=True)
        cp = mon.checkpoint_set(sym["loop"], sym["loop"], CPU_OP_EXEC)
        mon.exit()
        mon.wait_stopped(20)
        mon.checkpoint_delete(cp.number)
        mon.mem_set(REF_CHAR, b"\xa0")                  # reversed space
        mon.mem_set(REF_CHAR + 0xD400, bytes([REF_COLOUR]))  # its colour RAM ($D827)
        for name, d011, enable, yexp, ys, lines in CONFIGS:
            mon.mem_set(sym["d011_val"], b"\x1b")      # screen on for the display scan
            mon.mem_set(sym["spr_enable"], bytes([enable]))
            mon.mem_set(sym["spr_yexp"], bytes([yexp]))
            mon.mem_set(sym["spr_y"], bytes(ys))
            # Displayed rows: probe a line that never skips a frame, so the border opens every frame.
            mon.mem_set(sym["probe_hi"], b"\x00")
            mon.mem_set(sym["probe_lo"], bytes([100]))
            run_frames(mon, 4)
            x0 = mon.mem_get(sym["spr_x"], sym["spr_x"])[0]
            shown, rendered = shown_lines(x0, 1)
            mon.mem_set(sym["d011_val"], bytes([d011]))
            run_frames(mon, 2)
            dma = []
            skipped = 0
            for line in lines:
                # Line 0 is probed as line 312 (the probe waits for the wrap); see main.asm.
                hi, lo = (1, line - 256) if line >= 256 else (1, 312 - 256) if line == 0 else (0, line)
                mon.mem_set(sym["probe_hi"], bytes([hi]))
                mon.mem_set(sym["probe_lo"], bytes([lo]))
                run_frames(mon, 3)
                a, b = (sym["wrap_blk_hi"], sym["wrap_blk_hi_end"]) if hi else (sym["wrap_blk"], sym["wrap_blk_end"])
                # Keep passes that start on line L at cycle 11-36: those see exactly the DMA that
                # feeds display line L + 1 (main.asm's header says why).
                c = [cost for lin, cyc, cost in profile(a, b) if lin == line and START_MIN <= cyc <= START_MAX]
                skipped += passes - len(c)
                if len(c) < MIN_KEPT:
                    raise RuntimeError(f"{name}: line {line}: only {len(c)} usable passes")
                lo_s, hi_s = min(c) - BLOCK, max(c) - BLOCK
                if hi_s:
                    dma.append((line, f"{lo_s}" if lo_s == hi_s else f"{lo_s}-{hi_s}"))
            print(f"== {name}")
            print(f"   DMA feeding display line L + 1, by block start line L (steal min-max; "
                  f"{passes} passes a line, {skipped} discarded in all): {ranges(dma)}")
            print(f"   sprite 0 shown on raster lines (VICE frame buffer, lines {rendered.start}-"
                  f"{rendered.stop - 1} rendered): {ranges([(s, '') for s in shown])}")
            if enable == 0x01:
                # Compare only display lines whose feeding line L was probed and that VICE renders.
                seen = {(line + 1) % 312 for line in lines} & set(rendered)
                expect = sorted(l for l in ((line + 1) % 312 for line, _ in dma) if l in seen)
                got = [l for l in shown if l in seen]
                print(f"   shown == DMA lines + 1 (on {len(seen)} rendered, probed lines): "
                      f"{'yes' if expect == got else 'NO'}")
            sys.stdout.flush()
    finally:
        mon.quit()
        mon.close()
        proc.wait(timeout=5)


if __name__ == "__main__":
    main()
