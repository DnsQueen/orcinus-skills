"""Tests for scripts/check_drift.py (round 5, T7).

Two holes the drift check had:
- Any file named test_*.py inside a vendored skill was treated as
  ORCINUS-owned and escaped the check, so a new upstream test file
  (or a misplaced ORCINUS file) would be invisible. The exclusion is
  now an explicit allowlist of the four ORCINUS-authored test files,
  verified absent from upstream at the pinned commits.
- agents/ and commands/ were a hardcoded list of ten files, so a new
  file added under either directory was invisible. build_manifest()
  now glob-scans both directories.

Run: python3 -m pytest scripts/test_check_drift.py -q
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_drift as cd  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

ORCINUS_TEST_FILES = [
    "skills/database-designer/test_migration_generator.py",
    "skills/database-designer/test_migration_integration.py",
    "skills/database-designer/test_postgres_migration.py",
    "skills/webapp-testing/scripts/test_with_server.py",
]


def _tmp_repo(tmp_path):
    """A minimal repo tree for the drift check."""
    root = tmp_path / "repo"
    (root / "skills" / "database-designer").mkdir(parents=True)
    (root / "skills" / "other").mkdir()
    (root / "agents").mkdir()
    (root / "commands").mkdir()
    (root / "scripts").mkdir()
    for rel in (
        "skills/database-designer/SKILL.md",
        "skills/database-designer/migration_generator.py",
        "skills/other/SKILL.md",
        "agents/analyzer.md",
        "commands/review-pr.md",
    ):
        (root / rel).write_text("x\n", encoding="utf-8")
    return root


def test_orcinus_test_files_are_excluded(monkeypatch, tmp_path):
    """The four ORCINUS-authored test files inside vendored skills
    are not vendored — verified absent from upstream at the pinned
    commits (database-designer: alirezarezvani/claude-skills @
    8f08254; webapp-testing: anthropics/skills @ ca45fc4)."""
    root = _tmp_repo(tmp_path)
    monkeypatch.setattr(cd, "ROOT", root)
    for rel in ORCINUS_TEST_FILES:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
        assert not cd._is_vendored(path), f"{rel} must be excluded"


def test_new_test_file_in_vendored_skill_is_vendored(monkeypatch, tmp_path):
    """A test_*.py that is NOT on the allowlist is vendored: the old
    name heuristic let any such file escape the check."""
    root = _tmp_repo(tmp_path)
    monkeypatch.setattr(cd, "ROOT", root)
    path = root / "skills" / "database-designer" / "test_new_thing.py"
    path.write_text("x\n", encoding="utf-8")
    assert cd._is_vendored(path)


def test_build_manifest_globs_agents_and_commands(monkeypatch, tmp_path):
    """A new file under agents/ or commands/ is in the manifest —
    the old hardcoded list of ten files made additions invisible."""
    root = _tmp_repo(tmp_path)
    monkeypatch.setattr(cd, "ROOT", root)
    (root / "agents" / "new-agent.md").write_text("x\n", encoding="utf-8")
    (root / "commands" / "new-command.md").write_text("x\n", encoding="utf-8")
    manifest = cd.build_manifest()
    assert "agents/new-agent.md" in manifest
    assert "commands/new-command.md" in manifest
    assert "agents/analyzer.md" in manifest
    assert "commands/review-pr.md" in manifest


def test_check_flags_unrecorded_agent(monkeypatch, tmp_path, capsys):
    """The check fails on an unrecorded agents/ file, naming it."""
    root = _tmp_repo(tmp_path)
    monkeypatch.setattr(cd, "ROOT", root)
    monkeypatch.setattr(cd, "MANIFEST", root / "scripts" / "drift-manifest.json")
    (root / "agents" / "new-agent.md").write_text("x\n", encoding="utf-8")
    (root / "scripts" / "drift-manifest.json").write_text(
        json.dumps(cd.build_manifest(), indent=2) + "\n", encoding="utf-8"
    )
    # The manifest above already includes the new agent; remove it
    # to simulate an addition nobody recorded.
    manifest = json.loads((root / "scripts" / "drift-manifest.json").read_text())
    del manifest["agents/new-agent.md"]
    (root / "scripts" / "drift-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    assert cd.main([]) == 1
    assert "unrecorded: agents/new-agent.md" in capsys.readouterr().out


def test_orcinus_root_files_are_excluded(monkeypatch, tmp_path):
    """An agents/ file listed as ORCINUS-authored is not vendored."""
    root = _tmp_repo(tmp_path)
    monkeypatch.setattr(cd, "ROOT", root)
    monkeypatch.setattr(cd, "ORCINUS_ROOT_FILES", {"agents/orcinus-agent.md"})
    (root / "agents" / "orcinus-agent.md").write_text("x\n", encoding="utf-8")
    assert "agents/orcinus-agent.md" not in cd.build_manifest()


def test_manifest_unchanged_on_real_repo():
    """The refactor changes what the check SEES, not what it tracks:
    the manifest built from the real repo is exactly the committed
    one (130 files — 129 vendored plus the ORCINUS-authored
    accessibility gate wrapper, recorded in the manifest in round 6
    so a silent edit to the gate is caught)."""
    manifest = cd.build_manifest()
    committed = json.loads((REPO / "scripts" / "drift-manifest.json").read_text())
    assert manifest == committed
    assert len(manifest) == 130
