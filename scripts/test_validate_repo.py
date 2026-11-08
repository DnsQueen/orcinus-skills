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

import pytest

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
    skill = "---\nname: {name}\ndescription: {desc}\nlicense: MIT\n---\n\nBody.\n"
    (root / "skills" / "orcinus" / "SKILL.md").write_text(
        skill.format(name="orcinus", desc="Router.")
        + "- **Idea (0–9):** x.\n- **Architecture (10–19):** x.\n"
        + "- **Scaffold (20–29):** x.\n- **Build (30–39):** x.\n"
        + "- **Verify (40–59):** x.\n- **Security (50–79, cross-cutting):** x.\n"
        + "- **Debugging (50–79):** x.\n- **Finalize (80–100):** x.\n",
        encoding="utf-8",
    )
    (root / "skills" / "other" / "SKILL.md").write_text(
        "---\nname: other\ndescription: Other.\nlicense: MIT\n"
        "user-invocable: false\n---\n\nBody.\n",
        encoding="utf-8",
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
        json.dumps(
            {
                "name": "x",
                "version": "1.0.0",
                "description": "Router + 1 focused sub-skills.",
                "author": {"name": "x"},
                "skills": ["./skills"],
            }
        ),
        encoding="utf-8",
    )
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "x",
                "description": "Test marketplace.",
                "owner": {"name": "x"},
                "plugins": [{"name": "x", "source": "./"}],
            }
        ),
        encoding="utf-8",
    )
    (root / ".claude-plugin" / "icon.png").write_bytes(b"")
    (root / "README.md").write_text(
        "all 2 skills\nthe router and 1 focused sub-skills\n", encoding="utf-8"
    )
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [1.0.0] — 2026-11-06\n\nThe first release.\n",
        encoding="utf-8",
    )
    (root / "SCOPE.md").write_text("scope\n", encoding="utf-8")
    (root / "SECURITY.md").write_text(
        "# Security Policy\n\n## Supported Versions\n\n"
        "| Version | Supported |\n| ------- | --------- |\n"
        "| 1.0.x | Yes |\n"
        "| < 1.0 | No (no release was cut before 1.0.0) |\n",
        encoding="utf-8",
    )
    (root / "skills" / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "skills": {
                    "orcinus": {
                        "name": "orcinus",
                        "description": "Router.",
                        "license": "MIT",
                        "stages": ["0-100"],
                        "source": "from-scratch",
                        "integration": "from-scratch",
                        "status": "built",
                    },
                    "other": {
                        "name": "other",
                        "description": "Other.",
                        "license": "MIT",
                        "stages": ["20-39"],
                        "source": "from-scratch",
                        "integration": "from-scratch",
                        "status": "built",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "skills" / "stages.json").write_text(
        json.dumps({"stages": {"orcinus": ["0-100"], "other": ["20-39"]}}),
        encoding="utf-8",
    )
    (root / "THIRD_PARTY_NOTICES.md").write_text(
        "| Skill | Upstream source | Licence | What was taken |\n|---|---|---|---|\n",
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
    (root / "README.md").write_text(
        "all 99 skills\nthe router and 1 focused sub-skills\n", encoding="utf-8"
    )
    failures = _run_with_root(monkeypatch, root, vr.check_skill_counts)
    assert len(failures) == 1 and "99" in failures[0]


def test_skill_counts_status_paragraph_must_match(tmp_path, monkeypatch):
    """Round 7 (F-14): the README Status paragraph's 'N focused
    sub-skills' is a counted claim too — 'focused sub-skill' means
    every skill except the router (folders − 1), verifier included.
    The old '34' (router + verifier + 34 = 36) used the term the
    other way and passed nothing, because no check read it."""
    root = _minimal_repo(tmp_path)
    readme = root / "README.md"
    readme.write_text("all 2 skills\nthe router and 1 focused sub-skills\n", encoding="utf-8")
    assert _run_with_root(monkeypatch, root, vr.check_skill_counts) == []
    readme.write_text(
        "all 2 skills\nthe router, the verifier, and 0 focused sub-skills\n",
        encoding="utf-8",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_skill_counts)
    assert len(failures) == 1 and "0" in failures[0]


def test_stage_ranges_cover_idea_and_finalize(tmp_path, monkeypatch):
    root = _minimal_repo(tmp_path)
    assert _run_with_root(monkeypatch, root, vr.check_stage_ranges) == []
    # Removing the Finalize range from the router must fail.
    router = root / "skills" / "orcinus" / "SKILL.md"
    text = router.read_text(encoding="utf-8")
    router.write_text(text.replace("- **Finalize (80–100):** x.\n", ""), encoding="utf-8")
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
        save(
            {
                "version": 1,
                "skills": {
                    "orcinus": {
                        "name": "orcinus",
                        "description": "Router.",
                        "license": "MIT",
                        "stages": ["0-100"],
                        "source": "from-scratch",
                        "integration": "from-scratch",
                        "status": "built",
                    },
                    "other": {
                        "name": "other",
                        "description": "Other.",
                        "license": "MIT",
                        "stages": ["20-39"],
                        "source": "from-scratch",
                        "integration": "from-scratch",
                        "status": "built",
                    },
                },
            }
        )

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
    data["skills"]["phantom"] = {
        "name": "phantom",
        "license": "MIT",
        "stages": ["20-39"],
        "source": "x",
        "status": "built",
    }
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


# --- Round-3 regression tests: the YAML subset parser. ---


def _parse_text(text, tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("---\n" + text + "---\n\nBody.\n", encoding="utf-8")
    fields, err = vr.parse_frontmatter(path)
    assert err is None, err
    return fields


def test_frontmatter_parser_matches_pyyaml_on_every_skill():
    """The subset parser must agree with a real YAML parser on every
    SKILL.md in the repo. This is the oracle test: if a frontmatter
    construct is added that the subset parser misreads, this fails
    here, not silently in the validator."""
    yaml = pytest.importorskip("yaml")
    for skill in sorted((vr.ROOT / "skills").iterdir()):
        if not skill.is_dir():
            continue
        text = (skill / "SKILL.md").read_text(encoding="utf-8")
        end = text.find("\n---\n", 4)
        expected = yaml.safe_load(text[4:end])
        fields, err = vr.parse_frontmatter(skill / "SKILL.md")
        assert err is None, f"{skill.name}: {err}"
        assert fields == expected, f"{skill.name}: {fields} != {expected}"


def test_frontmatter_folded_scalar(tmp_path):
    """The refactor skill uses `description: >`. The old hand-rolled
    parser returned the literal '>' as the description; the subset
    parser must return the folded text."""
    fields = _parse_text(
        "name: refactor\n"
        "description: >\n"
        "  Safe, behavior-preserving refactoring.\n"
        "  Applies patterns, runs tests per step.\n"
        "license: MIT\n",
        tmp_path,
    )
    assert fields["description"] == (
        "Safe, behavior-preserving refactoring. Applies patterns, runs tests per step.\n"
    )
    assert not fields["description"].startswith(">")


def test_frontmatter_quoted_and_commented_scalars(tmp_path):
    fields = _parse_text(
        'name: "database-designer" # the quoted name\n'
        "description: 'Design a schema: tables, indexes. It''s quoted.'\n"
        "# a full-line comment\n"
        "license: MIT\n",
        tmp_path,
    )
    assert fields["name"] == "database-designer"
    assert fields["description"] == ("Design a schema: tables, indexes. It's quoted.")
    assert fields["license"] == "MIT"


def test_frontmatter_nested_maps_lists_and_types(tmp_path):
    fields = _parse_text(
        "name: x\n"
        "description: X.\n"
        "license: MIT\n"
        "user-invocable: false\n"
        "metadata:\n"
        "  orcinus-role: sub-skill\n"
        "  hermes:\n"
        "    tags: [terminal, review]\n"
        "    category: software-development\n"
        "notes: |\n"
        "  line one\n"
        "  line two\n"
        "count: 3\n"
        "ratio: 1.5\n"
        "empty:\n",
        tmp_path,
    )
    assert fields["user-invocable"] is False
    assert fields["metadata"]["orcinus-role"] == "sub-skill"
    assert fields["metadata"]["hermes"]["tags"] == ["terminal", "review"]
    assert fields["metadata"]["hermes"]["category"] == "software-development"
    assert fields["notes"] == "line one\nline two\n"
    assert fields["count"] == 3
    assert fields["ratio"] == 1.5
    assert fields["empty"] is None


def test_frontmatter_rejects_bad_yaml(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: x\nthis line has no colon\n---\n\nBody.\n", encoding="utf-8")
    _fields, err = vr.parse_frontmatter(path)
    assert err is not None
    path.write_text('---\nname: "unterminated\n---\n\nBody.\n', encoding="utf-8")
    _fields, err = vr.parse_frontmatter(path)
    assert err is not None


# --- Round-3 regression tests: the manifest must agree with its
# sources (frontmatter, stages registry), not just with the folders. ---


def _manifest_with_root(monkeypatch, root):
    """Load the minimal repo's manifest as a dict for mutation."""
    path = root / "skills" / "manifest.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_manifest_description_must_match_frontmatter(tmp_path, monkeypatch):
    root = _minimal_repo(tmp_path)
    path, data = _manifest_with_root(monkeypatch, root)
    data["skills"]["other"]["description"] = "A different description."
    path.write_text(json.dumps(data), encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_manifest)
    assert any("description" in f and "other" in f for f in failures)


def test_manifest_source_trailing_comma_fails(tmp_path, monkeypatch):
    root = _minimal_repo(tmp_path)
    path, data = _manifest_with_root(monkeypatch, root)
    data["skills"]["other"]["source"] = "owner/repo,"
    path.write_text(json.dumps(data), encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_manifest)
    assert any("source" in f and "trailing comma" in f for f in failures)


def test_manifest_from_scratch_with_upstream_commit_fails(tmp_path, monkeypatch):
    root = _minimal_repo(tmp_path)
    path, data = _manifest_with_root(monkeypatch, root)
    data["skills"]["other"]["upstream_commit"] = "b" * 40
    path.write_text(json.dumps(data), encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_manifest)
    assert any("from-scratch" in f and "upstream_commit" in f for f in failures)


def test_manifest_stages_must_match_registry(tmp_path, monkeypatch):
    root = _minimal_repo(tmp_path)
    path, data = _manifest_with_root(monkeypatch, root)
    data["skills"]["other"]["stages"] = ["10-19"]
    path.write_text(json.dumps(data), encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_manifest)
    assert any("stages" in f and "other" in f for f in failures)


def test_manifest_license_spdx_expression(tmp_path, monkeypatch):
    """'MIT AND Apache-2.0' is a valid license expression; an unknown
    part is not."""
    assert vr._license_is_known("MIT")
    assert vr._license_is_known("MIT AND Apache-2.0")
    assert vr._license_is_known("MIT OR Apache-2.0")
    assert not vr._license_is_known("MIT AND Foo")
    assert not vr._license_is_known("")
    assert not vr._license_is_known(None)


def test_frontmatter_spec_limits(tmp_path, monkeypatch):
    """Agent Skills spec: name 1-64 chars with the pattern, description
    1-1024 chars. A 1025-char description and a bad name must fail."""
    root = _minimal_repo(tmp_path)
    other = root / "skills" / "other" / "SKILL.md"
    other.write_text(
        "---\nname: other\ndescription: " + "x" * 1025 + "\nlicense: MIT\n---\n\nBody.\n",
        encoding="utf-8",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_skill_frontmatter)
    assert any("1024" in f for f in failures)
    other.write_text(
        "---\nname: Other_Name\ndescription: Other.\nlicense: MIT\n---\n\nBody.\n",
        encoding="utf-8",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_skill_frontmatter)
    assert any("Other_Name" in f for f in failures)


# --- Third review round: regression tests (2026-11-06) ---


def _add_reference(root, skill, line):
    """Append one line naming a reference to a skill's SKILL.md."""
    path = root / "skills" / skill / "SKILL.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n" + line + "\n", encoding="utf-8")


def test_skill_reference_to_sibling_fails(tmp_path, monkeypatch):
    """A SKILL.md that links to a sibling skill's file dangles in a
    skill-only install — the file is not in this skill's folder."""
    root = _minimal_repo(tmp_path)
    _add_reference(root, "other", "See `../orcinus/SKILL.md`.")
    failures = _run_with_root(monkeypatch, root, vr.check_skill_references)
    assert failures, "a sibling reference must fail"
    assert "orcinus" in failures[0]


def test_skill_reference_to_missing_file_fails(tmp_path, monkeypatch):
    """A relative reference to a file that does not exist inside the
    skill folder fails — it only resolves nowhere."""
    root = _minimal_repo(tmp_path)
    _add_reference(root, "other", "See [guide](references/missing.md).")
    failures = _run_with_root(monkeypatch, root, vr.check_skill_references)
    assert failures, "a missing reference must fail"
    assert "missing.md" in failures[0]


def test_skill_reference_inside_folder_passes(tmp_path, monkeypatch):
    """A relative reference to a file that exists inside the skill
    folder passes — including with a #fragment, which names a section
    in the file, not another file."""
    root = _minimal_repo(tmp_path)
    (root / "skills" / "other" / "references").mkdir(parents=True)
    (root / "skills" / "other" / "references" / "guide.md").write_text(
        "# Guide\n", encoding="utf-8"
    )
    _add_reference(root, "other", "See [guide](references/guide.md#setup).")
    assert _run_with_root(monkeypatch, root, vr.check_skill_references) == []


def test_skill_reference_plugin_root_same_skill_passes(tmp_path, monkeypatch):
    """${CLAUDE_PLUGIN_ROOT}/skills/<same-skill>/... is self-contained:
    it resolves to this skill folder in a plugin install."""
    root = _minimal_repo(tmp_path)
    _add_reference(root, "other", "Run `${CLAUDE_PLUGIN_ROOT}/skills/other/scripts/x.py`.")
    assert _run_with_root(monkeypatch, root, vr.check_skill_references) == []


def test_skill_reference_plugin_root_other_skill_fails(tmp_path, monkeypatch):
    """${CLAUDE_PLUGIN_ROOT}/skills/<another-skill>/... is NOT this
    skill — it dangles in a skill-only install."""
    root = _minimal_repo(tmp_path)
    _add_reference(root, "other", "Run `${CLAUDE_PLUGIN_ROOT}/skills/orcinus/scripts/x.py`.")
    failures = _run_with_root(monkeypatch, root, vr.check_skill_references)
    assert failures, "another skill's plugin-root path must fail"


def test_skill_reference_user_project_path_passes(tmp_path, monkeypatch):
    """Paths in the user's project (docs/constitution.md, ideas/,
    evals/evals.json, ...) resolve where the skill runs, not where
    it is installed — they are not repo references."""
    root = _minimal_repo(tmp_path)
    _add_reference(root, "other", "Write `docs/constitution.md` first.")
    _add_reference(root, "other", "Ideas live in `ideas/`; verdicts in `evals/evals.json`.")
    assert _run_with_root(monkeypatch, root, vr.check_skill_references) == []


def test_skill_reference_bare_skill_name_passes(tmp_path, monkeypatch):
    """Naming another skill by its repo directory (`skills/orcinus`)
    is a skill reference the router resolves by name, not a file
    link — it passes. A file inside it does not."""
    root = _minimal_repo(tmp_path)
    _add_reference(root, "other", "Use `skills/orcinus` for routing.")
    assert _run_with_root(monkeypatch, root, vr.check_skill_references) == []
    _add_reference(root, "other", "See `skills/orcinus/SKILL.md`.")
    failures = _run_with_root(monkeypatch, root, vr.check_skill_references)
    assert failures, "a file inside another skill must fail"


def test_skill_reference_repo_evals_path_fails(tmp_path, monkeypatch):
    """A repo path such as `evals/waza-orcinus-verify/` only exists
    in a full-repo install — it fails, so the skill must name the
    example in prose instead."""
    root = _minimal_repo(tmp_path)
    _add_reference(root, "other", "The example is `evals/waza-orcinus-verify/`.")
    failures = _run_with_root(monkeypatch, root, vr.check_skill_references)
    assert failures, "a repo evals path must fail"


# --- Plugin components (round 3, track 8). ---


def _add_plugin_components(root, agents=None, commands=None):
    """Create the expected plugin-root agents/ and commands/ in a
    fixture repo. Each agent carries valid frontmatter (name ==
    filename, non-empty description)."""
    if agents is None:
        agents = vr.EXPECTED_AGENTS
    if commands is None:
        commands = vr.EXPECTED_COMMANDS
    (root / "agents").mkdir(exist_ok=True)
    for name in agents:
        (root / "agents" / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: Does {name} things.\n---\n\nBody.\n",
            encoding="utf-8",
        )
    (root / "commands").mkdir(exist_ok=True)
    for name in commands:
        (root / "commands" / f"{name}.md").write_text(
            f"---\ndescription: Runs {name}.\n---\n\nBody.\n",
            encoding="utf-8",
        )


def test_plugin_components_complete_passes(tmp_path, monkeypatch):
    """All expected agents and commands at the plugin root, no stale
    copies in the skill folders — the registration the plugin
    actually discovers."""
    root = _minimal_repo(tmp_path)
    _add_plugin_components(root)
    assert _run_with_root(monkeypatch, root, vr.check_plugin_components) == []


def test_plugin_components_missing_agent_fails(tmp_path, monkeypatch):
    """A missing agent file fails and names it — a skill that spawns
    it would invoke nothing."""
    root = _minimal_repo(tmp_path)
    _add_plugin_components(root)
    (root / "agents" / "code-reviewer.md").unlink()
    failures = _run_with_root(monkeypatch, root, vr.check_plugin_components)
    assert failures, "a missing agent must fail"
    assert "code-reviewer" in failures[0]


def test_plugin_components_missing_commands_fails(tmp_path, monkeypatch):
    """No commands/ directory at all fails — the review-pr command
    would not exist in the plugin."""
    root = _minimal_repo(tmp_path)
    _add_plugin_components(root, commands=[])
    failures = _run_with_root(monkeypatch, root, vr.check_plugin_components)
    assert failures, "a missing command must fail"
    assert "review-pr" in failures[0]


def test_plugin_components_stale_copy_fails(tmp_path, monkeypatch):
    """A copy left inside the skill folder fails — Claude Code does
    not register agents/commands nested under a skill, so the stale
    copy is dead weight that invites editing the wrong file."""
    root = _minimal_repo(tmp_path)
    _add_plugin_components(root)
    stale = root / "skills" / "other" / "agents"
    stale.mkdir()
    (stale / "code-reviewer.md").write_text("stale\n", encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_plugin_components)
    assert failures, "a stale agent copy must fail"
    assert "stale" in failures[0]


def test_plugin_components_agent_name_must_match_filename(tmp_path, monkeypatch):
    """An agent whose frontmatter name differs from its filename
    fails — Claude Code registers the agent by that name, so a
    mismatch means the skill spawns a name that does not exist."""
    root = _minimal_repo(tmp_path)
    _add_plugin_components(root)
    (root / "agents" / "grader.md").write_text(
        "---\nname: wrong-name\ndescription: Does grader things.\n---\n\nBody.\n",
        encoding="utf-8",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_plugin_components)
    assert failures, "a mismatched agent name must fail"
    assert "grader" in failures[0]


def test_plugin_components_agent_needs_description(tmp_path, monkeypatch):
    """An agent without a description fails — description is what
    Claude Code uses to route invocations to the agent."""
    root = _minimal_repo(tmp_path)
    _add_plugin_components(root)
    (root / "agents" / "analyzer.md").write_text(
        "---\nname: analyzer\n---\n\nBody.\n",
        encoding="utf-8",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_plugin_components)
    assert failures, "an agent without a description must fail"
    assert "analyzer" in failures[0]


# --- Version consistency (round 3, track 9). ---


def test_version_matches_changelog_passes(tmp_path, monkeypatch):
    """plugin.json version == the latest ## [x.y.z] heading in
    CHANGELOG.md — the version bump and the changelog entry travel
    together."""
    root = _minimal_repo(tmp_path)
    assert _run_with_root(monkeypatch, root, vr.check_version_matches_changelog) == []


def test_version_mismatch_fails(tmp_path, monkeypatch):
    """A plugin.json version that differs from the changelog's latest
    release fails and names both versions — one of the two was
    bumped without the other."""
    root = _minimal_repo(tmp_path)
    plugin = root / ".claude-plugin" / "plugin.json"
    data = json.loads(plugin.read_text(encoding="utf-8"))
    data["version"] = "0.9.1"
    plugin.write_text(json.dumps(data), encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_version_matches_changelog)
    assert failures, "a version mismatch must fail"
    assert "0.9.1" in failures[0] and "1.0.0" in failures[0]


def test_version_missing_changelog_fails(tmp_path, monkeypatch):
    """No CHANGELOG.md at all fails — the version cannot be checked
    against a missing release record."""
    root = _minimal_repo(tmp_path)
    (root / "CHANGELOG.md").unlink()
    failures = _run_with_root(monkeypatch, root, vr.check_version_matches_changelog)
    assert failures, "a missing CHANGELOG.md must fail"


def test_version_missing_heading_fails(tmp_path, monkeypatch):
    """A CHANGELOG.md with no ## [x.y.z] heading fails — there is no
    latest release to compare the version against."""
    root = _minimal_repo(tmp_path)
    (root / "CHANGELOG.md").write_text("# Changelog\n\nNo releases yet.\n", encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_version_matches_changelog)
    assert failures, "a CHANGELOG.md without a release heading must fail"


# --- user-invocable (round 3, track 10). ---


def _rewrite_skill(root, skill, frontmatter):
    """Replace a fixture skill's frontmatter with the given lines."""
    path = root / "skills" / skill / "SKILL.md"
    path.write_text("---\n" + frontmatter + "---\n\nBody.\n", encoding="utf-8")


def test_subskill_without_user_invocable_fails(tmp_path, monkeypatch):
    """Every sub-skill must carry user-invocable: false — the user
    invokes only the router; a sub-skill without the field would
    appear in the / menu and invite picking it mid-work."""
    root = _minimal_repo(tmp_path)
    _rewrite_skill(root, "other", "name: other\ndescription: Other.\nlicense: MIT\n")
    failures = _run_with_root(monkeypatch, root, vr.check_skill_frontmatter)
    assert failures, "a sub-skill without user-invocable must fail"
    assert any("user-invocable" in f for f in failures)


def test_subskill_user_invocable_true_fails(tmp_path, monkeypatch):
    """user-invocable: true on a sub-skill fails — only the router
    is a user entry point."""
    root = _minimal_repo(tmp_path)
    _rewrite_skill(
        root, "other", "name: other\ndescription: Other.\nlicense: MIT\nuser-invocable: true\n"
    )
    failures = _run_with_root(monkeypatch, root, vr.check_skill_frontmatter)
    assert failures, "user-invocable: true on a sub-skill must fail"


def test_subskill_user_invocable_string_fails(tmp_path, monkeypatch):
    """user-invocable: "false" (a string) fails — the field must be
    a real boolean false, not the word false."""
    root = _minimal_repo(tmp_path)
    _rewrite_skill(
        root, "other", 'name: other\ndescription: Other.\nlicense: MIT\nuser-invocable: "false"\n'
    )
    failures = _run_with_root(monkeypatch, root, vr.check_skill_frontmatter)
    assert failures, "a string user-invocable must fail"
    assert any("user-invocable" in f for f in failures)


def test_router_must_stay_user_invocable(tmp_path, monkeypatch):
    """The router with user-invocable: false fails — hiding the one
    entry point would leave the user no way to invoke ORCINUS."""
    root = _minimal_repo(tmp_path)
    _rewrite_skill(
        root,
        "orcinus",
        "name: orcinus\ndescription: Router.\nlicense: MIT\nuser-invocable: false\n",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_skill_frontmatter)
    assert failures, "a hidden router must fail"
    assert any("orcinus" in f and "user-invocable" in f for f in failures)


def test_disable_model_invocation_true_fails(tmp_path, monkeypatch):
    """disable-model-invocation: true on any skill fails — the router
    invokes sub-skills itself, so blocking model invocation would
    break routing (upstream monitoring-observability ships this
    value; ORCINUS removed it for exactly this reason)."""
    root = _minimal_repo(tmp_path)
    _rewrite_skill(
        root,
        "other",
        "name: other\ndescription: Other.\nlicense: MIT\n"
        "user-invocable: false\n"
        "disable-model-invocation: true\n",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_skill_frontmatter)
    assert failures, "disable-model-invocation: true must fail"
    assert any("disable-model-invocation" in f for f in failures)


def test_router_and_subskill_frontmatter_passes(tmp_path, monkeypatch):
    """The fixture as built — router with no user-invocable field,
    sub-skill with user-invocable: false — passes frontmatter."""
    root = _minimal_repo(tmp_path)
    assert _run_with_root(monkeypatch, root, vr.check_skill_frontmatter) == []


# --- Plugin validate guards (round 3, track 11). ---


def test_marketplace_description_missing_fails(tmp_path, monkeypatch):
    """A marketplace.json without a description fails — `claude
    plugin validate --strict` warns on it, and the description is
    what users see when they add the marketplace."""
    root = _minimal_repo(tmp_path)
    market = root / ".claude-plugin" / "marketplace.json"
    data = json.loads(market.read_text(encoding="utf-8"))
    del data["description"]
    market.write_text(json.dumps(data), encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_plugin_manifests)
    assert failures, "a missing marketplace description must fail"
    assert any("description" in f for f in failures)


def test_plugin_icon_missing_fails(tmp_path, monkeypatch):
    """A missing .claude-plugin/icon.png fails — `claude plugin
    validate --strict` fails without it (ICON_MISSING)."""
    root = _minimal_repo(tmp_path)
    (root / ".claude-plugin" / "icon.png").unlink()
    failures = _run_with_root(monkeypatch, root, vr.check_plugin_manifests)
    assert failures, "a missing plugin icon must fail"
    assert any("icon.png" in f for f in failures)


# --- Hermes bundle (round 3, track 12). ---


def _add_hermes_bundle(
    root, skills=("orcinus",), name="orcinus", description="One integrated companion."
):
    """Create hermes/orcinus.yaml in a fixture repo. The bundle lists
    the router only: a bundle loads everything it lists at once, so
    the router loads sub-skills on demand."""
    (root / "hermes").mkdir(exist_ok=True)
    text = f"name: {name}\n"
    if description is not None:
        text += f"description: {description}\n"
    text += "skills:\n"
    for skill in skills:
        text += f"  - {skill}\n"
    text += "instruction: |\n  Load a sub-skill with skill_view(name).\n"
    (root / "hermes" / "orcinus.yaml").write_text(text, encoding="utf-8")


def test_hermes_bundle_router_only_passes(tmp_path, monkeypatch):
    """A bundle listing only the router passes — the router loads
    sub-skills on demand."""
    root = _minimal_repo(tmp_path)
    _add_hermes_bundle(root)
    assert _run_with_root(monkeypatch, root, vr.check_hermes_bundle) == []


def test_hermes_bundle_missing_file_fails(tmp_path, monkeypatch):
    """No hermes/orcinus.yaml fails — Hermes users would have no
    bundle entry point."""
    root = _minimal_repo(tmp_path)
    failures = _run_with_root(monkeypatch, root, vr.check_hermes_bundle)
    assert failures, "a missing Hermes bundle must fail"
    assert any("hermes/orcinus.yaml" in f for f in failures)


def test_hermes_bundle_unknown_skill_fails(tmp_path, monkeypatch):
    """A listed skill with no folder fails — Hermes silently skips
    missing bundle skills, so a stale name would fail silently at
    runtime instead of at validation time."""
    root = _minimal_repo(tmp_path)
    _add_hermes_bundle(root, skills=("orcinus", "phantom"))
    failures = _run_with_root(monkeypatch, root, vr.check_hermes_bundle)
    assert failures, "an unknown bundle skill must fail"
    assert any("phantom" in f for f in failures)


def test_hermes_bundle_without_router_fails(tmp_path, monkeypatch):
    """A bundle without the router fails — it has no entry point."""
    root = _minimal_repo(tmp_path)
    _add_hermes_bundle(root, skills=("other",))
    failures = _run_with_root(monkeypatch, root, vr.check_hermes_bundle)
    assert failures, "a bundle without the router must fail"
    assert any("orcinus" in f for f in failures)


def test_hermes_bundle_lists_subskill_directly_fails(tmp_path, monkeypatch):
    """A bundle listing a sub-skill directly fails — this bundle is
    the entry point; the router loads sub-skills on demand. A bundle
    that listed all 36 skills would dump the whole collection into
    one message."""
    root = _minimal_repo(tmp_path)
    _add_hermes_bundle(root, skills=("orcinus", "other"))
    failures = _run_with_root(monkeypatch, root, vr.check_hermes_bundle)
    assert failures, "a bundle listing a sub-skill must fail"
    assert any("other" in f for f in failures)


def test_hermes_bundle_empty_skills_fails(tmp_path, monkeypatch):
    """An empty skills list fails — Hermes requires a non-empty list."""
    root = _minimal_repo(tmp_path)
    (root / "hermes").mkdir(exist_ok=True)
    (root / "hermes" / "orcinus.yaml").write_text(
        "name: orcinus\ndescription: Entry point.\nskills: []\n",
        encoding="utf-8",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_hermes_bundle)
    assert failures, "an empty bundle skills list must fail"
    assert any("non-empty" in f for f in failures)


def test_hermes_bundle_name_must_match_stem(tmp_path, monkeypatch):
    """A bundle name that differs from the filename stem fails —
    Hermes normalizes the name to the slash-command slug, so a
    mismatch means /orcinus would not invoke this bundle."""
    root = _minimal_repo(tmp_path)
    _add_hermes_bundle(root, name="wrong-name")
    failures = _run_with_root(monkeypatch, root, vr.check_hermes_bundle)
    assert failures, "a mismatched bundle name must fail"
    assert any("wrong-name" in f for f in failures)


def test_hermes_bundle_unparsable_fails(tmp_path, monkeypatch):
    """Unparsable bundle YAML fails loudly instead of being read as
    an empty bundle."""
    root = _minimal_repo(tmp_path)
    (root / "hermes").mkdir(exist_ok=True)
    (root / "hermes" / "orcinus.yaml").write_text("name: [unclosed\nskills: [\n", encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_hermes_bundle)
    assert failures, "unparsable bundle YAML must fail"
    assert any("unparsable" in f for f in failures)


# --- Round-4 regression tests: the manifest integration field. ---


def test_manifest_integration_must_be_known(tmp_path, monkeypatch):
    root = _minimal_repo(tmp_path)
    path, data = _manifest_with_root(monkeypatch, root)
    data["skills"]["other"]["integration"] = "copied"
    path.write_text(json.dumps(data), encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_manifest)
    assert any("integration" in f and "other" in f for f in failures)


def test_manifest_integration_missing_fails(tmp_path, monkeypatch):
    root = _minimal_repo(tmp_path)
    path, data = _manifest_with_root(monkeypatch, root)
    del data["skills"]["other"]["integration"]
    path.write_text(json.dumps(data), encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_manifest)
    assert any("integration" in f for f in failures)


def test_manifest_verbatim_without_commit_fails(tmp_path, monkeypatch):
    root = _minimal_repo(tmp_path)
    path, data = _manifest_with_root(monkeypatch, root)
    e = data["skills"]["other"]
    e["integration"] = "verbatim"
    e["source"] = "https://github.com/example/repo"
    e["upstream_commit"] = None
    path.write_text(json.dumps(data), encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_manifest)
    assert any("upstream_commit" in f and "other" in f for f in failures)


def test_manifest_wrapper_with_commit_passes(tmp_path, monkeypatch):
    root = _minimal_repo(tmp_path)
    path, data = _manifest_with_root(monkeypatch, root)
    e = data["skills"]["other"]
    e["integration"] = "wrapper"
    e["source"] = "https://github.com/example/repo"
    e["upstream_commit"] = "a" * 40
    path.write_text(json.dumps(data), encoding="utf-8")
    assert _run_with_root(monkeypatch, root, vr.check_manifest) == []


def test_manifest_owner_repo_source_fails(tmp_path, monkeypatch):
    # owner/repo is no longer accepted: the source is a full URL or
    # "from-scratch", so a consumer never has to guess the host.
    root = _minimal_repo(tmp_path)
    path, data = _manifest_with_root(monkeypatch, root)
    e = data["skills"]["other"]
    e["integration"] = "verbatim"
    e["source"] = "example/repo"
    e["upstream_commit"] = "a" * 40
    path.write_text(json.dumps(data), encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_manifest)
    assert any("source" in f and "other" in f for f in failures)


def test_manifest_from_scratch_with_url_source_fails(tmp_path, monkeypatch):
    root = _minimal_repo(tmp_path)
    path, data = _manifest_with_root(monkeypatch, root)
    e = data["skills"]["other"]
    e["integration"] = "from-scratch"
    e["source"] = "https://github.com/example/repo"
    path.write_text(json.dumps(data), encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_manifest)
    assert any("from-scratch" in f and "source" in f for f in failures)


def test_manifest_short_commit_fails(tmp_path, monkeypatch):
    root = _minimal_repo(tmp_path)
    path, data = _manifest_with_root(monkeypatch, root)
    e = data["skills"]["other"]
    e["integration"] = "verbatim"
    e["source"] = "https://github.com/example/repo"
    e["upstream_commit"] = "abc123"
    path.write_text(json.dumps(data), encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_manifest)
    assert any("upstream_commit" in f for f in failures)


# --- Round-4 regression tests: frontend descriptions are short. ---


def test_frontend_descriptions_are_short():
    """The three frontend skills are React/React Native-scoped, and
    their trigger conditions live in the router's rules.md, not in
    their descriptions. A description that grows the trigger list
    back in is a regression: on non-Claude-Code hosts the
    description is the only discovery signal, so it must say what
    the skill is and what it applies to — nothing more."""
    for name in (
        "frontend-architecture",
        "frontend-optimistic-mutations",
        "frontend-data-contracts",
    ):
        fields, err = vr.parse_frontmatter(vr.ROOT / "skills" / name / "SKILL.md")
        assert err is None, f"{name}: {err}"
        desc = fields["description"]
        assert "React" in desc, f"{name}: description must name its scope"
        assert "Use this skill when" not in desc, f"{name}: trigger conditions belong in rules.md"
        assert len(desc) < 400, f"{name}: description is {len(desc)} chars, expected < 400"


def test_manifest_supported_frameworks_shape(tmp_path, monkeypatch):
    root = _minimal_repo(tmp_path)
    path, data = _manifest_with_root(monkeypatch, root)
    data["skills"]["other"]["supported_frameworks"] = "React"
    path.write_text(json.dumps(data), encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_manifest)
    assert any("supported_frameworks" in f for f in failures)
    path, data = _manifest_with_root(monkeypatch, root)
    data["skills"]["other"]["supported_frameworks"] = ["React"]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert _run_with_root(monkeypatch, root, vr.check_manifest) == []


# --- SECURITY.md supported versions (round 4, track 6). ---


def _rewrite_security(root, yes_row):
    (root / "SECURITY.md").write_text(
        "# Security Policy\n\n## Supported Versions\n\n"
        "| Version | Supported |\n| ------- | --------- |\n"
        f"| {yes_row} | Yes |\n"
        "| < 1.0 | No (no release was cut before 1.0.0) |\n",
        encoding="utf-8",
    )


def test_security_versions_passes(tmp_path, monkeypatch):
    """The SECURITY.md Yes row (1.0.x) matches plugin.json 1.0.0."""
    root = _minimal_repo(tmp_path)
    assert _run_with_root(monkeypatch, root, vr.check_security_versions) == []


def test_security_versions_mismatch_fails(tmp_path, monkeypatch):
    """SECURITY.md said 1.0.x while the plugin was 0.9.0 in the real
    repo: a user reading it would conclude 0.9.0 is unsupported. The
    Yes row must match the plugin's major.minor."""
    root = _minimal_repo(tmp_path)
    _rewrite_security(root, "0.9.x")
    failures = _run_with_root(monkeypatch, root, vr.check_security_versions)
    assert failures, "a Yes row for another version must fail"
    assert "0.9.x" in failures[0] and "1.0.0" in failures[0]


def test_security_versions_missing_fails(tmp_path, monkeypatch):
    """No SECURITY.md at all fails — the supported versions cannot
    be checked against a missing policy."""
    root = _minimal_repo(tmp_path)
    (root / "SECURITY.md").unlink()
    failures = _run_with_root(monkeypatch, root, vr.check_security_versions)
    assert failures, "a missing SECURITY.md must fail"


# --- Round 5, T5: router self-containment (R3 #7 / F3) ---


def _router_resources_repo(tmp_path):
    """A minimal repo with the router resources generated from its MAP."""
    root = _minimal_repo(tmp_path)
    (root / "scripts").mkdir()
    repo_root = Path(__file__).resolve().parent.parent
    (root / "scripts" / "generate_router_resources.py").write_bytes(
        (repo_root / "scripts" / "generate_router_resources.py").read_bytes()
    )
    (root / "docs" / "project-state.md").write_text("# State\n", encoding="utf-8")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import generate_router_resources as grr

    grr.write_router_resources(root)
    return root


def test_router_resources_pass(tmp_path, monkeypatch):
    root = _router_resources_repo(tmp_path)
    assert _run_with_root(monkeypatch, root, vr.check_router_resources) == []


def test_router_resources_stale_status_fails(tmp_path, monkeypatch):
    # A MAP change without regenerating must fail: the bundled status
    # table is the router's decision table in a standalone install,
    # so a stale copy misclassifies skills.
    root = _router_resources_repo(tmp_path)
    map_file = root / "docs" / "MAP.md"
    map_file.write_text(
        map_file.read_text(encoding="utf-8") + "| New step | some-skill | MIT | copy | todo |\n",
        encoding="utf-8",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_router_resources)
    assert any("skill-status.md" in f for f in failures)


def test_router_resources_missing_status_fails(tmp_path, monkeypatch):
    root = _router_resources_repo(tmp_path)
    (root / "skills" / "orcinus" / "references" / "skill-status.md").unlink()
    failures = _run_with_root(monkeypatch, root, vr.check_router_resources)
    assert any("skill-status.md" in f for f in failures)


def test_router_resources_missing_project_state_fails(tmp_path, monkeypatch):
    root = _router_resources_repo(tmp_path)
    (root / "skills" / "orcinus" / "references" / "project-state.md").unlink()
    failures = _run_with_root(monkeypatch, root, vr.check_router_resources)
    assert any("project-state.md" in f for f in failures)


def test_router_resources_diverged_project_state_fails(tmp_path, monkeypatch):
    # The bundled state spec must be a byte-identical copy of the
    # canonical spec — a divergent copy makes two sessions disagree
    # about what VERIFIED means.
    root = _router_resources_repo(tmp_path)
    bundled = root / "skills" / "orcinus" / "references" / "project-state.md"
    bundled.write_text("# State\n\nEdited.\n", encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_router_resources)
    assert any("project-state.md" in f for f in failures)


def test_router_resources_missing_generator_fails(tmp_path, monkeypatch):
    # The check cannot run without its generator — that is a failure,
    # never a silent pass.
    root = _minimal_repo(tmp_path)
    (root / "docs" / "project-state.md").write_text("# State\n", encoding="utf-8")
    failures = _run_with_root(monkeypatch, root, vr.check_router_resources)
    assert any("generate_router_resources.py" in f for f in failures)


# --- Round 5, T8: licences + wording (R3 #8, #9, #10, #12, #13) ---

REPO_ROOT = Path(__file__).resolve().parent.parent

ROUTER_SENTENCE = "Only invoke via the orcinus router."


def _manifest():
    return json.loads((REPO_ROOT / "skills" / "manifest.json").read_text(encoding="utf-8"))


def _frontmatter_description(skill):
    fields, _ = vr.parse_frontmatter(REPO_ROOT / "skills" / skill / "SKILL.md")
    return fields["description"]


def test_router_description_is_narrow():
    """The router must trigger on the user asking for the ORCINUS
    lifecycle / stage — not on any coding conversation (R3 #13)."""
    desc = _frontmatter_description("orcinus")
    assert "ORCINUS lifecycle" in desc
    assert "any software project" not in desc


def test_i18n_description_has_no_slash_command():
    """Sub-skills are user-invocable: false, so no description may
    tell the user to type /<skill> (R3 #9)."""
    desc = _frontmatter_description("i18n")
    assert "/i18n" not in desc


def test_no_slash_invocation_in_subskill_descriptions(tmp_path, monkeypatch):
    """A sub-skill description that instructs a slash invocation
    must fail the validator check."""
    root = _minimal_repo(tmp_path)
    assert _run_with_root(monkeypatch, root, vr.check_no_slash_invocation) == []
    other = root / "skills" / "other" / "SKILL.md"
    other.write_text(
        other.read_text(encoding="utf-8").replace(
            "description: Other.", "description: Other. Use when the user types /other."
        ),
        encoding="utf-8",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_no_slash_invocation)
    assert any("/other" in f for f in failures)


def _stages_repo(tmp_path, stages):
    root = _minimal_repo(tmp_path)
    (root / "skills" / "stages.json").write_text(
        json.dumps({"note": "test", "stages": stages}), encoding="utf-8"
    )
    return root


def _write_stages(root, stages):
    (root / "skills" / "stages.json").write_text(
        json.dumps({"note": "test", "stages": stages}), encoding="utf-8"
    )


def test_stage_containment(tmp_path, monkeypatch):
    """Every coarse stages.json range is built from the router's fine
    ranges, and each fine stage's primary skill contains that stage
    (R3 #10)."""
    stages = {
        "idea-capture": ["0-9"],
        "idea-calibrate": ["0-9"],
        "architecture": ["10-19"],
        "scaffold": ["20-39"],
        "build": ["20-39"],
        "orcinus-verify": ["40-59"],
        "security-review": ["50-79"],
        "diagnosing-bugs": ["50-79"],
        "refactor": ["50-79"],
        "incomplete-refactor": ["50-79"],
        "finalize": ["80-100"],
    }
    root = _stages_repo(tmp_path, stages)
    assert _run_with_root(monkeypatch, root, vr.check_stage_containment) == []
    # A coarse range that no longer contains its fine stage fails.
    stages["build"] = ["20-29"]
    _write_stages(root, stages)
    failures = _run_with_root(monkeypatch, root, vr.check_stage_containment)
    assert any("build" in f and "30–39" in f for f in failures)
    # A coarse range that starts or ends mid-stage fails too.
    stages["build"] = ["20-39"]
    stages["scaffold"] = ["20-35"]
    _write_stages(root, stages)
    failures = _run_with_root(monkeypatch, root, vr.check_stage_containment)
    assert any("scaffold" in f for f in failures)


def test_stage_containment_passes_on_real_repo(monkeypatch):
    monkeypatch.setattr(vr, "ROOT", REPO_ROOT)
    vr.failures.clear()
    vr.check_stage_containment()
    assert list(vr.failures) == []


def test_apache_change_notices():
    """Every modified Apache-2.0 file carries its ORCINUS change
    notice in the file itself (Apache-2.0 §4(b), R3 #8)."""
    modified = [
        "skills/mcp-builder/SKILL.md",
        "skills/skill-creator/SKILL.md",
        "skills/skill-creator/scripts/package_skill.py",
        "skills/skill-creator/scripts/quick_validate.py",
        "skills/skill-creator/scripts/run_eval.py",
        "skills/webapp-testing/SKILL.md",
        "skills/webapp-testing/scripts/with_server.py",
        "agents/analyzer.md",
        "agents/comparator.md",
        "agents/grader.md",
    ]
    for rel in modified:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "ORCINUS change notice" in text, f"{rel} has no change notice"


def test_router_note_recorded_in_attribution():
    """Every vendored description that carries the ORCINUS router
    sentence must record the append in its ATTRIBUTION.md — a
    'description verbatim' claim next to that sentence is false
    (R3 #8)."""
    manifest = _manifest()
    for name, skill in sorted(manifest["skills"].items()):
        if skill.get("integration") != "verbatim":
            continue
        if not skill["description"].endswith(ROUTER_SENTENCE):
            continue
        attribution = (REPO_ROOT / "skills" / name / "ATTRIBUTION.md").read_text(encoding="utf-8")
        assert "router-only note" in attribution or "router sentence" in attribution, (
            f"{name}/ATTRIBUTION.md does not record the router-sentence append"
        )


def test_orcinus_verify_uses_relative_validator_path():
    """The validator is invoked by a path relative to the skill
    folder, not ${CLAUDE_PLUGIN_ROOT} — the host may not substitute
    the variable inside skill text (R3 #12)."""
    text = (REPO_ROOT / "skills" / "orcinus-verify" / "SKILL.md").read_text(encoding="utf-8")
    assert "python3 scripts/validate_evidence.py" in text
    assert "${CLAUDE_PLUGIN_ROOT}/skills/orcinus-verify/scripts/validate_evidence.py" not in text


# --- Round 5, T10: README skill table parity (R3 #20) ---


def _readme_table_repo(tmp_path):
    """A minimal repo whose README carries a generated skill table."""
    root = _minimal_repo(tmp_path)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import generate_readme_table as grt

    (root / "scripts").mkdir(exist_ok=True)
    repo_root = Path(__file__).resolve().parent.parent
    (root / "scripts" / "generate_readme_table.py").write_bytes(
        (repo_root / "scripts" / "generate_readme_table.py").read_bytes()
    )
    manifest = json.loads((root / "skills" / "manifest.json").read_text())
    table = grt.build_skill_table(manifest, root / "skills")
    (root / "README.md").write_text(
        "# Test\n\n" + grt.BEGIN + "\n" + table + grt.END + "\n", encoding="utf-8"
    )
    return root


def test_readme_skill_table_passes(tmp_path, monkeypatch):
    root = _readme_table_repo(tmp_path)
    assert _run_with_root(monkeypatch, root, vr.check_readme_skill_table) == []


def test_readme_skill_table_stale_fails(tmp_path, monkeypatch):
    root = _readme_table_repo(tmp_path)
    readme = root / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            "| [orcinus](skills/orcinus) |", "| [orcinus](skills/orcinus) | 0-100 |"
        ),
        encoding="utf-8",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_readme_skill_table)
    assert any("skill table" in f for f in failures)


def test_readme_skill_table_missing_markers_fails(tmp_path, monkeypatch):
    root = _minimal_repo(tmp_path)
    failures = _run_with_root(monkeypatch, root, vr.check_readme_skill_table)
    assert any("skill table" in f for f in failures)


# --- Round-6 track 5: router (R1-R4, R6-R8, 2-R1, 2-R2, 2-R5) ---


def _router_text():
    return (vr.ROOT / "skills" / "orcinus" / "SKILL.md").read_text(encoding="utf-8")


def _routing_table_text():
    """The router's routing table only (between '## Routing' and the
    next '## ' heading) — so a mention elsewhere in the skill cannot
    stand in for a routing row."""
    text = _router_text()
    start = text.index("## Routing")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def test_issue_triage_has_fa_branch():
    """R1: the router tells the agent to pass `fa`, so issue-triage
    must have a Persian branch — otherwise `fa` falls through to the
    French default (the actual user's language)."""
    skill = (vr.ROOT / "skills" / "issue-triage" / "SKILL.md").read_text(encoding="utf-8")
    fields, err = vr.parse_frontmatter(vr.ROOT / "skills" / "issue-triage" / "SKILL.md")
    assert err is None, err
    assert "'fa'" in fields["description"]
    lang = skill[skill.index("## Language") : skill.index("## Configuration")]
    assert "`fa`" in lang and "Persian" in lang
    assert "farsi" in lang.lower() or "persian" in lang.lower()


def test_monitoring_description_names_real_skill():
    """R2: monitoring's description must not name `observability` —
    no such skill exists. The telemetry skill is
    `monitoring-observability`."""
    fields, err = vr.parse_frontmatter(vr.ROOT / "skills" / "monitoring" / "SKILL.md")
    assert err is None, err
    assert "`observability`" not in fields["description"]
    assert "`monitoring-observability`" in fields["description"]


def test_router_routing_table_has_monitoring_observability():
    """R3 / 2-R3: monitoring-observability needs a row in the router's
    routing table, not just prose in rules.md."""
    assert "monitoring-observability" in _routing_table_text()


def test_skill_status_has_implemented_in_column(monkeypatch):
    """R4 / 2-R4: skill-status.md must say which ORCINUS skill covers
    each need — the Best source is the inspiration, not an installed
    skill. A `built` row whose Implemented in names no real folder
    (e.g. 'stack-selector: built', 'improve: built') misleads the
    router into invoking something that is not there."""
    status = (vr.ROOT / "skills" / "orcinus" / "references" / "skill-status.md").read_text(
        encoding="utf-8"
    )
    assert "| Need | Best source | Implemented in | Status |" in status
    assert (
        "| Stack choice | stack-selector (lysandre001/skills-registry) | architecture | built |"
        in status
    )
    assert (
        "| Scope v1 / non-goals | improve (installed, advisor-only) | idea-calibrate | built |"
        in status
    )
    # The new validator check enforces this on every row.
    assert _run_with_root(monkeypatch, vr.ROOT, vr.check_skill_status_implemented_in) == []


def test_pass_with_limitations_mapping():
    """R6: security-review's PASS WITH LIMITATIONS is not in the
    evidence schema's verdict enum, so the mapping must be stated
    where the verdict is consumed: waived-with-reason maps to PASS,
    otherwise to INCOMPLETE (not a blanket rule either way). The
    schema itself gains no fourth verdict."""
    schema = json.loads(
        (vr.ROOT / "skills" / "orcinus-verify" / "references" / "evidence.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema["properties"]["verdict"]["enum"] == ["PASS", "FAIL", "INCOMPLETE"]
    for path in (
        vr.ROOT / "skills" / "security-review" / "SKILL.md",
        vr.ROOT / "skills" / "orcinus-verify" / "SKILL.md",
        vr.ROOT / "skills" / "orcinus" / "SKILL.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert "PASS WITH LIMITATIONS" in text, path
        assert "waived" in text and "INCOMPLETE" in text, path


def test_router_host_incompatibility_is_general():
    """R7 (PARTIAL): the router's host-incompatibility row must cover
    any install other than the Claude Code plugin — plugin-root
    agents/ and commands/ and per-skill scripts/ do not travel there
    — not Hermes alone. The README states the same beyond Hermes."""
    table = _router_text()
    table = table[table.index("## When a sub-skill is missing") :]
    table = table[: table.index("\n## ", 1)]
    assert "Host-incompatible" in table
    row = [line for line in table.splitlines() if "Host-incompatible" in line]
    assert len(row) == 1
    assert "any install other than the Claude Code plugin" in row[0]
    assert "agents/" in row[0] and "commands/" in row[0]
    readme = (vr.ROOT / "README.md").read_text(encoding="utf-8")
    assert "any install other than the Claude Code plugin" in readme


def test_waza_i18n_descriptions_short_and_router_only_is_honest():
    """R8: the two longest descriptions (waza, i18n) must come down
    toward the ~287-char median, waza must not contradict the
    router-only rule in its own description, and the README must say
    plainly that 'Only invoke via the orcinus router' is unenforced
    prose — user-invocable: false hides a sub-skill from the / menu,
    it does not stop the model invoking it directly."""
    for name, limit in (("waza", 350), ("i18n", 350)):
        fields, err = vr.parse_frontmatter(vr.ROOT / "skills" / name / "SKILL.md")
        assert err is None, err
        assert len(fields["description"]) <= limit, (name, len(fields["description"]))
    waza, _ = vr.parse_frontmatter(vr.ROOT / "skills" / "waza" / "SKILL.md")
    assert "use waza run directly" not in waza["description"]
    readme = (vr.ROOT / "README.md").read_text(encoding="utf-8")
    assert "Only invoke via the orcinus router" in readme
    assert "does not stop the model" in readme


def test_frontmatter_rejects_unquoted_colon_space(tmp_path):
    """2-R5 (PARTIAL): the subset parser must agree with PyYAML that
    an unquoted plain scalar cannot contain ': ' — `description: Use
    when: ...` is a ScannerError in real YAML. The differential test
    already exists; this fixes the parser itself."""
    path = tmp_path / "SKILL.md"
    path.write_text(
        "---\nname: x\ndescription: Use when: building a thing\nlicense: MIT\n---\n\nBody.\n",
        encoding="utf-8",
    )
    fields, err = vr.parse_frontmatter(path)
    assert fields is None and err is not None, "unquoted ': ' must be rejected like PyYAML"
    # Quoted scalars may still contain ': ', and a colon without a
    # following space is still a plain scalar (e.g. a URL).
    fields = _parse_text(
        'name: x\ndescription: "Use when: building a thing"\nlicense: MIT\n', tmp_path
    )
    assert fields["description"] == "Use when: building a thing"
    fields = _parse_text(
        "name: x\ndescription: See https://example.com/docs\nlicense: MIT\n", tmp_path
    )
    assert fields["description"] == "See https://example.com/docs"


# --- Round 6 (2026-11-07): Rec3 — the docs agree with each other
# and with the repo. The README honesty paragraph, SCOPE.md's
# "scored eval" claims, the orcinus-verify verdict example, and the
# mock verify-pass task all stated numbers that nothing checked. ---


def _docs_numbers_repo(tmp_path):
    """A fake repo with 2 skills, 1 scenario eval, and a demo with
    2 tests — all the numbers consistent, so the check passes."""
    root = tmp_path / "repo"
    (root / "skills" / "alpha").mkdir(parents=True)
    (root / "skills" / "beta").mkdir(parents=True)
    (root / "evals").mkdir()
    (root / "examples" / "demo" / "tests").mkdir(parents=True)
    (root / "evals" / "waza-orcinus-verify" / "tasks").mkdir(parents=True)
    (root / "skills" / "orcinus-verify").mkdir(parents=True)
    (root / "evals" / "alpha-01.md").write_text("# Alpha eval\n", encoding="utf-8")
    (root / "evals" / "orcinus-verify-01.md").write_text("# Verify eval\n", encoding="utf-8")
    (root / "SCOPE.md").write_text(
        "One alpha skill, with a manual scenario eval (`evals/alpha-01.md`).\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "Eval honesty: the 2 scenario evals in `evals/*.md` are manual "
        "text scenarios, not scored harness runs. 1 of the 3 skills have "
        "no matching `*-01.md` eval file, and 0 eval files have no "
        "matching skill directory.\n",
        encoding="utf-8",
    )
    (root / "examples" / "demo" / "tests" / "demo.test.ts").write_text(
        "test('one', () => {});\ntest('two', () => {});\n", encoding="utf-8"
    )
    (root / "skills" / "orcinus-verify" / "SKILL.md").write_text(
        '{"verdict": "PASS", "finding": "2 tests pass"}\n', encoding="utf-8"
    )
    (root / "evals" / "waza-orcinus-verify" / "tasks" / "verify-pass.yaml").write_text(
        "description: Run the demo and confirm all 2 tests pass.\n", encoding="utf-8"
    )
    return root


def test_docs_numbers_passes(tmp_path, monkeypatch):
    root = _docs_numbers_repo(tmp_path)
    assert _run_with_root(monkeypatch, root, vr.check_docs_numbers) == []


def test_docs_numbers_scored_eval_fails(tmp_path, monkeypatch):
    """Rec3: SCOPE.md called the manual scenarios 'scored evals' —
    the README honesty paragraph says they are not scored. The
    phrase is forbidden in SCOPE.md now."""
    root = _docs_numbers_repo(tmp_path)
    scope = root / "SCOPE.md"
    scope.write_text(
        scope.read_text(encoding="utf-8").replace("manual scenario", "scored"),
        encoding="utf-8",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_docs_numbers)
    assert any("scored eval" in f for f in failures)


def test_docs_numbers_missing_cited_eval_fails(tmp_path, monkeypatch):
    """Rec3: every eval path SCOPE.md cites must exist."""
    root = _docs_numbers_repo(tmp_path)
    scope = root / "SCOPE.md"
    scope.write_text(
        scope.read_text(encoding="utf-8") + " See also `evals/nope-01.md`.\n",
        encoding="utf-8",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_docs_numbers)
    assert any("nope-01.md" in f for f in failures)


def test_docs_numbers_stale_demo_count_fails(tmp_path, monkeypatch):
    """Rec3: the demo test count is computed from the demo tests,
    not trusted from the docs — a stale hard-coding fails."""
    root = _docs_numbers_repo(tmp_path)
    skill = root / "skills" / "orcinus-verify" / "SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8").replace("2 tests pass", "7 tests pass"),
        encoding="utf-8",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_docs_numbers)
    assert any("tests pass" in f for f in failures)
    task = root / "evals" / "waza-orcinus-verify" / "tasks" / "verify-pass.yaml"
    task.write_text(
        task.read_text(encoding="utf-8").replace("all 2 tests", "all 7 tests"),
        encoding="utf-8",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_docs_numbers)
    assert any("verify-pass.yaml" in f for f in failures)


def test_docs_numbers_stale_readme_counts_fail(tmp_path, monkeypatch):
    """Rec3: the README honesty numbers are recomputed — a stale
    count fails instead of drifting silently."""
    root = _docs_numbers_repo(tmp_path)
    readme = root / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            "1 of the 3 skills have no matching", "0 of the 3 skills have no matching"
        ),
        encoding="utf-8",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_docs_numbers)
    assert any("README" in f for f in failures)


def test_related_skills_must_exist(tmp_path, monkeypatch):
    """Round 7 (N5): a name in a SKILL.md 'Related Skills' section
    must be a skill in this repo — monitoring-observability listed
    five skills that do not exist, and no check read the section."""
    root = _minimal_repo(tmp_path)
    other = root / "skills" / "other" / "SKILL.md"
    other.write_text(
        other.read_text(encoding="utf-8") + "\n## Related Skills\n\n- `orcinus` - the router\n",
        encoding="utf-8",
    )
    assert _run_with_root(monkeypatch, root, vr.check_related_skills_exist) == []
    other.write_text(
        other.read_text(encoding="utf-8") + "- `defense-in-depth` - does not exist\n",
        encoding="utf-8",
    )
    failures = _run_with_root(monkeypatch, root, vr.check_related_skills_exist)
    assert len(failures) == 1 and "defense-in-depth" in failures[0]
