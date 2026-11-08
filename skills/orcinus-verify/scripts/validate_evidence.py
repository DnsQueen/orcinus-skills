#!/usr/bin/env python3
"""Validate an ORCINUS verification evidence bundle against
references/evidence.schema.json (bundled in this skill folder).

Two layers, kept separate:

1. Structural validation: the bundle is checked against the schema
   itself, by a small JSON Schema interpreter below (standard library
   only). It enforces exactly the keywords the schema uses — type
   (with strict bool/int separation), const, enum, required,
   properties, additionalProperties, minLength, minItems, items,
   minimum, maximum, pattern, format (date-time only) — and fails loudly if the schema
   ever gains a keyword the interpreter does not know, so the subset
   can never silently drift. This is a subset interpreter for this
   schema, not a general JSON Schema validator; the docstring says so
   plainly and the tests pin the covered keywords.
2. Semantic validation: the rules the schema cannot express. The
   overall verdict is computed from the evidence by one function
   (expected_verdict), never taken from the agent: a blocking finding
   or a failed check forces FAIL; otherwise incomplete evidence forces
   INCOMPLETE; otherwise PASS. A finding without an explicit
   "non-blocking" severity counts as blocking (fail-closed). A PASS
   also needs a verification plan naming its required gates, each
   covered by a passing check with the same name — one passing check
   must never stand for all gates. Every canonical gate (build, lint,
   typecheck, test) must be required or explicitly waived with a
   reason; silence is not a waiver. A PASS for a behaviour change
   (bug-fix, feature, refactor) additionally needs the test gate and
   a fail-first proof. The proof carries the red run itself
   (command, non-zero exit code, output), and the test id must
   appear in the red output and in the passing test check's output
   — a bare test name with no output proves nothing. The test id
   is the pytest nodeid (`tests/test_sum.py::test_sum_two_decimals`),
   and the proof is structural, not a substring: fail_first
   red_report / green_report are JUnit XML files (pytest
   --junitxml), recorded as artifacts with their sha256, and the
   red report must list the test as failed and the green report
   as passed, matched exactly by (classname, name) — a 1-char id
   or a substring of an unrelated test's name proves nothing, and
   no report means no PASS. The stdout text is corroboration only.
   Every check
   that ran (verdict PASS or FAIL) must carry its output — an
   artifact file with its sha256, or inline text — so a PASS with
   no reviewable output is rejected. Artifact paths must stay
   inside the bundle directory (no absolute paths, no `..` escape,
   no symlinks) and are hashed by streaming from a descriptor with
   a size cap; without a bundle directory an artifact is recorded
   as unverified, never as passed. A change that touches code
   cannot call itself docs-only or config-only to escape the test
   gate and the fail-first proof. A PASS on a dirty tree must pin
   the diff it ran on (diff_sha256 of `git diff HEAD`): a dirty
   tree has no revision to bind the PASS to. A gate cannot be both
   required and waived. Security and data-loss findings are
   automatically blocking, whatever their severity says, and a
   non-blocking finding must declare its category. A bundle with
   no checks at all is valid only as INCOMPLETE, with a stop_reason
   saying why the verification stopped — except a docs-only /
   config-only PASS with every gate waived, which may have no
   checks. An honest FAIL or INCOMPLETE report is a valid bundle: the fail-first and plan
   rules are PASS rules, never validity rules — only a PASS must
   satisfy them. The prose ```verdict block is a second form of
   the same verdict: --verdict-block compares it against the
   bundle, so the two cannot disagree.

Structural validation runs first. If it finds any problem, the
semantic checks do not run at all: a malformed bundle produces a
controlled report and exit 1, never a traceback. A bundle file
that cannot even be read as JSON (not UTF-8, nested too deeply)
is a controlled error with exit 2, never a traceback.

Usage: python3 skills/orcinus-verify/scripts/validate_evidence.py <bundle.json> [--verdict-block <response.md>] [--repo <repo>] [--expected-revision <rev>] [--expected-diff <sha256>]
Exit 0 when the bundle is valid and consistent; exit 1 otherwise,
with each problem on its own line; exit 2 for a usage error, a
missing or unreadable schema, or an internal validator error.
--repo defaults to the working directory: the bundle is bound to
that repo's tree (every check's revision and content digest are
recomputed from it, and a dirty-tree PASS has its diff recomputed).
With no repo present a PASS bundle claiming a revision fails closed.
Pass --repo explicitly when the bundle was recorded against another
repo. --expected-revision / --expected-diff name the revision /
diff the caller expects the bundle to be bound to.

The validator and its schema live inside the orcinus-verify skill
folder and resolve relative to this file, so they work from a user
project with no repo checkout (in a plugin install, the skill folder
is skills/orcinus-verify under the plugin root; in a standalone
install it is the skill folder itself). The plugin-root variable is
named here only to describe that layout — the validator never reads
it, and no skill text relies on the host substituting it.

The validator does not prove the evidence is true — a bundle can
claim a command passed while the command never ran. It proves the
bundle is complete and self-consistent, so a missing check or a
contradicted verdict cannot slip through as a PASS. Since v3 every
executed check must also carry its output, so a PASS with no
reviewable output is rejected — but the output itself can still be
fabricated, which is what the agent-behaviour eval measures. Since v6
every check in a PASS bundle must be recorded by record_check.py: the
validator recomputes the binding hash (command argv, cwd, timestamps,
exit code, both stream hashes, content digest, revision) from the
stored fields and the artifact files on disk, so a hand-written check
cannot be filed as PASS. But a local writer can still run the wrapper
on a lying command, so the bundle is tamper-evident recording, not
proof the commands ran. Since round 8 the validator also binds a PASS
bundle to a tree when a repo is given (--repo, default the working
directory): every check's revision and content digest are recomputed
from that repo's tree, a dirty-tree PASS has its `git diff HEAD`
recomputed, and a PASS with a required test gate needs a JUnit
test_report with at least one test and at least one passed test —
but the binding is to the tree, not to the run: a lying command's
capture still binds cleanly to the tree it ran on, and a fabricated
JUnit file still parses. The claim stays "tamper-evident recording
bound to a tree", never "proof of execution".
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import types
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The binding hash lives in one place: record_check.py in this same
# skill folder. The import is guarded so the validator module still
# imports when the file is absent (a lone copy of the validator);
# check_recorded_checks then reports the missing file instead of
# crashing. record_check imports content_digest lazily, so importing
# it never needs a repo checkout — the validator stays self-contained
# in the skill folder.
sys.path.insert(0, str(Path(__file__).resolve().parent))
_record_check: types.ModuleType | None = None
try:
    import record_check as _record_check  # noqa: E402
except ImportError:
    pass

# The content digest lives beside this file too (a byte-identical
# copy of scripts/content_digest.py, bundled for skills-only
# installs). Guarded like record_check: the tree binding reports
# the missing file instead of crashing.
_content_digest_fn = None
try:
    import content_digest as _content_digest_module  # noqa: E402

    _content_digest_fn = _content_digest_module.content_digest
except ImportError:
    pass

# The skill folder (this file is <skill>/scripts/validate_evidence.py).
# The schema is bundled next to it, in <skill>/references/, and is
# resolved relative to this file — never relative to the working
# directory or a repo root, so the validator works from a user project.
ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "references" / "evidence.schema.json"

VERDICTS = ("PASS", "FAIL", "INCOMPLETE")

# Artifacts are test output, not arbitrary files: a 10 MiB cap keeps
# a hostile bundle from OOMing the validator (the old code hashed
# the whole file with read_bytes()).
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024

# Keywords the subset interpreter implements. Anything else in the
# schema raises, so an unimplemented keyword is a loud failure,
# never a silent pass.
SUPPORTED_KEYWORDS = {
    "type",
    "const",
    "enum",
    "required",
    "properties",
    "additionalProperties",
    "minLength",
    "minItems",
    "items",
    "minimum",
    "maximum",
    "format",
    "pattern",
    # Documentation-only keys, ignored by the interpreter.
    "description",
    "title",
    "$schema",
    "$id",
    "default",
    "examples",
}


def _is_bool(value):
    return type(value) is bool


def _is_int(value):
    # bool is a subclass of int in Python; an exit code or a schema
    # version of True is not an integer.
    return type(value) is int


def _type_matches(value, type_name):
    if type_name == "string":
        return type(value) is str
    if type_name == "integer":
        return _is_int(value)
    if type_name == "number":
        return _is_int(value) or type(value) is float
    if type_name == "boolean":
        return _is_bool(value)
    if type_name == "array":
        return type(value) is list
    if type_name == "object":
        return type(value) is dict
    if type_name == "null":
        return value is None
    raise ValueError(f"unsupported schema type: {type_name!r}")


def _strict_equal(a, b):
    return type(a) is type(b) and a == b


def _is_iso8601(value):
    """Strict RFC 3339 date-time: full date, 'T', time, and a 'Z' or
    numeric offset. datetime.fromisoformat alone is not enough: it
    accepts date-only strings and naive datetimes, and on 3.11+ it
    accepts week/basic formats that 3.10 rejects — so the same bundle
    would validate differently across the CI matrix. The regex makes
    acceptance identical on every Python >= 3.11: it pins the
    fractional seconds to 3 or 6 digits (3.10's fromisoformat
    accepted only those; the regex keeps the same acceptance on
    3.11+) and the year to 2000-2099, and
    fromisoformat then only validates the ranges."""
    if type(value) is not str:
        return False
    if not re.fullmatch(
        r"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3}|\.\d{6})?"
        r"(Z|[+-]\d{2}:\d{2})",
        value,
    ):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _validate(instance, schema, path, problems):
    """Check one value against one schema node; append problems."""
    if not isinstance(schema, dict):
        raise ValueError(f"schema at {path or 'root'} is not an object")
    unknown = set(schema) - SUPPORTED_KEYWORDS
    if unknown:
        raise ValueError(f"unsupported schema keyword(s) at {path or 'root'}: {sorted(unknown)}")
    if "type" in schema:
        wanted = schema["type"]
        types = wanted if isinstance(wanted, list) else [wanted]
        if not any(_type_matches(instance, t) for t in types):
            problems.append(
                f"{path or 'value'} must be of type {wanted}, got {type(instance).__name__}"
            )
            return
    if "const" in schema and not _strict_equal(instance, schema["const"]):
        problems.append(f"{path or 'value'} must be {schema['const']!r}, got {instance!r}")
    if "enum" in schema and not any(_strict_equal(instance, e) for e in schema["enum"]):
        problems.append(f"{path or 'value'} must be one of {schema['enum']}, got {instance!r}")
    if isinstance(instance, str) and "minLength" in schema:
        if len(instance) < schema["minLength"]:
            problems.append(
                f"{path or 'value'} must be at least {schema['minLength']} character(s)"
            )
    if isinstance(instance, list) and "minItems" in schema:
        if len(instance) < schema["minItems"]:
            problems.append(f"{path or 'value'} must have at least {schema['minItems']} item(s)")
    if isinstance(instance, (int, float)) and not _is_bool(instance):
        if "minimum" in schema and instance < schema["minimum"]:
            problems.append(f"{path or 'value'} must be >= {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            problems.append(f"{path or 'value'} must be <= {schema['maximum']}")
    if isinstance(instance, str) and "pattern" in schema:
        if not re.fullmatch(schema["pattern"], instance):
            problems.append(f"{path or 'value'} must match {schema['pattern']!r}")
    if "format" in schema:
        if schema["format"] == "date-time":
            if not _is_iso8601(instance):
                problems.append(f"{path or 'value'} must be an ISO 8601 date-time")
        else:
            raise ValueError(f"unsupported schema format at {path or 'root'}: {schema['format']!r}")
    if isinstance(instance, dict):
        for field in schema.get("required", []):
            if field not in instance:
                problems.append(f"{path + '.' if path else ''}{field}: missing required field")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                child = f"{path}.{key}" if path else key
                _validate(value, properties[key], child, problems)
            elif schema.get("additionalProperties") is False:
                problems.append(
                    f"{path + '.' if path else ''}{key}: unexpected property (not in the schema)"
                )
    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            _validate(item, schema["items"], f"{path}[{i}]", problems)


def validate_against_schema(bundle, schema):
    """Structural layer: the bundle against the schema. Returns the
    list of problems (empty means structurally valid)."""
    problems = []
    _validate(bundle, schema, "", problems)
    return problems


def _checks(bundle):
    checks = bundle.get("checks")
    if not isinstance(checks, list):
        return []
    return [c for c in checks if isinstance(c, dict)]


def _findings(bundle):
    findings = bundle.get("findings")
    if not isinstance(findings, list):
        return []
    return [f for f in findings if isinstance(f, dict)]


def _is_blocking(finding):
    """A finding is blocking unless it is explicitly non-blocking
    AND not a security / data-loss finding: those categories are
    automatically blocking, whatever their severity says (2-V7) —
    a security finding cannot label itself non-blocking."""
    if finding.get("category") in ("security", "data-loss"):
        return True
    return finding.get("severity") != "non-blocking"


def _docs_only_no_checks_pass(bundle):
    """True when a docs-only/config-only PASS may have no checks at
    all (2-V5): the plan names the change type, requires no gate,
    and waives every canonical gate with a reason. Anything else
    with no checks is an incomplete verification, never a PASS."""
    plan = bundle.get("verification_plan")
    if not isinstance(plan, dict):
        return False
    if plan.get("change_type") not in ("docs-only", "config-only"):
        return False
    if plan.get("required_gates"):
        return False
    waived = {e.get("gate") for e in plan.get("not_applicable_gates") or [] if isinstance(e, dict)}
    return all(g in waived for g in CANONICAL_GATES)


def expected_verdict(bundle):
    """The single verdict computation. A blocking finding or a failed
    check forces FAIL; otherwise incomplete evidence forces
    INCOMPLETE; otherwise PASS. A check that claims PASS with a
    non-zero exit code counts as failed. Fail-closed: a finding whose
    severity is anything other than "non-blocking" counts as
    blocking — and a security / data-loss finding counts as blocking
    whatever its severity says. No acceptance criteria means the verification stopped:
    INCOMPLETE, never PASS."""
    checks = _checks(bundle)
    findings = _findings(bundle)
    blocking = [f for f in findings if _is_blocking(f)]
    failed = [
        c
        for c in checks
        if c.get("verdict") == "FAIL"
        or (c.get("verdict") == "PASS" and _is_int(c.get("exit_code")) and c["exit_code"] != 0)
    ]
    unverified = bundle.get("unverified_items")
    criteria = bundle.get("acceptance_criteria")
    incomplete = (
        [c for c in checks if c.get("verdict") == "INCOMPLETE"]
        or (isinstance(unverified, list) and bool(unverified))
        or [c for c in checks if c.get("unverified_items")]
        or (isinstance(criteria, list) and not criteria)
        or (not checks and not _docs_only_no_checks_pass(bundle))
    )
    if blocking or failed:
        return "FAIL"
    if incomplete:
        return "INCOMPLETE"
    return "PASS"


def check_verdict_consistency(bundle, problems):
    """The stated verdict must equal the computed one."""
    verdict = bundle.get("verdict")
    if verdict not in VERDICTS:
        return
    checks = _checks(bundle)
    for c in checks:
        if c.get("verdict") == "PASS" and _is_int(c.get("exit_code")) and c["exit_code"] != 0:
            problems.append(
                f"check {c.get('name')!r} has verdict PASS but exit_code {c['exit_code']}"
            )
    expected = expected_verdict(bundle)
    if verdict == expected:
        return
    if verdict == "PASS":
        if any(c.get("verdict") == "FAIL" for c in checks):
            problems.append("verdict is PASS but a check has verdict FAIL")
        if any(c.get("verdict") == "INCOMPLETE" for c in checks):
            problems.append("verdict is PASS but a check has verdict INCOMPLETE")
        if any(_is_blocking(f) for f in _findings(bundle)):
            problems.append("verdict is PASS but there is a blocking finding")
        if bundle.get("unverified_items"):
            problems.append("verdict is PASS but unverified_items is non-empty")
        if any(c.get("unverified_items") for c in checks):
            problems.append("verdict is PASS but a check has non-empty unverified_items")
    elif verdict == "FAIL":
        problems.append(
            "verdict is FAIL but there is no blocking finding and no check with verdict FAIL"
        )
    elif verdict == "INCOMPLETE":
        if expected == "FAIL":
            problems.append(
                "verdict is INCOMPLETE but a check has verdict FAIL or "
                "there is a blocking finding: the evidence requires FAIL"
            )
        else:
            problems.append(
                "verdict is INCOMPLETE but no check is INCOMPLETE and nothing is unverified"
            )


# Change types that change behaviour: a PASS for one needs the test
# gate and a fail-first proof. docs-only / config-only have no
# behaviour to test, so fail-first may be absent or not-applicable.
BEHAVIOR_CHANGE_TYPES = ("bug-fix", "feature", "refactor")

# The canonical gates (orcinus-verify step 4: name every check after
# its gate). Every one must be required or explicitly waived with a
# reason in a PASS plan; silence is not a waiver.
CANONICAL_GATES = ("build", "lint", "typecheck", "test")


def _fail_first_output(red, bundle_dir, problems):
    """The red run's recorded output text, or None when it cannot
    be established (the problem is already appended)."""
    text = red.get("stdout_text")
    if isinstance(text, str) and text:
        return text
    artifact = red.get("stdout_artifact")
    if isinstance(artifact, str) and artifact:
        if bundle_dir is None:
            problems.append(
                f"fail_first.red_check stdout_artifact {artifact!r} was "
                f"not verified: no bundle directory was given, so the "
                f"artifact is unverified"
            )
            return None
        content, problem = _read_artifact_text(bundle_dir, artifact, "fail_first.red_check")
        if problem:
            problems.append(problem)
            return None
        return content
    problems.append(
        "fail_first.red_check has no output: record the red run's stdout_text or stdout_artifact"
    )
    return None


# Returned by _green_test_output when the test check's output
# existed but could not be read (problem already appended): the
# caller must not then also claim the test id is missing.
_UNREADABLE = object()


def _green_test_output(bundle, bundle_dir, problems):
    """The passing 'test' check's stdout text: the green run the
    red run is linked to. None when there is no passing 'test'
    check; _UNREADABLE when its output could not be read."""
    for c in _checks(bundle):
        if c.get("name") != "test" or c.get("verdict") != "PASS":
            continue
        text = c.get("stdout_text")
        if isinstance(text, str) and text:
            return text
        artifact = c.get("stdout_artifact")
        if isinstance(artifact, str) and artifact:
            if bundle_dir is None:
                problems.append(
                    f"check 'test' stdout_artifact {artifact!r} was not "
                    f"verified: no bundle directory was given, so the "
                    f"artifact is unverified"
                )
                return _UNREADABLE
            content, problem = _read_artifact_text(bundle_dir, artifact, "check 'test'")
            if problem:
                problems.append(problem)
                return _UNREADABLE
            return content
        return ""
    return None


def _nodeid_to_junit(test_id):
    """A pytest nodeid as the (classname, name) pair JUnit XML
    identifies a test by — or None when the id is not a nodeid.
    `tests/test_sum.py::test_sum_two_decimals` becomes
    ("tests.test_sum", "test_sum_two_decimals");
    `tests/test_x.py::TestFoo::test_bar` becomes
    ("tests.test_x.TestFoo", "test_bar"), with parameters (the
    part after the last `::`, `[param]` included) kept in the name.
    pytest --junitxml natively emits <testcase classname="..."
    name="..."> with <failure>/<error>/<skipped> children; the
    outcome is structural (child present = failed/error/skipped,
    no child = passed), and suite counts never identify *which*
    test failed — so the link is the exact tuple, never a
    substring."""
    parts = test_id.split("::")
    if len(parts) < 2:
        return None
    module = parts[0].removeprefix("./")
    if not module.endswith(".py"):
        return None
    classname = module[:-3].replace("/", ".")
    if len(parts) > 2:
        classname = classname + "." + ".".join(parts[1:-1])
    return (classname, parts[-1])


def _load_junit_report(report, bundle_dir, label, problems):
    """Read one JUnit report ({artifact, sha256, format}) as
    {(classname, name): status}, with status in passed / failed /
    error / skipped. `label` is the report's full dotted name
    ("fail_first.red_report", "test_report"). Returns None when the
    report cannot be established (the problem is already appended):
    absent, unreadable, hash-mismatched, or unparsable — and no
    report means no PASS, never a fallback to the stdout substring.
    The artifact is read through the same containment / symlink /
    size-cap path as every other artifact."""
    if not isinstance(report, dict):
        problems.append(
            f"{label} is missing: a PASS needs the structured "
            f"{label} (JUnit XML, pytest --junitxml) — no report means no PASS"
        )
        return None
    artifact = report.get("artifact")
    if not isinstance(artifact, str) or not artifact:
        problems.append(f"{label} has no artifact: record the JUnit XML report file")
        return None
    if bundle_dir is None:
        problems.append(
            f"{label} {artifact!r} was not verified: no "
            f"bundle directory was given, so the artifact is unverified"
        )
        return None
    f, problem = _open_artifact(bundle_dir, artifact, label)
    if problem:
        problems.append(problem)
        return None
    with f:
        data = f.read(MAX_ARTIFACT_BYTES + 1)
    if len(data) > MAX_ARTIFACT_BYTES:
        problems.append(
            f"{label} {artifact!r} is larger than the {MAX_ARTIFACT_BYTES}-byte artifact cap"
        )
        return None
    recorded = report.get("sha256")
    if isinstance(recorded, str) and recorded and hashlib.sha256(data).hexdigest() != recorded:
        problems.append(
            f"{label} {artifact!r} sha256 mismatch: the file changed since the bundle was written"
        )
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        problems.append(f"{label} {artifact!r} is not valid UTF-8 text")
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        problems.append(f"{label} {artifact!r} is not valid JUnit XML: {e}")
        return None
    statuses = {}
    for case in root.iter("testcase"):
        classname = case.get("classname") or ""
        name = case.get("name") or ""
        status = "passed"
        for child in case:
            if child.tag in ("failure", "error"):
                status = "failed" if child.tag == "failure" else "error"
                break
            if child.tag == "skipped":
                status = "skipped"
        statuses[(classname, name)] = status
    return statuses


def check_fail_first(bundle, problems, bundle_dir=None):
    """The fail-first proof must show the test failing before the fix
    and passing after it. These are PASS rules, not validity rules:
    a verifier that honestly reports a failed red proof with verdict
    INCOMPLETE is filing a valid bundle — the false values are the
    reason for INCOMPLETE, not a problem with the bundle. Only a
    PASS for a behaviour change must prove the red: there the proof
    must be present, the method must be worktree or
    revert-at-smallest-scope (not-applicable is only for changes with
    no behaviour to test), and both booleans must be true. Types are
    enforced by the schema layer, so truthiness here is safe:
    failed_before/passed_after are real booleans by the time this
    runs. The booleans alone are not the proof: the red run itself
    must be recorded in red_check (command, non-zero exit code,
    output), and the test id must appear in the red output and in
    the passing 'test' check's output — a bare test name with no
    output proves nothing (a bundle naming "nonexistent_test" used
    to pass). The test id is a pytest nodeid, and the structural
    proof is the JUnit XML reports: red_report must list the test
    as failed/error and green_report as passed, matched exactly by
    (classname, name). The stdout text is corroboration only; no
    report means no PASS, and there is no substring fallback."""
    ff = bundle.get("fail_first")
    verdict = bundle.get("verdict")
    plan = bundle.get("verification_plan")
    change_type = plan.get("change_type") if isinstance(plan, dict) else None
    is_behavior = change_type in BEHAVIOR_CHANGE_TYPES
    if not isinstance(ff, dict):
        if verdict == "PASS" and is_behavior:
            problems.append(
                "verdict is PASS for a behaviour change "
                f"({change_type}) but there is no fail_first proof: "
                "a test must be shown failing before the fix and "
                "passing after it"
            )
        return
    if ff.get("method") == "not-applicable":
        if not ff.get("note"):
            problems.append("fail_first.method is 'not-applicable' but no note says why")
        elif verdict == "PASS" and is_behavior:
            problems.append(
                "fail_first.method is 'not-applicable' for a behaviour "
                f"change ({change_type}): the red proof cannot be "
                "waived by assertion"
            )
        return
    if verdict != "PASS":
        return
    if "failed_before" in ff and not ff["failed_before"]:
        problems.append(
            "fail_first.failed_before is false: the test was "
            "never shown failing on the pre-fix code"
        )
    if "passed_after" in ff and not ff["passed_after"]:
        problems.append("fail_first.passed_after is false: the test does not pass after the fix")
    if not is_behavior:
        return
    test_id = ff.get("test")
    if not isinstance(test_id, str) or not test_id:
        return  # the schema layer already reported it
    red = ff.get("red_check")
    if not isinstance(red, dict):
        problems.append(
            "fail_first has no red_check: the red run must be recorded "
            "(command, non-zero exit_code, output) — two booleans do "
            "not prove the test failed before the fix"
        )
        return
    if not _is_int(red.get("exit_code")) or red["exit_code"] == 0:
        problems.append(
            "fail_first.red_check.exit_code must be non-zero: a red run that exits 0 is not a red"
        )
    red_text = _fail_first_output(red, bundle_dir, problems)
    if red_text is not None and test_id not in red_text:
        problems.append(
            f"fail_first.test {test_id!r} does not appear in the "
            f"red_check output: the red run must be the run of that test"
        )
    green = _green_test_output(bundle, bundle_dir, problems)
    if green is None:
        problems.append(
            f"fail_first.test {test_id!r} has no passing 'test' check "
            f"to link to: the green run must be the run of that test"
        )
    elif green is not _UNREADABLE and test_id not in green:
        problems.append(
            f"fail_first.test {test_id!r} does not appear in the "
            f"passing 'test' check's output: the green run must be "
            f"the run of that test"
        )
    # Structured link (F-03): the stdout checks above are
    # corroboration only. The proof is the JUnit reports: the test
    # id is a pytest nodeid, and the red report must list it as
    # failed/error and the green report as passed, matched exactly
    # by (classname, name). No report → no PASS, and there is no
    # fallback to the substring — that fallback is the hole being
    # fixed. TAP is not built here: its description-only identity
    # is the same weakness, and pytest --junitxml is the native
    # report for the Python runners this skill verifies.
    expected = _nodeid_to_junit(test_id)
    if expected is None:
        problems.append(
            f"fail_first.test {test_id!r} is not a pytest nodeid "
            f"(expected 'path/test_file.py::test_name'): the red and "
            f"green runs cannot be linked to a test without one"
        )
        return
    red_report = _load_junit_report(
        ff.get("red_report"), bundle_dir, "fail_first.red_report", problems
    )
    if red_report is not None:
        status = red_report.get(expected)
        if status is None:
            problems.append(
                f"fail_first.test {test_id!r} does not appear in the "
                f"red_report: the red run must be the run of that test"
            )
        elif status not in ("failed", "error"):
            problems.append(
                f"fail_first.test {test_id!r} in the red_report has "
                f"status {status!r}, not failed: the red run must show "
                f"the test failing before the fix"
            )
    green_report = _load_junit_report(
        ff.get("green_report"), bundle_dir, "fail_first.green_report", problems
    )
    if green_report is not None:
        status = green_report.get(expected)
        if status is None:
            problems.append(
                f"fail_first.test {test_id!r} does not appear in the "
                f"green_report: the green run must be the run of that test"
            )
        elif status != "passed":
            problems.append(
                f"fail_first.test {test_id!r} in the green_report has "
                f"status {status!r}, not passed: the green run must show "
                f"the test passing after the fix"
            )


def check_test_report(bundle, problems, bundle_dir):
    """A required test gate must be backed by a JUnit XML report
    with tests>0 and passed>0 (round 8, FND-005): a command printing
    "no tests ran in 0.00s" exits 0 and used to validate as a
    passing test gate, and an all-skipped suite ran no test either.
    Applies only when the test gate is required — never for a
    legitimately waived docs-only/config-only gate — and only for
    PASS (an honest FAIL/INCOMPLETE bundle needs no report). The
    report is read through the same artifact path as the fail-first
    reports, so a tampered file fails its sha256. What this does NOT
    close: a lying command printing fake output. The report file
    itself can be fabricated the same way; only a trust boundary
    the job cannot touch closes that (see the module docstring)."""
    if bundle.get("verdict") != "PASS":
        return
    plan = bundle.get("verification_plan")
    if not isinstance(plan, dict):
        return
    required = plan.get("required_gates")
    if not isinstance(required, list) or "test" not in required:
        return
    statuses = _load_junit_report(bundle.get("test_report"), bundle_dir, "test_report", problems)
    if statuses is None:
        return
    total = len(statuses)
    passed = sum(1 for status in statuses.values() if status == "passed")
    if total == 0:
        problems.append(
            "test_report lists no tests: a required test gate must run at least one test"
        )
    elif passed == 0:
        problems.append(
            f"test_report lists {total} test(s) but none passed: a required test gate "
            "must have at least one passing test (an all-skipped suite ran no test)"
        )


# A timestamp more than this far in the future is not clock skew:
# it is a fabricated or mis-recorded run (round 8, FND-006).
FUTURE_TOLERANCE = timedelta(minutes=5)


def _parse_timestamp(value):
    """An aware datetime for an RFC 3339 timestamp, or None when it
    cannot be parsed or has no timezone (the schema / time-order
    checks already report those; this check must not raise on
    unvalidated input)."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def check_future_timestamps(bundle, problems):
    """Timestamps in the future beyond a 5-minute clock-skew
    tolerance are rejected (round 8, FND-006): a bundle dated 2099
    used to validate. All checks plus fail_first.red_check. There
    is deliberately no lower bound: a historical bundle must keep
    validating, so only the future is rejected."""
    now = datetime.now(timezone.utc)
    targets = [(c, f"check {c.get('name')!r}") for c in _checks(bundle)]
    ff = bundle.get("fail_first")
    if isinstance(ff, dict) and isinstance(ff.get("red_check"), dict):
        targets.append((ff["red_check"], "fail_first.red_check"))
    for check, label in targets:
        for field in ("started_at", "finished_at"):
            parsed = _parse_timestamp(check.get(field))
            if parsed is None:
                continue
            if parsed > now + FUTURE_TOLERANCE:
                problems.append(
                    f"{label} {field} {check[field]} is in the future "
                    f"(more than {FUTURE_TOLERANCE} ahead of the validator's clock): "
                    "a timestamp from the future is not a recorded run"
                )


# Commands that run nothing: a check whose command is a shell no-op
# proves no work happened, however clean its exit code looks.
NOOP_COMMANDS = ("true", "false", ":", "echo", "exit")

# Exit-code masking constructs (F-02): a command that always exits 0
# whatever the gate did — `pytest || true`, `pytest ; exit 0`,
# `bash -c true`, `python3 -c 'pass'`. This is defence against
# sloppiness, not against a determined agent: a determined agent can
# always fabricate output (see F-01), and no regex layer can stop
# that. There is no real tool that detects deliberate `|| true` as a
# defect — ShellCheck *recommends* `|| true` as the "ignore the
# return value" idiom (SC2312) — so this is our own regex layer,
# stdlib `re` only, no shell parser, no ShellCheck code. Only
# constructs that are themselves always-zero are flagged: a genuine
# fallback (`pytest || ruff check`, RHS a real command) and a
# failure-preserving suffix (`|| exit 1`, `; exit 1`) pass, as do
# `! cmd` (a legitimate absence assertion) and `cmd && exit 0` /
# `cmd || exit 1` (failure preserved). There is deliberately NO
# allowlist — notably no `grep -q ... || true` exemption: in a
# *check* command the exit code is the evidence, and `grep -q` as
# the check itself is the correct restructure.
_MASKING_PATTERNS = (
    (re.compile(r"\|\|\s*(?:true|/bin/true|/usr/bin/true)(?![\w/])"), "`|| true`"),
    (re.compile(r"\|\|\s*:(?![\w/])"), "`|| :`"),
    (re.compile(r"\|\|\s*exit\s+0(?![\w])"), "`|| exit 0`"),
    (re.compile(r";\s*exit\s+0(?![\w])\s*(?:;|$)"), "`; exit 0`"),
    (re.compile(r";\s*true(?![\w])\s*(?:;|$)"), "`; true`"),
    (re.compile(r";\s*:(?![\w/])\s*(?:;|$)"), "`; :`"),
    (re.compile(r"\|\s*true(?![\w])\s*$"), "`| true`"),
    (re.compile(r"\|\s*:(?![\w/])\s*$"), "`| :`"),
)

# Bodies that make `python -c '...'` run nothing.
_NOOP_PYTHON_BODIES = ("pass", "", "0", "exit(0)", "sys.exit(0)")


def _masking_reason(command, _nested=False):
    """The always-zero construct in `command`, or None.

    Applies the masking patterns above, plus — one level only — the
    inside of a leading `sh -c '...'` / `bash -c '...'` /
    `dash -c '...'` and a `python -c '...'` whose body is a no-op.
    """
    for pattern, label in _MASKING_PATTERNS:
        if pattern.search(command):
            return label
    if _nested:
        first = command.strip().split()
        if first and first[0] in NOOP_COMMANDS:
            return f"a no-op command {first[0]!r}"
        return None
    stripped = command.strip()
    shell = re.match(r"(?:ba|da)?sh\s+-c\s+(.*)$", stripped, re.DOTALL)
    if shell:
        inner = shell.group(1).strip()
        if len(inner) >= 2 and inner[0] == inner[-1] and inner[0] in ("'", '"'):
            inner = inner[1:-1]
        reason = _masking_reason(inner, _nested=True)
        if reason:
            return f"`sh -c` wrapping {reason}"
    python = re.match(r"python3?\s+-c\s+(.*)$", stripped, re.DOTALL)
    if python:
        body = python.group(1).strip()
        if len(body) >= 2 and body[0] == body[-1] and body[0] in ("'", '"'):
            body = body[1:-1]
        normalised = re.sub(r"\s+", "", body.strip().rstrip(";").strip())
        if normalised in _NOOP_PYTHON_BODIES:
            return f"`python -c {body!r}`"
    return None


def _noop_problem(command, label):
    """The no-op problem for one command, or None when it runs a gate."""
    if not isinstance(command, str):
        return None
    first = command.strip().split()
    if first and first[0] in NOOP_COMMANDS:
        return (
            f"{label} command {command!r} is a no-op: "
            f"a check must run the gate, not a command that always succeeds"
        )
    reason = _masking_reason(command)
    if reason:
        return (
            f"{label} command {command!r} is a no-op: it masks the exit "
            f"code with {reason} — a check must run the gate, not a "
            f"command that always succeeds"
        )
    return None


def check_noop_commands(bundle, problems):
    """A check that ran a no-op command is not evidence of anything
    (2-V2: command="true" for the test gate used to pass). The same
    applies to fail_first.red_check: a red run whose command always
    exits 0 is not a red."""
    for c in _checks(bundle):
        problem = _noop_problem(c.get("command"), f"check {c.get('name')!r}")
        if problem:
            problems.append(problem)
    ff = bundle.get("fail_first")
    if isinstance(ff, dict):
        red = ff.get("red_check")
        if isinstance(red, dict):
            problem = _noop_problem(red.get("command"), "fail_first.red_check")
            if problem:
                problems.append(problem)


def _normalise_identity(identity):
    """One normalisation for both sides of an identity comparison:
    strip surrounding whitespace and casefold. casefold, not lower:
    it is the stronger Unicode case-insensitive comparison (for
    example the German 'ß' casefolds to 'ss', where lower leaves it
    unchanged), so two spellings of the same identity cannot differ
    only by case."""
    return identity.strip().casefold()


def check_identities(bundle, problems):
    """The verifier must differ from the implementer: a verifier
    cannot verify their own work (2-V2: reviewer_identity
    "implementer" used to pass — there was no implementer field to
    compare against at all). Both sides are normalised in both
    comparisons, so case or whitespace cannot defeat the check."""
    reviewer = bundle.get("reviewer_identity")
    implementer = bundle.get("implementer_identity")
    if isinstance(reviewer, str) and _normalise_identity(reviewer) == "implementer":
        problems.append(
            "reviewer_identity is 'implementer': the verifier must differ from the implementer"
        )
    if (
        isinstance(reviewer, str)
        and isinstance(implementer, str)
        and _normalise_identity(reviewer) == _normalise_identity(implementer)
    ):
        problems.append(
            "reviewer_identity is the same as implementer_identity: "
            "the verifier must differ from the implementer"
        )


def check_plan_coverage(bundle, problems):
    """A PASS needs a verification plan naming its required gates,
    each covered by a passing check with the same name. The plan is
    the agent's own, so the validator also enforces the policy the
    agent cannot set for itself: every canonical gate (build, lint,
    typecheck, test) must be required or listed in
    not_applicable_gates with a reason — a gate that is never
    mentioned is a hole, not an omission. A behaviour change
    additionally needs the test gate required (waiving it is not
    enough). For FAIL/INCOMPLETE the plan is only shape-checked (the
    schema layer already enforces its types); coverage is a PASS
    rule. The reason for a waiver is required but its truth is not
    machine-checkable — that residual gap is recorded in SCOPE.md,
    not silently assumed away."""
    plan = bundle.get("verification_plan")
    verdict = bundle.get("verdict")
    if verdict != "PASS":
        return
    if plan is None:
        problems.append(
            "verdict is PASS but there is no verification_plan: a PASS "
            "needs the plan naming its required gates"
        )
        return
    if not isinstance(plan, dict):
        return
    required = plan.get("required_gates")
    if not isinstance(required, list):
        return
    waived = {}
    for entry in plan.get("not_applicable_gates") or []:
        if not isinstance(entry, dict):
            continue
        if not entry.get("reason"):
            problems.append(
                f"gate {entry.get('gate')!r} is listed as not-applicable but no reason says why"
            )
        elif entry.get("gate"):
            waived[entry["gate"]] = entry["reason"]
    checks = _checks(bundle)
    passing = {c.get("name") for c in checks if c.get("verdict") == "PASS"}
    for gate in required:
        if gate in waived:
            problems.append(
                f"gate {gate!r} is in both required_gates and "
                f"not_applicable_gates: a gate cannot be both required and waived"
            )
        if gate not in passing:
            problems.append(f"required gate {gate!r} has no passing check")
    for gate in CANONICAL_GATES:
        if gate in required or gate in waived:
            continue
        problems.append(
            f"gate {gate!r} is neither a required gate nor listed as "
            f"not-applicable with a reason: a gate that is never "
            f"mentioned cannot be PASSed by silence"
        )
    change_type = plan.get("change_type")
    if change_type in BEHAVIOR_CHANGE_TYPES and "test" not in required:
        problems.append(
            f"change_type {change_type!r} needs the 'test' gate in "
            f"required_gates: a behaviour change cannot waive its "
            f"test gate"
        )


# File suffixes that mean the change touches code: a change that
# touches one cannot call itself docs-only or config-only.
CODE_SUFFIXES = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cs",
    ".swift",
    ".sh",
    ".sql",
)


def check_change_type_files(bundle, problems):
    """A docs-only/config-only PASS whose files_changed lists a code
    file is a behaviour change escaping the test gate and the
    fail-first proof (V2): the validator never read files_changed
    at all. A PASS rule only — an honest FAIL or INCOMPLETE bundle
    may still describe the mismatch."""
    if bundle.get("verdict") != "PASS":
        return
    plan = bundle.get("verification_plan")
    if not isinstance(plan, dict):
        return
    change_type = plan.get("change_type")
    if change_type not in ("docs-only", "config-only"):
        return
    for f in bundle.get("files_changed") or []:
        if isinstance(f, str) and f.endswith(CODE_SUFFIXES):
            problems.append(
                f"change_type is {change_type!r} but files_changed lists code file {f!r}: "
                f"a change touching code is a behaviour change, not {change_type}"
            )


def check_files_changed_for_behaviour_change(bundle, problems):
    """A PASS for a behaviour change must name at least one file
    changed: a change that touched nothing is not a behaviour
    change, and a PASS with `files_changed: []` claims a change
    with no evidence of one. The schema has no minItems on
    files_changed, so this constraint lives in the semantic layer.
    Pattern: github/spec-kit `.github/scripts/
    check_extension_version_bump.py:174-272` invariant 1 (MIT,
    pattern-only) — a semantic gate over a computed change-set,
    not a schema rule. docs-only / config-only are exempt: they
    have no behaviour to change, and the docs-only no-checks PASS
    may list no files."""
    if bundle.get("verdict") != "PASS":
        return
    plan = bundle.get("verification_plan")
    if not isinstance(plan, dict):
        return
    if plan.get("change_type") not in BEHAVIOR_CHANGE_TYPES:
        return
    files = bundle.get("files_changed")
    if not isinstance(files, list) or not files:
        problems.append(
            f"verdict is PASS for a behaviour change "
            f"({plan.get('change_type')}) but files_changed is empty: "
            f"a behaviour change must name the files it changed"
        )


def check_finding_categories(bundle, problems):
    """Security and data-loss findings are automatically blocking
    (2-V7): the category, not the self-declared severity, decides.
    And a non-blocking claim must declare its category, or the
    auto-blocking rule could be dodged by omitting it. A PASS rule
    only — an honest FAIL bundle may still report the finding."""
    if bundle.get("verdict") != "PASS":
        return
    for f in _findings(bundle):
        category = f.get("category")
        if category in ("security", "data-loss"):
            problems.append(
                f"finding in {f.get('file')!r} has category {category!r}: "
                f"security and data-loss findings are automatically blocking"
            )
        elif f.get("severity") == "non-blocking" and not isinstance(category, str):
            problems.append(
                f"finding in {f.get('file')!r} is 'non-blocking' but has no category: "
                f"a non-blocking finding must declare its category"
            )


def check_acceptance_criteria(bundle, problems):
    """An empty acceptance_criteria list means the verification
    stopped: the verdict must be INCOMPLETE, never PASS. (The
    verdict computation already treats it as incomplete; this is the
    explicit problem for the PASS case.)"""
    if (
        bundle.get("verdict") == "PASS"
        and isinstance(bundle.get("acceptance_criteria"), list)
        and not bundle["acceptance_criteria"]
    ):
        problems.append(
            "verdict is PASS but acceptance_criteria is empty: with no "
            "acceptance criteria the verification must stop "
            "(INCOMPLETE), not invent them"
        )


def check_time_order(bundle, problems):
    """finished_at must not precede started_at. The schema layer
    already enforces RFC 3339 on both, so parsing cannot fail here
    — but the check must not depend on that: if it is ever called
    on unvalidated input, a bad timestamp is a problem to record,
    not an exception to raise (F-11). The red run's timestamps are
    checked the same way: they are part of its recorded binding."""
    for c in _checks(bundle):
        _check_one_time_order(c, f"check {c.get('name')!r}", problems)
    ff = bundle.get("fail_first")
    if isinstance(ff, dict) and isinstance(ff.get("red_check"), dict):
        _check_one_time_order(ff["red_check"], "fail_first.red_check", problems)


def _check_one_time_order(check, label, problems):
    started = check.get("started_at")
    finished = check.get("finished_at")
    if not isinstance(started, str) or not isinstance(finished, str):
        return
    try:
        start = datetime.fromisoformat(started.replace("Z", "+00:00"))
        end = datetime.fromisoformat(finished.replace("Z", "+00:00"))
    except (ValueError, TypeError) as e:
        problems.append(
            f"{label} started_at {started!r} or finished_at {finished!r} could not be parsed: {e}"
        )
        return
    try:
        out_of_order = end < start
    except TypeError as e:
        problems.append(
            f"{label} started_at {started!r} and finished_at {finished!r} cannot be compared: {e}"
        )
        return
    if out_of_order:
        problems.append(f"{label} finished_at {finished} is before started_at {started}")


def _resolve_inside(bundle_dir, artifact):
    """Resolve an artifact path against the bundle directory.

    Returns (path, problem): path is the resolved file inside the
    bundle, or None with a problem when the artifact is absolute,
    escapes the bundle, or passes through a symlink. The symlink
    walk uses the lexical path, before resolve(), because resolve()
    would silently follow the link away."""
    base = Path(bundle_dir).resolve()
    raw = Path(artifact)
    if raw.is_absolute():
        return None, (
            f"artifact {artifact!r} is an absolute path: artifact "
            f"paths must be relative to the bundle"
        )
    current = base
    for part in raw.parts:
        if part in ("", "."):
            continue
        current = current / part
        if current.is_symlink():
            return None, f"artifact {artifact!r} passes through a symlink: {current}"
    resolved = (base / raw).resolve()
    if not resolved.is_relative_to(base):
        return None, f"artifact {artifact!r} escapes the bundle directory"
    return resolved, None


def _open_artifact(bundle_dir, artifact, label):
    """Resolve + containment + symlink checks, then open the file
    by descriptor (O_NOFOLLOW where the platform has it: the final
    component must not be a symlink at open time either), with the
    size cap enforced on the opened file. Returns (file, problem)."""
    path, problem = _resolve_inside(bundle_dir, artifact)
    if problem:
        return None, f"{label} {problem}"
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as e:
        return None, f"{label} {artifact!r} cannot be read: {e}"
    f = os.fdopen(fd, "rb")
    try:
        if os.fstat(f.fileno()).st_size > MAX_ARTIFACT_BYTES:
            f.close()
            return None, (
                f"{label} {artifact!r} is larger than the {MAX_ARTIFACT_BYTES}-byte artifact cap"
            )
    except OSError as e:
        f.close()
        return None, f"{label} {artifact!r} cannot be read: {e}"
    return f, None


def _read_artifact_text(bundle_dir, artifact, label):
    """Read a validated artifact as UTF-8 text (for the fail-first
    test-id link). Returns (text, problem)."""
    f, problem = _open_artifact(bundle_dir, artifact, label)
    if problem:
        return None, problem
    try:
        with f:
            data = f.read(MAX_ARTIFACT_BYTES + 1)
            if len(data) > MAX_ARTIFACT_BYTES:
                return None, (
                    f"{label} {artifact!r} is larger than the "
                    f"{MAX_ARTIFACT_BYTES}-byte artifact cap"
                )
            return data.decode("utf-8"), None
    except OSError as e:
        return None, f"{label} {artifact!r} cannot be read: {e}"
    except UnicodeDecodeError:
        return None, f"{label} {artifact!r} is not valid UTF-8 text"


def _hash_artifact(bundle_dir, artifact, label):
    """The sha256 of one artifact file, read through the containment /
    symlink / size-cap path. Returns (hex, problem): problem is None
    on success, and the hash is over the exact bytes on disk."""
    f, problem = _open_artifact(bundle_dir, artifact, label)
    if problem:
        return None, problem
    with f:
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ARTIFACT_BYTES:
                return None, (
                    f"{label} {artifact!r} is larger than the "
                    f"{MAX_ARTIFACT_BYTES}-byte artifact cap"
                )
            digest.update(chunk)
    return digest.hexdigest(), None


def check_artifacts(bundle, problems, bundle_dir):
    """An artifact path that does not exist is not evidence, and an
    artifact without its sha256 is a claim nobody can verify: the
    file could have been replaced after the run. When the bundle
    directory is known the recorded hash must match the file, which
    must live inside the bundle directory: absolute paths, `..`
    escapes and symlinks are rejected, and the file is hashed by
    streaming from a descriptor with a size cap. When the directory
    is unknown (the in-process API without one) the artifact is
    recorded as explicitly unverified — never silently passed. The
    sha256-presence rule needs no file, so it runs even then; the
    CLI always passes the directory."""
    for c in _checks(bundle):
        for field, hash_field in (
            ("stdout_artifact", "stdout_sha256"),
            ("stderr_artifact", "stderr_sha256"),
        ):
            artifact = c.get(field)
            if not isinstance(artifact, str) or not artifact:
                continue
            label = f"check {c.get('name')!r} {field} {artifact!r}"
            recorded = c.get(hash_field)
            if not isinstance(recorded, str) or not recorded:
                problems.append(
                    f"{label} has no {hash_field}: an artifact without its "
                    f"sha256 cannot be verified"
                )
            if bundle_dir is None:
                problems.append(
                    f"{label} was not verified: no bundle directory "
                    f"was given, so the artifact is unverified"
                )
                continue
            digest, problem = _hash_artifact(bundle_dir, artifact, label)
            if problem:
                problems.append(problem)
                continue
            if isinstance(recorded, str) and recorded and digest != recorded:
                problems.append(
                    f"{label} sha256 mismatch: the file changed since the bundle was written"
                )


# The recorder identity a PASS bundle's checks must carry.
RECORDED_BY = "record_check.py/1"


def _verify_recorded_binding(check, label, bundle_dir, problems, require):
    """Verify one check's recorded binding, if it claims one.

    `require` is True for a check in a PASS bundle: recorded fields
    are required there, and a hand-written check is not evidence. For
    a FAIL/INCOMPLETE bundle they are not required — an honest
    failure report may carry unrecorded checks — but a binding that
    IS present must still recompute: a present-but-wrong hash is a
    self-contradiction, not an honest report. The recompute reads the
    artifact files from disk and hashes their bytes, so the stored
    stdout_sha256/stderr_sha256 are never trusted on their own."""
    recorded_by = check.get("recorded_by")
    capture = check.get("capture_sha256")
    if recorded_by is None and capture is None:
        if require:
            problems.append(
                f"{label} has no recorded capture: a PASS bundle must record "
                f"every check with record_check.py (recorded_by + "
                f"capture_sha256) - a hand-written check is not evidence"
            )
        return
    if recorded_by != RECORDED_BY:
        problems.append(
            f"{label} recorded_by is {recorded_by!r}, not {RECORDED_BY!r}: "
            f"only record_check.py captures validate as recorded checks"
        )
        return
    if not isinstance(capture, str) or not capture:
        problems.append(f"{label} has recorded_by but no capture_sha256")
        return
    # The binding needs the whole record: argv, shell, cwd, both
    # timestamps, exit code, both stream hashes, digest, revision.
    missing = [
        field
        for field in (
            "command_argv",
            "shell",
            "cwd",
            "started_at",
            "finished_at",
            "exit_code",
            "content_digest",
            "revision",
            "stdout_artifact",
            "stderr_artifact",
        )
        if field not in check
    ]
    if missing:
        problems.append(
            f"{label} is recorded but missing {', '.join(missing)}: the binding "
            f"cannot be recomputed without the whole record"
        )
        return
    if check.get("stdout_text") is not None or check.get("stderr_text") is not None:
        problems.append(
            f"{label} is recorded but carries inline stdout_text/stderr_text: "
            f"a recorded check's output is its artifacts - the binding hashes "
            f"the raw stream bytes, never inline text"
        )
        return
    argv = check["command_argv"]
    shell = check["shell"]
    command = check.get("command")
    if shell is True:
        if argv != ["sh", "-c", command]:
            problems.append(
                f"{label} command {command!r} does not match its recorded argv: "
                f"a shell recording must be ['sh', '-c', <command>]"
            )
            return
    else:
        try:
            rendered = shlex.join(argv)
        except (AttributeError, TypeError, ValueError) as e:
            problems.append(f"{label} recorded command_argv cannot be rendered: {e}")
            return
        if command != rendered:
            problems.append(
                f"{label} command {command!r} does not match its recorded argv "
                f"{argv!r}: the command must be the canonical rendering of the argv"
            )
            return
    if bundle_dir is None:
        problems.append(
            f"{label} capture was not verified: no bundle directory was given, "
            f"so the artifact files are unverified"
        )
        return
    stdout_hash, problem = _hash_artifact(bundle_dir, check["stdout_artifact"], label)
    if problem:
        problems.append(problem)
        return
    stderr_hash, problem = _hash_artifact(bundle_dir, check["stderr_artifact"], label)
    if problem:
        problems.append(problem)
        return
    try:
        recomputed = _record_check.capture_binding_hash(
            command_argv=argv,
            shell=shell,
            cwd=check["cwd"],
            started_at=check["started_at"],
            finished_at=check["finished_at"],
            exit_code=check["exit_code"],
            stdout_sha256=stdout_hash,
            stderr_sha256=stderr_hash,
            content_digest=check["content_digest"],
            revision=check["revision"],
        )
    except (TypeError, ValueError) as e:
        problems.append(f"{label} recorded fields cannot be hashed: {e}")
        return
    if recomputed != capture:
        problems.append(
            f"{label} capture_sha256 mismatch: the stored binding hash does not "
            f"match the recorded fields and artifact files - the capture was "
            f"edited, or reused under a different command, tree, or revision"
        )


def check_recorded_checks(bundle, problems, bundle_dir):
    """A PASS bundle's checks must be recorded by record_check.py,
    with a binding hash the validator recomputes (F-01). The same
    rule covers fail_first.red_check: the red run is part of the PASS
    claim. FAIL/INCOMPLETE bundles are exempt from the requirement
    (they are not success claims), but a binding present there must
    still recompute. A capture recorded on one tree cannot validate a
    bundle for another: the content digest is inside the hash, so the
    same capture_sha256 under two different content_digests is a
    forgery, and is reported as such on top of the recompute failure."""
    verdict = bundle.get("verdict")
    require = verdict == "PASS"
    targets = [(c, f"check {c.get('name')!r}") for c in _checks(bundle)]
    ff = bundle.get("fail_first")
    if isinstance(ff, dict) and isinstance(ff.get("red_check"), dict):
        targets.append((ff["red_check"], "fail_first.red_check"))
    if not targets:
        return
    if _record_check is None and (
        require
        or any(
            c.get("recorded_by") is not None or c.get("capture_sha256") is not None
            for c, _ in targets
        )
    ):
        problems.append(
            "record_check.py is missing from the skill folder: a recorded "
            "capture cannot be verified without it"
        )
        return
    for check, label in targets:
        _verify_recorded_binding(check, label, bundle_dir, problems, require)
    seen = {}
    for check, _label in targets:
        capture = check.get("capture_sha256")
        digest = check.get("content_digest")
        if not isinstance(capture, str) or not capture:
            continue
        if capture in seen and seen[capture] != digest:
            problems.append(
                f"capture_sha256 {capture[:12]}... appears with two different "
                f"content_digests: a capture recorded on one tree cannot "
                f"validate a bundle for another"
            )
        else:
            seen[capture] = digest


def check_output_present(bundle, problems):
    """Every check that ran must carry its output: an artifact file
    or inline text. A PASS with no reviewable output is not
    evidence (reviewer 4, F4). INCOMPLETE checks are exempt — a
    check that could not run has no output to show, and claiming
    INCOMPLETE to dodge the rule costs the PASS anyway."""
    for c in _checks(bundle):
        if c.get("verdict") not in ("PASS", "FAIL"):
            continue
        has_output = any(
            isinstance(c.get(field), str) and c[field]
            for field in (
                "stdout_artifact",
                "stderr_artifact",
                "stdout_text",
                "stderr_text",
            )
        )
        if not has_output:
            problems.append(
                f"check {c.get('name')!r} has verdict {c.get('verdict')} "
                f"but no output: record an artifact (with its sha256) "
                f"or inline stdout_text/stderr_text"
            )


def check_empty_checks(bundle, problems):
    """A bundle with no checks at all is an honest stop only as
    INCOMPLETE with a recorded reason (reviewer 4, F5). Without
    the reason it says nothing; as PASS it claims a verification
    that never ran. The one exception is a docs-only/config-only
    PASS with every gate waived (2-V5): there is nothing to run,
    and the SKILL says never to invent a check to fill the bundle."""
    checks = bundle.get("checks")
    if not isinstance(checks, list) or checks:
        return
    if bundle.get("verdict") == "PASS" and _docs_only_no_checks_pass(bundle):
        return
    if bundle.get("verdict") != "INCOMPLETE":
        problems.append(
            "checks is empty but the verdict is not INCOMPLETE: no "
            "check ran, so the verification cannot be PASS or FAIL"
        )
    reason = bundle.get("stop_reason")
    if not isinstance(reason, str) or not reason:
        problems.append(
            "checks is empty but there is no stop_reason: record why "
            "the verification stopped before the first check"
        )


def check_dirty_files(bundle, problems):
    """dirty_files is listed when the tree is dirty and empty when
    it is clean (a conditional rule the schema cannot express). A
    PASS on a dirty tree must also pin the diff it ran on
    (diff_sha256 of `git diff HEAD`): a dirty tree has no revision
    to bind the PASS to (V4)."""
    state = bundle.get("working_tree_state")
    if state == "dirty":
        dirty = bundle.get("dirty_files")
        if not isinstance(dirty, list) or not dirty:
            problems.append("working_tree_state is 'dirty' but dirty_files is empty or missing")
        elif bundle.get("verdict") == "PASS" and not bundle.get("diff_sha256"):
            problems.append(
                "verdict is PASS on a dirty tree but there is no diff_sha256: "
                "record the sha256 of `git diff HEAD` so the PASS is bound to this diff"
            )
    elif state == "clean":
        dirty = bundle.get("dirty_files")
        if isinstance(dirty, list) and dirty:
            problems.append(
                "working_tree_state is 'clean' but dirty_files is non-empty: "
                "dirty_files must be empty when the tree is clean"
            )


def _old_schema_problems(bundle, schema):
    """The migration message (F-24): a bundle from an older schema
    version is rejected with an explicit message — the schema moved
    on, and the fix is to re-run verification with the current
    validator — instead of the flat const error ("must be 6, got 4"),
    which says nothing about what changed or how to upgrade.
    Returns the problem list, or None when this does not apply: no
    version, a non-integer version, the current version, or a newer
    one — those keep the flat schema error. The CHANGELOG names only
    schema v3 explicitly, so the message does not cite it for the
    version history; the history is recorded in the validator's
    tests (v3 rejection, v4 rejection, v5 rejection)."""
    if not isinstance(bundle, dict):
        return None
    version = bundle.get("schema_version")
    if type(version) is not int:
        return None
    current = schema.get("properties", {}).get("schema_version", {}).get("const")
    if type(current) is not int or version >= current:
        return None
    return [
        f"schema_version is {version}: this bundle was written against an older "
        f"evidence schema (v{version}) - re-run verification with the current "
        f"validator (schema v{current}) to produce a new bundle; old bundles are "
        f"rejected, not migrated"
    ]


# A full commit SHA in this repo's object format: SHA-1 (40 hex)
# or SHA-256 (64 hex) — the same shape record_check.py requires
# for a resolved revision (round 8, FND-023).
_SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def _git_output(repo, *args):
    """(returncode, stdout) of a git command in `repo`, or
    (None, "") when git cannot run at all."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None, ""
    return proc.returncode, proc.stdout


def _resolve_commit(repo, rev):
    """The full SHA `rev` names in `repo`, or None when it names
    nothing: `git rev-parse --verify <rev>^{commit}` must succeed
    and print a single full SHA — a bare rev-parse echoing its
    input, or a stubbed git printing nothing, resolves to nothing."""
    rc, out = _git_output(repo, "rev-parse", "--verify", f"{rev}^{{commit}}")
    if rc != 0:
        return None
    sha = out.strip()
    return sha if _SHA_RE.fullmatch(sha) else None


def _git_diff_sha256(repo):
    """The sha256 of `git diff HEAD` in `repo`, or None when git
    cannot produce it."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "diff", "HEAD"], capture_output=True, timeout=60
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return hashlib.sha256(proc.stdout).hexdigest()


def check_tree_binding(bundle, problems, repo, expected_revision=None, expected_diff_sha256=None):
    """Bind the bundle to the tree it ran on (round 8, FND-004;
    pattern: SLSA's slsa-verifier and in-toto's in_toto_verify —
    the verifier re-reads the object itself, recomputes the digest,
    and compares it against the claim and the caller's expected
    identity, instead of trusting self-declared fields).

    When `repo` is None no tree binding is performed (legacy /
    in-process behaviour — state.py calls validate_bundle this way
    until it passes a repo). When a repo is given:
    - the bundle revision must resolve to a commit in it, and every
      check's revision (including fail_first.red_check) must resolve
      to that same commit; a bundle revision of "working-tree"
      binds to HEAD, the commit its diff applies to;
    - every check's content_digest must equal the digest recomputed
      from the tree at that revision;
    - a PASS on a dirty tree must pin the diff it ran on: the sha256
      of `git diff HEAD`, recomputed here, must match diff_sha256;
    - --expected-revision / --expected-diff, when given, must match
      the bundle revision / recomputed diff.
    When no repo can be resolved at all, a PASS bundle claiming a
    revision FAILS CLOSED — never silently passes. An honest
    FAIL/INCOMPLETE bundle in the same situation is still fileable:
    it is not a success claim. What this does NOT prove: that the
    commands ran (the lying-command half stays out of scope — see
    the module docstring and docs/adr/0006-tree-binding.md)."""
    if repo is None:
        return
    verdict = bundle.get("verdict")
    rc, out = _git_output(repo, "rev-parse", "--show-toplevel")
    top = out.strip() if rc == 0 else ""
    if rc != 0 or not top or "\n" in top or not Path(top).is_dir():
        if verdict == "PASS":
            problems.append(
                f"cannot bind the bundle to a tree: {repo} is not a git "
                "repository — a PASS bundle claiming a revision cannot "
                "validate without a repo to recompute it against "
                "(pass --repo <repo>)"
            )
        return
    repo = Path(top)
    head = _resolve_commit(repo, "HEAD")
    if head is None:
        if verdict == "PASS":
            problems.append(
                f"cannot bind the bundle to a tree: HEAD does not resolve to a commit in {repo}"
            )
        return
    bundle_revision = bundle.get("revision")
    if bundle_revision == "working-tree":
        target = head
    elif isinstance(bundle_revision, str):
        target = _resolve_commit(repo, bundle_revision)
        if target is None:
            problems.append(
                f"bundle revision {bundle_revision!r} does not resolve to a commit in {repo}: "
                "the bundle cannot be bound to a tree that has no such revision"
            )
            return
    else:
        return  # the schema layer already reported a non-string revision
    if expected_revision is not None:
        expected = _resolve_commit(repo, expected_revision)
        if expected is None:
            problems.append(
                f"--expected-revision {expected_revision!r} does not resolve to a commit in {repo}"
            )
        elif expected != target:
            problems.append(
                f"bundle revision {bundle_revision!r} (resolved {target}) does not match "
                f"--expected-revision {expected_revision!r} (resolved {expected})"
            )
    if _content_digest_fn is None:
        problems.append(
            "content_digest.py is missing from the skill folder: the bundle's "
            "content digests cannot be recomputed without it"
        )
        return
    try:
        recomputed = _content_digest_fn(repo, target)
    except Exception as e:
        problems.append(f"cannot recompute the content digest for revision {target} in {repo}: {e}")
        return
    targets = [(c, f"check {c.get('name')!r}") for c in _checks(bundle)]
    ff = bundle.get("fail_first")
    if isinstance(ff, dict) and isinstance(ff.get("red_check"), dict):
        targets.append((ff["red_check"], "fail_first.red_check"))
    for check, label in targets:
        revision = check.get("revision")
        if isinstance(revision, str) and revision:
            resolved = _resolve_commit(repo, revision)
            if resolved is None:
                problems.append(
                    f"{label} revision {revision!r} does not resolve to a commit in {repo}"
                )
            elif resolved != target:
                problems.append(
                    f"{label} revision {revision!r} (resolved {resolved}) does not match "
                    f"the bundle revision {bundle_revision!r} (resolved {target}): a check "
                    "recorded on another revision cannot validate this bundle"
                )
        digest = check.get("content_digest")
        if isinstance(digest, str) and digest:
            if digest != recomputed:
                problems.append(
                    f"{label} content_digest {digest} does not match the digest recomputed "
                    f"from the tree at revision {target} ({recomputed})"
                )
    if verdict == "PASS" and bundle.get("working_tree_state") == "dirty":
        diff = _git_diff_sha256(repo)
        if diff is None:
            problems.append(
                f"cannot recompute `git diff HEAD` in {repo}: the dirty-tree PASS "
                "cannot be bound to its diff"
            )
        else:
            recorded = bundle.get("diff_sha256")
            if isinstance(recorded, str) and recorded and recorded != diff:
                problems.append(
                    f"diff_sha256 {recorded} does not match the sha256 of `git diff HEAD` "
                    f"recomputed in {repo} ({diff}): the PASS is bound to a different diff"
                )
            if expected_diff_sha256 is not None and expected_diff_sha256 != diff:
                problems.append(
                    f"--expected-diff {expected_diff_sha256} does not match the sha256 of "
                    f"`git diff HEAD` recomputed in {repo} ({diff})"
                )


def validate_bundle(
    bundle, schema, bundle_dir=None, repo=None, expected_revision=None, expected_diff_sha256=None
):
    """Both layers. Structural problems short-circuit the semantic
    checks, so a malformed bundle can never crash them. bundle_dir
    is the directory the bundle file lives in; artifact paths resolve
    against it (the CLI passes the bundle's parent). When it is None,
    artifacts are recorded as explicitly unverified, never as passed.
    repo is the git repo the bundle is bound to (round 8, FND-004):
    when given, every check's revision and content digest are
    recomputed from that repo's tree and compared against the bundle
    and against expected_revision / expected_diff_sha256; when None,
    no tree binding is performed (legacy/in-process behaviour)."""
    problems = _old_schema_problems(bundle, schema)
    if problems:
        return problems
    problems = validate_against_schema(bundle, schema)
    if problems:
        return problems
    check_verdict_consistency(bundle, problems)
    check_fail_first(bundle, problems, bundle_dir)
    check_test_report(bundle, problems, bundle_dir)
    check_identities(bundle, problems)
    check_noop_commands(bundle, problems)
    check_plan_coverage(bundle, problems)
    check_change_type_files(bundle, problems)
    check_files_changed_for_behaviour_change(bundle, problems)
    check_finding_categories(bundle, problems)
    check_acceptance_criteria(bundle, problems)
    check_time_order(bundle, problems)
    check_future_timestamps(bundle, problems)
    check_artifacts(bundle, problems, bundle_dir)
    check_recorded_checks(bundle, problems, bundle_dir)
    check_output_present(bundle, problems)
    check_empty_checks(bundle, problems)
    check_dirty_files(bundle, problems)
    check_tree_binding(bundle, problems, repo, expected_revision, expected_diff_sha256)
    return problems


def extract_verdict_block(text):
    """Extract the single ```verdict block from a prose response.
    Returns (block, problem): block is the parsed JSON object, or
    None with a problem when there is no block, more than one, or
    the block is not a JSON object."""
    blocks = re.findall(r"```verdict\s*\n(.*?)```", text, re.DOTALL)
    if not blocks:
        return None, "no ```verdict block found in the verdict-block file"
    if len(blocks) > 1:
        return None, f"found {len(blocks)} ```verdict blocks: exactly one is expected"
    try:
        block = json.loads(blocks[0])
    except json.JSONDecodeError as e:
        return None, f"the ```verdict block is not valid JSON: {e}"
    if not isinstance(block, dict):
        return None, "the ```verdict block is not a JSON object"
    return block, None


def check_verdict_block(bundle, block, problems):
    """The prose verdict block (SKILL.md: the machine-readable form
    of the verdict) must agree with the evidence bundle (V8): the
    same verdict, the same check verdicts, and a named finding file
    must be a file the bundle has a finding for. The block's
    `finding` text is free prose and is not compared."""
    if block.get("verdict") != bundle.get("verdict"):
        problems.append(
            f"verdict block says verdict {block.get('verdict')!r} but "
            f"the bundle says {bundle.get('verdict')!r}"
        )
    block_checks = block.get("checks")
    if isinstance(block_checks, dict):
        bundle_checks = {c.get("name"): c.get("verdict") for c in _checks(bundle)}
        for name, verdict in block_checks.items():
            if name not in bundle_checks:
                problems.append(f"verdict block check {name!r} has no check in the bundle")
            elif bundle_checks[name] != verdict:
                problems.append(
                    f"verdict block check {name!r} says {verdict!r} but "
                    f"the bundle check says {bundle_checks[name]!r}"
                )
        for name in bundle_checks:
            if name not in block_checks:
                problems.append(f"bundle check {name!r} is missing from the verdict block")
    else:
        problems.append("verdict block has no 'checks' object")
    block_file = block.get("file")
    if block_file is None:
        if any(_is_blocking(f) for f in _findings(bundle)):
            problems.append(
                "verdict block names no finding file but the bundle has a blocking finding"
            )
    elif isinstance(block_file, str):
        if block_file not in {f.get("file") for f in _findings(bundle)}:
            problems.append(
                f"verdict block names file {block_file!r} but the bundle has no finding for it"
            )


def load_schema(path):
    with open(path, encoding="utf-8") as f:
        schema = json.load(f)
    if not isinstance(schema, dict):
        raise ValueError(f"{path} is not a JSON object")
    return schema


def main(argv):
    parser = argparse.ArgumentParser(
        description="Validate an ORCINUS verification evidence bundle.",
        usage="python3 skills/orcinus-verify/scripts/validate_evidence.py "
        "<bundle.json> [--verdict-block <response.md>] [--repo <repo>] "
        "[--expected-revision <rev>] [--expected-diff <sha256>]",
    )
    parser.add_argument("bundle", help="the evidence bundle JSON file")
    parser.add_argument(
        "--verdict-block",
        default=None,
        metavar="<response.md>",
        help="a file holding the prose response: its ```verdict block must agree with the bundle",
    )
    parser.add_argument(
        "--repo",
        default=None,
        metavar="<repo>",
        help="the git repo the bundle is bound to (default: the working directory)",
    )
    parser.add_argument(
        "--expected-revision",
        default=None,
        metavar="<rev>",
        help="the revision the bundle must be bound to",
    )
    parser.add_argument(
        "--expected-diff",
        default=None,
        dest="expected_diff_sha256",
        metavar="<sha256>",
        help="the sha256 of `git diff HEAD` a dirty-tree PASS must be bound to",
    )
    args = parser.parse_args(argv[1:])
    path = Path(args.bundle)
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"{path} is not valid JSON: {e}", file=sys.stderr)
        return 1
    except (UnicodeDecodeError, RecursionError, OSError) as e:
        # 2-V4: a bundle that cannot even be read as JSON (not UTF-8,
        # nested too deeply) is a controlled error, exit 2 — never a
        # traceback, against the module docstring's promise.
        print(f"{path} could not be read as JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(bundle, dict):
        print(f"{path} is not a JSON object", file=sys.stderr)
        return 1
    if not SCHEMA_PATH.is_file():
        print(f"schema missing: {SCHEMA_PATH}", file=sys.stderr)
        return 2
    try:
        schema = load_schema(SCHEMA_PATH)
        problems = validate_bundle(
            bundle,
            schema,
            bundle_dir=path.parent,
            repo=Path(args.repo) if args.repo is not None else Path.cwd(),
            expected_revision=args.expected_revision,
            expected_diff_sha256=args.expected_diff_sha256,
        )
    except (ValueError, OSError, RecursionError) as e:
        print(f"validator error: {e}", file=sys.stderr)
        return 2
    if args.verdict_block is not None:
        block_path = Path(args.verdict_block)
        if not block_path.is_file():
            print(f"no such file: {block_path}", file=sys.stderr)
            return 2
        try:
            block_text = block_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            print(f"{block_path} could not be read: {e}", file=sys.stderr)
            return 2
        block, problem = extract_verdict_block(block_text)
        if problem:
            problems.append(problem)
        else:
            check_verdict_block(bundle, block, problems)
    if problems:
        print(f"FAIL: {len(problems)} problem(s) in {path}")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK: {path} is a valid, consistent evidence bundle")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
