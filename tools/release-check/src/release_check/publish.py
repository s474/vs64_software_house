"""release-publish GAME TAG: draft the GitHub release for a game's release build.

Run:  make publish GAME=swarm TAG=swarm-m5            (refuses unless TAG is given)
      make publish GAME=swarm TAG=swarm-m5 DRY_RUN=1   (does everything local, prints the rest)
      uv run --package release-check release-publish swarm swarm-m5 [--dry-run] [--title T] [--notes-template F]

Steps, in order; the first failure exits 1 and says which rule broke:
  1. TAG is given, is a valid tag name, and does not exist yet (locally; on the remote and as a
     GitHub release too in a real run).
  2. The working tree is clean (no modified, staged or untracked files; git-ignored ones don't count)
     and HEAD is on a remote branch (so the tag's commit is public).
  3. `make test-release GAME=<game>` passes: builds the release, checks the d64, boots the d64 and
     the crunched PRG in headless VICE.
  4. Notes are written to dist/<game>/RELEASE-NOTES-<tag>.md from games/<game>/release-notes.md if it
     exists (else a generic text), with the SHA-256 checksums and the build info.
  5. (Before any of that, `releases/<tag>/` must not exist: it is never overwritten.)
  6. An annotated tag is made on HEAD and pushed (`git push origin <tag>`: that one tag, never
     anything else), then a DRAFT release is created with the d64 and the crunched PRG. A human
     publishes the draft on GitHub. The release's URL is printed. The d64, the crunched PRG and the
     notes (as RELEASE-NOTES.md) are copied to the git-ignored releases/<tag>/ as a kept archive.

--dry-run runs steps 1-4 for real (they only read, build and write under dist/) and prints the
commands of step 5 instead of running them; the network is not touched at all (no ls-remote, no gh).

Template (games/<game>/release-notes.md): plain Markdown. An optional first line `title: Swarm
(M4 training game)` is the release title (else --title, else "<Game> (<tag>)") and is not part of
the notes. Placeholders: {game} {tag} {d64} {sfx} {checksums} {build}. If the template has no
{checksums} / {build}, those two sections are appended.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

DEFAULT_TEMPLATE = """**{game}** for the PAL Commodore 64.

**Files**
- `{d64}`: the disk image. `LOAD"*",8,1` then `RUN`.
- `{sfx}`: the same game as a single crunched program (Exomizer), for quick loading.

{checksums}

{build}
"""


class PublishError(Exception):
    pass


class Runner:
    """Runs commands. In a dry run, `mutating` ones are only printed."""

    def __init__(self, dry_run: bool, cwd: Path = REPO, out=None):
        self.dry_run, self.cwd = dry_run, cwd
        self.out = out or sys.stdout

    def read(self, cmd: list[str]) -> subprocess.CompletedProcess:
        """A command that changes nothing and uses no network (git status, make, ...)."""
        return subprocess.run(cmd, cwd=self.cwd, capture_output=True, text=True)

    def stream(self, cmd: list[str]) -> int:
        """A long local command (the release build and its VICE boot) whose output is shown."""
        return subprocess.run(cmd, cwd=self.cwd).returncode

    def change(self, cmd: list[str]) -> str:
        """A command that changes git or GitHub. Dry run: print it, return ''."""
        if self.dry_run:
            print("would run: " + " ".join(shell_quote(c) for c in cmd), file=self.out)
            return ""
        p = subprocess.run(cmd, cwd=self.cwd, capture_output=True, text=True)
        if p.returncode:
            raise PublishError(f"`{' '.join(cmd)}` failed ({p.returncode}): {(p.stdout + p.stderr).strip()}")
        return p.stdout.strip()

    def query(self, cmd: list[str]) -> subprocess.CompletedProcess:
        """A read that needs the network (ls-remote, gh release view): skipped in a dry run."""
        if self.dry_run:
            print("would check: " + " ".join(shell_quote(c) for c in cmd), file=self.out)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return self.read(cmd)


def shell_quote(s: str) -> str:
    return s if re.fullmatch(r"[\w@%+=:,./-]+", s) else "'" + s.replace("'", "'\\''") + "'"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def checksums_block(files: list[Path]) -> str:
    """The `shasum -a 256` format, in a fenced block under a SHA-256 heading."""
    return "SHA-256\n```\n" + "\n".join(f"{sha256(f)}  {f.name}" for f in files) + "\n```"


def first_line(text: str) -> str:
    return (text.strip().splitlines() or [""])[0].strip()


def tool_version(r: Runner, cmd: list[str], pattern: str) -> str:
    try:
        p = r.read(cmd)
    except OSError:
        return "unknown"
    m = re.search(pattern, p.stdout + p.stderr)
    return m.group(0) if m else "unknown"


def build_info(r: Runner, game: str, tag: str, commit: str, remote_url: str | None) -> str:
    java = os.environ.get("JAVA", "/opt/homebrew/opt/openjdk/bin/java")
    jar = os.environ.get("KICKASS_JAR", "/Applications/KickAssembler/KickAss.jar")
    kick = tool_version(r, [java, "-jar", jar], r"Kick Assembler v[\d.]+").replace("Kick Assembler", "KickAssembler")
    exo = tool_version(r, [os.environ.get("EXOMIZER", "exomizer"), "-v"], r"Exomizer v[\d.]+")
    url = (remote_url or "").removesuffix(".git")
    src = f" ([source at the tag]({url}/tree/{tag}))" if url.startswith("https://") else ""
    return (f"Built with {kick} and {exo} from commit `{commit[:10]}`{src}: "
            f"`make release GAME={game}`.")


def render_notes(template: str, game: str, tag: str, files: list[Path], build: str) -> tuple[str, str | None]:
    """(notes, title from the template's `title:` first line or None)."""
    title = None
    lines = template.splitlines()
    if lines and lines[0].lower().startswith("title:"):
        title = lines[0].split(":", 1)[1].strip()
        template = "\n".join(lines[1:]).lstrip("\n")
    if "{checksums}" not in template:
        template = template.rstrip() + "\n\n{checksums}\n"
    if "{build}" not in template:
        template = template.rstrip() + "\n\n{build}\n"
    values = {"game": game, "tag": tag, "d64": files[0].name, "sfx": files[1].name,
              "checksums": checksums_block(files), "build": build}
    notes = re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), template)
    return notes.rstrip() + "\n", title


def check_tag_name(r: Runner, tag: str) -> None:
    if not tag or tag.startswith("-") or r.read(["git", "check-ref-format", f"refs/tags/{tag}"]).returncode:
        raise PublishError(f"TAG {tag!r} is not a valid tag name (try swarm-m5)")
    if r.read(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"]).returncode == 0:
        raise PublishError(f"tag {tag} already exists in this repository: pick a new TAG (nothing was changed)")


def check_clean(r: Runner) -> str | None:
    """None if the tree is clean, else the git status lines."""
    p = r.read(["git", "status", "--porcelain"])
    if p.returncode:
        raise PublishError(f"git status failed: {p.stderr.strip()}")
    return p.stdout.rstrip() or None


def check_on_remote(r: Runner) -> str | None:
    """None if HEAD is on some remote-tracking branch (local refs only), else the reason."""
    p = r.read(["git", "branch", "-r", "--contains", "HEAD"])
    return None if p.stdout.strip() else "HEAD is not on any remote branch: push the commits first (this tool never pushes branches)"


def publish(game: str, tag: str, dry_run: bool = False, title: str | None = None,
            template: Path | None = None, runner: Runner | None = None, out=None) -> int:
    r = runner or Runner(dry_run, out=out)
    out = out or r.out
    dry_run = r.dry_run
    say = lambda s: print(s, file=out)  # noqa: E731
    try:
        check_tag_name(r, tag)
        archive = r.cwd / "releases" / tag
        if archive.exists():
            raise PublishError(f"{archive.relative_to(r.cwd)} already exists: releases/ is never overwritten "
                               "(pick a new TAG or move the folder; nothing was changed)")
        problems = []
        dirty = check_clean(r)
        if dirty:
            problems.append("the working tree is not clean:\n" + "\n".join("    " + x for x in dirty.splitlines()))
        unpushed = check_on_remote(r)
        if unpushed:
            problems.append(unpushed)
        if problems:
            msg = "\n  ".join(problems)
            if not dry_run:
                raise PublishError(msg + "\n  (nothing was changed)")
            say("dry run: a real run would stop here:\n  " + msg)
        if not dry_run:
            if not shutil.which("gh"):
                raise PublishError("the GitHub CLI `gh` is not installed")
            if r.read(["gh", "auth", "status"]).returncode:
                raise PublishError("`gh auth status` fails: run `gh auth login`")
            if r.query(["git", "ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{tag}"]).returncode == 0:
                raise PublishError(f"tag {tag} already exists on origin")
            if r.query(["gh", "release", "view", tag]).returncode == 0:
                raise PublishError(f"a GitHub release for {tag} already exists")
        else:
            say(f"dry run: no network: skipping the remote tag and release checks for {tag}")

        make = ["make", "test-release", f"GAME={game}"] + [
            f"{k}={os.environ[k]}" for k in ("SRC_DIR", "ASSET_DIR") if os.environ.get(k)]
        say(f"running {' '.join(make)} ...")
        if r.stream(make):
            raise PublishError(f"`{' '.join(make)}` failed: nothing was tagged or released")

        dist = r.cwd / "dist" / game
        files = [dist / f"{game}.d64", dist / f"{game}-sfx.prg"]
        for f in files:
            if not f.is_file():
                raise PublishError(f"{f} is missing after the release build")
        commit = r.read(["git", "rev-parse", "HEAD"]).stdout.strip()
        remote = r.read(["git", "remote", "get-url", "origin"]).stdout.strip() or None
        tpl_path = template or r.cwd / "games" / game / "release-notes.md"
        text = tpl_path.read_text() if tpl_path.is_file() else DEFAULT_TEMPLATE
        notes, tpl_title = render_notes(text, game.capitalize(), tag, files,
                                        build_info(r, game, tag, commit, remote))
        title = title or tpl_title or f"{game.capitalize()} ({tag})"
        notes_file = dist / f"RELEASE-NOTES-{tag}.md"
        notes_file.write_text(notes)
        used = f"template {tpl_path}" if tpl_path.is_file() else "the generic template"
        say(f"notes: {notes_file.relative_to(r.cwd)} ({used})")

        r.change(["git", "tag", "-a", tag, "-m", title, commit])
        r.change(["git", "push", "origin", f"refs/tags/{tag}"])
        url = r.change(["gh", "release", "create", tag, *map(str, (f.relative_to(r.cwd) for f in files)),
                        "--draft", "--verify-tag", "--title", title, "--notes-file",
                        str(notes_file.relative_to(r.cwd))])
        kept = [(f, archive / f.name) for f in files] + [(notes_file, archive / "RELEASE-NOTES.md")]
        if dry_run:
            say(f"would copy to {archive.relative_to(r.cwd)}/: " + ", ".join(d.name for _, d in kept))
        else:
            archive.mkdir(parents=True)
            for src, dst in kept:
                shutil.copy2(src, dst)
            say(f"kept a copy in {archive.relative_to(r.cwd)}/")
        if dry_run:
            say("dry run: nothing was tagged, pushed or created")
        else:
            say(f"draft release: {url}\nit is a DRAFT: review it on GitHub and publish it there")
        return 0
    except PublishError as e:
        print(f"release-publish: error: {e}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="release-publish", description=__doc__.split("\n\n")[0])
    ap.add_argument("game")
    ap.add_argument("tag", nargs="?", default="", help="the tag to create: required, never guessed")
    ap.add_argument("--dry-run", action="store_true", help="do everything local; print the git/gh commands")
    ap.add_argument("--title", help="release title (default: the template's `title:` line, else '<Game> (<tag>)')")
    ap.add_argument("--notes-template", type=Path, help="notes template (default games/<game>/release-notes.md)")
    a = ap.parse_args(argv)
    if not a.tag:
        print("release-publish: error: TAG is required, e.g. make publish GAME=swarm TAG=swarm-m5 "
              "(nothing was changed)", file=sys.stderr)
        return 2
    return publish(a.game, a.tag, a.dry_run, a.title, a.notes_template)


if __name__ == "__main__":
    sys.exit(main())
