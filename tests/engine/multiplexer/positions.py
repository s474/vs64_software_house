"""QA position/attribute check of the multiplexer spike (M3 sign-off, follow-up to soak.py).

soak.py proves sprites are SHOWN. This proves each shown sprite is written to the hardware with the
RIGHT values: for every virtual sprite the multiplexer kept, the hardware sprite it was assigned
must hold that virtual sprite's X low byte, X bit 8, Y, pointer, colour and multicolour bit, and be
enabled in $D015.

Method (instruction-exact, one monitor stop per event; nothing is sampled sparsely):
  * mux_build_end (end of every mux_update that built a frame): snapshot the 24-entry virtual
    arrays (mux_x_lo/x_hi/y/ptr/col/flags), mux_order, mux_kept, mux_slow_from, mux_mc_mode and the
    build's end index, keyed by the BACK buffer base (0 or 32). The arrays are stable here (the
    main loop has finished reading them), so this is exactly what the frame was built from.
    The slot -> virtual-sprite map is derived independently where possible: a fast frame must keep
    every in-range sprite in mux_order order (mux_order must be sorted by Y); a slow (flicker) frame
    uses mux_kept, which must be distinct, in range, in non-decreasing Y order, and a sub-sequence
    of the in-range sorted order.
  * (deadline used for "before the sprite's Y line": all six writes complete on a line < Y, or on line Y
    before cycle 55, where the VIC-II does its Y compare and the p-access is cycle 58. Slots that finish
    on line Y itself are counted separately: the engine's own `raster < Y` rule only covers the Y write.)
  * mux_irq_top after its 8 slot writes (the `txa` after the unrolled block): the registers of
    slots base..base+7 are read ($D000-$D02E in one read, plus the 8 pointers at MUX_SCREEN+$3F8)
    and compared with the snapshot of the front buffer. $D015 must equal the first min(n,8) bits.
  * mux_zone_N+offset of the `inx` that ends each zone slot block (uniform and mixed-multicolour
    block sets): X = the slot just written, the registers of hardware sprite (X & 7) are compared
    with the snapshot, $D015 bit (X & 7) must be set, and the raster line (LIN) must be < the
    slot's Y (the engine's own late criterion, but for ALL six writes, not only the Y write).
  * mux_zone_N entry: the raster line must be >= y[k-8] + MUX_FREE_AFTER (the hardware sprite has
    finished displaying its previous slot before it is overwritten).
  * mux_irq_top entry: $D015 must equal the previous frame's mux_b_d015 & ~mux_b_park (ghost
    parking), and mux_b_park must equal the bits of the last min(n,8) slots whose Y <= MUX_WRAP_Y.
    Every slot of the front buffer must have been checked exactly once in the previous frame.

Input variety (the spike alone only ever uses hires, fixed colours and fixed pointers): after the
STATIC frames the script, while stopped at mux_build_end (so nothing can race), rewrites the
virtual mux_col / mux_ptr (a random permutation of the 24 spike pointers) every frame and cycles the
multicolour pattern of mux_flags bit 0 (bit 7 pinned flags are preserved): all hires, all
multicolour, then random mixed (exercising the mixed zone blocks and the cumulative $D01C).
Phases: STATIC (spike as shipped), HIRES (random col/ptr), MC (all multicolour), MIXED (random).

What it does NOT prove: it reads registers at the end of each slot's writes, not at the moment the
VIC-II fetches the sprite, so it cannot see a write that lands after the DMA start on line Y-ish
(that is what mux_late_count and the `LIN < Y` criterion cover); it does not look at pixels (the
screenshots do); sprites dropped by flicker are not checked for being the "right" ones to drop
(soak.py covers fairness).

Run from the repo root (build first: make GAME=multiplexer SRC_DIR=tests/engine/multiplexer):

    uv run --package budget-runner python tests/engine/multiplexer/positions.py \
        [--static 200] [--hires 200] [--mc 100] [--mixed 200] [--seed 1] [--inject] [--prg build/multiplexer/multiplexer.prg]

Exit code 0 = all checks pass, 1 = a mismatch, 2 = jam/hang. About 700 frames takes several minutes
(35 monitor stops per frame).
"""

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

from budget_runner.session import STOP_TIMEOUT, MeasureError, Vice
from vice_monitor import CPU_OP_EXEC  # on sys.path once budget_runner.session is imported

REPO = Path(__file__).resolve().parents[3]
N = 24
Y_MIN, Y_MAX, WRAP_Y, FREE_AFTER = 0x1E, 0xF9, 55, 22
DMA_CYCLE = 55  # VIC-II checks Y == raster in cycle 55 of each line; p-access of sprite 0 is cycle 58
PTRS = 0x0400 + 0x3F8
PTR0 = 0xA0
ATTRS = ["x_lo", "x_hi", "y", "ptr", "col", "mc", "enable"]
ZONE_UNI, ZONE_MIX = (0, 45, 81), (0, 51, 87)  # (unused, inx offset, block size)


class Checker:
    def __init__(self, v, sym):
        self.v, self.sym = v, sym
        self.snap = {0: None, 32: None}
        self.inject = False
        self.checked = Counter()
        self.bad = Counter()
        self.examples = {a: [] for a in ATTRS}
        self.other = []                       # structural / timing failures (text)
        self.counts = Counter()               # misc statistics
        self.frame = 0
        self.phase = "static"
        self.slots_done = set()               # slot indices checked in the current front buffer
        self.front_for_done = None

    # -- helpers ----------------------------------------------------------------------------
    def b(self, name, n=1):
        a = self.sym[name]
        return self.v.mon.mem_get(a, a + n - 1)

    def fail(self, text):
        self.other.append(f"frame {self.frame} [{self.phase}]: {text}")

    def cmp(self, attr, got, exp, ctx):
        self.checked[attr] += 1
        if got != exp:
            self.bad[attr] += 1
            if len(self.examples[attr]) < 8:
                self.examples[attr].append(f"frame {self.frame} [{self.phase}] {ctx}: got ${got:02x} expected ${exp:02x}")

    # -- events -----------------------------------------------------------------------------
    def on_build_end(self, rng):
        s, mon = self.sym, self.v.mon
        arr = {n: list(self.b("mux_" + n, N)) for n in ("x_lo", "x_hi", "ptr", "col", "flags")}
        arr["y"] = list(self.b("mux_y", N))
        order = list(self.b("mux_order", N))
        back = self.b("mux_back")[0]
        slow_from = self.b("mux_slow_from")[0]
        mc_mode = self.b("mux_mc_mode")[0]
        end = mon.mem_get(s["mux_b_end"] + back, s["mux_b_end"] + back)[0]
        kept_mem = list(mon.mem_get(s["mux_kept"] + back, s["mux_kept"] + back + N - 1))
        count = end - back
        y = arr["y"]
        ctx = f"build for buffer {back}"
        # sorted order check
        if sorted(order) != list(range(N)):
            self.fail(f"{ctx}: mux_order is not a permutation: {order}")
        if any(y[order[i]] > y[order[i + 1]] for i in range(N - 1)):
            self.fail(f"{ctx}: mux_order not sorted by Y: {[y[o] for o in order]}")
        in_range = [o for o in order if Y_MIN <= y[o] <= Y_MAX]
        if slow_from == 0xFF:
            kept = in_range[:count]
            if count != len(in_range):
                self.fail(f"{ctx}: fast frame kept {count} of {len(in_range)} in-range sprites")
            if mc_mode == 2 and kept_mem[:count] != kept:
                self.fail(f"{ctx}: mux_kept {kept_mem[:count]} != sorted in-range {kept} (mixed, fast)")
        else:
            kept = kept_mem[:count]
            pos = {o: i for i, o in enumerate(in_range)}
            if len(set(kept)) != count or any(o not in pos for o in kept):
                self.fail(f"{ctx}: slow frame kept list invalid {kept}")
            elif any(pos[kept[i]] >= pos[kept[i + 1]] for i in range(count - 1)):
                self.fail(f"{ctx}: slow frame kept list not in sorted order {kept}")
            self.counts["slow_frames"] += 1
        self.counts["builds"] += 1
        self.counts["kept_sprite_frames"] += count
        self.counts["x_gt_255_sprite_frames"] += sum(arr["x_hi"][o] & 1 for o in kept)
        self.snap[back] = dict(arr=arr, kept=kept, count=count, order=order)
        # perturb the NEXT build's inputs (safe: this build has finished reading them)
        if self.phase != "static":
            cols = [rng.randrange(16) for _ in range(N)]
            ptrs = list(range(PTR0, PTR0 + N))
            rng.shuffle(ptrs)
            fl = arr["flags"]
            if self.phase == "mc":
                fl = [f | 1 for f in fl]
            elif self.phase == "mixed":
                fl = [(f & 0xFE) | rng.randrange(2) for f in fl]
            else:
                fl = [f & 0xFE for f in fl]
            mon.mem_set(s["mux_col"], bytes(cols))
            mon.mem_set(s["mux_ptr"], bytes(ptrs))
            mon.mem_set(s["mux_flags"], bytes(fl))

    def finish_frame(self):
        """At mux_irq_top entry: close the previous frame's bookkeeping."""
        f = self.front_for_done
        if f is None:
            return
        sn = self.snap[f["base"]]
        if sn is not None and f["end"] > f["base"]:
            want = set(range(f["base"], f["end"]))
            if self.slots_done != want:
                self.fail(f"slots checked {sorted(self.slots_done)} != written {sorted(want)}")

    def on_top_entry(self):
        s = self.sym
        front = self.b("zp_mux_front")[0]
        ready = self.b("zp_mux_ready")[0]
        self.finish_frame()
        self.frame += 1
        # $D015 now = the previous frame's enable & ~park
        d015 = self.v.mon.mem_get(0xD015, 0xD015)[0]
        en = self.v.mon.mem_get(s["mux_b_d015"] + front, s["mux_b_d015"] + front)[0]
        park = self.v.mon.mem_get(s["mux_b_park"] + front, s["mux_b_park"] + front)[0]
        sn = self.snap[front]
        if self.frame > 2 and sn is not None:
            self.checked["park_d015"] += 1
            if d015 != (en & ~park & 0xFF):
                self.bad["park_d015"] += 1
                self.fail(f"top entry: $D015=${d015:02x}, expected enable ${en:02x} & ~park ${park:02x}")
            # independent park mask: last min(n,8) slots with Y <= WRAP_Y
            n = sn["count"]
            ys = [sn["arr"]["y"][v] for v in sn["kept"]]
            exp = 0
            for i in range(n - min(n, 8), n):
                if ys[i] <= WRAP_Y:
                    exp |= 1 << (i & 7)
            self.checked["park_mask"] += 1
            if park != exp:
                self.bad["park_mask"] += 1
                self.fail(f"mux_b_park=${park:02x}, expected ${exp:02x} from the kept sprites' Y")
        self.slots_done = set()
        self.front_for_done = None

    def check_slot(self, k, hw, regs, ptr, front, where):
        sn = self.snap[front]
        base = front
        i = k - base
        v = sn["kept"][i]
        a = sn["arr"]
        ctx = f"slot {k} (kept #{i}) virtual {v} hw {hw} ({where})"
        j = hw
        self.cmp("x_lo", regs[2 * j], a["x_lo"][v], ctx)
        self.cmp("x_hi", (regs[0x10] >> j) & 1, a["x_hi"][v] & 1, ctx)
        self.cmp("y", regs[2 * j + 1], a["y"][v], ctx)
        self.cmp("ptr", ptr[j], a["ptr"][v], ctx)
        self.cmp("col", regs[0x27 + j] & 0x0F, a["col"][v] & 0x0F, ctx)
        self.cmp("mc", (regs[0x1C] >> j) & 1, a["flags"][v] & 1, ctx)
        self.cmp("enable", (regs[0x15] >> j) & 1, 1, ctx)
        self.counts["slot_checks"] += 1
        self.counts["hw_x_hi_set"] += (regs[0x10] >> j) & 1
        self.counts["hw_mc_set"] += (regs[0x1C] >> j) & 1
        return v, a["y"][v]

    def read_hw(self):
        regs = self.v.mon.mem_get(0xD000, 0xD02E)
        ptr = self.v.mon.mem_get(PTRS, PTRS + 7)
        return regs, ptr

    def on_top_txa(self):
        front = self.b("zp_mux_front")[0]
        end = self.b("zp_mux_end")[0]
        sn = self.snap[front]
        self.front_for_done = dict(base=front, end=end)
        if sn is None:
            if end > front:
                self.fail(f"top: front buffer {front} has {end - front} slots but no snapshot")
            return
        if end - front != sn["count"]:
            self.fail(f"top: zp_mux_end-front {end - front} != built count {sn['count']}")
        regs, ptr = self.read_hw()
        n = min(end - front, 8)
        exp_en = (1 << n) - 1
        self.checked["d015_top"] += 1
        if regs[0x15] != exp_en:
            self.bad["d015_top"] += 1
            self.fail(f"top: $D015=${regs[0x15]:02x} expected ${exp_en:02x}")
        for k in range(front, front + n):
            self.check_slot(k, k & 7, regs, ptr, front, "top")
            self.slots_done.add(k)
            sn_y = sn["arr"]["y"][sn["kept"][k - front]]
            line = 16
            self.checked["before_y_line"] += 1
            if not line < sn_y:
                self.bad["before_y_line"] += 1
                self.fail(f"slot {k}: top writes done on line {line} >= Y {sn_y}")

    def on_zone_entry(self, lin, k):
        front = self.b("zp_mux_front")[0]
        sn = self.snap[front]
        if sn is None or not (front + 8 <= k < front + sn["count"]):
            self.fail(f"zone entry with slot {k}, front {front}")
            return
        a = sn["arr"]
        yprev = a["y"][sn["kept"][k - 8 - front]]
        self.checked["free_before_write"] += 1
        if lin < yprev + FREE_AFTER:
            self.bad["free_before_write"] += 1
            self.fail(f"slot {k}: write starts on line {lin}, previous slot on this hw sprite (Y {yprev}) "
                      f"only free on line {yprev + FREE_AFTER}")

    def on_zone_inx(self, lin, cyc, k):
        front = self.b("zp_mux_front")[0]
        sn = self.snap[front]
        if sn is None or not (front + 8 <= k < front + sn["count"]):
            self.fail(f"zone inx with slot {k}, front {front}")
            return
        if self.inject and k % 16 == 5:      # --inject: corrupt a register to prove the check can fail
            self.v.mon.mem_set(0xD000 + 2 * (k & 7), bytes([self.v.mon.mem_get(0xD000 + 2 * (k & 7), 0xD000 + 2 * (k & 7))[0] ^ 1]), True)
        regs, ptr = self.read_hw()
        v, y = self.check_slot(k, k & 7, regs, ptr, front, f"zone line {lin}")
        self.checked["before_y_line"] += 1
        if lin == y:
            self.counts["finished_on_line_y"] += 1          # past the engine's `raster < Y` margin
            self.counts["max_cyc_on_line_y"] = max(self.counts["max_cyc_on_line_y"], cyc)
        if lin > y or (lin == y and cyc >= DMA_CYCLE):
            self.bad["before_y_line"] += 1
            self.fail(f"slot {k} (virtual {v}): all six writes finished on line {lin} cycle {cyc}, "
                      f"after the sprite DMA check (line Y={y}, cycle {DMA_CYCLE})")
        if k in self.slots_done:
            self.fail(f"slot {k} written twice in one frame")
        self.slots_done.add(k)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--static", type=int, default=200)
    ap.add_argument("--hires", type=int, default=200)
    ap.add_argument("--mc", type=int, default=100)
    ap.add_argument("--mixed", type=int, default=200)
    ap.add_argument("--inject", action="store_true", help="self-test: corrupt X low of some slots; the run must FAIL")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--prg", default=str(REPO / "build/multiplexer/multiplexer.prg"))
    a = ap.parse_args()
    rng = random.Random(a.seed)
    phases = [("static", a.static), ("hires", a.hires), ("mc", a.mc), ("mixed", a.mixed)]
    total = sum(n for _, n in phases)

    v = Vice(Path(a.prg), 0)
    ok = True
    try:
        sym = v.symbols
        mon = v.mon
        ck = Checker(v, sym)
        ck.inject = a.inject
        # checkpoint addresses
        top_entry = sym["mux_irq_top"]
        top_txa = top_entry + 234
        entries, inxs = {}, {}
        for j in range(8):
            for name, (_, off, size), base in (("uni", ZONE_UNI, sym["mux_zone_0"]), ("mix", ZONE_MIX, sym["mux_zone_m0"])):
                entries[base + size * j] = j
                inxs[base + size * j + off] = j
        # sanity: opcodes where we put checkpoints
        if mon.mem_get(top_txa, top_txa)[0] != 0x8A:
            raise MeasureError("no txa at mux_irq_top+234: the top IRQ changed, update positions.py")
        for ad in inxs:
            if mon.mem_get(ad, ad)[0] != 0xE8:
                raise MeasureError(f"no inx at ${ad:04x}: zone block layout changed, update positions.py")
        for base, size in ((sym["mux_zone_0"], 81), (sym["mux_zone_m0"], 87)):
            for j in range(8):
                if mon.mem_get(base + size * j, base + size * j)[0] != 0xBD:  # lda abs,x
                    raise MeasureError("zone block stride changed")
        addrs = [top_entry, top_txa, sym["mux_build_end"], *entries, *inxs]
        cps = [mon.checkpoint_set(ad, ad, CPU_OP_EXEC) for ad in addrs]

        phase_iter = iter(phases)
        cur, left = next(phase_iter)
        ck.phase = cur
        stops = 0
        while ck.frame < total:
            mon.exit()
            if not mon.wait_stopped(STOP_TIMEOUT):
                mon.ping()
                raise MeasureError(f"no checkpoint within {STOP_TIMEOUT}s at frame {ck.frame}: jam? "
                                   f"jammed_pc={mon.state.jammed_pc}")
            stops += 1
            r = mon.registers()
            pc, lin, x = r["PC"], r["LIN"], r["X"]
            if pc == top_entry:
                ck.on_top_entry()
                left -= 1
                while left <= 0 and ck.frame < total:
                    cur, left = next(phase_iter)
                ck.phase = cur
            elif pc == top_txa:
                ck.on_top_txa()
            elif pc == sym["mux_build_end"]:
                ck.on_build_end(rng)
            elif pc in entries:
                ck.on_zone_entry(lin, x)
            elif pc in inxs:
                ck.on_zone_inx(lin, r['CYC'], x)
            else:
                ck.fail(f"stopped at unexpected PC ${pc:04x}")
            if ck.frame and ck.frame % 100 == 0 and ck.counts["_p"] != ck.frame:
                ck.counts["_p"] = ck.frame
                print(f"  ...{ck.frame} frames, {stops} stops", flush=True)
        ck.finish_frame()
        for c in cps:
            mon.checkpoint_delete(c.number)
        late = v.mon.mem_get(sym["mux_late_count"], sym["mux_late_count"])[0]
        ilate = v.mon.mem_get(sym["irq_late_count"], sym["irq_late_count"])[0]
    finally:
        v.close()

    print(f"\n{ck.frame} frames, {stops} monitor stops, phases {phases}, seed {a.seed}")
    print(f"builds {ck.counts['builds']}, slow (flicker) builds {ck.counts['slow_frames']}, "
          f"kept sprite-frames built {ck.counts['kept_sprite_frames']}, "
          f"with X > 255 (x_hi bit 0): {ck.counts['x_gt_255_sprite_frames']}")
    print(f"hardware slot checks {ck.counts['slot_checks']}: X bit 8 set in {ck.counts['hw_x_hi_set']}, "
          f"multicolour bit set in {ck.counts['hw_mc_set']}")
    print(f"zone slots whose six writes finished ON line Y (engine's raster < Y margin exceeded, still before "
          f"cycle {DMA_CYCLE}): {ck.counts['finished_on_line_y']}, latest cycle seen {ck.counts['max_cyc_on_line_y']}")
    print(f"mux_late_count {late}, irq_late_count {ilate}\n")
    print(f"{'attribute':<14}{'checked':>9}{'mismatch':>10}")
    fails = []
    for attr in ATTRS + ["before_y_line", "free_before_write", "d015_top", "park_d015", "park_mask"]:
        c, b = ck.checked[attr], ck.bad[attr]
        print(f"{attr:<14}{c:>9}{b:>10}  {'PASS' if c and not b else 'FAIL'}")
        if b or not c:
            fails.append(attr)
        for e in ck.examples.get(attr, []):
            print("    " + e)
    for o in ck.other[:20]:
        print("[FAIL] " + o)
    if ck.other:
        fails.append(f"{len(ck.other)} structural/timing failures")
    if late or ilate:
        fails.append("late counters")
    print("\nFAILED: " + ", ".join(fails) if fails else "\nALL PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MeasureError as e:
        print(f"FAIL (jam/hang/layout): {e}")
        sys.exit(2)
