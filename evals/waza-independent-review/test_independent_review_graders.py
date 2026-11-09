"""Tests for the waza independent-review eval graders.

The suite (evals/waza-independent-review/) has never run —
there is no real agent executor in this environment — so these
tests reproduce the grader semantics directly: each task's
`code` assertions are Python expressions evaluated with
`output` in scope, exactly as waza documents them. The tests
pin what the graders must do:

- A genuine good output passes its task.
- An output that repeats the author's "no behavior change"
  summary as fact fails the misleading task, and an output
  that passes the planted defects fails the planted task.
- The degenerate policies fail the suite: always-FAIL scores
  1/3 (planted only — each FAIL task needs its own file and
  finding) and always-PASS scores 1/3 (clean only), both below
  the 0.8 threshold.
- Every task requires the structured review block: the task
  assertions parse that block inline — `re` only, using
  waza-documented names — and compare its fields, instead of
  matching substrings of it. graders.py is the executable
  specification of those semantics: the assertions inline its
  report_block / finding bodies, because waza's code-grader
  namespace is closed (context vars plus len, any, all, str,
  int, float, bool, list, dict, re; no `json`, no
  sibling-module helpers — round 7, F-05) and a helper call in
  a task YAML raised NameError on the real runner.
- No task prompt states the answers: the verdicts, the
  defect rates, and the threshold live in the fixture files,
  not in the prompt.

The code-grader semantics (Python expressions evaluated with
`output` in scope) are corroborated by the real waza v0.40.0
smoke run, which evaluated `len(output) > 0` with recorded
pass/fail counts (see evals/waza-orcinus-verify-agent/
test_graders.py::test_smoke_run_corroborates_python_code_graders)
— corroboration of the semantics, not proof of literal eval().

Run: python3 -m pytest evals/waza-independent-review/test_independent_review_graders.py -q
"""

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]  # PyYAML ships no type stubs


def _load_graders():
    """Load this suite's graders.py by path, under a suite-unique
    module name: every waza suite ships a graders.py, so a plain
    `from graders import ...` would resolve to whichever suite
    pytest imported first in a combined run."""
    name = "waza_independent_review_graders"
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / "graders.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


report_block = _load_graders().report_block

SUITE = Path(__file__).resolve().parent
TASKS = SUITE / "tasks"
FIXTURES = SUITE / "fixtures"
THRESHOLD = 0.8

# task id -> its fixture folder.
TASK_FIXTURE = {
    "review-planted": "planted",
    "review-clean": "clean",
    "review-misleading": "misleading",
}

# Answer strings that must NOT appear in a task's prompt (the
# fenced block template removed first — it lists both options).
FORBIDDEN_IN_PROMPT = {
    "review-planted": ["0.8", "catch", "unknown"],
    "review-clean": ["code-simplifier"],
    "review-misleading": ["0.9", "behavior changed"],
}

# The review block every task prompt instructs the agent to end
# with. `verdict` is PASS or FAIL; `file` the primary file of
# the finding, or null; `finding` one line of evidence. The
# block is the LAST thing in the response.
FAIL_DISCOUNT_BLOCK = '```review\n{"verdict": "FAIL", "file": "discount.ts", "finding": "%s"}\n```'
PASS_BLOCK = '```review\n{"verdict": "PASS", "file": null, "finding": "%s"}\n```'
FAIL_BUDGET_BLOCK = '```review\n{"verdict": "FAIL", "file": "budget.ts", "finding": "%s"}\n```'

GOOD = {
    "review-planted": (
        "Critical issues in discount.ts. The comment says 10% off but "
        "the code returns total * 0.8 (20% off). The bare catch swallows "
        "the unknown-code error and silently returns the full total. The "
        "only test covers the happy path — there is no test for an "
        "unknown code. Verdict: FAIL.\n"
        + FAIL_DISCOUNT_BLOCK
        % "comment says 10% off but code returns total * 0.8; bare "
        "catch swallows the unknown-code error"
    ),
    "review-clean": (
        "No critical issues in discount.ts. SAVE10 gives 10% off, "
        "unknown codes throw, and three tests cover the happy path, the "
        "unknown code, and the empty code. Reviewers run: code-reviewer, "
        "pr-test-analyzer, comment-analyzer, silent-failure-hunter, "
        "type-design-analyzer, code-simplifier. Verdict: PASS.\n"
        + PASS_BLOCK
        % "no critical issues; all applicable reviewers ran"
    ),
    "review-misleading": (
        "The author's summary claims no behavior change, but the diff "
        "moves the warning threshold from budget * 0.8 to budget * 0.9, "
        "so the behavior changed: budgetWarning(80, 100) was true and "
        "is now false, and the existing test fails. Verdict: FAIL.\n"
        + FAIL_BUDGET_BLOCK
        % "threshold moved from budget * 0.8 to budget * 0.9; "
        "budgetWarning(80, 100) is now false"
    ),
}

# The plausible cheats: a PASS verdict on the planted defects,
# and repeating the author's summary as fact on the misleading
# change.
CHEAT_PASS_PLANTED = (
    "The change looks fine. discount.ts applies the discount and the "
    "test passes. Verdict: PASS.\n" + PASS_BLOCK % "no issues found"
)
CHEAT_TRUSTS_SUMMARY = (
    "Just a refactor, no behavior change, as the author says. "
    "Verdict: PASS.\n" + PASS_BLOCK % "no behavior change"
)

ALWAYS_FAIL = GOOD["review-planted"]
ALWAYS_PASS = GOOD["review-clean"]

EXPECTED = {
    "review-planted": "FAIL",
    "review-clean": "PASS",
    "review-misleading": "FAIL",
}


def _load_tasks():
    tasks = {}
    for path in sorted(TASKS.glob("*.yaml")):
        task = yaml.safe_load(path.read_text(encoding="utf-8"))
        tasks[task["id"]] = task
    return tasks


def _grade(task, output):
    """Evaluate a task's code assertions against one output, the way
    waza's code grader does: every assertion is a Python expression
    with `output` in scope, and all of them must hold. The namespace
    is waza's closed set — the context vars plus the documented
    built-ins (len, any, all, str, int, float, bool, list, dict, re)
    and NOTHING else: no `json`, no graders.py helpers."""
    assertions = task["graders"][0]["config"]["assertions"]
    namespace = {
        "__builtins__": {},
        "output": output,
        "re": re,
        "len": len,
        "any": any,
        "all": all,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
    }
    return all(eval(a, namespace) for a in assertions)


# The names a waza `code` assertion may reference, from waza's own
# graders docs (microsoft.github.io/waza/guides/graders/, v0.40.0):
# the context variables (output, outcome, transcript, tool_calls,
# tool_events, command_invocations, host_lifecycle,
# user_input_requests, errors, duration_ms) plus the closed
# built-in list (len, any, all, str, int, float, bool, list, dict,
# re). `json` is NOT in that list, and there is no module, prelude
# or globals mechanism for loading sibling-module helpers — a task
# assertion naming anything else raises NameError on the real
# runner (round 7, F-05).
WAZA_DOCUMENTED_NAMES = {
    "output",
    "outcome",
    "transcript",
    "tool_calls",
    "tool_events",
    "command_invocations",
    "host_lifecycle",
    "user_input_requests",
    "errors",
    "duration_ms",
    "len",
    "any",
    "all",
    "str",
    "int",
    "float",
    "bool",
    "list",
    "dict",
    "re",
}


def test_suite_has_three_tasks():
    """Planted, clean, misleading: the three cases of
    independent-review-01.md. Two tasks could not cover both
    failure modes (defects the tests miss, and a summary the
    diff contradicts)."""
    assert sorted(_load_tasks()) == [
        "review-clean",
        "review-misleading",
        "review-planted",
    ]


def test_all_suite_yaml_parses():
    """Every YAML file in this suite must parse — the agent suite's
    eval.yaml was unparseable from round 3 and nothing ever noticed,
    because the suite never ran and the repo validator does not
    check eval YAML."""
    for path in sorted(SUITE.rglob("*.yaml")):
        yaml.safe_load(path.read_text(encoding="utf-8"))


def test_task_fixture_files_exist():
    """Each task's bare `files:` paths must exist in its own fixture
    folder — a task naming a file the runner cannot load is
    ungradeable."""
    tasks = _load_tasks()
    for task_id, folder in TASK_FIXTURE.items():
        for entry in tasks[task_id]["inputs"]["files"]:
            assert (FIXTURES / folder / entry["path"]).is_file(), (
                f"{task_id} references missing fixture file {folder}/{entry['path']}"
            )


def test_prompts_do_not_state_the_answers():
    """The verdicts, the defect rates, and the threshold live in
    the fixture files, not in the prompt: an agent that passes
    without reading the diff proves nothing. The fenced block
    template is removed first — it lists both options for each
    field, which is the format, not the answer."""
    for task_id, task in _load_tasks().items():
        prompt = task["inputs"]["prompt"]
        template = re.search(r"```review\n.*?\n```", prompt, re.S)
        assert template is not None, f"{task_id} prompt has no review block template"
        without_template = prompt[: template.start()] + prompt[template.end() :]
        for forbidden in FORBIDDEN_IN_PROMPT[task_id]:
            assert forbidden not in without_template, (
                f"{task_id} prompt states the answer {forbidden!r}"
            )


def test_good_outputs_pass_their_task():
    tasks = _load_tasks()
    for task_id, output in GOOD.items():
        assert task_id in tasks, f"task {task_id} is missing"
        assert _grade(tasks[task_id], output), (
            f"the good output for {task_id} must pass its graders"
        )


def test_good_blocks_parse_and_agree():
    """Every good output's block is valid JSON, its verdict is the
    task's expected verdict, and the prose contains no opposite
    verdict block (hedging with both verdicts must fail)."""
    for task_id, output in GOOD.items():
        block = report_block(output)
        assert block is not None, f"no ```review block in {task_id}"
        assert block["verdict"] == EXPECTED[task_id]
        opposite = "FAIL" if block["verdict"] == "PASS" else "PASS"
        assert f'"verdict": "{opposite}"' not in output


def test_cheat_outputs_fail():
    """A PASS verdict on the planted defects must fail, and
    repeating the author's summary as fact must fail the
    misleading task."""
    tasks = _load_tasks()
    assert not _grade(tasks["review-planted"], CHEAT_PASS_PLANTED), (
        "a PASS verdict must fail review-planted"
    )
    assert not _grade(tasks["review-misleading"], CHEAT_TRUSTS_SUMMARY), (
        "trusting the summary must fail review-misleading"
    )


def test_degenerate_policies_below_threshold():
    """No constant policy can pass the suite: always-FAIL scores
    2/3 (planted + misleading) and always-PASS scores 1/3 (clean
    only), both below the 0.8 threshold."""
    tasks = _load_tasks()
    fail_score = sum(1 for t in tasks.values() if _grade(t, ALWAYS_FAIL))
    pass_score = sum(1 for t in tasks.values() if _grade(t, ALWAYS_PASS))
    assert fail_score == 1, f"always-FAIL must pass exactly 1, got {fail_score}"
    assert pass_score == 1, f"always-PASS must pass exactly 1, got {pass_score}"
    assert fail_score / len(tasks) < THRESHOLD
    assert pass_score / len(tasks) < THRESHOLD


def test_every_task_requires_a_review_block():
    """No task may grade on bare words alone: each grader list must
    parse the fenced ```review block inline (the `re.findall`
    pattern that extracts the block) and check its fields — never
    a bare-word match, and never a call to the graders.py helpers
    (those names do not resolve in waza's namespace; F-05)."""
    for task_id, task in _load_tasks().items():
        assertions = task["graders"][0]["config"]["assertions"]
        assert any("```review" in a for a in assertions), f"{task_id} has no review-block assertion"
        for assertion in assertions:
            assert "report_block(" not in assertion, (
                f"{task_id} calls report_block, which waza does not resolve"
            )
            assert "verdict(" not in assertion, (
                f"{task_id} calls verdict, which waza does not resolve"
            )
            assert "finding(" not in assertion, (
                f"{task_id} calls finding, which waza does not resolve"
            )


def test_task_assertions_use_only_waza_documented_names():
    """Round 7, F-05: every name a task assertion references must
    be in waza's documented set. `report_block`, `verdict`,
    `finding` and `json` must NOT appear. The eval.yaml
    suite-level assertions are checked the same way."""
    for task_id, task in _load_tasks().items():
        for assertion in task["graders"][0]["config"]["assertions"]:
            names = {
                node.id for node in ast.walk(ast.parse(assertion)) if isinstance(node, ast.Name)
            }
            assert names <= WAZA_DOCUMENTED_NAMES, (
                f"{task_id} references undocumented names {sorted(names - WAZA_DOCUMENTED_NAMES)}: {assertion!r}"
            )
    suite = yaml.safe_load((SUITE / "eval.yaml").read_text(encoding="utf-8"))
    for assertion in suite["graders"][0]["config"]["assertions"]:
        names = {node.id for node in ast.walk(ast.parse(assertion)) if isinstance(node, ast.Name)}
        assert names <= WAZA_DOCUMENTED_NAMES, (
            f"eval.yaml references undocumented names {sorted(names - WAZA_DOCUMENTED_NAMES)}: {assertion!r}"
        )


def _compact_block(output):
    """Re-serialise the output's review block as compact JSON (no
    spaces) — the equivalent good output the old substring graders
    rejected."""
    match = re.search(r"```review\n(.*?)\n```", output, re.S)
    assert match is not None
    compact = json.dumps(json.loads(match.group(1)), separators=(",", ":"))
    return output[: match.start(1)] + compact + output[match.end(1) :]


def test_compact_json_good_outputs_pass():
    """A correct output with equivalent compact JSON must pass:
    parsed-field comparison, not spaced-substring matching."""
    tasks = _load_tasks()
    for task_id, output in GOOD.items():
        assert _grade(tasks[task_id], _compact_block(output)), (
            f"the compact-JSON good output for {task_id} must pass"
        )


def test_opposite_verdict_last_block_fails():
    """An output whose LAST block has the opposite verdict must
    fail, whichever verdict the prose states."""
    tasks = _load_tasks()
    for task_id, output in GOOD.items():
        opposite = dict(
            report_block(output), verdict="PASS" if EXPECTED[task_id] == "FAIL" else "FAIL"
        )
        attack = output + "\n```review\n" + json.dumps(opposite, separators=(",", ":")) + "\n```"
        assert not _grade(tasks[task_id], attack), (
            f"an opposite-verdict last block must fail {task_id}"
        )


def test_two_review_blocks_fail():
    """Exactly one block is required: hedging with a second block
    must fail, whichever verdict it carries."""
    tasks = _load_tasks()
    for task_id, output in GOOD.items():
        attack = output + "\n" + (PASS_BLOCK % "no critical issues")
        assert not _grade(tasks[task_id], attack), f"a second review block must fail {task_id}"


def test_non_json_block_with_keywords_outside_fails():
    """A ```review block containing `not JSON`, plus the keywords
    separate from the block, must fail: the assertions read the
    block, not bare words in the prose."""
    tasks = _load_tasks()
    attack = (
        '"verdict": "FAIL", "file": "discount.ts", 0.8, catch, unknown\n```review\nnot JSON\n```'
    )
    assert not _grade(tasks["review-planted"], attack)


def test_no_spaced_json_in_expected_output_contains():
    """expected.output_contains must not list spaced JSON — a
    correct compact-JSON output would fail it. The verdict lives
    in the code assertions now."""
    for task_id, task in _load_tasks().items():
        for entry in task["expected"]["output_contains"]:
            assert not re.search(r'"\w+": "', entry), (
                f"{task_id} expected output_contains has spaced JSON: {entry!r}"
            )


def test_misleading_requires_threshold_and_changed_behaviour():
    """The misleading task is about both: the threshold the diff
    moved (0.9) AND the behaviour change the summary denies. A
    finding naming only the bug, or prose naming only the
    threshold, must not pass."""
    task = _load_tasks()["review-misleading"]
    assert _grade(task, GOOD["review-misleading"])
    prose = GOOD["review-misleading"].split("```review")[0]
    no_threshold = prose + FAIL_BUDGET_BLOCK % "the behavior changed"
    assert not _grade(task, no_threshold), "a finding without the threshold must fail"
    no_changed = prose.replace("behavior changed", "behavior") + FAIL_BUDGET_BLOCK % (
        "threshold moved from budget * 0.8 to budget * 0.9"
    )
    assert not _grade(task, no_changed), "prose without 'behavior changed' must fail"
