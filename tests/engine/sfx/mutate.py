"""Mutation test of tests/engine/sfx/check.py: does it catch a faulty engine/sfx.asm?

For each fault below, a copy of engine/sfx.asm with that one change is assembled with the spike
(in build/sfx_mutants/<name>/, with the spike's sources copied beside it so that
`#import "engine/sfx.asm"` finds the copy; nothing in the repo is modified; the script checks
that each mutant's PRG differs from the unmodified one), and check.py is run on the result. A mutant is
KILLED when check.py exits non-zero. Exit code 1 if any mutant survives or the unmodified module
fails.

Run from the repo root:

    uv run --package budget-runner python tests/engine/sfx/mutate.py | tee tests/engine/sfx/mutate_results.txt

About 3 minutes (most mutants die in the first case; the two control runs take 50 s each).
The mutants are built in build/sfx_mutants/ (scratch: only this script's output is kept).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
JAVA = os.environ.get("JAVA", "/opt/homebrew/opt/openjdk/bin/java")
KICKASS = os.environ.get("KICKASS_JAR", "/Applications/KickAssembler/KickAss.jar")
OUT = REPO / "build/sfx_mutants"

# (name, what the fault is, text to find exactly once in engine/sfx.asm, replacement)
MUTANTS = [
    ("equal-priority", "the tick: an equal priority no longer replaces what is playing",
     "        bcc play                        // 2 / 3  lower than what is playing: dropped  (= 23)",
     "        bcc play\n        beq play"),
    ("tie-first-wins", "sfx_play: on a tie the earlier request is kept",
     "        bcc sfx_play_end                // 2 / 3  lower: the pending one stays  (= 25)",
     "        bcc sfx_play_end\n        beq sfx_play_end"),
    ("lower-overwrites", "sfx_play: a lower priority overwrites the pending request",
     "        bcc sfx_play_end                // 2 / 3  lower: the pending one stays  (= 25)",
     ""),
    ("no-control-0", "a start leaves out the control-0 write (the registers end the tick the same)",
     "        _SfxSty(r + SFX_CTRL)           // 8 w  Y = 0",
     ""),
    ("write-order", "a start writes sustain/release before attack/decay",
     "        lda sfx_ad - 1,x                // 4\n        _SfxSta(r + SFX_AD)             // 8 w\n"
     "        lda sfx_sr - 1,x                // 4\n        _SfxSta(r + SFX_SR)             // 8 w\n",
     "        lda sfx_sr - 1,x\n        _SfxSta(r + SFX_SR)\n        lda sfx_ad - 1,x\n        _SfxSta(r + SFX_AD)\n"),
    ("one-tick-long", "a step lasts one tick too many",
     "        beq end                         // 2 / 3\n",
     "        beq end\n        clc\n        adc #1\n"),
    ("gate-left-on", "the end marker leaves the gate set",
     "end:    lda sfx_s_ctrl,y                // 4  the last waveform, gate clear: the release plays out",
     "end:    lda sfx_s_ctrl,y\n        ora #1"),
    ("queued", "a dropped request stays pending (queued) instead of being dropped",
     "        sty sfx_request + v             // 4  taken: from here the main loop's next request stands\n"
     "        lda sfx_prio - 1,x              // 4\n"
     "        cmp sfx_cur_prio + v            // 4\n"
     "        bcc play                        // 2 / 3  lower than what is playing: dropped  (= 23)\n",
     "        lda sfx_prio - 1,x\n        cmp sfx_cur_prio + v\n        bcc play\n        sty sfx_request + v\n"),
    ("slide-high", "the slide's high byte comes from the low table",
     "        adc sfx_s_shi,y                 // 4",
     "        adc sfx_s_slo,y"),
    ("slide-first-tick", "the slide is already applied on a step's first tick",
     "        lda sfx_s_flo,y                 // 4\n        sta sfx_freq_lo + v             // 4",
     "        lda sfx_s_flo,y\n        clc\n        adc sfx_s_slo,y\n        sta sfx_freq_lo + v"),
    ("voice-2-skipped", "voice 2 is never serviced (voice 1 twice)",
     "        _SfxVoice(2)", "        _SfxVoice(1)"),
    ("shadow-only", "DEBUG: a frequency write reaches the shadow but not the SID register ($D40F)",
     "        sta sfx_freq_hi + v             // 4\n        _SfxSta(r + SFX_FREQ_HI)        // 8 w  slide: 7 + 6 + 8 + 46 = 67",
     "        sta sfx_freq_hi + v\n        .if (v != 2) {\n        sta SFX_SID + r + SFX_FREQ_HI\n        }\n        sta sfx_shadow + r + SFX_FREQ_HI"),
    ("volume-click", "the tick rewrites $D418 every frame (same value: the registers look the same)",
     "sfx_update_end:\n        rts                             // 6",
     "        lda #$0f\n        sta SFX_SID + SFX_VOLUME\nsfx_update_end:\n        rts"),
]


def build(name: str, source: str) -> tuple[Path | None, str]:
    """Assemble the spike against `source` as engine/sfx.asm. The spike's own files are copied
    beside it, so that the import resolves to the copy (a path relative to the importing file
    wins over the include path, and so does one relative to the working directory)."""
    d = OUT / name
    (d / "engine").mkdir(parents=True, exist_ok=True)
    (d / "engine/sfx.asm").write_text(source)
    for f in ("main.asm", "zp.asm", "swarm_sfx.asm"):
        shutil.copy(REPO / "tests/engine/sfx" / f, d / f)
    prg = d / "sfx.prg"
    p = subprocess.run([JAVA, "-jar", KICKASS, "main.asm", "-o", str(prg), "-odir", str(d),
                        "-libdir", str(REPO), "-vicesymbols", "-define", "DEBUG"],
                       cwd=d, capture_output=True, text=True)
    if p.returncode or not prg.exists():
        return None, (p.stdout + p.stderr)[-600:]
    return prg, ""


def check(prg: Path) -> tuple[int, str]:
    p = subprocess.run(["uv", "run", "--quiet", "--package", "budget-runner", "python",
                        "tests/engine/sfx/check.py", "--prg", str(prg)], cwd=REPO, capture_output=True, text=True)
    lines = [x for x in p.stdout.splitlines() if x.startswith("[FAIL]") or x.startswith("FAIL")]
    return p.returncode, (lines[0] if lines else p.stdout.strip().splitlines()[-1])[:230]


# Room for a mutant to be longer than the module: the tick's first branch (`beq play`) is 127
# bytes long in a DEBUG build, the most a branch can be, and the code has a size limit. Every
# mutant is built from this roomier copy, which is itself checked first (it must pass).
ROOM = [
    ("        beq play                        // 2 / 3\n        ldy #0",
     "        bne *+5\n        jmp play\n        ldy #0"),
    (".const SFX_CODE_MAX = 600", ".const SFX_CODE_MAX = 700"),
]


def main() -> int:
    original = (REPO / "engine/sfx.asm").read_text()
    bad = 0
    prg, err = build("control", original)
    code, line = check(prg) if prg else (99, err)
    print(f"control (the module as it is): check.py exit {code}: {line}", flush=True)
    bad += code != 0
    for old, new in ROOM:
        if original.count(old) != 1:
            print(f"ROOM: text found {original.count(old)} times in engine/sfx.asm (fix this script)")
            return 1
        original = original.replace(old, new)
    prg, err = build("control-room", original)
    code, line = check(prg) if prg else (99, err)
    control = prg.read_bytes() if prg else b""
    print(f"control with room (a far jump for the tick's first branch, no fault): check.py exit {code}: {line}", flush=True)
    bad += code != 0
    for name, what, old, new in MUTANTS:
        if original.count(old) != 1:
            print(f"{name}: SKIPPED, its text is found {original.count(old)} times in engine/sfx.asm (fix this script)")
            bad += 1
            continue
        prg, err = build(name, original.replace(old, new))
        if prg is None:
            print(f"{name}: did not assemble:\n{err}")
            bad += 1
            continue
        if prg.read_bytes() == control:
            print(f"{name}: the mutant's PRG is the same as the unmodified one (the change did not reach the build)")
            bad += 1
            continue
        code, line = check(prg)
        print(f"{name}: {what}\n    {'KILLED' if code else 'SURVIVED'} (check.py exit {code}): {line}", flush=True)
        bad += code == 0
    print(f"\n{len(MUTANTS)} mutants, {len(MUTANTS) - bad if bad <= len(MUTANTS) else 0} killed"
          if not bad else f"\nFAILED: {bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
