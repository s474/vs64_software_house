"""Helpers for writing a game's clean-state guard (see cases.Suite.run)."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def expect_memory(rig, expected: Mapping[str, int | tuple | list | Callable]) -> list[str]:
    """Compare memory with what a clean state holds; returns a problem per mismatch (empty = clean).

    `expected` maps a label (or 'label+off') to
      an int            one byte,
      a list/tuple      that many bytes, or
      a callable        called with the bytes read (as many as `size`, default 1: use (callable, size)
                        for more) and returns True if acceptable.
    """
    problems = []
    for key, want in expected.items():
        label, _, off = key.partition("+")
        off = int(off, 0) if off else 0
        if isinstance(want, tuple) and len(want) == 2 and callable(want[0]):
            check, size = want
            got = rig.peeks(label, size, off)
            if not check(got):
                problems.append(f"{key} = {list(got)} fails its check")
            continue
        if callable(want):
            got = rig.peek(label, off)
            if not want(got):
                problems.append(f"{key} = {got} fails its check")
            continue
        wanted = [want] if isinstance(want, int) else list(want)
        got = list(rig.peeks(label, len(wanted), off))
        if got != wanted:
            problems.append(f"{key} = {got if len(got) > 1 else got[0]}, expected {wanted if len(wanted) > 1 else wanted[0]}")
    return problems
