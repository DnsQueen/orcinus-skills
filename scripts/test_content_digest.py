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
