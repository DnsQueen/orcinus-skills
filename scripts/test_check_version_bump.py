"""Tests for check_version_bump.py.

A push that changes shipped plugin content (skills/, agents/,
commands/) must bump the version in .claude-plugin/plugin.json AND
add a CHANGELOG.md entry in the same push. The tests build real
temporary git repos and run the script's CLI against them.

Run: python3 -m pytest scripts/test_check_version_bump.py -q
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "check_version_bump.py"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, timeout=30)


def _commit(repo, files, message):
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                         check=True, capture_output=True, text=True,
                         timeout=30)
    return out.stdout.strip()


def _repo(tmp_path):
    """A repo at version 0.9.0 with one skill, ready for a second
    commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@orcinus.local")
    _git(repo, "config", "user.name", "ORCINUS Test")
    _commit(repo, {
        ".claude-plugin/plugin.json": json.dumps(
            {"name": "x", "version": "0.9.0"}),
        "CHANGELOG.md": "# Changelog\n\n## [0.9.0] — 2026-11-06\n\nFirst.\n",
        "skills/other/SKILL.md": "---\nname: other\n---\n\nBody.\n",
    }, "init")
    return repo


def _run(repo, base, head):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--base", base, "--head", head,
         "--repo", str(repo)],
        capture_output=True, text=True, timeout=30)
    return proc.returncode, proc.stdout + proc.stderr


def _head(repo):
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                         check=True, capture_output=True, text=True,
                         timeout=30)
    return out.stdout.strip()


def test_docs_only_change_needs_no_bump(tmp_path):
    """A push that touches only docs/ passes without a bump."""
    repo = _repo(tmp_path)
    base = _head(repo)
    _commit(repo, {"README.md": "docs\n"}, "docs")
    rc, out = _run(repo, base, _head(repo))
    assert rc == 0, out
    assert "no version bump needed" in out


def test_skill_change_without_bump_fails(tmp_path):
    """A push that changes a skill without bumping the version
    fails and says the version is the missing part."""
    repo = _repo(tmp_path)
    base = _head(repo)
    _commit(repo, {"skills/other/SKILL.md": "---\nname: other\n---\n\nNew.\n"},
            "skill change")
    rc, out = _run(repo, base, _head(repo))
    assert rc == 1, out
    assert "version" in out.lower()


def test_skill_change_with_bump_but_no_changelog_fails(tmp_path):
    """Bumping the version without a CHANGELOG.md entry still fails
    — the two travel together."""
    repo = _repo(tmp_path)
    base = _head(repo)
    _commit(repo, {
        "skills/other/SKILL.md": "---\nname: other\n---\n\nNew.\n",
        ".claude-plugin/plugin.json": json.dumps(
            {"name": "x", "version": "0.9.1"}),
    }, "skill change + bump")
    rc, out = _run(repo, base, _head(repo))
    assert rc == 1, out
    assert "CHANGELOG.md" in out


def test_skill_change_with_bump_and_changelog_passes(tmp_path):
    """Skill change + version bump + changelog entry passes."""
    repo = _repo(tmp_path)
    base = _head(repo)
    _commit(repo, {
        "skills/other/SKILL.md": "---\nname: other\n---\n\nNew.\n",
        ".claude-plugin/plugin.json": json.dumps(
            {"name": "x", "version": "0.9.1"}),
        "CHANGELOG.md": "# Changelog\n\n## [0.9.1] — 2026-11-06\n\nFix.\n\n## [0.9.0] — 2026-11-06\n\nFirst.\n",
    }, "skill change + bump + changelog")
    rc, out = _run(repo, base, _head(repo))
    assert rc == 0, out


def test_agent_change_without_bump_fails(tmp_path):
    """agents/ and commands/ are shipped plugin content too — a
    change there without a bump fails, same as skills/."""
    repo = _repo(tmp_path)
    base = _head(repo)
    _commit(repo, {"agents/grader.md": "---\nname: grader\n---\n\nNew.\n"},
            "agent change")
    rc, out = _run(repo, base, _head(repo))
    assert rc == 1, out


def test_first_push_against_empty_tree_passes(tmp_path):
    """A first push (base 0000...) diffs against the empty tree: the
    initial plugin.json + CHANGELOG.md count as the bump, so it
    passes instead of failing on an unresolvable base."""
    repo = _repo(tmp_path)
    rc, out = _run(repo, "0" * 40, _head(repo))
    assert rc == 0, out


def test_changelog_without_version_bump_fails(tmp_path):
    """A changelog entry without the version bump still fails."""
    repo = _repo(tmp_path)
    base = _head(repo)
    _commit(repo, {
        "skills/other/SKILL.md": "---\nname: other\n---\n\nNew.\n",
        "CHANGELOG.md": "# Changelog\n\n## [0.9.1] — 2026-11-06\n\nFix.\n\n## [0.9.0] — 2026-11-06\n\nFirst.\n",
    }, "skill change + changelog only")
    rc, out = _run(repo, base, _head(repo))
    assert rc == 1, out
    assert "version" in out.lower()


def test_unresolvable_base_fails_loudly(tmp_path):
    """A non-zero base that cannot be resolved (CI forgot to fetch
    it) fails with exit 2 — it must NOT silently fall back to the
    empty tree, against which every push would pass."""
    repo = _repo(tmp_path)
    rc, out = _run(repo, "a" * 40, _head(repo))
    assert rc == 2, out
    assert "cannot resolve" in out
