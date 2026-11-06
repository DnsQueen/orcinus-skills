# Persistent project state — `.orcinus/state.json`

Date: 2026-11-06
Status: spec (v0.9). The router reads and writes this file; the
enforcement layer that would make it tamper-proof is v1.1 (see
SCOPE.md). This spec defines the file so the router, the verifier,
and the human all agree on what "verified" means.

## Why

Today, whether a project is verified lives in the agent's memory and
in prose reports. A new session cannot tell, without re-running
everything, whether the slice it is about to build on was verified,
for which revision, and what the human approved. The state file is
the durable answer: one JSON file in the project, committed with it,
that records the lifecycle state and binds every claim to a revision
and an evidence bundle.

## The file

`.orcinus/state.json` in the project root. It is committed with the
project (it is the project's own record, not the agent's). It is
never written by hand — the router and the verifier update it, and
the human approves transitions that need approval.

```json
{
  "format_version": 1,
  "project": "weekly-budget",
  "stage": "VERIFYING",
  "revision": "b2809bd64f5679ce56eb79a239109978f0c9f06a",
  "evidence_bundle": "docs/verification/stage-30.json",
  "approval": null,
  "history": [
    {
      "stage": "BUILDING",
      "revision": "90a91c8",
      "at": "2026-11-06T14:00:00+03:30",
      "note": "Stage 20 built test-first, 31/31 tests."
    }
  ]
}
```

## Stages

| Stage | Meaning |
|---|---|
| `BUILDING` | A slice is being built. Nothing in this stage is verified. |
| `VERIFYING` | The verifier is running. The `revision` is the one being checked. |
| `BLOCKED` | Verification found a blocking finding. The `evidence_bundle` says what. |
| `VERIFIED` | The revision passed verification. Bound to the `evidence_bundle` for that exact revision. A new commit moves the project back to `BUILDING` — a VERIFIED state from one revision does not certify another. |
| `AWAITING_APPROVAL` | Verified, and waiting for the human to approve the next step (release, merge, publish). |
| `RELEASE_READY` | The human approved the verified revision for release. The `approval` field records who approved, what revision, and what artifact. |

## Fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `format_version` | integer | yes | 1. Bump when a required field is added or a rule changes. |
| `project` | string | yes | The project name. |
| `stage` | string | yes | One of the six stages above. |
| `revision` | string | yes | The exact commit the stage refers to. |
| `evidence_bundle` | string or null | yes | The path to the evidence bundle (per `skills/orcinus-verify/references/evidence.schema.json`) for the `revision`, or null when there is none (BUILDING). |
| `approval` | object or null | yes | When the human approves: `{approved_by, revision, artifact, at}`. The approval is bound to a specific revision and artifact hash — approving one revision does not approve the next. |
| `history` | array | yes | Every stage transition, with the revision and the time. The history is append-only; a transition is never rewritten. |

## Rules

1. **VERIFIED is bound to a revision and an evidence bundle.** A
   state file that says VERIFIED without an `evidence_bundle` that
   validates (see `skills/orcinus-verify/scripts/validate_evidence.py`) is corrupt, not
   verified.
2. **A new commit resets the stage.** When the revision changes, the
   stage goes back to BUILDING. The history keeps the old VERIFIED
   entry — it is a record, not a claim about the new code.
3. **Approval is bound to a revision and an artifact.** The human
   approves a specific revision and a specific artifact (a release
   tarball, a commit, a published package). Approving revision A does
   not approve revision B.
4. **The state file is not the enforcement.** In v0.9, any agent (or
   human) with write access can edit it. The enforcement layer
   (v1.1, in SCOPE.md) would make transitions checkable — the
   verifier's signature, the evidence bundle's hash, the approval's
   binding. Until then, the state file is a record the human can
   audit, not a lock.
