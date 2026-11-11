"""Tests for the router's skill-authoring guidance (0.12.4, F1).

The guidance lives in skills/orcinus/references/authoring-guidance.md
and is wired in from the router skill (skills/orcinus/SKILL.md).
It adapts, in ORCINUS's own words, the form-to-failure taxonomy and
the micro-test protocol from obra/superpowers
(skills/writing-skills/SKILL.md, "Match the Form to the Failure" and
"Micro-Test Wording Before Full Scenarios", MIT) — pattern-only, no
verbatim copying.

Run: python3 -m pytest scripts/test_authoring_guidance.py -q
"""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GUIDANCE = REPO / "skills" / "orcinus" / "references" / "authoring-guidance.md"
ROUTER = REPO / "skills" / "orcinus" / "SKILL.md"


def _guidance():
    return GUIDANCE.read_text(encoding="utf-8")


def _lower():
    return _guidance().lower()


def test_guidance_file_exists():
    assert GUIDANCE.is_file(), "skills/orcinus/references/authoring-guidance.md is missing"


def test_router_wires_in_authoring_guidance():
    text = ROUTER.read_text(encoding="utf-8")
    assert "references/authoring-guidance.md" in text, (
        "router SKILL.md must point at references/authoring-guidance.md"
    )


def test_form_rule_violations_under_pressure():
    text = _lower()
    assert "rule-violations under pressure" in text
    assert "prohibition" in text
    assert "rationalisation table" in text
    assert "red flags" in text


def test_form_wrong_shaped_output():
    text = _lower()
    assert "wrong-shaped output" in text
    assert "positive recipe" in text
    assert "never a prohibition list" in text


def test_form_omitted_elements():
    text = _lower()
    assert "omitted elements" in text
    assert "required template slot" in text


def test_form_conditional_behaviour():
    text = _lower()
    assert "conditional behaviour" in text
    assert "observable predicate" in text
    assert "don't x unless" in text


def test_micro_test_protocol():
    text = _lower()
    assert "no-guidance control" in text
    assert "5+ reps" in text
    assert "read every flagged match" in text
    assert "variance" in text
    assert "wording isn't binding" in text


def test_second_violation_structural_barrier():
    text = _lower()
    assert "second violation" in text
    assert "structural barrier" in text
    assert "hook" in text
    assert "lint" in text
    assert "default" in text
    assert "never a clearer sentence" in text
