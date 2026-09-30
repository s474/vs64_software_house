"""Parse and validate budget.json files."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

KINDS = ("profile", "profile_excl_irq", "start_cycle", "irq_time_per_frame", "memory")
BASES = ("measured", "estimate", "requirement")
COMPARISONS = ("equals", "max", "min")

# kind -> (required fields, optional fields with defaults)
FIELDS: dict[str, tuple[tuple[str, ...], dict[str, object]]] = {
    "profile": (("routine", "max_cycles"), {"samples": 50, "max_avg_cycles": None, "min_cycles": None}),
    "profile_excl_irq": (("routine", "max_cycles"), {"samples": 50, "max_avg_cycles": None, "min_cycles": None}),
    "start_cycle": (("label", "line", "max_spread"), {"frames": 100, "max_cycle": None}),
    "irq_time_per_frame": (("max_cycles", "frames"), {}),
    "memory": (("address", "size", "after_frames"), {"scale": 1}),
}
COMMON = {"name", "kind", "basis", "source", "notes", "from_stage"}


class BudgetError(Exception):
    """A budget file is malformed. The message names the file and check."""


@dataclass
class Check:
    name: str
    kind: str
    basis: str
    source: str
    params: dict = field(default_factory=dict)
    from_stage: int | None = None  # not run while the budget's stage is lower (reported as PENDING)


@dataclass
class Budget:
    path: Path
    spike: str
    src_dir: str
    warmup_frames: int
    checks: list[Check]
    stage: int | None = None  # the build stage the spike's code has reached (see from_stage)

    def pending(self, check: Check) -> bool:
        """True if the check belongs to a later stage than the spike has reached."""
        return check.from_stage is not None and self.stage is not None and check.from_stage > self.stage


def _int(where: str, key: str, value: object, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise BudgetError(f"{where}: '{key}' must be an integer >= {minimum}, got {value!r}")
    return value


def parse_check(path: Path, index: int, raw: object) -> Check:
    if not isinstance(raw, dict):
        raise BudgetError(f"{path}: check #{index + 1} must be an object")
    name = raw.get("name")
    where = f"{path}: check #{index + 1}" + (f" ({name!r})" if name else "")
    if not isinstance(name, str) or not name:
        raise BudgetError(f"{where}: missing 'name'")
    kind = raw.get("kind", "profile")
    if kind not in KINDS:
        raise BudgetError(f"{where}: unknown kind {kind!r} (expected one of {', '.join(KINDS)})")
    basis = raw.get("basis")
    if basis not in BASES:
        raise BudgetError(f"{where}: 'basis' must be one of {', '.join(BASES)}, got {basis!r}")
    required, optional = FIELDS[kind]
    for key in required:
        if key not in raw:
            raise BudgetError(f"{where}: kind '{kind}' needs '{key}'")
    unknown = set(raw) - COMMON - set(required) - set(optional)
    comparison = [c for c in COMPARISONS if c in raw]
    if kind == "memory":
        unknown -= set(COMPARISONS)
        if len(comparison) != 1:
            raise BudgetError(f"{where}: kind 'memory' needs exactly one of {', '.join(COMPARISONS)}")
    if unknown:
        raise BudgetError(f"{where}: unknown field(s) {', '.join(sorted(unknown))} for kind '{kind}'")
    params = {k: raw.get(k, optional.get(k)) for k in (*required, *optional)}
    if kind == "memory":
        params[comparison[0]] = raw[comparison[0]]
        params["comparison"] = comparison[0]
        if params["size"] not in (1, 2):
            raise BudgetError(f"{where}: 'size' must be 1 or 2")
        _int(where, "after_frames", params["after_frames"])
        if not isinstance(params["scale"], (int, float)) or isinstance(params["scale"], bool):
            raise BudgetError(f"{where}: 'scale' must be a number")
        if not isinstance(raw[comparison[0]], (int, float)):
            raise BudgetError(f"{where}: '{comparison[0]}' must be a number")
    if "routine" in params:
        r = params["routine"]
        if not (isinstance(r, list) and len(r) == 2 and all(isinstance(x, str) for x in r)):
            raise BudgetError(f"{where}: 'routine' must be [start_label, end_label]")
    for key in ("max_cycles", "max_spread", "line"):
        if key in params:
            _int(where, key, params[key])
    for key in ("samples", "frames"):
        if key in params:
            _int(where, key, params[key], 1)
    if params.get("max_cycle") is not None:
        _int(where, "max_cycle", params["max_cycle"])
    if params.get("max_avg_cycles") is not None:
        if _int(where, "max_avg_cycles", params["max_avg_cycles"]) > params["max_cycles"]:
            raise BudgetError(f"{where}: 'max_avg_cycles' is above 'max_cycles', so it could never fail")
    if params.get("min_cycles") is not None:
        if _int(where, "min_cycles", params["min_cycles"]) > params["max_cycles"]:
            raise BudgetError(f"{where}: 'min_cycles' is above 'max_cycles', so it could never pass")
    from_stage = _int(where, "from_stage", raw["from_stage"], 1) if "from_stage" in raw else None
    return Check(name=name, kind=kind, basis=basis, source=str(raw.get("source", "")), params=params,
                 from_stage=from_stage)


def scaled(budget: Budget, factor: int) -> Budget:
    """A copy of the budget for a long run: every sample and frame count multiplied by `factor`.

    Scales `samples` (profile kinds), `frames` (start_cycle, irq_time_per_frame) and `after_frames`
    (memory). `warmup_frames` and all limits stay as they are: the limits must hold in any window.
    """
    if factor == 1:
        return budget
    counts = ("samples", "frames", "after_frames")
    checks = [replace(c, params={k: v * factor if k in counts else v for k, v in c.params.items()})
              for c in budget.checks]
    return replace(budget, checks=checks)


def load_budget(path: Path) -> Budget:
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise BudgetError(f"{path}: invalid JSON: {e}") from e
    if not isinstance(raw, dict):
        raise BudgetError(f"{path}: top level must be an object")
    for key in ("spike", "src_dir", "checks"):
        if key not in raw:
            raise BudgetError(f"{path}: missing '{key}'")
    if not isinstance(raw["checks"], list) or not raw["checks"]:
        raise BudgetError(f"{path}: 'checks' must be a non-empty list")
    warmup = _int(str(path), "warmup_frames", raw.get("warmup_frames", 50))
    stage = _int(str(path), "stage", raw["stage"], 1) if "stage" in raw else None
    checks = [parse_check(path, i, c) for i, c in enumerate(raw["checks"])]
    if stage is None:
        staged = [c.name for c in checks if c.from_stage is not None]
        if staged:
            raise BudgetError(f"{path}: check {staged[0]!r} has 'from_stage' but the file has no top-level 'stage'")
    return Budget(path, str(raw["spike"]), str(raw["src_dir"]), warmup, checks, stage)


def find_budgets(root: Path, selectors: list[str]) -> list[Path]:
    """All tests/**/budget.json under root, or only those a selector names.

    A selector is a spike/directory name ('irq_chain') or a path to any budget.json or its folder.
    """
    found = sorted((root / "tests").rglob("budget.json"))
    if not selectors:
        return found
    chosen: list[Path] = []
    for sel in selectors:
        p = Path(sel)
        direct = p if p.is_file() else p / "budget.json"
        if direct.is_file():  # any budget.json by path, e.g. a scratch copy
            chosen.append(direct)
            continue
        matches = [f for f in found
                   if f.parent.name == sel or f.resolve() in (p.resolve(), (p / "budget.json").resolve())]
        if not matches:
            raise BudgetError(f"no budget.json matches {sel!r} (found: {', '.join(f.parent.name for f in found) or 'none'})")
        chosen += [m for m in matches if m not in chosen]
    return chosen
