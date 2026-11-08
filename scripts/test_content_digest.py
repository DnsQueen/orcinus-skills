"""Tests for content_digest.py (the state-machine fix, round 4).

The spec contradiction (docs/project-state.md): state.json is committed
with the project, but any new commit reset the stage to BUILDING — so
VERIFIED could never survive its own commit. The fix binds VERIFIED
to the *content digest* (sha256 over the tree excluding .orcinus/ and
docs/verification/), not to the commit SHA: a commit that only records
state or evidence leaves the digest unchanged and does not reset.

Run: python3 -m pytest scripts/test_content_digest.py -q
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import content_digest as cd  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@orcinus.local")
    _git(repo, "config", "user.name", "ORCINUS Test")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "code")
    return repo


def test_digest_ignores_state_and_evidence_commits():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        repo = _repo(Path(d))
        before = cd.content_digest(repo)
        (repo / ".orcinus").mkdir()
        (repo / ".orcinus" / "state.json").write_text('{"stage": "VERIFIED"}', encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "record VERIFIED state")
        assert cd.content_digest(repo) == before
        (repo / "docs" / "verification").mkdir(parents=True)
        (repo / "docs" / "verification" / "stage-30.json").write_text("{}", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "record evidence bundle")
        assert cd.content_digest(repo) == before


def test_digest_changes_when_code_changes():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        repo = _repo(Path(d))
        before = cd.content_digest(repo)
        (repo / "src" / "app.py").write_text("x = 2\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "change code")
        assert cd.content_digest(repo) != before


def test_digest_is_stable_and_prefixed():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        repo = _repo(Path(d))
        digest = cd.content_digest(repo)
        assert digest.startswith("sha256:")
        assert len(digest) == len("sha256:") + 64
        assert all(c in "0123456789abcdef" for c in digest[7:])
        assert cd.content_digest(repo) == digest


def test_excluded_prefixes_are_exact():
    # Only the directories .orcinus/ and docs/verification/ are
    # excluded — similarly named paths must still count.
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        repo = _repo(Path(d))
        before = cd.content_digest(repo)
        (repo / ".orcinus-notes.txt").write_text("note\n", encoding="utf-8")
        (repo / "docs").mkdir(exist_ok=True)
        (repo / "docs" / "verification-notes.txt").write_text("note\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "similarly named files")
        assert cd.content_digest(repo) != before


def test_digest_of_non_repo_fails():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        try:
            cd.content_digest(Path(d))
        except cd.ContentDigestError:
            return
        raise AssertionError("expected ContentDigestError for a non-repo")


def test_cli_rev_flag(capsys):
    """F-15: --rev names the revision. `content_digest.py [repo]
    [--rev REV]`, default HEAD."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        repo = _repo(Path(d))
        assert cd.main([str(repo), "--rev", "HEAD"]) == 0
        assert capsys.readouterr().out.strip() == cd.content_digest(repo)
        assert cd.main([str(repo)]) == 0
        assert capsys.readouterr().out.strip() == cd.content_digest(repo)


def test_cli_bare_rev_rejected(capsys, monkeypatch):
    """F-15: a bare revision is ambiguous with a repo path — the
    old CLI silently treated it as a repo path and failed with a
    confusing git error. It is now a usage error (exit 2) that
    says to use --rev."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        repo = _repo(Path(d))
        # monkeypatch teardown runs only after this `with` block exits,
        # so a plain monkeypatch.chdir(repo) would leave the cwd inside
        # the temp dir while it is deleted — WinError 32 on Windows.
        # The context restores the cwd before the directory goes away.
        with monkeypatch.context() as m:
            m.chdir(repo)
            assert cd.main(["HEAD"]) == 2
            err = capsys.readouterr().err
            assert "--rev" in err
            assert cd.main(["HEAD", "--rev", "HEAD"]) == 2
    # Regression (Windows WinError 32): the cwd must be back outside
    # the (now deleted) temp dir. On Linux the old code left it
    # pointing at the deleted dir (getcwd raises FileNotFoundError);
    # on Windows it failed earlier, at the TemporaryDirectory exit.
    assert Path.cwd().is_dir()


def test_cli_repo_rev_positionals_still_work(capsys):
    """F-15: the documented [repo] [rev] form still works."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        repo = _repo(Path(d))
        assert cd.main([str(repo), "HEAD"]) == 0
        assert capsys.readouterr().out.strip() == cd.content_digest(repo)


def test_cli_rev_flag_conflicts_with_positional_rev():
    """--rev and a positional revision together are a usage error:
    give one."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        repo = _repo(Path(d))
        assert cd.main([str(repo), "HEAD", "--rev", "HEAD"]) == 2


def test_cli_git_failure_is_exit_1(capsys):
    """Exit codes follow the spec-kit CLI shape: 2 bad usage, 1
    violation, 0 success. A git failure on valid arguments (not
    a repo, unknown revision) is a violation — exit 1, not 2."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        repo = _repo(Path(d))
        assert cd.main([str(repo), "--rev", "no-such-rev"]) == 1
        assert "content_digest:" in capsys.readouterr().err
        assert cd.main([str(repo), "no-such-rev"]) == 1
        assert cd.main([str(Path(d))]) == 1  # an existing dir that is not a repo
        assert cd.main(["/nonexistent-path-orcinus-xyz"]) == 2  # not a dir: usage, not a repo


def test_cli_entry_point_via_subprocess(tmp_path):
    """FND-001 (round 8): the real entry point — `sys.exit(main(sys.argv))`
    passed argv[0] (the script path) as the positional repo, so every
    documented invocation exited 2. main([...]) without argv[0] never
    caught it; only running the script as a script does."""
    repo = _repo(tmp_path)
    script = Path(__file__).resolve().parent / "content_digest.py"
    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=repo, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == cd.content_digest(repo)
    proc = subprocess.run(
        [sys.executable, str(script), "--rev", "HEAD"],
        capture_output=True,
        text=True,
        cwd=repo,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == cd.content_digest(repo)
    proc = subprocess.run(
        [sys.executable, str(script), str(repo)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == cd.content_digest(repo)


def test_content_digest_empty_tree_is_genuine_not_broken_git(tmp_path):
    """N-A1 (round 8): an empty tree hashes to the empty digest — but
    so does stubbed/broken git printing nothing with exit 0. A
    genuinely empty tree (an --allow-empty commit) must still digest;
    empty ls-tree output with no tree object behind it must fail."""

    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@orcinus.local")
    _git(repo, "config", "user.name", "ORCINUS Test")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "empty")
    assert (
        cd.content_digest(repo)
        == "sha256:" + "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_content_digest_empty_git_output_fails(tmp_path, monkeypatch):
    """N-A1 (round 8): git printing nothing with exit 0 is broken git,
    not an empty tree — the tree object must be confirmed to exist
    before empty ls-tree output is accepted."""
    import os
    import stat

    repo = _repo(tmp_path)
    stubdir = tmp_path / "stubbin"
    stubdir.mkdir()
    # Windows cannot execute an extensionless `git` file
    # (CreateProcess only tries the exact name and the PATHEXT
    # extensions), so the stub must be `git.bat` there — with the
    # extensionless file the real git.exe runs and the stub is
    # silently ignored, which is what failed this test on the
    # Windows runner (CI run 42499224528).
    if sys.platform == "win32":
        stub = stubdir / "git.bat"
        stub.write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
    else:
        stub = stubdir / "git"
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(stat.S_IRWXU)
    monkeypatch.setenv("PATH", str(stubdir) + os.pathsep + os.environ["PATH"])
    try:
        cd.content_digest(repo)
    except cd.ContentDigestError:
        return
    raise AssertionError("expected ContentDigestError for empty git output")


def _repo_with_persian_code(tmp_path):
    """A repo whose tree contains a non-ASCII path: the case the
    v1 digest got wrong (git quotes such paths unless -z is used)."""
    repo = _repo(tmp_path)
    (repo / "src" / "فایل.py").write_text("y = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "persian filename")
    return repo


def test_digest_same_under_quotePath_true_and_false():
    # R4 F2 / R3 #2 acceptance: one tree must have one digest,
    # whatever core.quotePath the machine sets. The v1 digest
    # hashed git's quoted display, so it changed with the setting.
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        repo = _repo_with_persian_code(Path(d))
        _git(repo, "config", "core.quotePath", "true")
        quoted = cd.content_digest(repo)
        _git(repo, "config", "core.quotePath", "false")
        unquoted = cd.content_digest(repo)
        assert quoted == unquoted


def test_digest_excludes_non_ascii_state_and_evidence_files():
    # R4 F2 acceptance: a Persian file under .orcinus/ or
    # docs/verification/ must not change the digest — the quoted
    # form used to escape the startswith exclusion.
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        repo = _repo_with_persian_code(Path(d))
        _git(repo, "config", "core.quotePath", "true")
        before = cd.content_digest(repo)
        (repo / ".orcinus").mkdir()
        (repo / ".orcinus" / "یادداشت.json").write_text("{}", encoding="utf-8")
        (repo / "docs" / "verification").mkdir(parents=True)
        (repo / "docs" / "verification" / "نتیجه.json").write_text("{}", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "persian state and evidence files")
        assert cd.content_digest(repo) == before


def test_digest_changes_for_non_ascii_code_file():
    # The control for the two tests above: a Persian file under
    # src/ (not excluded) must change the digest.
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        repo = _repo_with_persian_code(Path(d))
        before = cd.content_digest(repo)
        (repo / "src" / "جدید.py").write_text("z = 1\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "another persian file")
        assert cd.content_digest(repo) != before
