"""Tests for scripts/generate_router_resources.py (round 5, T5).

The router (skills/orcinus) must work from a standalone install,
where only the skill folders exist and the repo's docs/ does not.
Two resources travel with the router skill, generated from the
canonical repo docs:

- references/skill-status.md — the MAP status table, generated from
  docs/MAP.md (which step is built, external-optional, or todo);
- references/project-state.md — a byte-identical copy of
  docs/project-state.md (the .orcinus/state.json spec).

The router's SKILL.md and rules.md point at the bundled copies, never
at the repo's docs/ — in a user project docs/MAP.md is the user's
file, not ORCINUS's, and in a skill-only install docs/ is absent.

Run: python3 -m pytest scripts/test_generate_router_resources.py -q
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_router_resources as grr  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _map_text():
    return (REPO / "docs" / "MAP.md").read_text(encoding="utf-8")


def test_parse_map_tables():
    # The MAP's section tables (A-G) are the canonical status source:
    # 55 rows, every row 5 cells, no pipe inside a cell.
    sections = grr.parse_map_tables(_map_text())
    rows = [r for s in sections.values() for r in s["rows"]]
    assert len(sections) == 7
    assert len(rows) == 55
    assert all(len(r) == 5 for r in rows)
    statuses = [r[4] for r in rows]
    assert sum(s.startswith("built") for s in statuses) == 47
    assert statuses.count("external-optional") == 5
    assert statuses.count("todo") == 3


def test_parse_map_external_optional_names():
    # The non-built steps the router must classify, not improvise.
    sections = grr.parse_map_tables(_map_text())
    rows = [r for s in sections.values() for r in s["rows"]]
    external = [r[1] for r in rows if r[4] == "external-optional"]
    assert any("egm-brainstorm" in s for s in external)
    assert any("grill-me" in s for s in external)
    assert any("ponytail" in s for s in external)
    assert any("tdd" in s for s in external)
    assert any("ponytail-debt" in s for s in external)
    todo = [r[1] for r in rows if r[4] == "todo"]
    assert todo == ["SWE-bench", "SWE-agent/swe-rex", "openai/plugins: plugin-eval"]


def test_generate_skill_status_matches_committed():
    # The committed copy is exactly what the generator produces from
    # the current MAP — a stale copy must fail this test.
    bundled = REPO / "skills" / "orcinus" / "references" / "skill-status.md"
    assert bundled.is_file(), "references/skill-status.md is missing"
    assert grr.generate_skill_status(_map_text()) == bundled.read_text(encoding="utf-8")


def test_generate_is_deterministic():
    assert grr.generate_skill_status(_map_text()) == grr.generate_skill_status(_map_text())


def test_project_state_bundled_identical():
    # The state spec travels with the router as a byte-identical copy,
    # like the glossary (checked by the repo validator).
    bundled = REPO / "skills" / "orcinus" / "references" / "project-state.md"
    assert bundled.is_file(), "references/project-state.md is missing"
    assert bundled.read_bytes() == (REPO / "docs" / "project-state.md").read_bytes()


def test_router_never_references_repo_docs():
    # In a standalone install docs/ does not exist, and in a user
    # project docs/MAP.md is the user's file. The router must point
    # at the bundled copies instead.
    for path in (
        REPO / "skills" / "orcinus" / "SKILL.md",
        REPO / "skills" / "orcinus" / "references" / "rules.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert "docs/MAP.md" not in text, f"{path.name} still points at docs/MAP.md"
        assert "docs/project-state.md" not in text, (
            f"{path.name} still points at docs/project-state.md"
        )


def test_standalone_install_has_router_resources(tmp_path):
    # F3 acceptance: only the installed skill folders, in an empty
    # project — no docs/. Missing-skill detection (the status table),
    # fallback selection (rules.md), and state recovery (the state
    # spec) must still work from the bundled files alone.
    install = tmp_path / "install"
    shutil.copytree(REPO / "skills", install / "skills")
    assert not (install / "docs").exists()
    router = install / "skills" / "orcinus"
    status = router / "references" / "skill-status.md"
    state = router / "references" / "project-state.md"
    assert status.is_file()
    assert state.is_file()
    # The status table still classifies the non-built steps.
    text = status.read_text(encoding="utf-8")
    assert "external-optional" in text
    assert "SWE-bench" in text
    # Every references/*.md the router SKILL.md names resolves inside
    # the copied skill folder.
    skill_text = (router / "SKILL.md").read_text(encoding="utf-8")
    import re

    for target in sorted(set(re.findall(r"references/[A-Za-z0-9_.-]+\.md", skill_text))):
        assert (router / target).is_file(), f"{target} dangles in a skill-only install"
