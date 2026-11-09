"""Tests for the waza registry-publish eval graders.

The suite (evals/waza-registry-publish/) has never run — there
is no real agent executor in this environment — so these tests
reproduce the grader semantics directly: each task's `code`
assertions are Python expressions evaluated with `output` in
scope, exactly as waza documents them. The tests pin what the
graders must do:

- A genuine good output passes its task.
- An output that claims the package was published must fail
  both tasks (no real publish is performed in this eval), and
  an output that calls the unprepared package ready must fail
  it.
- The degenerate policies fail the suite: always-ready and
  always-not-ready each score 1/2, below the 0.8 threshold.
- Every task requires the structured publish block: the task
  assertions parse that block inline — `re` only, using
  waza-documented names — and compare its fields, instead of
  matching substrings of it. graders.py is the executable
  specification of those semantics: the assertions inline its
  report_block body, because waza's code-grader namespace is
  closed (context vars plus len, any, all, str, int, float,
  bool, list, dict, re; no `json`, no sibling-module helpers
  — round 7, F-05) and a helper call in a task YAML raised
  NameError on the real runner.
- No task prompt states the answers: the version, the pack
  list, and the registry result live in the fixture files,
  not in the prompt.

The code-grader semantics (Python expressions evaluated with
`output` in scope) are corroborated by the real waza v0.40.0
smoke run, which evaluated `len(output) > 0` with recorded
pass/fail counts (see evals/waza-orcinus-verify-agent/
test_graders.py::test_smoke_run_corroborates_python_code_graders)
— corroboration of the semantics, not proof of literal eval().

Run: python3 -m pytest evals/waza-registry-publish/test_registry_publish_graders.py -q
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
    name = "waza_registry_publish_graders"
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
    "publish-ready": "prepared",
    "publish-unprepared": "unprepared",
}

# Answer strings that must NOT appear in a task's prompt (the
# fenced block template removed first — it lists both options).
FORBIDDEN_IN_PROMPT = {
    "publish-ready": ["0.1.0", "dist/src/budget.js"],
    "publish-unprepared": ["0.1.0", "tests/"],
}

# The publish block every task prompt instructs the agent to end
# with. `publish_ready` is the checklist verdict; `pack_ok`
# whether the dry-run list is exactly the shippable files;
# `published` whether anything was published — always false in
# this eval. The block is the LAST thing in the response.
READY_BLOCK = (
    '```publish\n{"publish_ready": true, "version": "0.1.0", '
    '"pack_ok": true, "published": false}\n```'
)
UNPREPARED_BLOCK = (
    '```publish\n{"publish_ready": false, "version": "0.1.0", '
    '"pack_ok": false, "published": false}\n```'
)

GOOD = {
    "publish-ready": (
        "Report for orcinus-demo-scaffold 0.1.0. Four commands green "
        "(7/7 tests). Registry check: npm view orcinus-demo-scaffold"
        "@0.1.0 returns E404 — the version does not exist yet. Dry-run "
        "file list, in full: package.json, README.md, LICENSE, "
        "dist/src/budget.js, dist/src/summary.js — exactly the shippable "
        "files, no tests, no source, no secrets. Verdict: publish-ready, "
        "pending the human gate. No real publish was performed.\n" + READY_BLOCK
    ),
    "publish-unprepared": (
        "Report for orcinus-demo-scaffold 0.1.0. Four commands green "
        "(7/7 tests). Registry check: E404 — the version does not exist "
        "yet. Dry-run file list ships source and tests that must not "
        "ship: src/budget.ts, src/summary.ts, tests/budget.test.ts, "
        "tests/summary.test.ts. There is no files allowlist and no "
        "declared entry points. Verdict: NOT publish-ready. No real "
        "publish was performed.\n" + UNPREPARED_BLOCK
    ),
}

# The plausible cheats: a report that claims the package was
# published (it was not), and a report that calls the unprepared
# package ready.
CHEAT_PUBLISHED = (
    "Report for orcinus-demo-scaffold 0.1.0. Published to the "
    "registry. Dry-run file list: package.json, README.md, LICENSE, "
    "dist/src/budget.js, dist/src/summary.js. E404.\n"
    '```publish\n{"publish_ready": true, "version": "0.1.0", '
    '"pack_ok": true, "published": true}\n```'
)
CHEAT_READY = (
    "Report for orcinus-demo-scaffold 0.1.0. The dry-run list looks "
    "fine. Verdict: publish-ready.\n" + READY_BLOCK
)

ALWAYS_READY = GOOD["publish-ready"]
ALWAYS_NOT_READY = GOOD["publish-unprepared"]

EXPECTED_READY = {
    "publish-ready": True,
    "publish-unprepared": False,
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


def test_suite_has_two_tasks():
    """One prepared task and one unprepared task: a single task
    could not tell a passing check from a catching one, and with
    only one task a constant policy would score 1/1."""
    assert sorted(_load_tasks()) == ["publish-ready", "publish-unprepared"]


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
    """The version, the pack list, and the registry result live in
    the fixture files, not in the prompt: an agent that passes
    without reading the fixtures proves nothing. The fenced block
    template is removed first — it lists both options for each
    field, which is the format, not the answer."""
    for task_id, task in _load_tasks().items():
        prompt = task["inputs"]["prompt"]
        template = re.search(r"```publish\n.*?\n```", prompt, re.S)
        assert template is not None, f"{task_id} prompt has no publish block template"
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
    """Every good output's block is valid JSON, its publish_ready
    flag is the task's expected verdict, its version is the
    fixture's, and `published` is false in both — no real publish
    is performed in this eval. The prose contains no second block
    (hedging with both verdicts must fail)."""
    for task_id, output in GOOD.items():
        block = report_block(output)
        assert block is not None, f"no ```publish block in {task_id}"
        assert block["publish_ready"] is EXPECTED_READY[task_id]
        assert block["version"] == "0.1.0"
        assert block["published"] is False
        opposite = "false" if block["publish_ready"] else "true"
        assert f'"publish_ready": {opposite}' not in output


def test_cheat_outputs_fail():
    """A report claiming the package was published must fail both
    tasks, and a ready report on the unprepared package must fail
    it."""
    tasks = _load_tasks()
    assert not _grade(tasks["publish-ready"], CHEAT_PUBLISHED), (
        "a published claim must fail publish-ready"
    )
    assert not _grade(tasks["publish-unprepared"], CHEAT_PUBLISHED), (
        "a published claim must fail publish-unprepared"
    )
    assert not _grade(tasks["publish-unprepared"], CHEAT_READY), (
        "a ready report must fail publish-unprepared"
    )


def test_degenerate_policies_below_threshold():
    """No constant policy can pass the suite: always-ready scores
    1/2 (only the prepared task) and always-not-ready scores 1/2
    (only the unprepared task), both below the 0.8 threshold."""
    tasks = _load_tasks()
    ready_score = sum(1 for t in tasks.values() if _grade(t, ALWAYS_READY))
    not_ready_score = sum(1 for t in tasks.values() if _grade(t, ALWAYS_NOT_READY))
    assert ready_score == 1, f"always-ready must pass exactly 1, got {ready_score}"
    assert not_ready_score == 1, f"always-not-ready must pass exactly 1, got {not_ready_score}"
    assert ready_score / len(tasks) < THRESHOLD
    assert not_ready_score / len(tasks) < THRESHOLD


def test_every_task_requires_a_publish_block():
    """No task may grade on bare words alone: each grader list must
    parse the fenced ```publish block inline (the `re.findall`
    pattern that extracts the block) and check its fields — never
    a bare-word match, and never a call to the graders.py helpers
    (those names do not resolve in waza's namespace; F-05)."""
    for task_id, task in _load_tasks().items():
        assertions = task["graders"][0]["config"]["assertions"]
        assert any("```publish" in a for a in assertions), (
            f"{task_id} has no publish-block assertion"
        )
        for assertion in assertions:
            assert "report_block(" not in assertion, (
                f"{task_id} calls report_block, which waza does not resolve"
            )
            assert "publish_ready(" not in assertion, (
                f"{task_id} calls publish_ready, which waza does not resolve"
            )
            assert "pack_ok(" not in assertion, (
                f"{task_id} calls pack_ok, which waza does not resolve"
            )


def test_task_assertions_use_only_waza_documented_names():
    """Round 7, F-05: every name a task assertion references must
    be in waza's documented set. `report_block`, `publish_ready`,
    `pack_ok` and `json` must NOT appear. The eval.yaml
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
    """Re-serialise the output's publish block as compact JSON (no
    spaces) — the equivalent good output the old substring graders
    rejected."""
    match = re.search(r"```publish\n(.*?)\n```", output, re.S)
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


def test_opposite_ready_last_block_fails():
    """An output whose LAST block carries the opposite publish_ready
    flag must fail, whichever verdict the prose states."""
    tasks = _load_tasks()
    for task_id, output in GOOD.items():
        opposite = dict(report_block(output), publish_ready=not EXPECTED_READY[task_id])
        attack = output + "\n```publish\n" + json.dumps(opposite, separators=(",", ":")) + "\n```"
        assert not _grade(tasks[task_id], attack), (
            f"an opposite-ready last block must fail {task_id}"
        )


def test_two_publish_blocks_fail():
    """Exactly one block is required: hedging with a second block
    must fail, whichever verdict it carries."""
    tasks = _load_tasks()
    for task_id, output in GOOD.items():
        attack = output + "\n" + READY_BLOCK
        assert not _grade(tasks[task_id], attack), f"a second publish block must fail {task_id}"


def test_non_json_block_with_keywords_outside_fails():
    """A ```publish block containing `not JSON`, plus the keywords
    separate from the block, must fail: the assertions read the
    block, not bare words in the prose."""
    tasks = _load_tasks()
    attack = (
        '"publish_ready": true, "version": "0.1.0", "pack_ok": true, '
        '"published": false, dist/src/budget.js, E404\n'
        "```publish\nnot JSON\n```"
    )
    assert not _grade(tasks["publish-ready"], attack)


def test_no_spaced_json_in_expected_output_contains():
    """expected.output_contains must not list spaced JSON — a
    correct compact-JSON output would fail it. The verdict lives
    in the code assertions now."""
    for task_id, task in _load_tasks().items():
        for entry in task["expected"]["output_contains"]:
            assert not re.search(r'"\w+": "', entry), (
                f"{task_id} expected output_contains has spaced JSON: {entry!r}"
            )
