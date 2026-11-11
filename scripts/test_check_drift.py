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


def test_manifest_keys_are_posix_for_windows_paths():
    """Manifest keys are forward-slash paths: on Windows, str() of
    a relative path uses backslashes, so a Windows build produced
    keys that never matched the recorded manifest and every vendored
    file was reported 'unrecorded' (CI 0.9.4, windows job: 130
    unrecorded, all of them)."""
    from pathlib import PureWindowsPath

    assert cd._manifest_key(PureWindowsPath("skills") / "a" / "b.md") == "skills/a/b.md"
    assert cd._manifest_key(PureWindowsPath("agents") / "x.md") == "agents/x.md"


def test_gitattributes_forces_lf_line_endings():
    """The repo must check out LF on every platform: with no
    .gitattributes, a Windows checkout converts LF to CRLF, so every
    text file's bytes differ from the recorded hash and the drift
    check reports them all 'drifted' (CI 0.9.4, windows job: 129
    drifted — every file with a newline; the one survivor was the
    empty __init__.py, which has no line endings to convert).
    .gitattributes with eol=lf makes checkouts byte-identical."""
    attrs = (REPO / ".gitattributes").read_text(encoding="utf-8")
    rules = [
        line.split()
        for line in attrs.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert any(parts[0] == "*" and "eol=lf" in parts[1:] for parts in rules), (
        ".gitattributes must force LF checkouts (a '*' rule with eol=lf)"
    )


# Empty-scan guard (0.12.4): a scan that returns empty over content
# known to be non-empty is a broken instrument — it must fail loudly,
# not silently pass. Adapted from rebelytics/one-skill-to-rule-them-all
# (CC-BY-4.0, pattern only, no code copied): its session-start scan
# exits 1 with "SCAN COMMAND BROKEN — $n files present, 0 headers
# parsed" when files are present but nothing parses
# (scripts/session-start-scan.sh:331).


def _empty_build_repo(tmp_path):
    """A repo with no vendored files at all: no vendored skill
    folder, empty agents/ and commands/ — build_manifest() is {}."""
    root = tmp_path / "repo"
    (root / "skills" / "other").mkdir(parents=True)
    (root / "agents").mkdir()
    (root / "commands").mkdir()
    (root / "scripts").mkdir()
    (root / "skills" / "other" / "SKILL.md").write_text("x\n", encoding="utf-8")
    return root


def test_empty_manifest_fails_loudly(monkeypatch, tmp_path, capsys):
    """The manifest is known to record the vendored files, so an
    empty manifest over an empty build is a broken instrument —
    'OK: 0 vendored files match' must not pass."""
    root = _empty_build_repo(tmp_path)
    monkeypatch.setattr(cd, "ROOT", root)
    monkeypatch.setattr(cd, "MANIFEST", root / "scripts" / "drift-manifest.json")
    (root / "scripts" / "drift-manifest.json").write_text("{}\n", encoding="utf-8")
    assert cd.build_manifest() == {}
    assert cd.main([]) == 1
    assert "SCAN BROKEN" in capsys.readouterr().err


def test_update_refuses_empty_build(monkeypatch, tmp_path, capsys):
    """--update with an empty build would overwrite the recorded
    manifest with {} — a scan that finds no vendored file over a
    tree known to hold them is broken, so the update must refuse
    and leave the manifest untouched."""
    root = _empty_build_repo(tmp_path)
    monkeypatch.setattr(cd, "ROOT", root)
    monkeypatch.setattr(cd, "MANIFEST", root / "scripts" / "drift-manifest.json")
    before = json.dumps({"skills/other/SKILL.md": "0" * 64}, indent=2) + "\n"
    (root / "scripts" / "drift-manifest.json").write_text(before, encoding="utf-8")
    assert cd.main(["--update"]) == 1
    assert (root / "scripts" / "drift-manifest.json").read_text(encoding="utf-8") == before
    assert "SCAN BROKEN" in capsys.readouterr().err
