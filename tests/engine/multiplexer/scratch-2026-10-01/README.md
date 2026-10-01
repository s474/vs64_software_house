# Scratch scripts and results, M3 stage 4 (2026-10-01)

Saved by the producer from the session's temporary folder, so the long-run figures quoted in
[M3-stage4-pinning-diagnosis.md](../../../../docs/milestones/M3-stage4-pinning-diagnosis.md) and
`engine/README.md` have their evidence in the repo. These are **unreviewed scratch scripts**, written
by the Technical Director during the stage 4 re-baseline and the final review. They use hard-coded
paths and aren't part of `make test`.

| File | What it is |
|---|---|
| `longrun.py`, `longrun20k.txt` | 20,000-pass trace of the stage 4 engine, and its results |
| `fast.py`, `fast920k.txt` | Free-CPU minima over 919,800 frames (non-stress 5,344, stress 4,480) |
| `soak300k.txt` | Free-CPU minima over 300,000 frames |
| `split.py`, `split2.py`, `split300k.txt`, `split2.txt` | Stress / non-stress classification trials (amp 2-3 against amp 2-5) |
| `an.py` | Analysis helper for the traces |
| ~~`slack.py`~~ | Deleted: now `tests/engine/multiplexer/positions.py --slack` (reproduced 2026-10-01: 60,000 slots, 139 on line Y, latest cycle 26, min slack 29) |

To do: replace the long-run scripts with `make test-long`. Then delete this folder.
