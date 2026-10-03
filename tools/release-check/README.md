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

## release-publish: draft the GitHub release

```
make publish GAME=swarm TAG=swarm-m5 DRY_RUN=1    # everything local, then prints the git / gh commands
make publish GAME=swarm TAG=swarm-m5              # for real: tags, pushes that one tag, drafts the release
```

`TAG` has no default: without it nothing happens (exit 2). In order, stopping at the first failure
(nothing is changed until the last steps): `TAG` is a valid name and no such tag exists (real run:
neither on `origin` nor as a GitHub release) and `releases/<TAG>/` does not exist; the working tree
is clean (no modified, staged or untracked files) and HEAD is on a remote branch (checked on local
refs; branches are never pushed); `make test-release GAME=<game>` passes; notes are written to
`dist/<game>/RELEASE-NOTES-<TAG>.md`; then `git tag -a <TAG>`, `git push origin refs/tags/<TAG>` (only
that tag) and `gh release create <TAG> <d64> <crunched prg> --draft --verify-tag --notes-file ...`,
whose URL is printed. It is a **draft**: a human reviews and publishes it on GitHub. Last, the d64,
the crunched PRG and the notes (as `RELEASE-NOTES.md`) are copied to `releases/<TAG>/`, a git-ignored
archive of every published release by tag, **never overwritten** (like `dist/`, it survives
`make clean`).

Notes come from `games/<game>/release-notes.md` if it exists (Markdown; an optional first line
`title: ...` is the release title; placeholders `{game} {tag} {d64} {sfx} {checksums} {build}`; the
SHA-256 block and the build info are appended if the template lacks them), else a generic text.
`--notes-template F` and `--title T` override (`uv run --package release-check release-publish -h`).
An example template, Swarm's M4 notes: `tests/fixtures/swarm-release-notes.md`. Build info: commit,
KickAssembler and Exomizer versions, the make command, a link to the source at the tag.

`DRY_RUN=1` (`--dry-run`) does steps 1-4 for real (they only read, build, and write under `dist/`);
a dirty tree or unpushed HEAD is reported ("a real run would stop here") instead of fatal, and no
network is touched (no `ls-remote`, no `gh`). Tests (fake git / make / gh, no network): `make test-tools`.
