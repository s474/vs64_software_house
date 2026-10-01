"""How hard does Swarm's worst-case play work the multiplexer's slow path? (Technical Director, M4 stage 0)

Backs the "overflow frames" and "pinned evictions" figures in docs/games/swarm/memory-map.md.
No emulator, stdlib only. Run from the repo root:

    uv run python tests/games/swarm/mux_load.py | tee tests/games/swarm/mux_load_results.txt

It reuses the designer's worst-case play simulation (check_design.py: the formation never dies, the
player sweeps the screen firing at the maximum rate) and swaps its selection function for a copy
that counts, per frame:

  - whether the frame overflows (a sprite fails the fit rule, so mux_update takes its slow path);
  - evictions made by pinned sprites, fair evictions (an older unpinned sprite replacing a younger
    one) and plain drops;
  - the slot at which the first sprite fails (the fast walk stops there);
  - sort work: pairs of sprites that changed places in Y order since the previous frame, which is
    the number of shifts the engine's insertion sort makes (276 is the full reversal), and how
    often a busy sort (20 shifts or more) lands on a frame that also overflows or has a pinned
    eviction: the two halves of the README's one exception to the free-CPU promise;
  - how many sprites are in the player's zone (Y 183-221).

Everything printed is a MODEL figure (a transcription of engine/README.md's selection pseudocode),
so it is an estimate, not a measurement. The engine's own counts replace it when the game exists:
tests/games/swarm/budget.json and QA's positions.py.
"""
import check_design as cd

ZONE_TOP = 183                      # the player's zone: Y 183..221 (design.md, "Close to the limits")


class Counter:
    def __init__(self):
        self.frames = 0
        self.overflow = 0           # frames that take the slow path
        self.pin_ev_frames = 0      # frames with at least one pinned eviction
        self.pin_ev = 0
        self.fair_ev = 0
        self.drops = 0
        self.pin_drop = 0           # a pinned sprite left out: must stay 0
        self.max_pin_ev = 0
        self.max_events = 0         # most evictions + drops in one frame
        self.first_fail = []        # slot index of the first failure, per overflow frame
        self.max_shifts = 0
        self.shifts = 0
        self.busy_sort_pin = 0      # frames with >= 20 sort shifts AND a pinned eviction
        self.busy_sort_over = 0     # frames with >= 20 sort shifts AND an overflow
        self.max_zone = 0
        self.zone9 = 0              # frames with 9 or more sprites in the player's zone
        self.prev_order = None

    def select(self, order, y, age, pinned):
        """check_design.select with counters. Same decisions, same age updates."""
        kept, evictions = [], 0
        pin_ev = fair_ev = drops = 0
        first_fail = None

        def youngest(lst):
            cand = [k for k in lst[-8:] if k not in pinned]
            if not cand:
                return None
            return min(cand, key=lambda k: (age[k], -lst.index(k)))

        def fits(lst, v):
            return cd.all_fit([y[k] for k in lst] + [y[v]])

        for v in order:
            if not cd.MUX_Y_MIN <= y[v] <= cd.MUX_Y_MAX:
                continue
            if fits(kept, v):
                kept.append(v)
                continue
            if first_fail is None:
                first_fail = len(kept)
            if v in pinned:
                while evictions < 8 and not fits(kept, v):
                    w = youngest(kept)
                    if w is None:
                        break
                    kept.remove(w)
                    evictions += 1
                    pin_ev += 1
                if fits(kept, v):
                    kept.append(v)
                else:
                    self.pin_drop += 1
            else:
                w = youngest(kept)
                done = False
                if w is not None and age[v] > age[w]:
                    trial = [k for k in kept if k != w]
                    if fits(trial, v):
                        kept = trial + [v]
                        fair_ev += 1
                        done = True
                if not done:
                    drops += 1
        shown = set(kept)
        for v in range(24):
            if cd.MUX_Y_MIN <= y[v] <= cd.MUX_Y_MAX and v not in shown:
                age[v] += 1
            else:
                age[v] = 0

        # ---- statistics ----
        self.frames += 1
        if first_fail is not None:
            self.overflow += 1
            self.first_fail.append(first_fail)
        self.pin_ev += pin_ev
        self.fair_ev += fair_ev
        self.drops += drops
        if pin_ev:
            self.pin_ev_frames += 1
        self.max_pin_ev = max(self.max_pin_ev, pin_ev)
        self.max_events = max(self.max_events, pin_ev + fair_ev + drops)
        if self.prev_order is not None:
            pos = {v: i for i, v in enumerate(self.prev_order)}
            seq = [pos[v] for v in order]
            shifts = sum(1 for i in range(24) for j in range(i + 1, 24) if seq[i] > seq[j])
            self.shifts += shifts
            self.max_shifts = max(self.max_shifts, shifts)
            if shifts >= 20 and pin_ev:
                self.busy_sort_pin += 1
            if shifts >= 20 and first_fail is not None:
                self.busy_sort_over += 1
        self.prev_order = list(order)
        zone = sum(1 for v in range(24) if ZONE_TOP <= y[v] <= cd.MUX_Y_MAX)
        self.max_zone = max(self.max_zone, zone)
        if zone >= 9:
            self.zone9 += 1
        return shown


def run(frames=6000):
    print(f"== Multiplexer slow-path load in worst-case play, {frames} frames each (MODEL: estimates) ==")
    print("Design pinning: player + 3 enemy shots. Formation never dies, player fires at the maximum rate.")
    print("wave loop | overflow frames | frames with a pinned eviction | pinned ev., fair ev., drops "
          "(total) | most pinned ev. in a frame | most ev. + drops in a frame | first failing slot "
          "min / median | sort shifts per frame avg / max | most in the player's zone, frames with 9+")
    worst = dict(overflow=0.0, pin=0, events=0, shifts=0)
    for loop in range(4):
        for pattern in range(3):
            c = Counter()
            cd.select = c.select
            cd.simulate(pattern, loop, frames, True)
            ff = sorted(c.first_fail)
            ffs = f"{ff[0]} / {ff[len(ff) // 2]}" if ff else "- / -"
            print(f"  {pattern + 1}    {loop}   | {100 * c.overflow / c.frames:5.2f}% ({c.overflow}) | "
                  f"{100 * c.pin_ev_frames / c.frames:5.2f}% ({c.pin_ev_frames}) | "
                  f"{c.pin_ev}, {c.fair_ev}, {c.drops} | {c.max_pin_ev} | {c.max_events} | {ffs} | "
                  f"{c.shifts / c.frames:.1f} / {c.max_shifts} | {c.busy_sort_over}, {c.busy_sort_pin} | "
                  f"{c.max_zone}, {c.zone9}")
            assert c.pin_drop == 0, "a pinned sprite was dropped"
            worst["overflow"] = max(worst["overflow"], 100 * c.overflow / c.frames)
            worst["pin"] = max(worst["pin"], c.max_pin_ev)
            worst["events"] = max(worst["events"], c.max_events)
            worst["shifts"] = max(worst["shifts"], c.max_shifts)
    print(f"\nworst over all waves: {worst['overflow']:.2f}% overflow frames, {worst['pin']} pinned "
          f"eviction(s) in a frame, {worst['events']} evictions + drops in a frame, "
          f"{worst['shifts']} sort shifts in a frame (a full reversal is 276)")
    print("for comparison, the engine's multiplexer spike (measured, engine/README.md): 65% overflow "
          "frames, about 8 evictions + drops per overflow frame, up to 4 pinned evictions in a frame")


if __name__ == "__main__":
    run()
