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
   — a bare test name with no output proves nothing. Every check
   that ran (verdict PASS or FAIL) must carry its output — an
   artifact file with its sha256, or inline text — so a PASS with
   no reviewable output is rejected. Artifact paths must stay
   inside the bundle directory (no absolute paths, no `..` escape,
   no symlinks) and are hashed by streaming from a descriptor with
   a size cap; without a bundle directory an artifact is recorded
   as unverified, never as passed.
   A bundle with no checks at all is valid only as INCOMPLETE, with
   a stop_reason saying why the verification stopped. An honest FAIL
   or INCOMPLETE report is a valid bundle: the fail-first and plan
   rules are PASS rules, never validity rules — only a PASS must
   satisfy them.

Structural validation runs first. If it finds any problem, the
semantic checks do not run at all: a malformed bundle produces a
controlled report and exit 1, never a traceback.

Usage: python3 skills/orcinus-verify/scripts/validate_evidence.py <bundle.json>
Exit 0 when the bundle is valid and consistent; exit 1 otherwise,
with each problem on its own line; exit 2 for a usage error, a
missing or unreadable schema, or an internal validator error.

The validator and its schema live inside the orcinus-verify skill
folder and resolve relative to this file, so they work from a user
project with no repo checkout (in a plugin install, the skill folder
is ${CLAUDE_PLUGIN_ROOT}/skills/orcinus-verify; in a standalone
install it is the skill folder itself).

The validator does not prove the evidence is true — a bundle can
claim a command passed while the command never ran. It proves the
bundle is complete and self-consistent, so a missing check or a
contradicted verdict cannot slip through as a PASS. Since v3 every
executed check must also carry its output, so a PASS with no
reviewable output is rejected — but the output itself can still be
fabricated, which is what the agent-behaviour eval measures.
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

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
    acceptance identical on every Python >= 3.10; fromisoformat then
    only validates the ranges."""
    if type(value) is not str:
        return False
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?"
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


def expected_verdict(bundle):
    """The single verdict computation. A blocking finding or a failed
    check forces FAIL; otherwise incomplete evidence forces
    INCOMPLETE; otherwise PASS. A check that claims PASS with a
    non-zero exit code counts as failed. Fail-closed: a finding whose
    severity is anything other than "non-blocking" counts as
    blocking. No acceptance criteria means the verification stopped:
    INCOMPLETE, never PASS."""
    checks = _checks(bundle)
    findings = _findings(bundle)
    blocking = [f for f in findings if f.get("severity") != "non-blocking"]
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
        or not checks
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
        if any(f.get("severity") != "non-blocking" for f in _findings(bundle)):
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
    to pass)."""
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
            "the run of that test"
        )


# Commands that run nothing: a check whose command is a shell no-op
# proves no work happened, however clean its exit code looks.
NOOP_COMMANDS = ("true", "false", ":", "echo", "exit")


def check_noop_commands(bundle, problems):
    """A check that ran a no-op command is not evidence of anything
    (2-V2: command="true" for the test gate used to pass)."""
    for c in _checks(bundle):
        command = c.get("command")
        if not isinstance(command, str):
            continue
        first = command.strip().split()
        if first and first[0] in NOOP_COMMANDS:
            problems.append(
                f"check {c.get('name')!r} command {command!r} is a no-op: "
                f"a check must run the gate, not a command that always succeeds"
            )


def check_identities(bundle, problems):
    """The verifier must differ from the implementer: a verifier
    cannot verify their own work (2-V2: reviewer_identity
    "implementer" used to pass — there was no implementer field to
    compare against at all)."""
    reviewer = bundle.get("reviewer_identity")
    implementer = bundle.get("implementer_identity")
    if isinstance(reviewer, str) and reviewer.strip().lower() == "implementer":
        problems.append(
            "reviewer_identity is 'implementer': the verifier must differ from the implementer"
        )
    if isinstance(reviewer, str) and isinstance(implementer, str) and reviewer == implementer:
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
    already enforces RFC 3339 on both, so parsing cannot fail here."""
    for c in _checks(bundle):
        started = c.get("started_at")
        finished = c.get("finished_at")
        if not isinstance(started, str) or not isinstance(finished, str):
            continue
        start = datetime.fromisoformat(started.replace("Z", "+00:00"))
        end = datetime.fromisoformat(finished.replace("Z", "+00:00"))
        if end < start:
            problems.append(
                f"check {c.get('name')!r} finished_at {finished} is before started_at {started}"
            )


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
            f, problem = _open_artifact(bundle_dir, artifact, label)
            if problem:
                problems.append(problem)
                continue
            with f:
                digest = hashlib.sha256()
                total = 0
                too_large = False
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_ARTIFACT_BYTES:
                        problems.append(
                            f"{label} is larger than the {MAX_ARTIFACT_BYTES}-byte artifact cap"
                        )
                        too_large = True
                        break
                    digest.update(chunk)
                if too_large:
                    continue
                if isinstance(recorded, str) and recorded and digest.hexdigest() != recorded:
                    problems.append(
                        f"{label} sha256 mismatch: the file changed since the bundle was written"
                    )


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
    that never ran."""
    checks = bundle.get("checks")
    if not isinstance(checks, list) or checks:
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
    """dirty_files is listed when the tree is dirty (a conditional
    rule the schema cannot express)."""
    if bundle.get("working_tree_state") == "dirty":
        dirty = bundle.get("dirty_files")
        if not isinstance(dirty, list) or not dirty:
            problems.append("working_tree_state is 'dirty' but dirty_files is empty or missing")


def validate_bundle(bundle, schema, bundle_dir=None):
    """Both layers. Structural problems short-circuit the semantic
    checks, so a malformed bundle can never crash them. bundle_dir
    is the directory the bundle file lives in; artifact paths resolve
    against it (the CLI passes the bundle's parent). When it is None,
    artifacts are recorded as explicitly unverified, never as passed."""
    problems = validate_against_schema(bundle, schema)
    if problems:
        return problems
    check_verdict_consistency(bundle, problems)
    check_fail_first(bundle, problems, bundle_dir)
    check_identities(bundle, problems)
    check_noop_commands(bundle, problems)
    check_plan_coverage(bundle, problems)
    check_acceptance_criteria(bundle, problems)
    check_time_order(bundle, problems)
    check_artifacts(bundle, problems, bundle_dir)
    check_output_present(bundle, problems)
    check_empty_checks(bundle, problems)
    check_dirty_files(bundle, problems)
    return problems


def load_schema(path):
    with open(path, encoding="utf-8") as f:
        schema = json.load(f)
    if not isinstance(schema, dict):
        raise ValueError(f"{path} is not a JSON object")
    return schema


def main(argv):
    if len(argv) != 2:
        print(
            "usage: python3 skills/orcinus-verify/scripts/validate_evidence.py <bundle.json>",
            file=sys.stderr,
        )
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
    try:
        schema = load_schema(SCHEMA_PATH)
        problems = validate_bundle(bundle, schema, bundle_dir=path.parent)
    except (ValueError, OSError) as e:
        print(f"validator error: {e}", file=sys.stderr)
        return 2
    if problems:
        print(f"FAIL: {len(problems)} problem(s) in {path}")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK: {path} is a valid, consistent evidence bundle")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
