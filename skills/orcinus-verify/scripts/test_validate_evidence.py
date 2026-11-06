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
    Path(__file__).resolve().parent.parent / "references" / "evidence.schema.json")


def _problems(bundle):
    return ve.validate_bundle(bundle, _SCHEMA)


def _good_bundle():
    return {
        "schema_version": 1,
        "revision": "abc1234",
        "working_tree_state": "clean",
        "requirement": "Fix the Persian capture crash.",
        "acceptance_criteria": ["A Persian-only idea captures without a traceback."],
        "files_changed": ["skills/idea-capture/scripts/capture.py"],
        "checks": [
            {"name": "pytest", "command": "python3 -m pytest -q",
             "cwd": "/repo", "exit_code": 0, "verdict": "PASS",
             "tool_version": "pytest 8.4.2"},
        ],
        "findings": [],
        "unresolved_risks": [],
        "unverified_items": [],
        "verdict": "PASS",
        "reviewer_identity": "orcinus-verify (independent session)",
        "verification_plan": {
            "change_type": "bug-fix",
            "required_gates": ["pytest"],
            "not_applicable_gates": [],
        },
        "fail_first": {
            "test": "test_capture_persian_only",
            "failed_before": True,
            "passed_after": True,
            "method": "worktree",
        },
    }


def _problems(bundle):
    return ve.validate_bundle(bundle, _SCHEMA)


def test_good_bundle_passes():
    assert _problems(_good_bundle()) == []


def test_pass_hiding_a_failed_check_fails():
    b = _good_bundle()
    b["checks"][0]["verdict"] = "FAIL"
    problems = _problems(b)
    assert any("FAIL" in p and "PASS" in p for p in problems)


def test_pass_hiding_a_blocking_finding_fails():
    b = _good_bundle()
    b["findings"] = [{"file": "src/x.ts", "line": 12,
                      "evidence": "crashes on empty input",
                      "severity": "blocking"}]
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
    b["fail_first"]["note"] = "Docs-only change; no behaviour to test."
    b["fail_first"]["failed_before"] = False
    b["fail_first"]["passed_after"] = False
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
    with tempfile.NamedTemporaryFile("w", suffix=".json",
                                     delete=False) as f:
        json.dump(bundle, f)
        path = f.name
    proc = subprocess.run([sys.executable, str(validator), path],
                          capture_output=True, text=True)
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
    b["checks"].append({"name": "ruff", "command": "ruff check",
                        "cwd": "/repo", "exit_code": 1, "verdict": "FAIL"})
    b["checks"].append({"name": "typecheck", "command": "tsc",
                        "cwd": "/repo", "exit_code": 2,
                        "verdict": "INCOMPLETE"})
    b["verdict"] = "INCOMPLETE"
    problems = _problems(b)
    assert any("FAIL" in p for p in problems)


def test_blocking_finding_plus_incomplete_forces_fail_verdict():
    b = _good_bundle()
    b["findings"] = [{"file": "src/x.ts", "line": 12,
                      "evidence": "crashes on empty input",
                      "severity": "blocking"}]
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
    b["verification_plan"]["required_gates"] = ["pytest", "ruff"]
    problems = _problems(b)
    assert any("ruff" in p for p in problems)


def test_pass_with_covered_gates_passes():
    b = _good_bundle()
    b["verification_plan"]["required_gates"] = ["pytest"]
    assert _problems(b) == []


def test_not_applicable_gate_needs_a_reason():
    b = _good_bundle()
    b["verification_plan"]["required_gates"] = ["pytest"]
    b["verification_plan"]["not_applicable_gates"] = [
        {"gate": "typecheck"}]
    problems = _problems(b)
    assert any("reason" in p for p in problems)
    b["verification_plan"]["not_applicable_gates"] = [
        {"gate": "typecheck", "reason": "Docs-only change; no types."}]
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
        [sys.executable,
         str(elsewhere / "orcinus-verify" / "scripts" / "validate_evidence.py"),
         str(bundle)],
        capture_output=True, text=True, cwd=elsewhere, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
