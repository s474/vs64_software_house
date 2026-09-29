"""Trace sprites.prg's bls_blk (63 NOPs across badline $33 = line 51) one instruction at a time.

vice_profile gives the total raster time of a block; this shows WHERE the CPU was halted and
how many CPU cycles land on the badline itself. It stops at every NOP in bls_blk and reads the
raster (line, cycle) from VICE, so a gap of more than 2 cycles between NOPs is a stall.

    cd mcp/vice && uv run python ../../tests/timing/sprites/trace_badline.py <mask> [passes] [-q]

mask: hex sprite-enable byte poked into spr_enable (00, 01, 07, f8, ff ...).
-q prints only one SUMMARY line per pass: CPU cycles executed on line 51 and the block's raster
time. Line counts are quantized by the 2-cycle NOPs (an instruction can't use a lone free cycle).
Needs a build first: make GAME=sprites SRC_DIR=tests/timing/sprites
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "mcp" / "vice"))

from vice_monitor import CPU_OP_EXEC, ViceMonitor, free_port, load_symbols  # noqa: E402

BADLINE = 51
CYCLES_PER_LINE = 63  # measured: tests/timing/rasterline


def main() -> None:
    prg = REPO / "build" / "sprites" / "sprites.prg"
    mask = int(sys.argv[1], 16)
    passes = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] != "-q" else 1
    quiet = "-q" in sys.argv
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
    try:
        mon.autostart(str(prg), run=True)
        cp = mon.checkpoint_set(sym["start"], sym["start"], CPU_OP_EXEC)
        mon.exit()
        mon.wait_stopped(20)
        mon.checkpoint_delete(cp.number)
        mon.mem_set(sym["spr_enable"], bytes([mask]))
        cp = mon.checkpoint_set(sym["loop"], sym["loop"], CPU_OP_EXEC)
        for _ in range(3):  # let the mask reach $d015
            mon.exit()
            mon.wait_stopped(5)
        mon.checkpoint_delete(cp.number)

        a, b = sym["bls_blk"], sym["bls_blk_end"]
        cp = mon.checkpoint_set(a, b, CPU_OP_EXEC)
        for p in range(passes):
            rows: list[tuple[int, int, int]] = []
            while True:
                mon.exit()
                mon.wait_stopped(5)
                r = mon.registers()
                if r["PC"] == a:
                    rows = []
                if r["PC"] == a or rows:
                    rows.append((r["PC"] - a, r["LIN"], r["CYC"]))
                if r["PC"] == b and rows:
                    break
            t0 = rows[0][1] * CYCLES_PER_LINE + rows[0][2]
            total = rows[-1][1] * CYCLES_PER_LINE + rows[-1][2] - t0
            on_badline = sum(
                (lin + c // CYCLES_PER_LINE) == BADLINE for _, lin, cyc in rows[:-1] for c in (cyc, cyc + 1)
            )
            print(f"SUMMARY mask ${mask:02x} cpu_cycles_on_line{BADLINE}={on_badline} total_raster={total}")
            if quiet:
                continue
            prev = None
            for off, lin, cyc in rows:
                t = lin * CYCLES_PER_LINE + cyc
                gap = "" if prev is None else f"+{t - prev}"
                stall = "  <-- stall" if prev is not None and t - prev > 2 else ""
                print(f"  nop#{off:2d} line {lin} cycle {cyc:2d} {gap}{stall}")
                prev = t
    finally:
        mon.quit()
        mon.close()
        proc.wait(timeout=5)


if __name__ == "__main__":
    main()
