"""Tests for the mock waza suite (round-6 E7 / 2-E2).

The mock suite (evals/waza-orcinus-verify/) measures only the
harness: the mock executor echoes the prompt, and the suite and
task graders used to assert nothing but len(output) > 0. Each
task's grader must now also check its expected verdict token —
still a weak check on a mock (the token is in the echoed prompt),
but strictly more than non-empty output, and the suite
description must say so plainly instead of implying the suite
measures the skill.

What this suite still does NOT measure: anything about
orcinus-verify. trials_per_task is 1, and >=5 trials per task
with a real executor is 0.10 scope — until then the agent suite's
results are labelled "unproven" in the README.

Run: python3 -m pytest evals/waza-orcinus-verify/test_mock_suite.py -q
"""

from pathlib import Path

import yaml  # type: ignore[import-untyped]  # PyYAML ships no type stubs

SUITE = Path(__file__).resolve().parent


def _load_tasks():
    tasks = {}
    for path in sorted((SUITE / "tasks").glob("*.yaml")):
        task = yaml.safe_load(path.read_text(encoding="utf-8"))
        tasks[task["id"]] = task
    return tasks


def test_each_task_grades_more_than_nonempty_output():
    """E7: a mock task grader that only asserts len(output) > 0
    passes any non-empty echo. Each task must also assert its
    expected verdict token appears in the output."""
    for task_id, task in _load_tasks().items():
        assertions = task["graders"][0]["config"]["assertions"]
        assert assertions != ["len(output) > 0"], f"{task_id} grades only non-empty output"
        expected = task["expected"]["output_contains"]
        verdict = next(token for token in expected if token in ("PASS", "FAIL"))
        assert any(f'"{verdict}" in output' in a for a in assertions), (
            f"{task_id} must assert {verdict!r} appears in the output"
        )


def test_suite_description_states_the_mock_limit():
    """E7/E9: the suite description must say the mock echoes the
    prompt and a pass proves the harness, never the skill."""
    description = yaml.safe_load((SUITE / "eval.yaml").read_text(encoding="utf-8"))["description"]
    assert "echo" in description.lower(), "suite description must say the mock echoes the prompt"
    assert "harness" in description.lower(), "suite description must say a pass proves the harness"


def test_suite_level_grader_stays_a_smoke_check():
    """The suite-level grader is deliberately still len(output) > 0:
    it is a smoke check that the harness produced output, not a
    claim about the skill. If it ever grows a verdict assertion,
    that claim would be false on a mock."""
    suite = yaml.safe_load((SUITE / "eval.yaml").read_text(encoding="utf-8"))
    assert suite["graders"][0]["config"]["assertions"] == ["len(output) > 0"]
