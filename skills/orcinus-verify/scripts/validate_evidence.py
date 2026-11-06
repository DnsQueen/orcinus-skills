#!/usr/bin/env python3
"""Validate an ORCINUS verification evidence bundle against
references/evidence.schema.json (bundled in this skill folder).

Two layers, kept separate:

1. Structural validation: the bundle is checked against the schema
   itself, by a small JSON Schema interpreter below (standard library
   only). It enforces exactly the keywords the schema uses — type
   (with strict bool/int separation), const, enum, required,
   properties, additionalProperties, minLength, minItems, items,
   minimum, format (date-time only) — and fails loudly if the schema
   ever gains a keyword the interpreter does not know, so the subset
   can never silently drift. This is a subset interpreter for this
   schema, not a general JSON Schema validator; the docstring says so
   plainly and the tests pin the covered keywords.
2. Semantic validation: the rules the schema cannot express. The
   overall verdict is computed from the evidence by one function
   (expected_verdict), never taken from the agent: a blocking finding
   or a failed check forces FAIL; otherwise incomplete evidence forces
   INCOMPLETE; otherwise PASS. A PASS also needs a verification plan
   naming its required gates, each covered by a passing check with
   the same name — one passing check must never stand for all gates.

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
contradicted verdict cannot slip through as a PASS.
"""

import json
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

# Keywords the subset interpreter implements. Anything else in the
# schema raises, so an unimplemented keyword is a loud failure,
# never a silent pass.
SUPPORTED_KEYWORDS = {
    "type", "const", "enum", "required", "properties",
    "additionalProperties", "minLength", "minItems", "items",
    "minimum", "maximum", "format",
    # Documentation-only keys, ignored by the interpreter.
    "description", "title", "$schema", "$id", "default", "examples",
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
    if type(value) is not str:
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
        raise ValueError(
            f"unsupported schema keyword(s) at {path or 'root'}: "
            f"{sorted(unknown)}")
    if "type" in schema:
        wanted = schema["type"]
        types = wanted if isinstance(wanted, list) else [wanted]
        if not any(_type_matches(instance, t) for t in types):
            problems.append(
                f"{path or 'value'} must be of type {wanted}, "
                f"got {type(instance).__name__}")
            return
    if "const" in schema and not _strict_equal(instance, schema["const"]):
        problems.append(
            f"{path or 'value'} must be {schema['const']!r}, "
            f"got {instance!r}")
    if "enum" in schema and not any(
            _strict_equal(instance, e) for e in schema["enum"]):
        problems.append(
            f"{path or 'value'} must be one of {schema['enum']}, "
            f"got {instance!r}")
    if isinstance(instance, str) and "minLength" in schema:
        if len(instance) < schema["minLength"]:
            problems.append(
                f"{path or 'value'} must be at least "
                f"{schema['minLength']} character(s)")
    if isinstance(instance, list) and "minItems" in schema:
        if len(instance) < schema["minItems"]:
            problems.append(
                f"{path or 'value'} must have at least "
                f"{schema['minItems']} item(s)")
    if isinstance(instance, (int, float)) and not _is_bool(instance):
        if "minimum" in schema and instance < schema["minimum"]:
            problems.append(
                f"{path or 'value'} must be >= {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            problems.append(
                f"{path or 'value'} must be <= {schema['maximum']}")
    if "format" in schema:
        if schema["format"] == "date-time":
            if not _is_iso8601(instance):
                problems.append(
                    f"{path or 'value'} must be an ISO 8601 date-time")
        else:
            raise ValueError(
                f"unsupported schema format at {path or 'root'}: "
                f"{schema['format']!r}")
    if isinstance(instance, dict):
        for field in schema.get("required", []):
            if field not in instance:
                problems.append(
                    f"{path + '.' if path else ''}{field}: "
                    f"missing required field")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                child = f"{path}.{key}" if path else key
                _validate(value, properties[key], child, problems)
            elif schema.get("additionalProperties") is False:
                problems.append(
                    f"{path + '.' if path else ''}{key}: "
                    f"unexpected property (not in the schema)")
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
    non-zero exit code counts as failed."""
    checks = _checks(bundle)
    findings = _findings(bundle)
    blocking = [f for f in findings if f.get("severity") == "blocking"]
    failed = [c for c in checks
              if c.get("verdict") == "FAIL"
              or (c.get("verdict") == "PASS"
                  and _is_int(c.get("exit_code"))
                  and c["exit_code"] != 0)]
    unverified = bundle.get("unverified_items")
    incomplete = (
        [c for c in checks if c.get("verdict") == "INCOMPLETE"]
        or (isinstance(unverified, list) and bool(unverified))
        or [c for c in checks if c.get("unverified_items")])
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
        if (c.get("verdict") == "PASS" and _is_int(c.get("exit_code"))
                and c["exit_code"] != 0):
            problems.append(
                f"check {c.get('name')!r} has verdict PASS but "
                f"exit_code {c['exit_code']}")
    expected = expected_verdict(bundle)
    if verdict == expected:
        return
    if verdict == "PASS":
        if any(c.get("verdict") == "FAIL" for c in checks):
            problems.append("verdict is PASS but a check has verdict FAIL")
        if any(c.get("verdict") == "INCOMPLETE" for c in checks):
            problems.append(
                "verdict is PASS but a check has verdict INCOMPLETE")
        if any(f.get("severity") == "blocking" for f in _findings(bundle)):
            problems.append(
                "verdict is PASS but there is a blocking finding")
        if bundle.get("unverified_items"):
            problems.append(
                "verdict is PASS but unverified_items is non-empty")
        if any(c.get("unverified_items") for c in checks):
            problems.append(
                "verdict is PASS but a check has non-empty "
                "unverified_items")
    elif verdict == "FAIL":
        problems.append(
            "verdict is FAIL but there is no blocking finding and no "
            "check with verdict FAIL")
    elif verdict == "INCOMPLETE":
        if expected == "FAIL":
            problems.append(
                "verdict is INCOMPLETE but a check has verdict FAIL or "
                "there is a blocking finding: the evidence requires FAIL")
        else:
            problems.append(
                "verdict is INCOMPLETE but no check is INCOMPLETE and "
                "nothing is unverified")


def check_fail_first(bundle, problems):
    """The fail-first proof must show the test failing before the fix
    and passing after it, unless the method is not-applicable (with a
    note saying why). Types are enforced by the schema layer, so
    truthiness here is safe: failed_before/passed_after are real
    booleans by the time this runs."""
    ff = bundle.get("fail_first")
    if ff is None:
        return
    if not isinstance(ff, dict):
        return
    if ff.get("method") == "not-applicable":
        if not ff.get("note"):
            problems.append("fail_first.method is 'not-applicable' but no "
                            "note says why")
        return
    if "failed_before" in ff and not ff["failed_before"]:
        problems.append("fail_first.failed_before is false: the test was "
                        "never shown failing on the pre-fix code")
    if "passed_after" in ff and not ff["passed_after"]:
        problems.append("fail_first.passed_after is false: the test does "
                        "not pass after the fix")


def check_plan_coverage(bundle, problems):
    """A PASS needs a verification plan naming its required gates,
    each covered by a passing check with the same name. Gates the
    change does not need go in not_applicable_gates with a reason.
    For FAIL/INCOMPLETE the plan is only shape-checked (the schema
    layer already enforces its types); coverage is a PASS rule."""
    plan = bundle.get("verification_plan")
    verdict = bundle.get("verdict")
    if verdict != "PASS":
        return
    if plan is None:
        problems.append(
            "verdict is PASS but there is no verification_plan: a PASS "
            "needs the plan naming its required gates")
        return
    if not isinstance(plan, dict):
        return
    required = plan.get("required_gates")
    if not isinstance(required, list) or not required:
        problems.append(
            "verdict is PASS but verification_plan.required_gates is "
            "empty or missing: name the gates this change was verified "
            "against")
        return
    checks = _checks(bundle)
    passing = {c.get("name") for c in checks
               if c.get("verdict") == "PASS"}
    for gate in required:
        if gate not in passing:
            problems.append(
                f"required gate {gate!r} has no passing check")
    for entry in plan.get("not_applicable_gates") or []:
        if not isinstance(entry, dict):
            continue
        if not entry.get("reason"):
            problems.append(
                f"gate {entry.get('gate')!r} is listed as "
                f"not-applicable but no reason says why")


def check_dirty_files(bundle, problems):
    """dirty_files is listed when the tree is dirty (a conditional
    rule the schema cannot express)."""
    if bundle.get("working_tree_state") == "dirty":
        dirty = bundle.get("dirty_files")
        if not isinstance(dirty, list) or not dirty:
            problems.append("working_tree_state is 'dirty' but dirty_files "
                            "is empty or missing")


def validate_bundle(bundle, schema):
    """Both layers. Structural problems short-circuit the semantic
    checks, so a malformed bundle can never crash them."""
    problems = validate_against_schema(bundle, schema)
    if problems:
        return problems
    check_verdict_consistency(bundle, problems)
    check_fail_first(bundle, problems)
    check_plan_coverage(bundle, problems)
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
        print("usage: python3 skills/orcinus-verify/scripts/validate_evidence.py <bundle.json>",
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
    try:
        schema = load_schema(SCHEMA_PATH)
        problems = validate_bundle(bundle, schema)
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
