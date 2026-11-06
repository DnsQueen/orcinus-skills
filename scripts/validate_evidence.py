#!/usr/bin/env python3
"""Validate an ORCINUS verification evidence bundle against
evals/evidence.schema.json.

The schema is the contract; this script is the gate. It is standard
library only (no jsonschema package), so it checks the fields and the
verdict rules directly rather than interpreting the full JSON Schema:

- every required field is present, with the right type;
- enums hold (verdict, working_tree_state, fail_first.method);
- dirty_files is listed when the tree is dirty;
- the overall verdict is consistent with the checks, the findings, and
  the unverified items: PASS needs every check PASS, no blocking
  finding, and no unverified items anywhere; a blocking finding or a
  FAIL check needs FAIL; an INCOMPLETE check or a non-empty
  unverified_items needs INCOMPLETE (or FAIL, if a blocking finding
  also exists);
- the fail-first proof, when present, must show the test failing
  before the fix and passing after it (unless the method is
  not-applicable, in which case a note must say why).

Usage: python3 scripts/validate_evidence.py <bundle.json>
Exit 0 when the bundle is valid and consistent; exit 1 otherwise,
with each problem on its own line.

The validator does not prove the evidence is true — a bundle can
claim a command passed while the command never ran. It proves the
bundle is complete and self-consistent, so a missing check or a
contradicted verdict cannot slip through as a PASS.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "evals" / "evidence.schema.json"

REQUIRED = (
    "schema_version", "revision", "working_tree_state", "requirement",
    "acceptance_criteria", "files_changed", "checks", "findings",
    "unresolved_risks", "unverified_items", "verdict",
    "reviewer_identity",
)
VERDICTS = ("PASS", "FAIL", "INCOMPLETE")
CHECK_REQUIRED = ("name", "command", "cwd", "exit_code", "verdict")


def fail(problems, msg):
    problems.append(msg)


def check_types(bundle, problems):
    """Required fields, and the type each must have."""
    for field in REQUIRED:
        if field not in bundle:
            fail(problems, f"missing required field: {field}")
    if "schema_version" in bundle and bundle["schema_version"] != 1:
        fail(problems, f"schema_version is {bundle['schema_version']!r}, "
                       "expected 1")
    for field in ("acceptance_criteria", "files_changed", "checks",
                  "findings", "unresolved_risks", "unverified_items"):
        if field in bundle and not isinstance(bundle[field], list):
            fail(problems, f"{field} must be a list")
    for field in ("revision", "requirement", "reviewer_identity"):
        if field in bundle and not isinstance(bundle[field], str):
            fail(problems, f"{field} must be a string")
        elif field in bundle and not bundle[field].strip():
            fail(problems, f"{field} must not be empty")
    if ("acceptance_criteria" in bundle
            and isinstance(bundle["acceptance_criteria"], list)
            and not bundle["acceptance_criteria"]):
        fail(problems, "acceptance_criteria must not be empty")
    if "checks" in bundle and isinstance(bundle["checks"], list):
        if not bundle["checks"]:
            fail(problems, "checks must not be empty")
        for i, check in enumerate(bundle["checks"]):
            if not isinstance(check, dict):
                fail(problems, f"checks[{i}] is not an object")
                continue
            for field in CHECK_REQUIRED:
                if field not in check:
                    fail(problems, f"checks[{i}] is missing {field}")
            if "verdict" in check and check["verdict"] not in VERDICTS:
                fail(problems, f"checks[{i}].verdict is "
                               f"{check['verdict']!r}, expected one of "
                               f"{VERDICTS}")
            if ("exit_code" in check
                    and not isinstance(check["exit_code"], int)):
                fail(problems, f"checks[{i}].exit_code must be an integer")
    if "verdict" in bundle and bundle["verdict"] not in VERDICTS:
        fail(problems, f"verdict is {bundle['verdict']!r}, expected one "
                       f"of {VERDICTS}")
    if ("working_tree_state" in bundle
            and bundle["working_tree_state"] not in ("clean", "dirty")):
        fail(problems, f"working_tree_state is "
                       f"{bundle['working_tree_state']!r}, expected "
                       "'clean' or 'dirty'")
    if bundle.get("working_tree_state") == "dirty":
        if not isinstance(bundle.get("dirty_files"), list) \
                or not bundle["dirty_files"]:
            fail(problems, "working_tree_state is 'dirty' but dirty_files "
                           "is empty or missing")
    for i, finding in enumerate(bundle.get("findings", [])):
        if not isinstance(finding, dict):
            fail(problems, f"findings[{i}] is not an object")
            continue
        if "file" not in finding or "evidence" not in finding:
            fail(problems, f"findings[{i}] needs 'file' and 'evidence'")
        if finding.get("severity") not in (None, "blocking", "non-blocking"):
            fail(problems, f"findings[{i}].severity is "
                           f"{finding.get('severity')!r}")


def check_verdict_consistency(bundle, problems):
    """The overall verdict must follow from the checks, the findings,
    and the unverified items. A PASS that hides a FAIL check or an
    unverified item is the exact failure this gate exists to catch."""
    checks = bundle.get("checks", [])
    findings = bundle.get("findings", [])
    unverified = bundle.get("unverified_items", [])
    verdict = bundle.get("verdict")
    if verdict not in VERDICTS:
        return
    blocking = [f for f in findings
                if isinstance(f, dict) and f.get("severity") == "blocking"]
    failed_checks = [c for c in checks
                     if isinstance(c, dict) and c.get("verdict") == "FAIL"]
    incomplete_checks = [c for c in checks
                         if isinstance(c, dict)
                         and c.get("verdict") == "INCOMPLETE"]
    check_unverified = [c for c in checks
                        if isinstance(c, dict)
                        and c.get("unverified_items")]
    nonzero_exit_pass = [c for c in checks
                         if isinstance(c, dict)
                         and c.get("verdict") == "PASS"
                         and isinstance(c.get("exit_code"), int)
                         and c["exit_code"] != 0]
    for c in nonzero_exit_pass:
        fail(problems, f"check {c.get('name')!r} has verdict PASS but "
                       f"exit_code {c['exit_code']}")
    if verdict == "PASS":
        if failed_checks:
            fail(problems, "verdict is PASS but a check has verdict FAIL")
        if incomplete_checks:
            fail(problems, "verdict is PASS but a check has verdict "
                           "INCOMPLETE")
        if blocking:
            fail(problems, "verdict is PASS but there is a blocking finding")
        if unverified:
            fail(problems, "verdict is PASS but unverified_items is "
                           "non-empty")
        if check_unverified:
            fail(problems, "verdict is PASS but a check has non-empty "
                           "unverified_items")
    elif verdict == "FAIL":
        if not blocking and not failed_checks:
            fail(problems, "verdict is FAIL but there is no blocking "
                           "finding and no check with verdict FAIL")
    elif verdict == "INCOMPLETE":
        if not incomplete_checks and not unverified \
                and not check_unverified:
            fail(problems, "verdict is INCOMPLETE but no check is "
                           "INCOMPLETE and nothing is unverified")


def check_fail_first(bundle, problems):
    """The fail-first proof must show the test failing before the fix
    and passing after it, unless the method is not-applicable (with a
    note saying why)."""
    ff = bundle.get("fail_first")
    if ff is None:
        return
    if not isinstance(ff, dict):
        fail(problems, "fail_first is not an object")
        return
    for field in ("test", "failed_before", "passed_after", "method"):
        if field not in ff:
            fail(problems, f"fail_first is missing {field}")
            return
    if ff["method"] not in ("worktree", "revert-at-smallest-scope",
                            "not-applicable"):
        fail(problems, f"fail_first.method is {ff['method']!r}")
        return
    if ff["method"] == "not-applicable":
        if not ff.get("note"):
            fail(problems, "fail_first.method is 'not-applicable' but no "
                           "note says why")
        return
    if not ff["failed_before"]:
        fail(problems, "fail_first.failed_before is false: the test was "
                       "never shown failing on the pre-fix code")
    if not ff["passed_after"]:
        fail(problems, "fail_first.passed_after is false: the test does "
                       "not pass after the fix")


def main(argv):
    if len(argv) != 2:
        print("usage: python3 scripts/validate_evidence.py <bundle.json>",
              file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"{path} is not valid JSON: {e}", file=sys.stderr)
        return 1
    if not isinstance(bundle, dict):
        print(f"{path} is not a JSON object", file=sys.stderr)
        return 1
    if not SCHEMA_PATH.is_file():
        print(f"schema missing: {SCHEMA_PATH}", file=sys.stderr)
        return 2
    problems = []
    check_types(bundle, problems)
    check_verdict_consistency(bundle, problems)
    check_fail_first(bundle, problems)
    if problems:
        print(f"FAIL: {len(problems)} problem(s) in {path}")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK: {path} is a valid, consistent evidence bundle")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
