"""F5 (0.12.4): observed-vs-inferred + uncertainties discipline in
codebase-knowledge-builder.

The skill already labels findings observed/inferred/unknown and cites
observed claims, but it never states the grounding rule itself: that
every observation must rest on code evidence actually read. The
spec-miner MUST DO list (Jeffallan/claude-skills,
skills/spec-miner/SKILL.md) states it as a requirement — ground all
observations in actual code evidence; distinguish observed facts from
inferences; document uncertainties; include code locations — and this
skill must carry the same discipline in its own words, as one rule in
Phase 2, where observations are made. These tests pin that rule's
presence in SKILL.md; on the old text they fail.

Run: python3 -m pytest scripts/test_codebase_knowledge_builder.py -q
"""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SKILL = REPO / "skills" / "codebase-knowledge-builder" / "SKILL.md"


def _phase(text, heading):
    """The lines of the ## section named heading (without the heading)."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f"## {heading}")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start + 1 : end])


def test_phase_two_states_grounding_rule():
    """F5: Phase 2 must state the grounding rule — every observation
    rests on code evidence actually read — and that a finding counts
    as observed only when the inspected code shows it."""
    phase_two = _phase(SKILL.read_text(encoding="utf-8"), "Phase 2: Deep-Dive Study")
    assert "Ground every observation in code evidence actually read" in phase_two
    assert "State as observed only what the inspected code shows" in phase_two


def test_phase_two_keeps_observed_separate_from_inferred():
    """F5: observed facts stay separate from inferences — the rule
    must say so in Phase 2, not only in the methodology reference."""
    phase_two = _phase(SKILL.read_text(encoding="utf-8"), "Phase 2: Deep-Dive Study")
    assert "Keep observed facts separate from inferences" in phase_two


def test_phase_two_records_uncertainties_with_resolving_evidence():
    """F5: uncertainties are recorded together with the evidence
    that would resolve them."""
    phase_two = _phase(SKILL.read_text(encoding="utf-8"), "Phase 2: Deep-Dive Study")
    assert "Record what is uncertain" in phase_two
    assert "the evidence that would resolve it" in phase_two


def test_phase_two_requires_code_location_per_observation():
    """F5: every observation carries its code location."""
    phase_two = _phase(SKILL.read_text(encoding="utf-8"), "Phase 2: Deep-Dive Study")
    assert "Cite the code location of each observation" in phase_two
    assert "relative/path:line" in phase_two
