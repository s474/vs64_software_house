"""End-to-end check of the VICE MCP server, talking to it exactly as Claude Code does:
launched with the command in the repo's .mcp.json, from the repo root, over stdio.

    cd mcp/vice && uv run smoke_test.py

Builds hello with make first. Screenshots land in screenshots/smoke-*.png.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

REPO_ROOT = Path(__file__).resolve().parents[2]
PROGRAM = "build/hello/hello.prg"


def text_of(result) -> str:
    return "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")


async def main() -> int:
    subprocess.run(["make", "-s", "GAME=hello"], cwd=REPO_ROOT, check=True, stdout=subprocess.DEVNULL)
    config = json.loads((REPO_ROOT / ".mcp.json").read_text())["mcpServers"]["vice"]
    server = StdioServerParameters(command=config["command"], args=config["args"], cwd=str(REPO_ROOT))
    failures = 0
    async with Client(server) as client:
        tools = await client.list_tools()
        print("tools:", ", ".join(t.name for t in tools.tools))

        async def call(tool: str, check: str | None = None, **args):
            nonlocal failures
            result = await client.call_tool(tool, args)
            text = text_of(result)
            ok = not result.is_error and (check is None or check in text)
            failures += not ok
            print(f"\n[{'ok' if ok else 'FAIL'}] {tool}({args})\n{text}")
            return result

        await call("vice_start", "symbols", program=PROGRAM)
        # anticipated failures must reach the model with their message, not a generic error
        missing = await client.call_tool("vice_load", {"program": "build/nope.prg"})
        if not (missing.is_error and "file not found" in text_of(missing)):
            failures += 1
            print(f"[FAIL] missing-file error not reported clearly: {text_of(missing)!r}")
        else:
            print(f"\n[ok] vice_load(missing) -> {text_of(missing)}")
        await call("vice_symbols", "irq_top")
        await call("vice_run_frames", "Ran 10", frames=10)
        shot = await call("vice_screenshot", "384x272", name="smoke-hello")
        if not any(getattr(c, "type", "") == "image" for c in shot.content):
            failures += 1
            print("[FAIL] screenshot returned no image")
        await call("vice_screenshot", "504x312", name="smoke-hello-full", area="full")
        await call("vice_read_memory", "$d020", address="$d020", length=1)
        # hello's two raster IRQs are $b0-$80 = 48 lines apart: 48 * 63 = 3024 cycles, give or
        # take a few cycles of IRQ entry jitter (the CPU finishes its current instruction first)
        prof = await call("vice_profile", "cycles", start="irq_top", end="irq_bottom", samples=10)
        words = text_of(prof).replace(",", "").split()
        lo, hi = int(words[words.index("min") + 1]), int(words[words.index("max") + 1])
        if not (3024 - 7 <= lo <= hi <= 3024 + 7):
            failures += 1
            print(f"[FAIL] profile {lo}..{hi} not within 3024 +/- 7")
        await call("vice_run_until", "Hit exec", address="irq_bottom")
        # now stopped at `end`: the next stops come end-first, and must still pair up correctly
        prof = await call("vice_profile", "over 5 pass", start="irq_top", end="irq_bottom", samples=5)
        if "min 30" not in text_of(prof):
            failures += 1
            print("[FAIL] profile starting between start and end measured the wrong span")
        await call("vice_registers")
        # joystick: $dc00 should read up+fire while held (bits 0 and 4 low)
        await call("vice_write_memory", "Wrote", address="$c000",
                   hex_bytes="ad 00 dc 8d 00 c1 4c 00 c0")  # loop: lda $dc00 / sta $c100
        await call("vice_registers", "PC=$c000", set_values={"PC": 0xC000})
        await call("vice_joystick", "held up+fire", input="up+fire", frames=2, release=False)
        mem = await call("vice_read_memory", None, address="$c100", length=1)
        if (int(text_of(mem).split()[1], 16) & 0x1F) != 0x0E:
            failures += 1
            print("[FAIL] joystick value not seen in $dc00")
        await call("vice_joystick", "held none", input="none", frames=1)  # release port 2
        await call("vice_joystick", "Port 1", port=1, input="fire", frames=2)
        # charset must still be upper case: $d018 = $15 (port 1 input must not leak into the keyboard)
        await call("vice_reset", "PC=")
        await call("vice_read_memory", "$d018: 15", address="$d018", length=1)
        await call("vice_type", "Typed", text='PRINT "HI"\n')
        await call("vice_screenshot", "Saved", name="smoke-basic")
        await call("vice_stop", "stopped")
    print(f"\n{'PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
