"""Check engine/sfx.asm against an independent model of its contract (engine/sfx.md: "sfx_play,
exactly" and "sfx_update, exactly"), every SID register write, every frame.

How. The spike (tests/engine/sfx/main.asm) is put in SCRIPT mode (spike_mode = 0): each frame its
main loop calls sfx_play for each non-zero byte of spike_cmd, in order, then the tick at line 251
calls sfx_update. This script stops the machine once a frame at spike_frame (after the tick,
before the next frame's requests), pokes that frame's requests, and between two stops it also
stops at EVERY store to $D400-$D418 (one store checkpoint a register) and records the register
and the value written. After each frame it compares, with the Python model below:

  - the list of writes the tick made: which registers, which values, in which order (so the
    control-0 write of a start, which the next write hides, is checked too);
  - $D400-$D418 as the monitor reads them (the last value written to each: measured,
    docs/reference/sid.md fact 3), so the same script checks a release build;
  - sfx_shadow, all 25 bytes, in a DEBUG build (the label exists);
  - sfx_cur and sfx_request.

The model reads the effect tables from the running program's memory (sfx_voice ... sfx_s_shi,
SFX_COUNT, SFX_STEPS) and shares nothing else with the module.

Cases (PASS/FAIL each; exit code 1 on any failure, 2 if the machine jams):
  init        after sfx_init and the first frames: $D418 = $0F, nothing written to $D415-$D418 since
  alone       each of the 13 effects alone, to its end and two frames beyond; its gate is cleared
              and its voice idle on tick N = the sum of its steps' frames, not before
  pairs       every ordered pair of effects on one voice, the second asked for 3 ticks after the
              first: a higher priority replaces, an equal one replaces, a lower one is dropped and
              the first ends on its own tick. An effect on another voice runs through each
  same-frame  two and three requests for one voice in one frame: every ordered pair, each effect
              twice, and every order of one triple a voice: the highest priority starts, the
              later call on a tie
  end-frame   a request on the tick before an effect ends, in the frame it ends and in the frame
              after, lower and equal (the three shortest effects of each voice as the first)
  triple      three effects starting in one frame (three sets, one with a fourth request)
  random      3,000 frames of requests from random.Random(20261002): 0 to 4 a frame, any effect,
              in blocks that are busy, sparse or silent, so that long idles, ends, step changes
              and pile-ups all occur. Compared every frame. The model's counts of what happened
              are printed
  untouched   $D402/$D409/$D410 (pulse width low) and $D415-$D418 were never written after init,
              in the whole run

Run from the repo root (build first: make GAME=sfx SRC_DIR=tests/engine/sfx):

    uv run --package budget-runner python tests/engine/sfx/check.py [--prg build/sfx/sfx.prg] [--frames 3000]

About 50 s. On a release build (make BUILD=release ...): the same, without the shadow.
make test runs it as the spike's script check.
"""

import argparse
import itertools
import random
import sys
from collections import Counter
from pathlib import Path

from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice
from vice_monitor import CPU_OP_EXEC, CPU_OP_STORE  # on sys.path once budget_runner.session is imported

REPO = Path(__file__).resolve().parents[3]
SID = 0xD400
FLO, FHI, PWLO, PWHI, CTRL, AD, SR = range(7)
SEED = 20261002


class Model:
    """engine/sfx.md's semantics, written from the contract's text."""

    def __init__(self, tab, reg):
        self.t = tab
        self.request = [0, 0, 0]
        self.cur = [0, 0, 0]
        self.cur_prio = [0, 0, 0]
        self.step = [0, 0, 0]
        self.left = [0, 0, 0]
        self.freq = [0, 0, 0]
        self.reg = bytearray(reg)  # $D400-$D418 as last written
        self.stats = Counter()

    def play(self, e):
        t = self.t
        v = t["voice"][e]
        p = self.request[v]
        if p == 0:
            self.request[v] = e + 1
            self.stats["play: nothing pending"] += 1
        elif t["prio"][p - 1] > t["prio"][e]:
            self.stats["play: pending higher, kept"] += 1
        else:
            self.request[v] = e + 1
            self.stats["play: pending equal or lower, replaced"] += 1

    def _w(self, out, v, r, val):
        self.reg[7 * v + r] = val
        out.append((7 * v + r, val))

    def _load(self, out, v, s):
        t = self.t
        if t["frames"][s] != 0:
            self.left[v] = t["frames"][s]
            self.freq[v] = t["freq"][s]
            self._w(out, v, FLO, self.freq[v] & 255)
            self._w(out, v, FHI, self.freq[v] >> 8)
            self._w(out, v, CTRL, t["ctrl"][s])
            self.step[v] = s
        else:
            self._w(out, v, CTRL, t["ctrl"][s])
            self.cur[v] = 0
            self.cur_prio[v] = 0
            self.stats["tick: end"] += 1

    def update(self):
        """One tick. Returns the writes it makes, in order: [(register 0-24, value)]."""
        t, out = self.t, []
        starts = 0
        for v in range(3):
            r = self.request[v]
            if r != 0:
                self.request[v] = 0
                e = r - 1
                if t["prio"][e] >= self.cur_prio[v]:
                    self.stats["tick: start" + (" (cutting an effect off)" if self.cur[v] else "")] += 1
                    starts += 1
                    self.cur[v] = e + 1
                    self.cur_prio[v] = t["prio"][e]
                    self._w(out, v, AD, t["ad"][e])
                    self._w(out, v, SR, t["sr"][e])
                    self._w(out, v, PWHI, t["pw"][e])
                    self._w(out, v, CTRL, 0)
                    self._load(out, v, t["first"][e])
                    continue
                self.stats["tick: request dropped (lower than what is playing)"] += 1
            if self.cur_prio[v] == 0:
                continue
            self.left[v] -= 1
            if self.left[v] != 0:
                self.freq[v] = (self.freq[v] + t["slide"][self.step[v]]) & 0xFFFF
                self._w(out, v, FLO, self.freq[v] & 255)
                self._w(out, v, FHI, self.freq[v] >> 8)
                self.stats["tick: slide"] += 1
            else:
                if t["frames"][self.step[v] + 1] != 0:
                    self.stats["tick: step change"] += 1
                self._load(out, v, self.step[v] + 1)
        if starts == 3:
            self.stats["tick: three starts"] += 1
        return out

    def idle(self):
        return self.cur == [0, 0, 0] and self.request == [0, 0, 0]


class Spike:
    def __init__(self, prg):
        self.v = Vice(Path(prg), 20)
        self.mon, self.sym = self.v.mon, self.v.symbols
        mon, sym = self.mon, self.sym
        self.debug = "sfx_shadow" in sym
        n, s = sym["SFX_COUNT"], sym["SFX_STEPS"]

        def tab(label, size):
            return list(mon.mem_get(sym[label], sym[label] + size - 1))

        flo, fhi, slo, shi = (tab(x, s) for x in ("sfx_s_flo", "sfx_s_fhi", "sfx_s_slo", "sfx_s_shi"))
        self.tab = {
            "voice": tab("sfx_voice", n), "prio": tab("sfx_prio", n), "ad": tab("sfx_ad", n),
            "sr": tab("sfx_sr", n), "pw": tab("sfx_pw", n), "first": tab("sfx_first", n),
            "frames": tab("sfx_s_frames", s), "ctrl": tab("sfx_s_ctrl", s),
            "freq": [a | b << 8 for a, b in zip(flo, fhi)], "slide": [a | b << 8 for a, b in zip(slo, shi)],
        }
        self.count = n
        self.frame_cp = mon.checkpoint_set(sym["spike_frame"], sym["spike_frame"], CPU_OP_EXEC).number
        self.store_cp = {}
        self.written = Counter()  # register -> writes seen, over the whole run
        self.frames = 0
        self.model = None

    def close(self):
        self.v.close()

    def length(self, e):
        """Sum of the effect's steps' frames."""
        s, n = self.tab["first"][e], 0
        while self.tab["frames"][s]:
            n += self.tab["frames"][s]
            s += 1
        return n

    def to_frame(self):
        """Run to the next spike_frame; returns the SID writes on the way, in order."""
        mon, writes = self.mon, []
        while True:
            mon.exit()
            if not mon.wait_stopped(STOP_TIMEOUT):
                mon.ping()
                raise MeasureError("spike_frame not reached: jam?")
            hits = list(mon.state.hit_checkpoints)
            regs = [self.store_cp[h] for h in hits if h in self.store_cp]
            for r in regs:
                writes.append((r, mon.mem_get(SID + r, SID + r)[0]))
                self.written[r] += 1
            if self.frame_cp in hits or (not regs and mon.registers()["PC"] == self.sym["spike_frame"]):
                return writes

    def begin(self):
        """SCRIPT mode, every voice idle, store checkpoints set, the model in step."""
        mon, sym = self.mon, self.sym
        self.to_frame()
        mon.mem_set(sym["spike_mode"], bytes([0]))
        mon.mem_set(sym["spike_cmd"], bytes(4))
        for _ in range(300):
            self.to_frame()
            if mon.mem_get(sym["sfx_cur"], sym["sfx_cur"] + 2) == bytes(3) and \
                    mon.mem_get(sym["sfx_request"], sym["sfx_request"] + 2) == bytes(3):
                break
        else:
            raise MeasureError("the spike's voices never went idle")
        for r in range(25):
            self.store_cp[mon.checkpoint_set(SID + r, SID + r, CPU_OP_STORE).number] = r
        self.model = Model(self.tab, mon.mem_get(SID, SID + 24))

    def frame(self, cmds=()):
        """One frame with these requests (effect numbers, at most 4). Returns None, or what differs."""
        mon, sym, m = self.mon, self.sym, self.model
        assert len(cmds) <= 4
        mon.mem_set(sym["spike_cmd"], bytes([e + 1 for e in cmds] + [0] * (4 - len(cmds))))
        for e in cmds:
            m.play(e)
        want = m.update()
        got = self.to_frame()
        self.frames += 1

        def fmt(w):
            return " ".join(f"${SID + r:04x}={v:02x}" for r, v in w) or "(none)"

        if got != want:
            return f"writes differ.\n         module: {fmt(got)}\n         model : {fmt(want)}"
        reg = mon.mem_get(SID, SID + 24)
        if reg != bytes(m.reg):
            return f"$D400-$D418 differ.\n         monitor: {reg.hex(' ')}\n         model  : {bytes(m.reg).hex(' ')}"
        if self.debug:
            sh = mon.mem_get(sym["sfx_shadow"], sym["sfx_shadow"] + 24)
            if sh != bytes(m.reg):
                return f"sfx_shadow differs.\n         shadow: {sh.hex(' ')}\n         model : {bytes(m.reg).hex(' ')}"
        cur = list(mon.mem_get(sym["sfx_cur"], sym["sfx_cur"] + 2))
        req = list(mon.mem_get(sym["sfx_request"], sym["sfx_request"] + 2))
        if cur != m.cur or req != m.request:
            return f"state differs: sfx_cur {cur} (model {m.cur}), sfx_request {req} (model {m.request})"
        return None

    def play(self, script, extra=2):
        """script: {frame: [effects]}. Runs it, then on until every voice is idle, + `extra`
        frames. Returns (None or the first difference, frames run, {frame: model.cur after it})."""
        last = max(script)
        f, curs = 0, {}
        while True:
            bad = self.frame(script.get(f, ()))
            if bad:
                return f"frame {f} (requests {script.get(f, [])}): {bad}", f, curs
            curs[f] = list(self.model.cur)
            f += 1
            if f > last and self.model.idle():
                break
            if f > 600:
                return "the model never went idle", f, curs
        for _ in range(extra):
            bad = self.frame()
            if bad:
                return f"frame {f} (after the end): {bad}", f, curs
            f += 1
        return None, f, curs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prg", default=str(REPO / "build/sfx/sfx.prg"))
    ap.add_argument("--frames", type=int, default=3000, help="frames of the random case")
    a = ap.parse_args()
    fails = []

    def rep(name, ok, text):
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {text}", flush=True)
        if not ok:
            fails.append(name)

    sp = Spike(a.prg)
    try:
        t, n = sp.tab, sp.count
        by_voice = {v: [e for e in range(n) if t["voice"][e] == v] for v in range(3)}
        other = {}  # for each voice, a long effect on another voice
        longest = sorted(range(n), key=sp.length, reverse=True)
        for v in range(3):
            other[v] = next(e for e in longest if t["voice"][e] != v)
        print(f"{'DEBUG' if sp.debug else 'release'} build, {n} effects, {len(t['frames'])} steps; "
              f"voices {t['voice']}, priorities {t['prio']}, lengths {[sp.length(e) for e in range(n)]}")

        sp.begin()
        reg = sp.mon.mem_get(SID, SID + 24)
        rep("init", reg[0x18] == 0x0F and reg[0x15:0x18] == bytes(3) and all(reg[7 * v + PWLO] == 0 for v in range(3)),
            f"$D418 = ${reg[0x18]:02x}, $D415-$D417 = {reg[0x15:0x18].hex(' ')}, pulse width low registers 0")

        # alone
        bad, frames = [], 0
        for e in range(n):
            v, length = t["voice"][e], sp.length(e)
            err, f, curs = sp.play({0: [e]})
            frames += f
            if err:
                bad.append(f"effect {e}: {err}")
                break
            if not (all(curs[k][v] == e + 1 for k in range(length)) and curs[length][v] == 0):
                bad.append(f"effect {e}: voice not idle exactly on tick {length}")
            if sp.model.reg[7 * v + CTRL] & 1:
                bad.append(f"effect {e}: gate left set")
        rep("alone", not bad, f"{n} effects, each to its end + 2 frames ({frames} frames); each idle and gate clear on "
            f"tick N = its frames, not before" if not bad else "; ".join(bad))

        # pairs
        bad, frames, kinds = [], 0, Counter()
        for v in range(3):
            for first, second in itertools.product(by_voice[v], repeat=2):
                pa, pb = t["prio"][first], t["prio"][second]
                kinds["higher replaces" if pb > pa else "equal replaces" if pb == pa else "lower dropped"] += 1
                err, f, curs = sp.play({0: [first, other[v]], 3: [second]})
                frames += f
                if err:
                    bad.append(f"{first} then {second}: {err}")
                    break
                want = second + 1 if pb >= pa else first + 1
                if curs[3][v] != want:
                    bad.append(f"{first} then {second}: playing {curs[3][v] - 1} after the request")
                if pb < pa and not (curs[sp.length(first) - 1][v] == first + 1 and curs[sp.length(first)][v] == 0):
                    bad.append(f"{first} then {second}: the first didn't end on its own tick")
            if bad:
                break
        rep("pairs", not bad, f"{sum(kinds.values())} ordered pairs on one voice, the second 3 ticks after the first "
            f"({dict(kinds)}), an effect on another voice running through each ({frames} frames)" if not bad else "; ".join(bad))

        # same-frame
        bad, frames, cases = [], 0, 0
        for v in range(3):
            sets = list(itertools.permutations(by_voice[v], 2))
            # triples: the voice's three shortest effects that cover the most priorities, every order
            trio = sorted(sorted(by_voice[v], key=sp.length)[:4], key=lambda e: t["prio"][e])
            trio = [trio[0], trio[1], trio[-1]]
            sets += list(itertools.permutations(trio)) + [(e, e) for e in by_voice[v]]
            for reqs in sets:
                cases += 1
                top = max(t["prio"][e] for e in reqs)
                want = [e for e in reqs if t["prio"][e] == top][-1]  # highest priority, the later on a tie
                err, f, curs = sp.play({0: list(reqs)}, extra=1)
                frames += f
                if err:
                    bad.append(f"{reqs}: {err}")
                    break
                if curs[0][v] != want + 1:
                    bad.append(f"{reqs}: started {curs[0][v] - 1}, expected {want}")
            if bad:
                break
        rep("same-frame", not bad, f"{cases} sets of two or three requests for one voice in one frame, every order: the "
            f"highest priority starts, the later call on a tie ({frames} frames)" if not bad else "; ".join(bad))

        # end-frame
        bad, frames, cases = [], 0, 0
        for v in range(3):
            firsts = sorted(by_voice[v], key=sp.length)[:3]  # the voice's three shortest: the cases are about the end
            for first, second in itertools.product(firsts, by_voice[v]):
                if t["prio"][second] > t["prio"][first]:
                    continue
                length = sp.length(first)
                for at in (length - 1, length, length + 1):
                    cases += 1
                    err, f, curs = sp.play({0: [first], at: [second]}, extra=1)
                    frames += f
                    if err:
                        bad.append(f"{first}, then {second} at tick {at}: {err}")
                        break
                    # At tick N the request is looked at before the effect's own end: a lower one is dropped.
                    lower = t["prio"][second] < t["prio"][first]
                    want = 0 if (lower and at == length) else first + 1 if (lower and at < length) else second + 1
                    if curs[at][v] != want:
                        bad.append(f"{first}, then {second} at tick {at} (N = {length}): voice has {curs[at][v] - 1}")
                if bad:
                    break
            if bad:
                break
        rep("end-frame", not bad, f"{cases} cases: an equal or lower request on the tick before an effect's end, on its "
            f"end tick N and on N + 1 (a lower one on tick N is dropped: the request is looked at first) ({frames} frames)"
            if not bad else "; ".join(bad))

        # triple
        bad, frames = [], 0
        triples = [tuple(by_voice[v][-1] for v in range(3)), tuple(by_voice[v][0] for v in range(3)),
                   tuple(by_voice[v][1] for v in range(3)) + (by_voice[0][0],)]
        before = sp.model.stats["tick: three starts"]
        for reqs in triples:
            err, f, curs = sp.play({0: list(reqs)})
            frames += f
            if err:
                bad.append(f"{reqs}: {err}")
                break
        got3 = sp.model.stats["tick: three starts"] - before
        rep("triple", not bad and got3 == len(triples), f"{len(triples)} frames with a start on every voice {triples}: "
            f"21 writes each, in order ({frames} frames)" if not bad else "; ".join(bad))

        # random
        rng = random.Random(SEED)
        before = Counter(sp.model.stats)
        bad, f, asked = None, 0, 0
        while f < a.frames and not bad:
            kind = rng.choice(["busy", "busy", "sparse", "sparse", "sparse", "silent"])
            for _ in range(rng.randint(20, 120)):
                if f >= a.frames:
                    break
                if kind == "busy":
                    k = rng.randint(0, 4)
                elif kind == "sparse":
                    k = rng.choice([0] * 12 + [1, 1, 2, 3])
                else:
                    k = 0
                reqs = [rng.randrange(n) for _ in range(k)]
                asked += k
                err = sp.frame(reqs)
                if err:
                    bad = f"frame {f} (requests {reqs}): {err}"
                    break
                f += 1
        stats = sp.model.stats - before
        rep("random", not bad, f"{f} frames, seed {SEED}, {asked} requests, every frame equal to the model"
            if not bad else bad)
        for k in sorted(stats):
            print(f"       {k}: {stats[k]}")

        # untouched
        never = [r for r in (PWLO, 7 + PWLO, 14 + PWLO, 0x15, 0x16, 0x17, 0x18) if sp.written[r]]
        rep("untouched", not never, f"no write to the pulse width low registers or $D415-$D418 in {sp.frames} frames "
            f"({sum(sp.written.values())} register writes checked)" if not never
            else "written: " + ", ".join(f"${SID + r:04x}" for r in never))
    finally:
        sp.close()

    print("\nFAILED: " + ", ".join(fails) if fails else f"\nALL PASS ({'DEBUG' if sp.debug else 'release'} build, "
          f"{sp.frames} frames, {sum(sp.written.values())} register writes compared)")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL (jam/hang): {e}")
        sys.exit(2)
