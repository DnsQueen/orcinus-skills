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

The negative control (round 7, F-10) lives in a SEPARATE suite,
evals/waza-orcinus-verify/control/, not in this suite's tasks/:
its prompt, name and description omit the verdict word, so the
mock echo cannot pass its grader — the suite CAN fail. It is
kept out of the main suite so the main run's contract (2/2,
exit 0) is unchanged; CI runs the control separately and
asserts the failure. The tests below pin that shape.

Run: python3 -m pytest evals/waza-orcinus-verify/test_mock_suite.py -q
"""

from pathlib import Path

import yaml  # type: ignore[import-untyped]  # PyYAML ships no type stubs

SUITE = Path(__file__).resolve().parent
CONTROL = SUITE / "control"


def _load_tasks():
    tasks = {}
    for path in sorted((SUITE / "tasks").glob("*.yaml")):
        task = yaml.safe_load(path.read_text(encoding="utf-8"))
        tasks[task["id"]] = task
    return tasks


def _load_control_tasks():
    tasks = {}
    for path in sorted((CONTROL / "tasks").glob("*.yaml")):
        task = yaml.safe_load(path.read_text(encoding="utf-8"))
        tasks[task["id"]] = task
    return tasks


def _mock_echo(task):
    """What the mock executor returns for a task (recorded run):
    the prompt plus the task name plus the description. The exact
    separator does not matter for the verdict-word checks below:
    if no field contains the word, no join of them can."""
    return "\n".join([task["inputs"]["prompt"], task["name"], task["description"]])


def _grade_mock(task, output):
    """Evaluate a mock task's code assertions against one output.
    The mock assertions use only `len` and `in` on `output`."""
    assertions = task["graders"][0]["config"]["assertions"]
    namespace = {"__builtins__": {}, "output": output, "len": len}
    return all(eval(a, namespace) for a in assertions)


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


# --- Round-7 negative control (F-10). The mock suite is circular
# by construction: the mock echoes the prompt, and the graders
# assert a word the prompt supplies. The control proves the suite
# CAN fail: its prompt, name and description omit the answer word,
# so the mock echo cannot pass its grader. ---


def test_main_suite_still_has_two_tasks():
    """The control must not leak into the main suite: the main
    tasks/ dir still holds exactly verify-pass and verify-fail, so
    the main run's contract (2/2, exit 0) is unchanged."""
    assert sorted(_load_tasks()) == ["verify-fail", "verify-pass"]


def test_negative_control_is_a_separate_suite():
    """The control is its own eval.yaml under control/, with the
    mock executor and a tasks glob relative to its own directory —
    a separate `waza run` invocation, not a third task in the
    main suite."""
    assert (CONTROL / "eval.yaml").is_file()
    assert (CONTROL / "tasks" / "verify-negative-control.yaml").is_file()
    control = yaml.safe_load((CONTROL / "eval.yaml").read_text(encoding="utf-8"))
    assert control["name"] == "orcinus-verify-negative-control"
    assert control["config"]["executor"] == "mock"
    assert control["tasks"] == ["tasks/*.yaml"]
    assert control["graders"][0]["config"]["assertions"] == ["len(output) > 0"]


def test_negative_control_task_omits_the_answer_word():
    """F-10 (with the verification correction): the answer word
    must be stripped from the prompt AND the name AND the
    description — for verify-pass the uppercase PASS came from
    the task name and description, not the prompt. Checked
    case-insensitively: the grader's `"FAIL" in output` is
    case-sensitive, but a case-insensitive match (e.g. in a
    future output_contains check) must not rescue it either."""
    for task_id, task in _load_control_tasks().items():
        for field, text in (
            ("prompt", task["inputs"]["prompt"]),
            ("name", task["name"]),
            ("description", task["description"]),
        ):
            lowered = text.lower()
            assert "pass" not in lowered, f"{task_id} {field} contains the answer word"
            assert "fail" not in lowered, f"{task_id} {field} contains the answer word"


def test_negative_control_grader_still_asserts_the_verdict():
    """The control is not a vacuous task: its grader still asserts
    the expected verdict word appears in the output, in the same
    shape as verify-fail's grader (non-empty output plus the
    token)."""
    for task_id, task in _load_control_tasks().items():
        assertions = task["graders"][0]["config"]["assertions"]
        assert assertions != ["len(output) > 0"], f"{task_id} grades only non-empty output"
        expected = task["expected"]["output_contains"]
        verdict = next(token for token in expected if token in ("PASS", "FAIL"))
        assert any(f'"{verdict}" in output' in a for a in assertions), (
            f"{task_id} must assert {verdict!r} appears in the output"
        )


def test_mock_echo_passes_main_tasks_but_fails_the_control():
    """The behavioural heart of the control: on the mock echo
    (prompt + name + description), both main tasks pass — the
    circularity, still disclosed — and the control task fails,
    because its echo contains no answer word. If the control
    ever passes here, the grader passes without the answer."""
    for task_id, task in _load_tasks().items():
        assert _grade_mock(task, _mock_echo(task)), f"the mock echo must pass {task_id}"
    for task_id, task in _load_control_tasks().items():
        assert not _grade_mock(task, _mock_echo(task)), (
            f"the mock echo must fail the control {task_id}"
        )
