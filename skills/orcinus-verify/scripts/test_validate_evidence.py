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
        "schema_version": 5,
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
                "stdout_text": "test_capture_persian_only passed; 45 passed in 0.42s",
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
                "stdout_text": "All checks passed!",
            },
        ],
        "findings": [],
        "unresolved_risks": [],
        "unverified_items": [],
        "verdict": "PASS",
        "reviewer_identity": "orcinus-verify (independent session)",
        "implementer_identity": "implementer (author session)",
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
            "red_check": {
                "command": "python3 -m pytest -q -k test_capture_persian_only",
                "exit_code": 1,
                "stdout_text": "FAILED test_capture_persian_only - AssertionError: Persian-only idea raised",
            },
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
    b["files_changed"] = ["README.md"]
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
    b["files_changed"] = ["README.md"]
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
    # blocking in the verdict computation itself. The non-blocking
    # case needs a passing check: since v3 an empty checks list
    # means "stopped before the first check" and is INCOMPLETE,
    # not PASS.
    assert (
        ve.expected_verdict(
            {"findings": [{"severity": "blocking"}], "checks": [], "unverified_items": []}
        )
        == "FAIL"
    )
    assert ve.expected_verdict({"findings": [{}], "checks": [], "unverified_items": []}) == "FAIL"
    assert (
        ve.expected_verdict(
            {
                "findings": [{"severity": "non-blocking"}],
                "checks": [{"verdict": "PASS"}],
                "unverified_items": [],
            }
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
    # Since v3 the artifact also needs its sha256 recorded.
    import hashlib
    import json

    b = _good_bundle()
    b["checks"][0]["stdout_artifact"] = "logs/pytest-stdout.log"
    b["checks"][0]["stderr_artifact"] = "logs/pytest-stderr.log"
    b["checks"][0].pop("stdout_text", None)
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps(b), encoding="utf-8")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("stdout_artifact" in p for p in problems)
    assert any("stderr_artifact" in p for p in problems)
    (tmp_path / "logs").mkdir()
    # write_bytes, not write_text: the sha256 is computed over these
    # exact bytes, and text mode translates "\n" to "\r\n" on Windows
    # — the bytes on disk would no longer match the recorded hash.
    (tmp_path / "logs" / "pytest-stdout.log").write_bytes(b"test_capture_persian_only passed\n")
    (tmp_path / "logs" / "pytest-stderr.log").write_bytes(b"")
    b["checks"][0]["stdout_sha256"] = hashlib.sha256(
        b"test_capture_persian_only passed\n"
    ).hexdigest()
    b["checks"][0]["stderr_sha256"] = hashlib.sha256(b"").hexdigest()
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
    # The v0.9.3 schema (version 4) adds required fields and rules;
    # a v3 bundle must not silently pass under it.
    b = _good_bundle()
    b["schema_version"] = 3
    problems = _problems(b)
    assert any("schema_version" in p for p in problems)


def test_pass_check_without_any_output_fails():
    # F4 (round 5): a PASS bundle whose checks carry no output at
    # all — no artifact, no inline text — used to validate. The
    # validator proved the bundle was complete and self-consistent,
    # not that any check really ran.
    b = _good_bundle()
    for c in b["checks"]:
        c.pop("stdout_text", None)
        c.pop("stderr_text", None)
        c.pop("stdout_artifact", None)
        c.pop("stderr_artifact", None)
    problems = _problems(b)
    assert any("output" in p for p in problems)


def test_artifact_without_sha256_fails(tmp_path):
    # F4 / R3 #19: an artifact without its sha256 is a claim nobody
    # can verify — the file could have been replaced after the run.
    b = _good_bundle()
    b["checks"][0]["stdout_artifact"] = "logs/pytest-stdout.log"
    b["checks"][0].pop("stdout_text", None)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "pytest-stdout.log").write_text("ok")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("sha256" in p for p in problems)


def test_artifact_with_wrong_sha256_fails(tmp_path):
    # The hash must match the file, or the artifact changed since
    # the bundle was written.
    b = _good_bundle()
    b["checks"][0]["stdout_artifact"] = "logs/pytest-stdout.log"
    b["checks"][0]["stdout_sha256"] = "0" * 64
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "pytest-stdout.log").write_text("ok")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("sha256" in p for p in problems)


def test_artifact_with_correct_sha256_passes(tmp_path):
    # Control for the two tests above: artifact + matching hash is
    # valid evidence.
    import hashlib

    b = _good_bundle()
    content = "2 passed in 0.12s\n"
    b["checks"][0]["stdout_artifact"] = "logs/pytest-stdout.log"
    b["checks"][0]["stdout_sha256"] = hashlib.sha256(content.encode()).hexdigest()
    (tmp_path / "logs").mkdir()
    # write_bytes, not write_text: the sha256 is computed over these
    # exact bytes, and text mode translates "\n" to "\r\n" on Windows
    # — the bytes on disk would no longer match the recorded hash.
    (tmp_path / "logs" / "pytest-stdout.log").write_bytes(content.encode())
    assert ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path) == []


def test_artifact_with_crlf_bytes_and_lf_hash_fails(tmp_path):
    # Round-6 follow-up (Windows CI): the two tests above failed on
    # Windows because their fixtures hashed the LF string but wrote
    # the log with write_text — text mode translates "\n" to "\r\n"
    # on Windows, so the bytes on disk no longer matched the recorded
    # hash. That is the validator working correctly, not a bug in it:
    # the sha256 is over exact bytes and must stay strict. This test
    # pins that strictness — a CRLF file with an LF hash must still
    # fail — which is also why the artifact fixtures must use
    # write_bytes.
    import hashlib

    b = _good_bundle()
    content = "2 passed in 0.12s\n"
    b["checks"][0]["stdout_artifact"] = "logs/pytest-stdout.log"
    b["checks"][0]["stdout_sha256"] = hashlib.sha256(content.encode()).hexdigest()
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "pytest-stdout.log").write_bytes(content.replace("\n", "\r\n").encode())
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("sha256" in p for p in problems)


def test_sha256_must_be_hex():
    # The schema pins the hash format: 64 lowercase hex chars.
    b = _good_bundle()
    b["checks"][0]["stdout_artifact"] = "logs/out.log"
    b["checks"][0]["stdout_sha256"] = "not-a-hash"
    problems = _problems(b)
    assert any("sha256" in p for p in problems)


def test_incomplete_with_no_checks_and_stop_reason_is_valid():
    # F5 (round 5): the verifier stopped before the first check
    # (no acceptance criteria) — the bundle records the stop with
    # a reason instead of inventing a check. The old schema
    # rejected checks: [] (minItems 1) and had no reason field, so
    # the stop the SKILL.md promises could not be filed.
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    b["acceptance_criteria"] = []
    b["checks"] = []
    b["stop_reason"] = "no acceptance criteria were given; stopped"
    b["unverified_items"] = ["no acceptance criteria were given; stopped"]
    assert _problems(b) == []


def test_empty_checks_without_stop_reason_fails():
    # An empty checks list with no recorded reason is not an
    # honest stop — it is a bundle that says nothing.
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    b["acceptance_criteria"] = []
    b["checks"] = []
    b["unverified_items"] = ["no acceptance criteria were given; stopped"]
    problems = _problems(b)
    assert any("stop_reason" in p for p in problems)


def test_empty_checks_with_pass_verdict_fails():
    # No checks can never be a PASS, even with a stop reason.
    b = _good_bundle()
    b["checks"] = []
    b["stop_reason"] = "no acceptance criteria were given; stopped"
    problems = _problems(b)
    assert problems


# --- Round-6 regression tests (M5–M8). Each of these passed on the
# old validator; they are the red-first tests for this fix pass. ---


def _artifact_bundle(tmp_path, artifact, content):
    """A good bundle whose test check records `artifact` with the
    sha256 of `content`, written under tmp_path. Returns the bundle;
    the caller places the file (or link) itself."""
    import hashlib

    b = _good_bundle()
    b["checks"][0]["stdout_artifact"] = artifact
    b["checks"][0]["stdout_sha256"] = hashlib.sha256(content).hexdigest()
    b["checks"][0].pop("stdout_text", None)
    return b


def test_artifact_absolute_path_fails(tmp_path):
    # M5 (V3 / 2-V3 / 3-P1-5): an absolute path overrides the bundle
    # directory, so a file outside the bundle used to hash and pass.
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"not in the bundle")
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    b = _artifact_bundle(bundle_dir, str(outside), b"not in the bundle")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=bundle_dir)
    assert any("absolute" in p for p in problems)


def test_artifact_traversal_fails(tmp_path):
    # M5: a ../ path that resolves outside the bundle must fail,
    # even with the correct sha256.
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"not in the bundle")
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    b = _artifact_bundle(bundle_dir, "../outside.txt", b"not in the bundle")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=bundle_dir)
    assert any("outside" in p or "escapes" in p for p in problems)


def test_artifact_symlink_fails(tmp_path):
    # M5: a symlink inside the bundle pointing outside it must fail,
    # even when the target has the recorded hash.
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"not in the bundle")
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "link.txt").symlink_to(outside)
    b = _artifact_bundle(bundle_dir, "link.txt", b"not in the bundle")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=bundle_dir)
    assert any("symlink" in p for p in problems)


def test_artifact_without_bundle_dir_is_unverified():
    # M5 (3-P1-5, API half): validate_bundle with bundle_dir=None
    # used to return [] for an artifact it never checked — "not
    # checked" silently equated with "passed". The artifact must be
    # recorded as explicitly unverified.
    b = _good_bundle()
    b["checks"][0]["stdout_artifact"] = "logs/out.log"
    b["checks"][0]["stdout_sha256"] = "0" * 64
    b["checks"][0].pop("stdout_text", None)
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=None)
    assert any("unverified" in p for p in problems)


def test_artifact_over_size_cap_fails(tmp_path):
    # M5: a huge artifact must fail instead of being read fully
    # into memory (the old code hashed with read_bytes()).
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    content = b"x" * (ve.MAX_ARTIFACT_BYTES + 1)
    (bundle_dir / "big.log").write_bytes(content)
    b = _artifact_bundle(bundle_dir, "big.log", content)
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=bundle_dir)
    assert any("larger than" in p for p in problems)


def test_fail_first_without_red_check_fails():
    # M6 (V1 / 2-V1): the red proof was only two booleans. A PASS
    # for a behaviour change now needs the red run itself: command,
    # non-zero exit code, and output.
    b = _good_bundle()
    b["fail_first"].pop("red_check", None)
    problems = _problems(b)
    assert any("red_check" in p for p in problems)


def test_fail_first_red_check_zero_exit_fails():
    # A red run that exits 0 is not a red.
    b = _good_bundle()
    b["fail_first"]["red_check"] = {
        "command": "python3 -m pytest -q -k test_capture_persian_only",
        "exit_code": 0,
        "stdout_text": "FAILED test_capture_persian_only - AssertionError",
    }
    problems = _problems(b)
    assert any("red_check" in p and "exit" in p for p in problems)


def test_fail_first_unlinked_test_name_fails():
    # M6 (2-V1): a bundle naming "nonexistent_test" used to pass —
    # check_fail_first never read fail_first.test at all. The test
    # id must appear in the red output and in the green check.
    b = _good_bundle()
    b["fail_first"]["test"] = "nonexistent_test"
    problems = _problems(b)
    assert any("nonexistent_test" in p for p in problems)


def test_fail_first_test_missing_from_red_output_fails():
    b = _good_bundle()
    b["fail_first"]["red_check"] = {
        "command": "python3 -m pytest -q -k test_capture_persian_only",
        "exit_code": 1,
        "stdout_text": "1 failed, 1 passed in 0.12s",
    }
    problems = _problems(b)
    assert any("red" in p and "test_capture_persian_only" in p for p in problems)


def test_fail_first_test_missing_from_green_check_fails():
    b = _good_bundle()
    b["checks"][0]["stdout_text"] = "45 passed in 0.42s"
    problems = _problems(b)
    assert any("test_capture_persian_only" in p for p in problems)


def test_whitespace_only_stdout_text_fails():
    # M8 (2-V2): stdout_text=" " used to count as output. Output
    # must contain a non-whitespace character.
    b = _good_bundle()
    b["checks"][0]["stdout_text"] = " "
    problems = _problems(b)
    assert any("stdout_text" in p for p in problems)


def test_empty_tool_version_fails():
    # M8 (2-V2): tool_version="" used to pass (presence only).
    b = _good_bundle()
    b["checks"][0]["tool_version"] = ""
    problems = _problems(b)
    assert any("tool_version" in p for p in problems)


def test_noop_command_fails():
    # M8 (2-V2): command="true" for the test gate used to pass
    # with exit 0 and whitespace output. A no-op command proves
    # nothing ran.
    for noop in ("true", "false", ":", "echo", "exit 0"):
        b = _good_bundle()
        b["checks"][0]["command"] = noop
        problems = _problems(b)
        assert any("no-op" in p for p in problems), noop


def test_bad_revision_fails():
    # M8 (2-V2): revision="not-a-sha!!" used to pass (minLength 1
    # only). A revision is a hex SHA or 'working-tree'.
    b = _good_bundle()
    b["revision"] = "not-a-sha!!"
    problems = _problems(b)
    assert any("revision" in p for p in problems)


def test_missing_implementer_identity_fails():
    # M8 (2-V2): implementer_identity did not exist at all, so the
    # "verifier != implementer" condition had nothing to compare
    # against. It is now required.
    b = _good_bundle()
    b.pop("implementer_identity", None)
    problems = _problems(b)
    assert any("implementer_identity" in p for p in problems)


def test_reviewer_is_implementer_fails():
    # M8 (2-V2): reviewer_identity="implementer" used to pass. The
    # verifier must differ from the implementer.
    b = _good_bundle()
    b["implementer_identity"] = "the-author"
    b["reviewer_identity"] = "the-author"
    problems = _problems(b)
    assert any("differ" in p for p in problems)
    b = _good_bundle()
    b["reviewer_identity"] = "implementer"
    problems = _problems(b)
    assert any("implementer" in p for p in problems)


# --- Round-6 Track 4 regression tests (P1 verifier: V2, V4, V5, V8,
# 2-V4, 2-V5, 2-V6, 2-V7). Each of these passed on the old validator;
# they are the red-first tests for this fix pass. ---


def _docs_only_no_checks_bundle():
    """A docs-only PASS with no checks at all: every canonical gate
    waived with a reason, so there is nothing to run — the 2-V5 case.
    """
    b = _good_bundle()
    b.pop("fail_first", None)
    b["checks"] = []
    b["files_changed"] = ["README.md"]
    b["verification_plan"]["change_type"] = "docs-only"
    b["verification_plan"]["required_gates"] = []
    b["verification_plan"]["not_applicable_gates"] = [
        {"gate": "build", "reason": "Docs-only change; nothing to build."},
        {"gate": "lint", "reason": "Docs-only change; no code to lint."},
        {"gate": "typecheck", "reason": "Docs-only change; nothing to typecheck."},
        {"gate": "test", "reason": "Docs-only change; no behaviour to test."},
    ]
    return b


def test_config_only_with_code_file_fails():
    # V2: a behavioural change labelled config-only used to escape
    # both fail-first and the test gate — the validator never read
    # files_changed at all.
    b = _good_bundle()
    b["verification_plan"]["change_type"] = "config-only"
    b["files_changed"] = ["src/a.py"]
    problems = _problems(b)
    assert any("config-only" in p and "src/a.py" in p for p in problems)


def test_docs_only_with_code_file_fails():
    # V2, docs-only half: same bypass with a .py file.
    b = _good_bundle()
    b["verification_plan"]["change_type"] = "docs-only"
    b["files_changed"] = ["skills/x/scripts/y.py"]
    problems = _problems(b)
    assert any("docs-only" in p for p in problems)


def test_docs_only_with_docs_files_passes():
    # V2 control: a docs-only change touching only docs is fine.
    b = _docs_only_no_checks_bundle()
    b["files_changed"] = ["README.md", "docs/guide.md"]
    assert _problems(b) == []


def test_pass_on_dirty_tree_without_diff_hash_fails():
    # V4: PASS on a dirty tree used to be accepted although the
    # schema ties PASS to a revision and a dirty tree has none. The
    # PASS must pin the diff it ran on (git diff HEAD | sha256sum).
    b = _good_bundle()
    b["working_tree_state"] = "dirty"
    b["dirty_files"] = ["skills/x/scripts/y.py"]
    b["revision"] = "working-tree"
    problems = _problems(b)
    assert any("dirty" in p and "diff" in p for p in problems)


def test_pass_on_dirty_tree_with_diff_hash_passes():
    # V4 control: the same dirty PASS with the diff pinned is valid.
    b = _good_bundle()
    b["working_tree_state"] = "dirty"
    b["dirty_files"] = ["skills/x/scripts/y.py"]
    b["revision"] = "working-tree"
    b["diff_sha256"] = "0" * 64
    assert _problems(b) == []


def test_clean_tree_with_dirty_files_fails():
    # V5, second half: dirty_files is "empty otherwise" per the
    # schema, but a clean tree with non-empty dirty_files passed.
    b = _good_bundle()
    b["dirty_files"] = ["skills/x/scripts/y.py"]
    problems = _problems(b)
    assert any("dirty_files" in p for p in problems)


def test_gate_in_both_required_and_waived_fails():
    # V5 / 2-V7 overlap half: a gate in both required_gates and
    # not_applicable_gates used to be accepted.
    b = _good_bundle()
    b["verification_plan"]["not_applicable_gates"] = [
        {"gate": "lint", "reason": "Waived and required at once."},
        {"gate": "build", "reason": "Python scripts have no build step."},
        {"gate": "typecheck", "reason": "No typechecker in this Python project."},
    ]
    problems = _problems(b)
    assert any("lint" in p and ("both" in p or "required" in p) for p in problems)


def _run_cli_bytes(raw):
    """Run the validator CLI on a temp file with these exact bytes."""
    import subprocess
    import tempfile

    validator = Path(__file__).resolve().parent / "validate_evidence.py"
    with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False) as f:
        f.write(raw)
        path = f.name
    proc = subprocess.run([sys.executable, str(validator), path], capture_output=True, text=True)
    Path(path).unlink()
    return proc


def test_non_utf8_bundle_exits_2_without_traceback():
    # 2-V4: a non-UTF-8 file raised an uncaught UnicodeDecodeError
    # with a traceback and exit 1, against the "never a traceback"
    # docstring. It is a controlled error: exit 2, no traceback.
    proc = _run_cli_bytes(b'{"schema_version": 4, "bad": "\xff\xfe"}')
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr


def test_deeply_nested_json_exits_2_without_traceback():
    # 2-V4: 20,000 levels of nesting raised an uncaught
    # RecursionError with a traceback and exit 1.
    proc = _run_cli_bytes(("[" * 20000 + "]" * 20000).encode())
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr


def test_docs_only_pass_with_no_checks_passes():
    # 2-V5: docs-only with all gates waived and no checks used to be
    # forced INCOMPLETE, while the schema says required_gates may be
    # empty and the SKILL says "do not fabricate a check".
    assert _problems(_docs_only_no_checks_bundle()) == []


def test_config_only_pass_with_no_checks_passes():
    # 2-V5, config-only half.
    b = _docs_only_no_checks_bundle()
    b["verification_plan"]["change_type"] = "config-only"
    assert _problems(b) == []


def test_docs_only_pass_with_no_checks_needs_all_gates_waived():
    # 2-V5 boundary: the empty-checks PASS is only for a fully
    # waived plan — a docs-only change with a gate never mentioned
    # still fails (silence is not a waiver).
    b = _docs_only_no_checks_bundle()
    b["verification_plan"]["not_applicable_gates"] = [
        {"gate": "build", "reason": "Docs-only change; nothing to build."},
    ]
    problems = _problems(b)
    assert any("lint" in p or "test" in p for p in problems)


def test_iso8601_fractional_digits_pinned():
    # 2-V6: the regex accepted any number of fractional digits and
    # fromisoformat then behaved differently on 3.10 (only 3 or 6
    # digits) vs 3.12. Only 3 or 6 digits are accepted now.
    for frac in (".1", ".12", ".1234", ".12345", ".1234567"):
        b = _good_bundle()
        b["checks"][0]["started_at"] = f"2026-11-06T10:00:00{frac}Z"
        assert any("started_at" in p for p in _problems(b)), frac
    for frac in (".123", ".123456"):
        b = _good_bundle()
        b["checks"][0]["started_at"] = f"2026-11-06T10:00:00{frac}Z"
        assert _problems(b) == [], frac


def test_iso8601_year_bounds():
    # 2-V6: years 1999 / 2100 are outside the sane range for a
    # verification timestamp (2000-2099).
    b = _good_bundle()
    b["checks"][0]["started_at"] = "1999-11-06T10:00:00Z"
    assert any("started_at" in p for p in _problems(b))
    b = _good_bundle()
    b["checks"][0]["started_at"] = "2100-11-06T10:00:00Z"
    assert any("started_at" in p for p in _problems(b))
    b = _good_bundle()
    b["checks"][0]["started_at"] = "2099-11-06T10:00:00Z"
    b["checks"][0]["finished_at"] = "2099-11-06T10:00:12Z"
    assert _problems(b) == []


def test_security_finding_cannot_be_non_blocking():
    # 2-V7: a "SQL injection" finding labelled non-blocking used to
    # PASS — the findings schema had no category, so severity was
    # purely self-declared. Security / data-loss categories are
    # automatically blocking.
    for category in ("security", "data-loss"):
        b = _good_bundle()
        b["findings"] = [
            {
                "file": "src/x.py",
                "line": 12,
                "evidence": "SQL injection via string concat",
                "severity": "non-blocking",
                "category": category,
            }
        ]
        problems = _problems(b)
        assert any("blocking" in p for p in problems), category


def test_non_blocking_finding_needs_a_category():
    # 2-V7: without a category the auto-blocking rule could be
    # dodged by omitting it — a non-blocking claim must say what
    # kind of finding it is.
    b = _good_bundle()
    b["findings"] = [
        {
            "file": "src/x.py",
            "line": 12,
            "evidence": "typo in a comment",
            "severity": "non-blocking",
        }
    ]
    problems = _problems(b)
    assert any("category" in p for p in problems)


def test_non_blocking_finding_with_other_category_passes():
    # 2-V7 control: a genuinely non-blocking finding with a
    # non-security category still passes.
    b = _good_bundle()
    b["findings"] = [
        {
            "file": "src/x.py",
            "line": 12,
            "evidence": "typo in a comment",
            "severity": "non-blocking",
            "category": "other",
        }
    ]
    assert _problems(b) == []


def test_old_schema_version_4_is_rejected():
    # The Track-4 schema change (category + diff hash + new rules)
    # bumps schema_version 4 -> 5; a v4 bundle must not silently
    # pass under v5.
    b = _good_bundle()
    b["schema_version"] = 4
    problems = _problems(b)
    assert any("schema_version" in p for p in problems)


def _run_cli_with_verdict_block(bundle, block_text):
    """Run the validator CLI with --verdict-block on temp files."""
    import json
    import subprocess
    import tempfile

    validator = Path(__file__).resolve().parent / "validate_evidence.py"
    with tempfile.TemporaryDirectory() as d:
        bundle_path = Path(d) / "bundle.json"
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        block_path = Path(d) / "response.md"
        block_path.write_text(block_text, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(validator), str(bundle_path), "--verdict-block", str(block_path)],
            capture_output=True,
            text=True,
        )
        return proc


def _matching_verdict_block():
    # The good bundle's checks are test + lint, both PASS.
    return (
        "Some prose.\n\n```verdict\n"
        '{"verdict": "PASS", "checks": {"test": "PASS", "lint": "PASS"}, '
        '"file": null, "finding": "test and lint pass"}\n```\n'
    )


def test_verdict_block_matching_passes():
    # V8: the prose verdict block and the bundle must agree.
    proc = _run_cli_with_verdict_block(_good_bundle(), _matching_verdict_block())
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_verdict_block_wrong_verdict_fails():
    # V8: a block saying FAIL while the bundle says PASS disagrees.
    block = _matching_verdict_block().replace('"verdict": "PASS"', '"verdict": "FAIL"')
    proc = _run_cli_with_verdict_block(_good_bundle(), block)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "verdict" in proc.stdout


def test_verdict_block_wrong_check_fails():
    # V8: a block saying the test gate FAILED while the bundle says
    # it passed disagrees.
    block = _matching_verdict_block().replace('"test": "PASS"', '"test": "FAIL"')
    proc = _run_cli_with_verdict_block(_good_bundle(), block)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "test" in proc.stdout


def test_verdict_block_missing_fence_fails():
    # V8: no ```verdict fence at all — there is nothing to compare.
    proc = _run_cli_with_verdict_block(_good_bundle(), "No verdict block here.\n")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "verdict" in proc.stdout.lower()
    assert "Traceback" not in proc.stderr


def test_verdict_block_not_json_fails():
    # V8: a ```verdict fence that is not JSON cannot agree with the
    # bundle (the 3-P1-6 attack shape, applied to the block itself).
    proc = _run_cli_with_verdict_block(_good_bundle(), "```verdict\nnot JSON\n```\n")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr


def test_verdict_block_file_not_in_findings_fails():
    # V8: the block names a finding file the bundle has no finding
    # for — the two formats disagree about what was found.
    block = _matching_verdict_block().replace('"file": null', '"file": "src/x.ts"')
    proc = _run_cli_with_verdict_block(_good_bundle(), block)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "src/x.ts" in proc.stdout


# --- Round-7 regression tests (Track 1: F-02, F-03, F-04, F-06, F-11).
# Each of these passed on the v0.9.8 validator; they are the
# red-first tests for this fix pass. ---


def test_noop_exit_code_masking_suffix_fails():
    # F-02: a check whose command masks its own exit code with an
    # always-zero suffix proves nothing ran, however clean the exit
    # code looks. ShellCheck recommends `|| true` as the "ignore the
    # return value" idiom (SC2312), so this is our own regex layer,
    # not a ShellCheck rule.
    masking = [
        "pytest -q || true",
        "pytest -q || /bin/true",
        "pytest -q || /usr/bin/true",
        "pytest -q || :",
        "pytest -q || exit 0",
        "pytest -q ; exit 0",
        "pytest -q ; :",
        "pytest -q | true",
        "bash -c true",
        "bash -c 'pytest -q || true'",
        'sh -c "exit 0"',
        "python3 -c 'pass'",
        "python3 -c 'exit(0)'",
        "python -c 'sys.exit(0)'",
        "python3 -c ''",
    ]
    for cmd in masking:
        b = _good_bundle()
        b["checks"][0]["command"] = cmd
        problems = _problems(b)
        assert any("no-op" in p for p in problems), cmd


def test_noop_masking_in_red_check_fails():
    # F-02: the masking check also applies to fail_first.red_check
    # — a red run whose command always exits 0 is not a red.
    b = _good_bundle()
    b["fail_first"]["red_check"]["command"] = "pytest -q || true"
    problems = _problems(b)
    assert any("no-op" in p for p in problems)


def test_noop_genuine_fallback_passes():
    # F-02 controls: a real fallback, a failure-preserving suffix,
    # a pipe to a real command, a nested shell running a real
    # command, a python -c that actually runs something, and the
    # legitimate `! cmd` absence assertion must NOT be flagged.
    genuine = [
        "pytest -q || ruff check",
        "pytest -q || exit 1",
        "pytest -q ; exit 1",
        "pytest -q ; echo done",
        "pytest -q | grep -q x",
        "bash -c 'pytest -q'",
        "python3 -c 'import sys; sys.exit(pytest.main())'",
        "! pytest -q",
        "pytest -q && exit 0",
        "pytest -q || exit 1",
    ]
    for cmd in genuine:
        b = _good_bundle()
        b["checks"][0]["command"] = cmd
        assert _problems(b) == [], cmd


def test_identity_case_or_whitespace_difference_fails():
    # F-04: reviewer/implementer independence is a comparison of
    # identities, not of spellings — case and surrounding whitespace
    # must not defeat it.
    for reviewer, implementer in [
        ("Alice", "alice"),
        ("alice ", "alice"),
        (" Alice ", "ALICE"),
        (" IMPLEMENTER ", "someone-else"),
        ("Implementer", "someone-else"),
    ]:
        b = _good_bundle()
        b["reviewer_identity"] = reviewer
        b["implementer_identity"] = implementer
        problems = _problems(b)
        assert any("differ" in p or "implementer" in p for p in problems), (
            reviewer,
            implementer,
        )


def test_identity_genuinely_different_passes():
    # F-04 control: genuinely different identities still pass.
    b = _good_bundle()
    b["reviewer_identity"] = "bob (review session)"
    b["implementer_identity"] = "alice (author session)"
    assert _problems(b) == []


def test_behaviour_change_pass_with_empty_files_changed_fails():
    # F-06: a behaviour-change PASS that lists no files changed
    # claims a change that touched nothing. The schema has no
    # minItems on files_changed, so this is a semantic constraint,
    # added here — not a schema change.
    for change_type in ("bug-fix", "feature", "refactor"):
        b = _good_bundle()
        b["verification_plan"]["change_type"] = change_type
        b["files_changed"] = []
        problems = _problems(b)
        assert any("files_changed" in p for p in problems), change_type


def test_docs_only_pass_with_empty_files_changed_passes():
    # F-06 control: the docs-only no-checks exemption must not
    # regress — a docs-only PASS with no files listed (nothing to
    # run, nothing changed in code) is still valid.
    b = _docs_only_no_checks_bundle()
    b["files_changed"] = []
    assert _problems(b) == []


def test_time_order_with_unvalidated_input_reports_instead_of_raising():
    # F-11: check_time_order calls datetime.fromisoformat on strings
    # it assumes the schema validated. Called directly on
    # unvalidated input it raised TypeError (mixed naive/aware) or
    # ValueError (garbage) — a latent coupling if the schema layer
    # is ever relaxed. It must record a problem instead of raising.
    for started, finished in [
        ("2026-11-06T10:00:00Z", "2026-11-06T10:00:00"),  # aware vs naive
        ("not-a-date", "2026-11-06T10:00:00Z"),  # garbage
        ("2026-11-06T10:00:00", "2026-11-06T10:00:00Z"),  # naive vs aware
    ]:
        bundle = {
            "checks": [
                {
                    "name": "test",
                    "started_at": started,
                    "finished_at": finished,
                }
            ]
        }
        problems = []
        ve.check_time_order(bundle, problems)  # must not raise
        assert problems, (started, finished)
        assert any("test" in p for p in problems), problems
