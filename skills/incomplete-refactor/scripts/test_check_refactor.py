"""Tests for check_refactor.py.

Each test covers a real defect found by external reviews (2026-11-06):
the basename allowlist, the missing skip dirs/lockfiles, the silent
non-UTF-8 skip, the $ identifier, the vacuous clean (empty --old,
nonexistent root), and the stale-test classification. Run:
    python3 -m pytest skills/incomplete-refactor/scripts/test_check_refactor.py -q
"""
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "check_refactor.py"


def run(root, *extra):
    cmd = [sys.executable, str(SCRIPT), "--root", str(root), *extra]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return result.returncode, result.stdout, result.stderr


def write(path, text, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding=encoding)


def test_clean_project(tmp_path):
    write(tmp_path / "src" / "a.ts", "export const newName = 1;\n")
    rc, out, _ = run(tmp_path, "--old", "oldName")
    assert rc == 0, out
    assert out.startswith("clean:")


def test_old_identifier_found(tmp_path):
    write(tmp_path / "src" / "a.ts", "export const oldName = 1;\n")
    rc, out, _ = run(tmp_path, "--old", "oldName")
    assert rc == 1, out
    assert "old-name" in out and "src/a.ts" in out


def test_allowlist_matches_relative_path_only(tmp_path):
    """--allow README.md must exempt the root README.md, not every
    README.md in the tree."""
    write(tmp_path / "README.md", "mentions oldName on purpose\n")
    write(tmp_path / "docs" / "README.md", "still uses oldName\n")
    rc, out, _ = run(tmp_path, "--old", "oldName", "--allow", "README.md")
    assert rc == 1, out
    assert "docs/README.md" in out
    assert out.count("oldName") >= 1
    # The root README.md is allowed; only the docs one is a hit.
    assert "README.md:1" not in out or "docs/README.md" in out
    assert "\tREADME.md\t" not in out


def test_generated_dirs_and_lockfiles_are_skipped(tmp_path):
    """build/, .next/, target/, Cargo.lock, poetry.lock are not scanned
    (walk fallback — tmp_path is not a git repo)."""
    write(tmp_path / "build" / "out.js", "oldName\n")
    write(tmp_path / ".next" / "out.js", "oldName\n")
    write(tmp_path / "target" / "out.rs", "oldName\n")
    write(tmp_path / "Cargo.lock", "oldName\n")
    write(tmp_path / "poetry.lock", "oldName\n")
    write(tmp_path / "src" / "a.ts", "export const newName = 1;\n")
    rc, out, _ = run(tmp_path, "--old", "oldName")
    assert rc == 0, out
    assert out.startswith("clean:")


def test_non_utf8_file_is_reported_not_silently_skipped(tmp_path):
    """A Latin-1 file is skipped, but the scan says so — and it is
    INCOMPLETE, not clean, because the file might contain the old name."""
    latin1 = "oldName in latin-1: café\n".encode("latin-1")
    write(tmp_path / "src" / "legacy.txt", latin1)
    rc, out, _ = run(tmp_path, "--old", "oldName")
    assert rc == 1, out
    assert "INCOMPLETE" in out
    assert "skipped (non-UTF-8)" in out


def test_dollar_identifier(tmp_path):
    """$store must match, but my$store and $storeV2 must not."""
    write(tmp_path / "src" / "a.ts", "const $store = 1;\n")
    write(tmp_path / "src" / "b.ts", "const my$store = 1;\n")
    write(tmp_path / "src" / "c.ts", "const $storeV2 = 1;\n")
    rc, out, _ = run(tmp_path, "--old", "$store")
    assert rc == 1, out
    assert "src/a.ts" in out
    assert "src/b.ts" not in out
    assert "src/c.ts" not in out


def test_word_boundary_still_works(tmp_path):
    write(tmp_path / "src" / "a.ts", "budgetWarningV2\n")
    rc, out, _ = run(tmp_path, "--old", "budgetWarning")
    assert rc == 0, out
    write(tmp_path / "src" / "b.ts", "budgetWarning\n")
    rc, out, _ = run(tmp_path, "--old", "budgetWarning")
    assert rc == 1, out


def test_empty_old_list_is_an_error(tmp_path):
    write(tmp_path / "src" / "a.ts", "oldName\n")
    rc, out, err = run(tmp_path, "--old", "")
    assert rc == 1
    assert "error" in err
    rc, out, err = run(tmp_path, "--old", " , ")
    assert rc == 1
    assert "error" in err


def test_nonexistent_root_is_an_error(tmp_path):
    rc, out, err = run(tmp_path / "does-not-exist", "--old", "oldName")
    assert rc == 1
    assert "error" in err


def test_stale_test_classification(tmp_path):
    """src/foo.test.ts is a test file, even though it is not under a
    tests/ directory."""
    write(tmp_path / "src" / "foo.test.ts", "oldName\n")
    write(tmp_path / "src" / "bar.ts", "oldName\n")
    write(tmp_path / "tests" / "baz.ts", "oldName\n")
    rc, out, _ = run(tmp_path, "--old", "oldName")
    assert rc == 1, out
    assert "stale-test\tsrc/foo.test.ts" in out
    assert "stale-test\ttests/baz.ts" in out
    assert "old-name\tsrc/bar.ts" in out


def test_removed_path_still_exists(tmp_path):
    write(tmp_path / "src" / "budget-old.ts", "export const x = 1;\n")
    rc, out, _ = run(tmp_path, "--old", "oldName",
                     "--removed", "src/budget-old.ts")
    assert rc == 1, out
    assert "removed-path" in out


def test_git_ls_files_respects_gitignore_and_includes_untracked(tmp_path):
    """In a git repo, an ignored file is not scanned, but an untracked
    file is."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=30)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.t"],
                   check=True, timeout=30)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"],
                   check=True, timeout=30)
    write(tmp_path / ".gitignore", "ignored/\n")
    write(tmp_path / "ignored" / "a.ts", "oldName\n")
    write(tmp_path / "src" / "new.ts", "oldName\n")  # untracked, not ignored
    write(tmp_path / "src" / "clean.ts", "export const x = 1;\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "src/clean.ts"],
                   check=True, timeout=30)
    rc, out, _ = run(tmp_path, "--old", "oldName")
    assert rc == 1, out
    assert "src/new.ts" in out
    assert "ignored/a.ts" not in out
