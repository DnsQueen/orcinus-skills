"""Tests for validate_evidence.py (the evidence-bundle gate).

The gate's job is to catch a PASS that hides a failure: a check with
verdict FAIL, a blocking finding, or a non-empty unverified_items
must never come out as an overall PASS. Each test is one such
contradiction, plus the happy path.

Run: python3 -m pytest skills/orcinus-verify/scripts/test_validate_evidence.py -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_evidence as ve  # noqa: E402

_SCHEMA = ve.load_schema(
    Path(__file__).resolve().parent.parent / "references" / "evidence.schema.json"
)


def _problems(bundle):
    return ve.validate_bundle(bundle, _SCHEMA)


def _good_bundle():
    return {
        "schema_version": 2,
        "revision": "abc1234",
        "working_tree_state": "clean",
        "requirement": "Fix the Persian capture crash.",
        "acceptance_criteria": ["A Persian-only idea captures without a traceback."],
        "files_changed": ["skills/idea-capture/scripts/capture.py"],
        "checks": [
            {
                "name": "test",
                "command": "python3 -m pytest -q",
                "cwd": "/repo",
                "exit_code": 0,
                "verdict": "PASS",
                "tool_version": "pytest 8.4.2",
                "started_at": "2026-11-06T10:00:00Z",
                "finished_at": "2026-11-06T10:00:12Z",
            },
            {
                "name": "lint",
                "command": "ruff check skills/idea-capture",
                "cwd": "/repo",
                "exit_code": 0,
                "verdict": "PASS",
                "tool_version": "ruff 0.17.4",
                "started_at": "2026-11-06T10:00:12Z",
                "finished_at": "2026-11-06T10:00:13Z",
            },
        ],
        "findings": [],
        "unresolved_risks": [],
        "unverified_items": [],
        "verdict": "PASS",
        "reviewer_identity": "orcinus-verify (independent session)",
        "verification_plan": {
            "change_type": "bug-fix",
            "required_gates": ["test", "lint"],
            "not_applicable_gates": [
                {"gate": "build", "reason": "Python scripts have no build step."},
                {"gate": "typecheck", "reason": "No typechecker in this Python project."},
            ],
        },
        "fail_first": {
            "test": "test_capture_persian_only",
            "failed_before": True,
            "passed_after": True,
            "method": "worktree",
        },
    }


def test_good_bundle_passes():
    assert _problems(_good_bundle()) == []


def test_pass_hiding_a_failed_check_fails():
    b = _good_bundle()
    b["checks"][0]["verdict"] = "FAIL"
    problems = _problems(b)
    assert any("FAIL" in p and "PASS" in p for p in problems)


def test_pass_hiding_a_blocking_finding_fails():
    b = _good_bundle()
    b["findings"] = [
        {
            "file": "src/x.ts",
            "line": 12,
            "evidence": "crashes on empty input",
            "severity": "blocking",
        }
    ]
    problems = _problems(b)
    assert any("blocking finding" in p for p in problems)


def test_pass_hiding_unverified_items_fails():
    b = _good_bundle()
    b["unverified_items"] = ["the 3.9 matrix has never run"]
    problems = _problems(b)
    assert any("unverified_items" in p for p in problems)


def test_pass_with_nonzero_exit_code_fails():
    b = _good_bundle()
    b["checks"][0]["exit_code"] = 1
    problems = _problems(b)
    assert any("exit_code 1" in p for p in problems)


def test_fail_without_a_blocking_finding_or_failed_check_fails():
    b = _good_bundle()
    b["verdict"] = "FAIL"
    problems = _problems(b)
    assert any("no blocking finding" in p for p in problems)


def test_incomplete_without_anything_unverified_fails():
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    problems = _problems(b)
    assert any("nothing is unverified" in p for p in problems)


def test_missing_required_field_fails():
    b = _good_bundle()
    del b["revision"]
    problems = _problems(b)
    assert any("revision" in p for p in problems)


def test_dirty_tree_without_dirty_files_fails():
    b = _good_bundle()
    b["working_tree_state"] = "dirty"
    problems = _problems(b)
    assert any("dirty_files" in p for p in problems)


def test_fail_first_never_shown_failing_fails():
    b = _good_bundle()
    b["fail_first"]["failed_before"] = False
    problems = _problems(b)
    assert any("never shown failing" in p for p in problems)


def test_fail_first_not_applicable_needs_a_note():
    b = _good_bundle()
    b["fail_first"]["method"] = "not-applicable"
    problems = _problems(b)
    assert any("no note" in p for p in problems)
    # not-applicable with a note is only acceptable when the change has
    # no behaviour to test: a docs-only change, not a bug-fix.
    b["fail_first"]["note"] = "Docs-only change; no behaviour to test."
    b["fail_first"]["failed_before"] = False
    b["fail_first"]["passed_after"] = False
    b["verification_plan"]["change_type"] = "docs-only"
    b["verification_plan"]["required_gates"] = []
    b["verification_plan"]["not_applicable_gates"] = [
        {"gate": "build", "reason": "Docs-only change; nothing to build."},
        {"gate": "lint", "reason": "Docs-only change; no code to lint."},
        {"gate": "typecheck", "reason": "Docs-only change; nothing to typecheck."},
        {"gate": "test", "reason": "Docs-only change; no behaviour to test."},
    ]
    assert _problems(b) == []


# --- Round-3 regression tests (reviewer 4, section 3). Each of these
# failed or crashed on the old validator; they are the red-first
# tests for the rewrite. ---


def test_schema_version_true_fails():
    # True == 1 in Python; the schema says const 1, a boolean is not 1.
    b = _good_bundle()
    b["schema_version"] = True
    assert any("schema_version" in p for p in _problems(b))


def test_exit_code_false_fails():
    # False is an int subclass; an exit code must be a real integer.
    b = _good_bundle()
    b["checks"][0]["exit_code"] = False
    assert any("exit_code" in p for p in _problems(b))


def test_acceptance_criteria_non_string_fails():
    b = _good_bundle()
    b["acceptance_criteria"] = [123]
    assert any("acceptance_criteria" in p for p in _problems(b))


def test_check_name_command_cwd_must_be_non_empty_strings():
    b = _good_bundle()
    b["checks"][0]["name"] = 123
    b["checks"][0]["command"] = None
    b["checks"][0]["cwd"] = ""
    problems = _problems(b)
    assert any("checks[0].name" in p for p in problems)
    assert any("checks[0].command" in p for p in problems)
    assert any("checks[0].cwd" in p for p in problems)


def test_extra_top_level_key_fails():
    b = _good_bundle()
    b["surprise_field"] = "not in the schema"
    assert any("surprise_field" in p for p in _problems(b))


def test_extra_check_key_fails():
    b = _good_bundle()
    b["checks"][0]["surprise_field"] = "not in the schema"
    assert any("surprise_field" in p for p in _problems(b))


def test_fail_first_string_false_fails():
    # "false" is truthy; failed_before/passed_after must be booleans.
    b = _good_bundle()
    b["fail_first"]["failed_before"] = "false"
    b["fail_first"]["passed_after"] = "false"
    problems = _problems(b)
    assert any("failed_before" in p for p in problems)
    assert any("passed_after" in p for p in problems)


def _run_cli(bundle):
    """Run the validator as a subprocess on a temp bundle file.

    A crash must surface here as a traceback on stderr, not as a
    clean failure, so these tests prove the no-crash fix.
    """
    import json
    import subprocess
    import tempfile

    validator = Path(__file__).resolve().parent / "validate_evidence.py"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(bundle, f)
        path = f.name
    proc = subprocess.run([sys.executable, str(validator), path], capture_output=True, text=True)
    Path(path).unlink()
    return proc


def test_checks_null_reports_without_crash():
    b = _good_bundle()
    b["checks"] = None
    proc = _run_cli(b)
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "checks" in proc.stdout


def test_findings_null_reports_without_crash():
    b = _good_bundle()
    b["findings"] = None
    proc = _run_cli(b)
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "findings" in proc.stdout


def test_fail_plus_incomplete_forces_fail_verdict():
    b = _good_bundle()
    b["checks"].append(
        {
            "name": "lint",
            "command": "ruff check",
            "cwd": "/repo",
            "exit_code": 1,
            "verdict": "FAIL",
            "tool_version": "ruff 0.17.4",
            "started_at": "2026-11-06T10:00:00Z",
            "finished_at": "2026-11-06T10:00:01Z",
        }
    )
    b["checks"].append(
        {
            "name": "typecheck",
            "command": "tsc",
            "cwd": "/repo",
            "exit_code": 2,
            "verdict": "INCOMPLETE",
            "tool_version": "tsc 5.0.0",
            "started_at": "2026-11-06T10:00:00Z",
            "finished_at": "2026-11-06T10:00:01Z",
        }
    )
    b["verdict"] = "INCOMPLETE"
    problems = _problems(b)
    assert any("FAIL" in p for p in problems)


def test_blocking_finding_plus_incomplete_forces_fail_verdict():
    b = _good_bundle()
    b["findings"] = [
        {
            "file": "src/x.ts",
            "line": 12,
            "evidence": "crashes on empty input",
            "severity": "blocking",
        }
    ]
    b["unverified_items"] = ["the 3.9 matrix has never run"]
    b["verdict"] = "INCOMPLETE"
    problems = _problems(b)
    assert any("FAIL" in p for p in problems)


def test_pass_without_verification_plan_fails():
    # One passing check must not stand for all required gates: a PASS
    # needs a plan naming the gates and their coverage.
    b = _good_bundle()
    b.pop("verification_plan", None)
    problems = _problems(b)
    assert any("verification_plan" in p for p in problems)


def test_pass_with_uncovered_required_gate_fails():
    b = _good_bundle()
    b["verification_plan"]["required_gates"] = ["test", "lint", "typecheck"]
    problems = _problems(b)
    assert any("typecheck" in p for p in problems)


def test_pass_with_only_test_gate_fails():
    # Round-4 regression (reviewer 4, section 3.2): a bug-fix verified
    # by the test gate alone used to PASS — lint, build and typecheck
    # were never even mentioned. Every canonical gate must now be
    # required or explicitly waived with a reason.
    b = _good_bundle()
    b["verification_plan"]["required_gates"] = ["test"]
    b["verification_plan"]["not_applicable_gates"] = []
    problems = _problems(b)
    assert any("lint" in p for p in problems)
    assert any("build" in p for p in problems)
    assert any("typecheck" in p for p in problems)


def test_not_applicable_gate_needs_a_reason():
    b = _good_bundle()
    b["verification_plan"]["required_gates"] = ["test"]
    b["verification_plan"]["not_applicable_gates"] = [{"gate": "typecheck"}]
    problems = _problems(b)
    assert any("reason" in p for p in problems)
    b["verification_plan"]["not_applicable_gates"] = [
        {"gate": "build", "reason": "Python scripts have no build step."},
        {"gate": "typecheck", "reason": "No typechecker in this Python project."},
    ]
    b["verification_plan"]["required_gates"] = ["test", "lint"]
    assert _problems(b) == []


def test_validator_is_self_contained_outside_the_repo(tmp_path):
    """The validator and its schema live inside the orcinus-verify
    skill folder and resolve relative to the script, so they work
    from a user project with no repo checkout: copy the skill folder
    elsewhere, run the validator from there, and the good bundle
    still validates. The old layout (scripts/ + evals/ at the repo
    root) only worked inside a full-repo install — in an npx-skills
    install (skill folders only) both files were absent."""
    import json
    import shutil
    import subprocess

    skill = Path(__file__).resolve().parent.parent
    assert (skill / "scripts" / "validate_evidence.py").is_file()
    assert (skill / "references" / "evidence.schema.json").is_file()
    elsewhere = tmp_path / "some-project"
    shutil.copytree(skill, elsewhere / "orcinus-verify")
    bundle = elsewhere / "bundle.json"
    bundle.write_text(json.dumps(_good_bundle()), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(elsewhere / "orcinus-verify" / "scripts" / "validate_evidence.py"),
            str(bundle),
        ],
        capture_output=True,
        text=True,
        cwd=elsewhere,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# --- Round-4 regression tests (reviewers 3 and 4, on cbb1bdf5).
# Each of these passed (or was untestable) on the old validator; they
# are the red-first tests for the v0.9.1 rewrite of the validator
# and the evidence schema (schema_version 1 -> 2). ---


def test_pass_without_fail_first_fails():
    # A behaviour-change PASS with no fail_first at all used to pass:
    # check_fail_first returned silently when the field was absent.
    b = _good_bundle()
    b.pop("fail_first", None)
    problems = _problems(b)
    assert any("fail_first" in p for p in problems)


def test_pass_with_fail_first_not_applicable_for_bug_fix_fails():
    # not-applicable with a note is only for changes with no behaviour
    # to test. A bug-fix cannot waive the red proof by assertion.
    b = _good_bundle()
    b["fail_first"]["method"] = "not-applicable"
    b["fail_first"]["note"] = "No behaviour to test."
    b["fail_first"]["failed_before"] = False
    b["fail_first"]["passed_after"] = False
    problems = _problems(b)
    assert any("not-applicable" in p for p in problems)


def test_docs_only_pass_without_fail_first_passes():
    # A docs-only change has no behaviour to test, so no fail_first
    # is needed — but every canonical gate must still be accounted
    # for, required or waived with a reason.
    b = _good_bundle()
    b.pop("fail_first", None)
    b["verification_plan"]["change_type"] = "docs-only"
    b["verification_plan"]["required_gates"] = []
    b["verification_plan"]["not_applicable_gates"] = [
        {"gate": "build", "reason": "Docs-only change; nothing to build."},
        {"gate": "lint", "reason": "Docs-only change; no code to lint."},
        {"gate": "typecheck", "reason": "Docs-only change; nothing to typecheck."},
        {"gate": "test", "reason": "Docs-only change; no behaviour to test."},
    ]
    assert _problems(b) == []


def test_finding_without_severity_fails():
    # severity is required: a finding without one used to be treated
    # as non-blocking (fail-open).
    b = _good_bundle()
    b["findings"] = [{"file": "src/x.ts", "line": 12, "evidence": "crashes on empty input"}]
    problems = _problems(b)
    assert any("severity" in p for p in problems)


def test_severity_less_finding_is_blocking():
    # Fail-closed: anything not explicitly "non-blocking" counts as
    # blocking in the verdict computation itself.
    assert (
        ve.expected_verdict(
            {"findings": [{"severity": "blocking"}], "checks": [], "unverified_items": []}
        )
        == "FAIL"
    )
    assert ve.expected_verdict({"findings": [{}], "checks": [], "unverified_items": []}) == "FAIL"
    assert (
        ve.expected_verdict(
            {"findings": [{"severity": "non-blocking"}], "checks": [], "unverified_items": []}
        )
        == "PASS"
    )


def test_schema_check_name_example_must_not_mention_fail_first():
    # The schema's own example invited recording the red run as a
    # check named 'fail-first' — which the exit-code rule then
    # rejects. The red run belongs in fail_first, never in checks.
    name_desc = _SCHEMA["properties"]["checks"]["items"]["properties"]["name"]["description"]
    assert "fail-first" not in name_desc


def test_check_without_timestamps_or_tool_version_fails():
    b = _good_bundle()
    for field in ("tool_version", "started_at", "finished_at"):
        del b["checks"][0][field]
    problems = _problems(b)
    assert any("tool_version" in p for p in problems)
    assert any("started_at" in p for p in problems)
    assert any("finished_at" in p for p in problems)


def test_finished_before_started_fails():
    b = _good_bundle()
    b["checks"][0]["started_at"] = "2026-11-06T10:00:00Z"
    b["checks"][0]["finished_at"] = "2026-11-06T09:00:00Z"
    problems = _problems(b)
    assert any("finished_at" in p for p in problems)


def test_missing_stdout_artifact_fails(tmp_path):
    # An artifact path that does not exist (relative to the bundle)
    # must fail: a claimed output nobody can read is not evidence.
    import json

    b = _good_bundle()
    b["checks"][0]["stdout_artifact"] = "logs/pytest-stdout.log"
    b["checks"][0]["stderr_artifact"] = "logs/pytest-stderr.log"
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps(b), encoding="utf-8")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("stdout_artifact" in p for p in problems)
    assert any("stderr_artifact" in p for p in problems)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "pytest-stdout.log").write_text("ok")
    (tmp_path / "logs" / "pytest-stderr.log").write_text("")
    assert ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path) == []


def test_date_only_timestamp_fails():
    b = _good_bundle()
    b["checks"][0]["started_at"] = "2026-11-06"
    problems = _problems(b)
    assert any("started_at" in p for p in problems)


def test_naive_timestamp_fails():
    b = _good_bundle()
    b["checks"][0]["started_at"] = "2026-11-06T10:00:00"
    problems = _problems(b)
    assert any("started_at" in p for p in problems)


def test_week_date_timestamp_fails():
    # fromisoformat accepts ISO week dates on 3.11+ but not on 3.10:
    # acceptance must not depend on the Python version.
    b = _good_bundle()
    b["checks"][0]["started_at"] = "2026-W45-5"
    problems = _problems(b)
    assert any("started_at" in p for p in problems)


def test_rfc3339_with_offset_passes():
    b = _good_bundle()
    b["checks"][0]["started_at"] = "2026-11-06T10:00:00+03:30"
    b["checks"][0]["finished_at"] = "2026-11-06T10:00:12+03:30"
    assert _problems(b) == []


def test_honest_incomplete_with_failed_fail_first_is_valid():
    # A verifier that honestly reports "no red proof" with verdict
    # INCOMPLETE used to be rejected as an invalid bundle. The
    # fail-first flags are PASS rules, not validity rules.
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    b["fail_first"]["failed_before"] = False
    b["fail_first"]["passed_after"] = False
    b["unverified_items"] = ["no red proof: the test never ran pre-fix"]
    assert _problems(b) == []


def test_honest_incomplete_without_acceptance_criteria_is_valid():
    # The schema itself says: with no acceptance criteria the
    # verification must stop (INCOMPLETE), not invent them. Recording
    # that stop must be possible.
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    b["acceptance_criteria"] = []
    b["unverified_items"] = ["no acceptance criteria were given; stopped"]
    assert _problems(b) == []


def test_pass_without_acceptance_criteria_fails():
    b = _good_bundle()
    b["acceptance_criteria"] = []
    problems = _problems(b)
    assert any("acceptance_criteria" in p for p in problems)


def test_change_type_must_be_a_known_value():
    b = _good_bundle()
    b["verification_plan"]["change_type"] = "whatever"
    problems = _problems(b)
    assert any("change_type" in p for p in problems)


def test_old_schema_version_is_rejected():
    # The v0.9.1 schema (version 2) adds required fields and rules;
    # a v1 bundle must not silently pass under it.
    b = _good_bundle()
    b["schema_version"] = 1
    problems = _problems(b)
    assert any("schema_version" in p for p in problems)
