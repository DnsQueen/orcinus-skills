"""Tests for validate_repo.py (the repo validator).

The validator is the gate for every other check, so its own bugs are
the highest-priority class: a validator that passes on a broken repo
is worse than no validator. Each test covers a defect found by an
external review (second round, 2026-11-06):
- lstrip("./") turned "../outside" into "outside" (a path escaping
  the repo passed as valid);
- the THIRD_PARTY_NOTICES check used a substring, so a missing
  "monitoring" row hid behind "monitoring-observability";
- the skill counts in plugin.json ("Router + 34") and README.md were
  stale and unchecked;
- the stage-range check ignored Idea and Finalize, and never checked
  that the linear stages do not overlap.

Run: python3 -m pytest scripts/test_validate_repo.py -q
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_repo as vr  # noqa: E402


def test_resolve_inside_rejects_escape():
    """../outside must not resolve to a path inside the repo."""
    assert vr._resolve_inside("../outside") is None
    assert vr._resolve_inside("../../etc/passwd") is None
    assert vr._resolve_inside("./skills") is not None
    assert vr._resolve_inside("skills/orcinus") is not None
    # "./.hidden" resolves to ROOT/.hidden, not to "hidden".
    assert vr._resolve_inside("./.hidden") == vr.ROOT / ".hidden"


def test_notices_table_names_are_exact():
    """The first column is parsed, not substring-searched: removing
    the monitoring row must make 'monitoring' disappear even though
    'monitoring-observability' is still listed."""
    text = (vr.ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    names = vr._notices_table_names(text)
    assert "monitoring" in names
    assert "monitoring-observability" in names
    broken = text.replace("| monitoring |", "| monitoring-xxx |")
    assert "monitoring" not in vr._notices_table_names(broken)


def _minimal_repo(tmp_path):
    """A minimal repo the validator accepts, so one break at a time
    can be tested."""
    root = tmp_path / "repo"
    (root / "skills" / "orcinus" / "references").mkdir(parents=True)
    (root / "skills" / "other").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / ".claude-plugin").mkdir()
    skill = (
        "---\nname: {name}\ndescription: {desc}\nlicense: MIT\n---\n\nBody.\n"
    )
    (root / "skills" / "orcinus" / "SKILL.md").write_text(
        skill.format(name="orcinus", desc="Router.")
        + "- **Idea (0–9):** x.\n- **Architecture (10–19):** x.\n"
        + "- **Scaffold (20–29):** x.\n- **Build (30–39):** x.\n"
        + "- **Verify (40–59):** x.\n- **Security (50–79, cross-cutting):** x.\n"
        + "- **Debugging (50–79):** x.\n- **Finalize (80–100):** x.\n",
        encoding="utf-8",
    )
    (root / "skills" / "other" / "SKILL.md").write_text(
        skill.format(name="other", desc="Other."), encoding="utf-8"
    )
    (root / "GLOSSARY.md").write_text("# Glossary\n", encoding="utf-8")
    (root / "skills" / "orcinus" / "references" / "GLOSSARY.md").write_text(
        "# Glossary\n", encoding="utf-8"
    )
    (root / "docs" / "MAP.md").write_text(
        "## A — Idea (0–9)\n## B — Architecture / Setup (10–19)\n"
        "## C — Coding (20–39)\n## D — Testing / Verification (40–59)\n"
        "## E — Security / Health (50–79, cross-cutting)\n"
        "## F — Debugging / Refactor (50–79)\n"
        "## G — Finalize / Post-publish (80–100)\n",
        encoding="utf-8",
    )
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({
            "name": "x", "version": "1.0.0",
            "description": "Router + 1 focused sub-skills.",
            "author": {"name": "x"}, "skills": ["./skills"],
        }),
        encoding="utf-8",
    )
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({
            "name": "x", "owner": {"name": "x"},
            "plugins": [{"name": "x", "source": "./"}],
        }),
        encoding="utf-8",
    )
    (root / "README.md").write_text("all 2 skills\n", encoding="utf-8")
    (root / "SCOPE.md").write_text("scope\n", encoding="utf-8")
    (root / "skills" / "manifest.json").write_text(
        json.dumps({
            "version": 1,
            "skills": {
                "orcinus": {
                    "name": "orcinus", "license": "MIT",
                    "stages": ["0-100"], "source": "from-scratch",
                    "status": "built",
                },
                "other": {
                    "name": "other", "license": "MIT",
                    "stages": ["20-39"], "source": "from-scratch",
                    "status": "built",
                },
            },
        }),
        encoding="utf-8",
    )
    (root / "THIRD_PARTY_NOTICES.md").write_text(
        "| Skill | Upstream source | Licence | What was taken |\n"
        "|---|---|---|---|\n",
        encoding="utf-8",
    )
    return root


def _run_with_root(monkeypatch, root, check):
    """Run one validator check with ROOT pointed at a fixture repo."""
    monkeypatch.setattr(vr, "ROOT", root)
    vr.failures.clear()
    check()
    return list(vr.failures)


def test_skill_counts_match_actual_folders(tmp_path, monkeypatch):
    root = _minimal_repo(tmp_path)
    assert _run_with_root(monkeypatch, root, vr.check_skill_counts) == []
    assert _run_with_root(monkeypatch, root, vr.check_stage_ranges) == []
    # A stale count in plugin.json must fail.
    plugin = root / ".claude-plugin" / "plugin.json"
    data = json.loads(plugin.read_text(encoding="utf-8"))
    data["description"] = "Router + 34 focused sub-skills."
    plugin.write_text(json.dumps(data), encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_skill_counts)
    assert len(failures) == 1 and "34" in failures[0]
    # A stale count in README.md must fail too.
    data["description"] = "Router + 1 focused sub-skills."
    plugin.write_text(json.dumps(data), encoding="utf-8")
    (root / "README.md").write_text("all 99 skills\n", encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_skill_counts)
    assert len(failures) == 1 and "99" in failures[0]


def test_stage_ranges_cover_idea_and_finalize(tmp_path, monkeypatch):
    root = _minimal_repo(tmp_path)
    assert _run_with_root(monkeypatch, root, vr.check_stage_ranges) == []
    # Removing the Finalize range from the router must fail.
    router = root / "skills" / "orcinus" / "SKILL.md"
    text = router.read_text(encoding="utf-8")
    router.write_text(text.replace("- **Finalize (80–100):** x.\n", ""),
                      encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_stage_ranges)
    assert any("Finalize" in f for f in failures)
    # Overlapping linear stages must fail.
    router.write_text(
        text.replace("- **Verify (40–59):** x.", "- **Verify (40–99):** x."),
        encoding="utf-8",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_stage_ranges)
    assert any("overlap" in f for f in failures)


def test_plugin_path_escape_fails(tmp_path, monkeypatch):
    """A plugin.json skills path escaping the repo must fail (the
    lstrip bug let '../outside' pass as 'outside')."""
    root = _minimal_repo(tmp_path)
    plugin = root / ".claude-plugin" / "plugin.json"
    data = json.loads(plugin.read_text(encoding="utf-8"))
    data["skills"] = ["../outside"]
    plugin.write_text(json.dumps(data), encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_plugin_manifests)
    assert len(failures) == 1 and "escapes the repo" in failures[0]


def test_manifest_matches_folders_and_frontmatter(tmp_path, monkeypatch):
    """The manifest must agree with the folders and the frontmatter:
    a missing entry, a phantom entry, a stale licence, and an unknown
    stage must each fail."""
    root = _minimal_repo(tmp_path)
    assert _run_with_root(monkeypatch, root, vr.check_manifest) == []
    manifest = root / "skills" / "manifest.json"

    def load():
        return json.loads(manifest.read_text(encoding="utf-8"))

    def save(data):
        manifest.write_text(json.dumps(data), encoding="utf-8")

    def fresh():
        """Restore the manifest to the good state, so each sub-case
        starts clean."""
        save({
            "version": 1,
            "skills": {
                "orcinus": {
                    "name": "orcinus", "license": "MIT",
                    "stages": ["0-100"], "source": "from-scratch",
                    "status": "built",
                },
                "other": {
                    "name": "other", "license": "MIT",
                    "stages": ["20-39"], "source": "from-scratch",
                    "status": "built",
                },
            },
        })

    # A folder with no manifest entry must fail.
    fresh()
    data = load()
    del data["skills"]["other"]
    save(data)
    failures = _run_with_root(monkeypatch, root, vr.check_manifest)
    assert len(failures) == 1 and "other" in failures[0] and "not in" in failures[0]
    # A manifest entry with no folder must fail.
    fresh()
    data = load()
    data["skills"]["phantom"] = {"name": "phantom", "license": "MIT",
                                 "stages": ["20-39"], "source": "x",
                                 "status": "built"}
    save(data)
    failures = _run_with_root(monkeypatch, root, vr.check_manifest)
    assert any("phantom" in f for f in failures)
    # A licence that disagrees with the frontmatter must fail.
    fresh()
    data = load()
    data["skills"]["other"]["license"] = "Apache-2.0"
    save(data)
    failures = _run_with_root(monkeypatch, root, vr.check_manifest)
    assert any("Apache-2.0" in f and "MIT" in f for f in failures)
    # An unknown stage must fail.
    fresh()
    data = load()
    data["skills"]["other"]["stages"] = ["30-99"]
    save(data)
    failures = _run_with_root(monkeypatch, root, vr.check_manifest)
    assert any("30-99" in f for f in failures)
