"""release-publish: everything up to the network calls, with a fake git/make/gh (no VICE, no network)."""

import io
import subprocess
from pathlib import Path

import pytest

from release_check import publish as P

FIX = Path(__file__).parent / "fixtures"


class FakeRunner(P.Runner):
    """Answers git / make / gh from a table and records every command it was asked to change."""

    def __init__(self, tmp, dry_run=False, dirty="", on_remote="origin/main", tag_exists=False, make_rc=0):
        super().__init__(dry_run, cwd=tmp, out=io.StringIO())
        self.dirty, self.on_remote, self.tag_exists, self.make_rc = dirty, on_remote, tag_exists, make_rc
        self.changed, self.ran = [], []

    def read(self, cmd):
        self.ran.append(cmd)
        ok = lambda out="": subprocess.CompletedProcess(cmd, 0, out, "")  # noqa: E731
        if cmd[:2] == ["git", "check-ref-format"]:
            return subprocess.CompletedProcess(cmd, 1 if " " in cmd[2] else 0, "", "")
        if cmd[:3] == ["git", "rev-parse", "-q"]:
            return subprocess.CompletedProcess(cmd, 0 if self.tag_exists else 1, "", "")
        if cmd[:2] == ["git", "status"]:
            return ok(self.dirty)
        if cmd[:3] == ["git", "branch", "-r"]:
            return ok(self.on_remote)
        if cmd[:2] == ["git", "rev-parse"]:
            return ok("0123456789abcdef0123456789abcdef01234567\n")
        if cmd[:3] == ["git", "remote", "get-url"]:
            return ok("https://github.com/o/r.git\n")
        return ok("")  # tool versions, gh auth status

    def stream(self, cmd):
        self.ran.append(cmd)
        if not self.make_rc:
            d = self.cwd / "dist" / "demo"
            d.mkdir(parents=True, exist_ok=True)
            (d / "demo.d64").write_bytes(b"d64 bytes")
            (d / "demo-sfx.prg").write_bytes(b"prg bytes")
        return self.make_rc

    def change(self, cmd):
        if self.dry_run:
            return super().change(cmd)
        self.changed.append(cmd)
        return "https://github.com/o/r/releases/tag/untagged-abc"

    def query(self, cmd):
        if self.dry_run:
            return super().query(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "")  # not found: fine


def run(tmp_path, tag="demo-1", **kw):
    r = FakeRunner(tmp_path, **{k: v for k, v in kw.items() if k in
                                ("dry_run", "dirty", "on_remote", "tag_exists", "make_rc")})
    rest = {k: v for k, v in kw.items() if k in ("template", "title")}
    rc = P.publish("demo", tag, runner=r, **rest)
    return rc, r, r.out.getvalue()


def test_checksums_are_shasum_format(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"abc")
    assert P.checksums_block([f]) == (
        "SHA-256\n```\nba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad  a.bin\n```")


def test_template_title_placeholders_and_appended_sections(tmp_path):
    files = [tmp_path / "x.d64", tmp_path / "x-sfx.prg"]
    for f in files:
        f.write_bytes(b"1")
    notes, title = P.render_notes("title: T (m)\nHello {game} {tag} {d64}", "Demo", "demo-1", files, "BUILD")
    assert title == "T (m)"
    assert notes.startswith("Hello Demo demo-1 x.d64\n")
    assert "SHA-256" in notes and notes.rstrip().endswith("BUILD")  # both appended


def test_requires_no_tag_name_with_spaces(tmp_path):
    rc, r, _ = run(tmp_path, tag="bad tag")
    assert rc == 1 and not r.changed


def test_refuses_dirty_tree_before_building_or_changing(tmp_path):
    rc, r, _ = run(tmp_path, dirty=" M engine/x.asm")
    assert rc == 1 and not r.changed
    assert not any(c[0] == "make" for c in r.ran)  # test-release never ran


def test_refuses_head_not_on_remote(tmp_path):
    rc, r, _ = run(tmp_path, on_remote="")
    assert rc == 1 and not r.changed


def test_refuses_existing_tag(tmp_path):
    rc, r, _ = run(tmp_path, tag_exists=True)
    assert rc == 1 and not r.changed


def test_refuses_when_test_release_fails(tmp_path):
    rc, r, _ = run(tmp_path, make_rc=2)
    assert rc == 1 and not r.changed


def test_real_run_tags_pushes_only_that_tag_and_drafts(tmp_path):
    rc, r, out = run(tmp_path)
    assert rc == 0
    tag, push, create = r.changed
    assert tag[:4] == ["git", "tag", "-a", "demo-1"]
    assert push == ["git", "push", "origin", "refs/tags/demo-1"]
    assert create[:3] == ["gh", "release", "create"] and create[3] == "demo-1"
    assert "--draft" in create and "--verify-tag" in create
    assert create[4:6] == ["dist/demo/demo.d64", "dist/demo/demo-sfx.prg"]
    assert "https://github.com/o/r/releases/tag/untagged-abc" in out
    notes = (tmp_path / "dist/demo/RELEASE-NOTES-demo-1.md").read_text()
    assert "SHA-256" in notes and "demo.d64" in notes and "commit `0123456789`" in notes


def test_dry_run_prints_commands_and_changes_nothing(tmp_path):
    rc, r, out = run(tmp_path, dry_run=True, dirty=" M x", template=FIX / "swarm-release-notes.md")
    assert rc == 0 and not r.changed
    assert "a real run would stop here" in out  # reported, not fatal
    assert "would run: git tag -a demo-1 -m" in out
    assert "would run: git push origin refs/tags/demo-1" in out
    assert "would run: gh release create demo-1 dist/demo/demo.d64 dist/demo/demo-sfx.prg --draft" in out
    assert "Swarm (M4 training game)" in out
    assert "would check:" not in out or "ls-remote" not in out  # the remote checks are skipped, not run
    assert "no network" in out


def test_main_without_tag_refuses_and_does_nothing(capsys):
    assert P.main(["demo"]) == 2
    assert "TAG is required" in capsys.readouterr().err


def test_default_template_has_files_checksums_and_build(tmp_path):
    rc, r, _ = run(tmp_path)
    notes = (tmp_path / "dist/demo/RELEASE-NOTES-demo-1.md").read_text()
    assert "**Demo**" in notes and 'LOAD"*",8,1' in notes and "Built with" in notes


def test_refuses_existing_archive_folder(tmp_path):
    (tmp_path / "releases" / "demo-1").mkdir(parents=True)
    rc, r, _ = run(tmp_path)
    assert rc == 1 and not r.changed and not any(c[0] == "make" for c in r.ran)


def test_real_run_keeps_an_archive_copy_and_dry_run_does_not(tmp_path):
    rc, r, _ = run(tmp_path)
    kept = tmp_path / "releases" / "demo-1"
    assert sorted(x.name for x in kept.iterdir()) == ["RELEASE-NOTES.md", "demo-sfx.prg", "demo.d64"]
    rc, r, out = run(tmp_path / "d", tag="demo-2", dry_run=True) if (tmp_path / "d").mkdir() is None else (0, 0, "")
    assert not (tmp_path / "d" / "releases").exists() and "would copy to releases/demo-2/" in out
