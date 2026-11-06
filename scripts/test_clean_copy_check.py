"""Tests for clean_copy_check.py (the clean-copy portability check).

The old design renamed the live checkout to <source>.orcinus-hidden
for the duration of the run: if the process was killed mid-run the
source stayed hidden and the next run refused to start. The redesign
never renames the source — the working-tree mode copies it, the
release mode extracts a committed revision with `git archive` — so
a kill at any point leaves the source exactly as it was.

Run: python3 -m pytest scripts/test_clean_copy_check.py -q
"""

import hashlib
import json
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clean_copy_check  # noqa: E402

HERE = Path(__file__).resolve().parent


def _fixture_repo(tmp_path, sleep=0):
    """A minimal repo the clean-copy gates accept. The gate scripts
    are stubs: validate_repo.py either exits 0 at once or sleeps
    first (for the kill test)."""
    root = tmp_path / "repo"
    (root / "skills" / "other").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "skills" / "other" / "SKILL.md").write_text(
        "---\nname: other\ndescription: Other.\nlicense: MIT\n---\n\nBody.\n", encoding="utf-8"
    )
    (root / "skills" / "manifest.json").write_text(
        json.dumps({"skills": {"other": {}}}), encoding="utf-8"
    )
    validate = ("import time\ntime.sleep(%d)\n" % sleep) if sleep else ""
    (root / "scripts" / "validate_repo.py").write_text(validate, encoding="utf-8")
    (root / "scripts" / "check_drift.py").write_text("", encoding="utf-8")
    (root / "test_stub.py").write_text("def test_stub():\n    assert True\n", encoding="utf-8")
    # Directories the copy must exclude.
    for name in (".venv", "venv", ".mypy_cache"):
        (root / name).mkdir()
        (root / name / "junk.txt").write_text("junk\n", encoding="utf-8")
    return root


def _snapshot(root):
    """name -> sha256 for every file under root."""
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def test_copy_excludes_venvs_and_caches(tmp_path):
    """The copy must not carry .venv, venv, or .mypy_cache — they are
    machine state, and a clean copy that includes them is not clean."""
    src = _fixture_repo(tmp_path)
    dest = tmp_path / "dest"
    clean_copy_check._copy_clean(src, dest)
    for name in (".venv", "venv", ".mypy_cache"):
        assert not (dest / name).exists(), f"{name} was copied"
    assert (dest / "skills" / "other" / "SKILL.md").is_file()
    assert (dest / "test_stub.py").is_file()


def test_working_tree_mode_leaves_source_untouched(tmp_path):
    """A normal run must not rename, move, or change the source at
    any point — the before/after snapshot must be identical, and no
    .orcinus-hidden sibling may ever appear."""
    src = _fixture_repo(tmp_path)
    before = _snapshot(src)
    assert clean_copy_check.main(["--source", str(src)]) == 0
    assert _snapshot(src) == before
    assert not src.with_name(src.name + ".orcinus-hidden").exists()


def test_killed_run_leaves_source_intact(tmp_path):
    """Kill the check mid-run (while a gate is still executing) and
    the source must still be exactly as it was — the failure the
    old rename design could not survive."""
    src = _fixture_repo(tmp_path, sleep=30)
    shutil.copy(HERE / "clean_copy_check.py", src / "scripts" / "clean_copy_check.py")
    before = _snapshot(src)
    proc = subprocess.Popen(
        [sys.executable, str(src / "scripts" / "clean_copy_check.py"), "--source", str(src)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    time.sleep(2)
    assert proc.poll() is None, "the run finished before the kill"
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)
    assert _snapshot(src) == before
    assert not src.with_name(src.name + ".orcinus-hidden").exists()


def _git_repo(tmp_path):
    """The fixture repo with a git history: one commit, then an
    uncommitted file on top."""
    src = _fixture_repo(tmp_path)

    def git(*args):
        subprocess.run(["git", "-C", str(src), *args], check=True, capture_output=True, timeout=30)

    git("init", "-q")
    git("-c", "user.name=x", "-c", "user.email=x@x", "add", ".")
    git("-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "-m", "first")
    (src / "UNCOMMITTED.txt").write_text("not committed\n", encoding="utf-8")
    return src


def test_release_mode_uses_committed_tree(tmp_path, capsys):
    """--mode release tests the committed revision, not the working
    tree: the uncommitted file must not reach the clean copy."""
    src = _git_repo(tmp_path)
    assert clean_copy_check.main(["--source", str(src), "--mode", "release", "--keep"]) == 0
    out = capsys.readouterr().out
    kept = [line for line in out.splitlines() if line.startswith("Kept: ")]
    assert kept, "the kept copy path must be printed with --keep"
    dest = Path(kept[0][len("Kept: ") :].strip())
    try:
        assert not (dest / "UNCOMMITTED.txt").exists()
        assert (dest / "skills" / "other" / "SKILL.md").is_file()
    finally:
        shutil.rmtree(dest.parent, ignore_errors=True)


def test_release_mode_unknown_rev_fails(tmp_path):
    """An unresolvable revision fails loudly (exit 2) instead of
    silently testing something else."""
    src = _git_repo(tmp_path)
    before = _snapshot(src)
    assert (
        clean_copy_check.main(["--source", str(src), "--mode", "release", "--rev", "nonexistent"])
        == 2
    )
    assert _snapshot(src) == before
