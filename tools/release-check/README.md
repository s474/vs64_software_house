# release-check

Verifies a release build made by `make release GAME=<title>` (files in `dist/<title>/`).

```
make test-release GAME=swarm          # builds the release, then checks it
uv run --package release-check release-check swarm [--text "PRESS FIRE"] [--mem zp_game_state=4]
```

Checks (exit 1, naming the file and the rule, on the first failure):

1. `dist/<title>/<title>.d64` exists; `c1541 -list` shows disk name `<TITLE>` and exactly one PRG
   named `<TITLE>`.
2. The crunched `<title>-sfx.prg` starts at `$0801` with a BASIC SYS line and is smaller than the raw PRG.
3. A fresh headless `x64sc` (warp, own monitor port, killed afterwards; started by
   `mcp/vice/vice_monitor.py`'s `start_vice`) autostarts the d64 (`LOAD"*",8,1`, true drive) and the
   title appears: the text is in screen memory in screen codes and each `--mem` label=value holds.
4. The same for the crunched PRG run directly.

Swarm's defaults: text `PRESS FIRE`, `zp_game_state = 4` (GAME_STATE_TITLE). Another game: pass `--text`
(add a default to `GAMES` in `cli.py` if it will be checked often). One line of output on success:
sizes, blocks, and the PAL frame the title was first seen in (counted from VICE's start, so the
~100-frame KERNAL boot is included; sampled every 2nd frame).

Unit tests (no VICE): `make test-tools`.
