"""Tests for skills/skill-creator/scripts/quick_validate.py.

Round 6 (2026-11-07), 3-R3-05: a SKILL.md with name "" and
description "" printed "Skill is valid!" and exited 0 — key
presence was checked, but after strip the `if name` /
`if description` guards skipped every content rule.

Run: python3 -m pytest skills/skill-creator/scripts/test_quick_validate.py -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quick_validate as qv  # noqa: E402


def _skill(tmp_path, name, description, dirname="demo-skill"):
    """A skill dir whose frontmatter has the given name/description.

    `name`/`description` may be None (key omitted) or any value, so
    missing-key and invalid-type cases are covered too.
    """
    skill = tmp_path / dirname
    skill.mkdir()
    lines = ["---"]
    if name is not None:
        lines.append(f"name: {name}")
    if description is not None:
        lines.append(f"description: {description}")
    lines.append("---")
    lines.append("")
    lines.append("# Demo")
    (skill / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")
    return skill


def test_empty_name_is_invalid(tmp_path):
    valid, message = qv.validate_skill(_skill(tmp_path, '""', '"Does things."'))
    assert not valid
    assert "name" in message.lower()


def test_whitespace_only_name_is_invalid(tmp_path):
    valid, message = qv.validate_skill(_skill(tmp_path, '"   "', '"Does things."'))
    assert not valid
    assert "name" in message.lower()


def test_empty_description_is_invalid(tmp_path):
    valid, message = qv.validate_skill(_skill(tmp_path, '"demo-skill"', '""'))
    assert not valid
    assert "description" in message.lower()


def test_whitespace_only_description_is_invalid(tmp_path):
    valid, message = qv.validate_skill(_skill(tmp_path, '"demo-skill"', '"   "'))
    assert not valid
    assert "description" in message.lower()


def test_missing_name_is_invalid(tmp_path):
    valid, _ = qv.validate_skill(_skill(tmp_path, None, '"Does things."'))
    assert not valid


def test_missing_description_is_invalid(tmp_path):
    valid, _ = qv.validate_skill(_skill(tmp_path, '"demo-skill"', None))
    assert not valid


def test_non_string_name_is_invalid(tmp_path):
    valid, message = qv.validate_skill(_skill(tmp_path, "123", '"Does things."'))
    assert not valid
    assert "name" in message.lower()


def test_name_must_match_directory(tmp_path):
    # The frontmatter name is the skill's identity: it must match
    # the directory the skill lives in.
    valid, message = qv.validate_skill(
        _skill(tmp_path, '"other-name"', '"Does things."', dirname="demo-skill")
    )
    assert not valid
    assert "demo-skill" in message


def test_valid_skill_passes(tmp_path):
    valid, message = qv.validate_skill(
        _skill(tmp_path, '"demo-skill"', '"Does things."', dirname="demo-skill")
    )
    assert valid
    assert message == "Skill is valid!"
