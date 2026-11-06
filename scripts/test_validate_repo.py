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
        json.dumps({
            "name": "x", "version": "1.0.0",
            "description": "Router + 1 focused sub-skills.",
            "author": {"name": "x"}, "skills": ["./skills"],
        }),
        encoding="utf-8",
    )
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({
            "name": "x", "description": "Test marketplace.",
            "owner": {"name": "x"},
            "plugins": [{"name": "x", "source": "./"}],
        }),
        encoding="utf-8",
    )
    (root / ".claude-plugin" / "icon.png").write_bytes(b"")
    (root / "README.md").write_text("all 2 skills\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [1.0.0] — 2026-11-06\n\nThe first release.\n",
        encoding="utf-8",
    )
    (root / "SCOPE.md").write_text("scope\n", encoding="utf-8")
    (root / "skills" / "manifest.json").write_text(
        json.dumps({
            "version": 1,
            "skills": {
                "orcinus": {
                    "name": "orcinus", "description": "Router.",
                    "license": "MIT",
                    "stages": ["0-100"], "source": "from-scratch",
                    "status": "built",
                },
                "other": {
                    "name": "other", "description": "Other.",
                    "license": "MIT",
                    "stages": ["20-39"], "source": "from-scratch",
                    "status": "built",
                },
            },
        }),
        encoding="utf-8",
    )
    (root / "skills" / "stages.json").write_text(
        json.dumps({"stages": {"orcinus": ["0-100"],
                               "other": ["20-39"]}}),
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
                    "name": "orcinus", "description": "Router.",
                    "license": "MIT",
                    "stages": ["0-100"], "source": "from-scratch",
                    "status": "built",
                },
                "other": {
                    "name": "other", "description": "Other.",
                    "license": "MIT",
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
        "Safe, behavior-preserving refactoring. "
        "Applies patterns, runs tests per step.\n")
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
    assert fields["description"] == (
        "Design a schema: tables, indexes. It's quoted.")
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
    path.write_text("---\nname: x\nthis line has no colon\n---\n\nBody.\n",
                    encoding="utf-8")
    _fields, err = vr.parse_frontmatter(path)
    assert err is not None
    path.write_text('---\nname: "unterminated\n---\n\nBody.\n',
                    encoding="utf-8")
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
    assert any("from-scratch" in f and "upstream_commit" in f
               for f in failures)


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
    path.write_text(path.read_text(encoding="utf-8") + "\n" + line + "\n",
                    encoding="utf-8")


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
        "# Guide\n", encoding="utf-8")
    _add_reference(root, "other", "See [guide](references/guide.md#setup).")
    assert _run_with_root(monkeypatch, root, vr.check_skill_references) == []


def test_skill_reference_plugin_root_same_skill_passes(tmp_path, monkeypatch):
    """${CLAUDE_PLUGIN_ROOT}/skills/<same-skill>/... is self-contained:
    it resolves to this skill folder in a plugin install."""
    root = _minimal_repo(tmp_path)
    _add_reference(
        root, "other",
        "Run `${CLAUDE_PLUGIN_ROOT}/skills/other/scripts/x.py`.")
    assert _run_with_root(monkeypatch, root, vr.check_skill_references) == []


def test_skill_reference_plugin_root_other_skill_fails(tmp_path, monkeypatch):
    """${CLAUDE_PLUGIN_ROOT}/skills/<another-skill>/... is NOT this
    skill — it dangles in a skill-only install."""
    root = _minimal_repo(tmp_path)
    _add_reference(
        root, "other",
        "Run `${CLAUDE_PLUGIN_ROOT}/skills/orcinus/scripts/x.py`.")
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
    assert _run_with_root(monkeypatch, root,
                          vr.check_version_matches_changelog) == []


def test_version_mismatch_fails(tmp_path, monkeypatch):
    """A plugin.json version that differs from the changelog's latest
    release fails and names both versions — one of the two was
    bumped without the other."""
    root = _minimal_repo(tmp_path)
    plugin = root / ".claude-plugin" / "plugin.json"
    data = json.loads(plugin.read_text(encoding="utf-8"))
    data["version"] = "0.9.1"
    plugin.write_text(json.dumps(data), encoding="utf-8")
    failures = _run_with_root(monkeypatch, root,
                              vr.check_version_matches_changelog)
    assert failures, "a version mismatch must fail"
    assert "0.9.1" in failures[0] and "1.0.0" in failures[0]


def test_version_missing_changelog_fails(tmp_path, monkeypatch):
    """No CHANGELOG.md at all fails — the version cannot be checked
    against a missing release record."""
    root = _minimal_repo(tmp_path)
    (root / "CHANGELOG.md").unlink()
    failures = _run_with_root(monkeypatch, root,
                              vr.check_version_matches_changelog)
    assert failures, "a missing CHANGELOG.md must fail"


def test_version_missing_heading_fails(tmp_path, monkeypatch):
    """A CHANGELOG.md with no ## [x.y.z] heading fails — there is no
    latest release to compare the version against."""
    root = _minimal_repo(tmp_path)
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\nNo releases yet.\n", encoding="utf-8")
    failures = _run_with_root(monkeypatch, root,
                              vr.check_version_matches_changelog)
    assert failures, "a CHANGELOG.md without a release heading must fail"


# --- user-invocable (round 3, track 10). ---

def _rewrite_skill(root, skill, frontmatter):
    """Replace a fixture skill's frontmatter with the given lines."""
    path = root / "skills" / skill / "SKILL.md"
    path.write_text("---\n" + frontmatter + "---\n\nBody.\n",
                    encoding="utf-8")


def test_subskill_without_user_invocable_fails(tmp_path, monkeypatch):
    """Every sub-skill must carry user-invocable: false — the user
    invokes only the router; a sub-skill without the field would
    appear in the / menu and invite picking it mid-work."""
    root = _minimal_repo(tmp_path)
    _rewrite_skill(root, "other",
                   "name: other\ndescription: Other.\nlicense: MIT\n")
    failures = _run_with_root(monkeypatch, root, vr.check_skill_frontmatter)
    assert failures, "a sub-skill without user-invocable must fail"
    assert any("user-invocable" in f for f in failures)


def test_subskill_user_invocable_true_fails(tmp_path, monkeypatch):
    """user-invocable: true on a sub-skill fails — only the router
    is a user entry point."""
    root = _minimal_repo(tmp_path)
    _rewrite_skill(root, "other",
                   "name: other\ndescription: Other.\nlicense: MIT\n"
                   "user-invocable: true\n")
    failures = _run_with_root(monkeypatch, root, vr.check_skill_frontmatter)
    assert failures, "user-invocable: true on a sub-skill must fail"


def test_subskill_user_invocable_string_fails(tmp_path, monkeypatch):
    """user-invocable: "false" (a string) fails — the field must be
    a real boolean false, not the word false."""
    root = _minimal_repo(tmp_path)
    _rewrite_skill(root, "other",
                   'name: other\ndescription: Other.\nlicense: MIT\n'
                   'user-invocable: "false"\n')
    failures = _run_with_root(monkeypatch, root, vr.check_skill_frontmatter)
    assert failures, "a string user-invocable must fail"
    assert any("user-invocable" in f for f in failures)


def test_router_must_stay_user_invocable(tmp_path, monkeypatch):
    """The router with user-invocable: false fails — hiding the one
    entry point would leave the user no way to invoke ORCINUS."""
    root = _minimal_repo(tmp_path)
    _rewrite_skill(root, "orcinus",
                   "name: orcinus\ndescription: Router.\nlicense: MIT\n"
                   "user-invocable: false\n")
    failures = _run_with_root(monkeypatch, root, vr.check_skill_frontmatter)
    assert failures, "a hidden router must fail"
    assert any("orcinus" in f and "user-invocable" in f for f in failures)


def test_disable_model_invocation_true_fails(tmp_path, monkeypatch):
    """disable-model-invocation: true on any skill fails — the router
    invokes sub-skills itself, so blocking model invocation would
    break routing (upstream monitoring-observability ships this
    value; ORCINUS removed it for exactly this reason)."""
    root = _minimal_repo(tmp_path)
    _rewrite_skill(root, "other",
                   "name: other\ndescription: Other.\nlicense: MIT\n"
                   "user-invocable: false\n"
                   "disable-model-invocation: true\n")
    failures = _run_with_root(monkeypatch, root, vr.check_skill_frontmatter)
    assert failures, "disable-model-invocation: true must fail"
    assert any("disable-model-invocation" in f for f in failures)


def test_router_and_subskill_frontmatter_passes(tmp_path, monkeypatch):
    """The fixture as built — router with no user-invocable field,
    sub-skill with user-invocable: false — passes frontmatter."""
    root = _minimal_repo(tmp_path)
    assert _run_with_root(monkeypatch, root,
                          vr.check_skill_frontmatter) == []


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

def _add_hermes_bundle(root, skills=("orcinus",), name="orcinus",
                       description="One integrated companion."):
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
    text += ("instruction: |\n"
             "  Load a sub-skill with skill_view(name).\n")
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
    (root / "hermes" / "orcinus.yaml").write_text(
        "name: [unclosed\nskills: [\n", encoding="utf-8"
    )
    failures = _run_with_root(monkeypatch, root, vr.check_hermes_bundle)
    assert failures, "unparsable bundle YAML must fail"
    assert any("unparsable" in f for f in failures)
