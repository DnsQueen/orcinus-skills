# Unified report format — one machine-readable shape for all checkers

Date: 2026-11-06
Status: spec (v0.9). The checkers do not all emit it yet; the format is
the contract they converge to. A checker that cannot emit it must say
so in its own output, not silently emit a different shape.

## Why

ORCINUS has several checkers (the repo validator, the drift check,
the architecture checker, the refactor checker, the migration
generator, the evidence validator, the doctor). Each prints its own
prose. A human can read them, but a machine cannot combine them:
"did everything pass?" requires parsing five different outputs. The
unified format is one JSON object that any checker can emit and any
consumer (CI, the router, a human reading a summary) can combine.

## The format

```json
{
  "format_version": 1,
  "tool": "validate_repo",
  "tool_version": "1.0.0",
  "revision": "abc1234",
  "scope": "the whole repo",
  "status": "PASS",
  "checks_run": [
    {"name": "skill frontmatter", "status": "PASS"},
    {"name": "manifest", "status": "PASS"}
  ],
  "findings": [],
  "artifacts": ["scripts/validate_repo.py"],
  "unverified_items": [],
  "started_at": "2026-11-06T15:00:00+03:30",
  "finished_at": "2026-11-06T15:00:01+03:30"
}
```

## Fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `format_version` | integer | yes | 1. Bump when a required field is added or a rule changes. |
| `tool` | string | yes | The checker that produced the report (e.g. `validate_repo`, `check_drift`, `check_architecture`, `check_refactor`, `validate_evidence`, `doctor`). |
| `tool_version` | string | no | The checker's version, when it has one. |
| `revision` | string | yes | The exact commit (or working-tree state) the checks ran on. A PASS is bound to this revision only — the same rule as the evidence bundle. |
| `scope` | string | yes | What was checked (e.g. `the whole repo`, `skills/architecture`, `the weekly-summary slice`). |
| `status` | string | yes | `PASS`, `FAIL`, or `INCOMPLETE`. Same meaning as the evidence bundle: PASS needs every check PASS and no unverified items; FAIL needs a blocking finding; INCOMPLETE means a check could not run or evidence is missing. |
| `checks_run` | array of `{name, status}` | yes | Every check the tool ran, each with its own `PASS` / `FAIL` / `INCOMPLETE`. A check that was skipped is listed with `INCOMPLETE` and a reason in `unverified_items`, never omitted. |
| `findings` | array of `{file, line, evidence, severity}` | yes | Findings, each with the file, the line, and the evidence that proves it. `severity` is `blocking` or `non-blocking`. A blocking finding makes `status` FAIL. |
| `artifacts` | array of strings | yes | Where the outputs are saved (paths, relative to the repo). |
| `unverified_items` | array of strings | yes | What could not be checked, and why. Non-empty means `status` cannot be PASS. |
| `started_at`, `finished_at` | ISO 8601 strings | no | When the run started and finished. |

## Rules

1. **A report is complete or it is INCOMPLETE.** A checker that
   passes on empty or missing inputs is a gate that cannot fail. If
   the expected files are missing, the report's `status` is
   INCOMPLETE and `unverified_items` says what is missing.
2. **No silent skips.** A check that did not run is listed in
   `checks_run` with `INCOMPLETE`, not omitted.
3. **A PASS is bound to its revision.** The `revision` field is the
   same binding as the evidence bundle's `revision`. A report from
   one revision does not certify another.
4. **The evidence bundle is the verification report.** The
   `skills/orcinus-verify/references/evidence.schema.json` bundle is the verification-specific
   form of this format (it adds `fail_first`, `files_changed`, and
   `reviewer_identity`). A verification report uses the evidence
   schema; a checker report uses this format. Both share the
   `status` / `revision` / `unverified_items` semantics.

## Adoption

- `skills/orcinus-verify/scripts/validate_evidence.py` already enforces the equivalent
  rules for evidence bundles (verdict consistency, fail-first).
- The Python checkers (`validate_repo.py`, `check_drift.py`,
  `check_architecture.py`, `check_refactor.py`, `doctor.py`) print
  prose today. Emitting this JSON (alongside the prose, or with a
  `--json` flag) is a v1.1 step, not a v1 blocker — the format is
  specified now so the checkers converge to one shape instead of
  five.
