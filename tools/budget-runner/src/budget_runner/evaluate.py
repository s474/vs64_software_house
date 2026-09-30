"""Turn raster-time events into check results. Pure functions: no VICE in here.

An Event is one execution of a watched address, with its raster position and an absolute time
`t` (cycles since the raster line 0 of the first frame in the trace, unwrapped across frames).
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field

from .spec import Check

CYCLES_PER_LINE = 63  # measured: tests/timing/rasterline
LINES = 312
FRAME = LINES * CYCLES_PER_LINE
IRQ_SEQUENCE = 7  # cycles the CPU spends entering an IRQ before the first vector instruction
RTI_TAIL = 6  # cycles of the RTI itself, so an IRQ spans dispatch - 7 .. exit_rti + 6


@dataclass(frozen=True)
class Event:
    pc: int
    t: int
    line: int
    cycle: int


@dataclass
class Part:
    """One comparison: `value` must satisfy `op` against `limit`."""

    label: str
    value: float
    op: str  # "<=", "==", ">="
    limit: float

    def describe(self) -> str:
        if self.op == "<=":
            return f"{self.label} {fmt(self.value)} / budget {fmt(self.limit)}"
        return f"{self.label} {fmt(self.value)} (required {self.op} {fmt(self.limit)})"

    @property
    def ok(self) -> bool:
        return {"<=": self.value <= self.limit, "==": self.value == self.limit,
                ">=": self.value >= self.limit}[self.op]


@dataclass
class Result:
    check: Check
    parts: list[Part] = field(default_factory=list)
    info: str = ""
    error: str | None = None  # the measurement itself could not be made
    pending: str | None = None  # not run: the check belongs to a later build stage

    @property
    def passed(self) -> bool:
        return self.error is None and self.pending is None and bool(self.parts) and all(p.ok for p in self.parts)


def irq_spans(events: list[Event], dispatch: int, rti: int) -> list[tuple[int, int]]:
    """(start, end) of every IRQ seen whole: dispatch hit - 7 to rti hit + 6. Nested IRQs pair by stack."""
    spans, stack = [], []
    for e in events:
        if e.pc == dispatch:
            stack.append(e.t - IRQ_SEQUENCE)
        elif e.pc == rti and stack:  # an rti with no dispatch is an IRQ that began before the trace
            spans.append((stack.pop(), e.t + RTI_TAIL))
    return sorted(spans)


def union_length(spans: list[tuple[int, int]]) -> int:
    total, end = 0, None
    for s, e in sorted(spans):
        if end is None or s > end:
            total += e - s
            end = e
        elif e > end:
            total += e - end
            end = e
    return total


def profile_costs(events: list[Event], start: int, end: int,
                  dispatch: int | None = None, rti: int | None = None) -> list[int]:
    """Cycles from each `start` execution to the next `end`; minus nested IRQs if dispatch/rti given.

    An IRQ counts as nested if its dispatch is hit after `start` and its rti before `end`; the
    IRQ the routine may itself be running inside is not subtracted.
    """
    spans = irq_spans(events, dispatch, rti) if dispatch is not None and rti is not None else []
    span_starts = [s for s, _ in spans]  # spans are sorted by start
    costs, started = [], None
    for e in events:
        if e.pc == start:
            started = e.t
        elif e.pc == end and started is not None:
            cost = e.t - started
            if spans:
                # Only spans starting in (started - 7, e.t) can be nested: a span starting at or
                # after e.t - 7 has its rti hit after e.t. Bisect instead of scanning every span.
                lo = bisect_right(span_starts, started - IRQ_SEQUENCE)
                hi = bisect_right(span_starts, e.t - IRQ_SEQUENCE)
                nested = [(s, f) for s, f in spans[lo:hi] if f - RTI_TAIL < e.t]
                cost -= union_length(nested)
            costs.append(cost)
            started = None
    return costs


class SampleCounter:
    """Counts complete start -> end pairs incrementally: O(new events) per call, not O(all events).

    Gives the same count as len(profile_costs(events, start, end)).
    """

    def __init__(self, start: int, end: int):
        self.start, self.end = start, end
        self.count = 0
        self._seen = 0
        self._started = False

    def update(self, events: list[Event]) -> int:
        for i in range(self._seen, len(events)):
            pc = events[i].pc
            if pc == self.start:
                self._started = True
            elif pc == self.end and self._started:
                self.count += 1
                self._started = False
        self._seen = len(events)
        return self.count


def irq_time_by_frame(events: list[Event], dispatch: int, rti: int, frames: int) -> list[int]:
    """IRQ cycles in each of `frames` whole frames (frames 1..frames of the trace; frame 0 is partial).

    A span belongs to the frame its start falls in. Nested IRQs are counted once.
    """
    by_frame: dict[int, list[tuple[int, int]]] = {}
    for s, e in irq_spans(events, dispatch, rti):
        by_frame.setdefault(s // FRAME, []).append((s, e))
    return [union_length(by_frame.get(f, [])) for f in range(1, frames + 1)]


def fmt(n: float) -> str:
    return f"{n:,}" if isinstance(n, int) else f"{n:,.2f}".rstrip("0").rstrip(".")


def eval_profile(check: Check, costs: list[int]) -> Result:
    if not costs:
        return Result(check, error="no complete start -> end pass was seen")
    avg = sum(costs) / len(costs)  # compared unrounded: 5,000.04 is over an average budget of 5,000
    parts = [Part("max", max(costs), "<=", check.params["max_cycles"])]
    if check.params.get("max_avg_cycles") is not None:
        parts.append(Part("avg", avg, "<=", check.params["max_avg_cycles"]))
    return Result(check, parts, info=f"min {min(costs)}, avg {avg:.1f}, {len(costs)} passes")


def eval_start_cycle(check: Check, hits: list[Event]) -> Result:
    p = check.params
    if not hits:
        return Result(check, error=f"'{p['label']}' was never executed")
    off = sorted({e.line for e in hits if e.line != p["line"]})
    cycles = [e.cycle for e in hits]
    parts = [Part("spread", max(cycles) - min(cycles), "<=", p["max_spread"])]
    if off:  # shown only when it fails: a pass is implied by the info line naming the line
        parts.insert(0, Part(f"hits off line {p['line']}", len(off), "==", 0))
    if p["max_cycle"] is not None:
        parts.append(Part("max cycle", max(cycles), "<=", p["max_cycle"]))
    info = f"line {p['line']}, cycles {min(cycles)}-{max(cycles)}, {len(hits)} frames"
    if off:
        info += f"; also hit on line(s) {', '.join(map(str, off))}"
    return Result(check, parts, info=info)


def eval_irq_time(check: Check, totals: list[int]) -> Result:
    if not totals or not any(totals):
        return Result(check, error="no complete IRQ was seen (irq_dispatch / irq_exit_rti never hit)")
    return Result(check, [Part("max", max(totals), "<=", check.params["max_cycles"])],
                  info=f"min {min(totals)}, {len(totals)} frames")


def eval_memory(check: Check, raw: int) -> Result:
    p = check.params
    value = raw * p["scale"]
    op = {"equals": "==", "max": "<=", "min": ">="}[p["comparison"]]
    label = f"{p['address']}" + (f" x {p['scale']}" if p["scale"] != 1 else "")
    return Result(check, [Part(label, value, op, p[p["comparison"]])],
                  info=f"after {p['after_frames']} frames, raw {raw}")


def format_result(spike: str, r: Result, name_width: int) -> str:
    """One line: spike, name, figures, PASS/FAIL, basis. Failures add one indented line per problem.

    A pending check (a later build stage) prints PENDING and why, with no figures.
    """
    if r.pending:
        return f"{spike}  {r.check.name.ljust(name_width)}  {r.pending}  PENDING  ({r.check.basis})"
    figures = "; ".join(p.describe() for p in r.parts) or "not measured"
    status = "PASS" if r.passed else "FAIL"
    lines = [f"{spike}  {r.check.name.ljust(name_width)}  {figures}  {status}  ({r.check.basis})"]
    if not r.passed:
        if r.error:
            lines.append(f"    error: {r.error}")
        for p in r.parts:
            if not p.ok:
                if p.op == "<=":
                    lines.append(f"    {p.label}: {fmt(p.value)} is over the budget of {fmt(p.limit)} "
                                 f"by {fmt(p.value - p.limit)}")
                else:
                    lines.append(f"    {p.label}: got {fmt(p.value)}, required {p.op} {fmt(p.limit)}")
        if r.info:
            lines.append(f"    measured: {r.info}")
        if r.check.source:
            lines.append(f"    budget source: {r.check.source}")
    return "\n".join(lines)
