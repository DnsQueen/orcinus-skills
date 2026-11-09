# Persistent project state — `.orcinus/state.json`

Date: 2026-11-09
Status: spec (v0.9.1), enforced locally by scripts/state.py since
round 7, with the VERIFIED attestation gate added in v0.11.0.
Nothing else reads or writes this file: the router does
not — no code path calls the state machine, so there is no router
integration to claim. The enforcement layer that would make it
tamper-proof is v1.1 (see SCOPE.md). This spec defines the file so the router, the verifier,
and the human all agree on what "verified" means. v0.9.1 fixes the
v0.9 self-contradiction: VERIFIED is bound to the *content digest*,
not to the commit SHA (see Rule 2 and "The content digest").
v0.11.0: a local PASS bundle is provisional — structurally valid,
not CI-attested. VERIFIED additionally requires a live CI
attestation for the revision, checked at transition time, or an
explicit targeted-rerun proof file; `validate` is local-only and
does not check attestation (see Rule 1).

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
updated through scripts/state.py (run by the agent or the human),
which enforces the transition rules and recomputes the content
digest; the human approves transitions that need approval. It is
never written by hand in the normal flow — but anyone with write
access still can (Rule 4), and the next `validate` detects a
hand-edited digest by recomputation.

```json
{
  "format_version": 2,
  "project": "weekly-budget",
  "stage": "VERIFYING",
  "revision": "b2809bd64f5679ce56eb79a239109978f0c9f06a",
  "content_digest": "sha256:9f2c…",
  "evidence_bundle": "docs/verification/stage-30.json",
  "approval": null,
  "history": [
    {
      "stage": "BUILDING",
      "revision": "90a91c8",
      "content_digest": "sha256:41ab…",
      "at": "2026-11-06T14:00:00+03:30",
      "note": "Stage 20 built test-first, 31/31 tests."
    }
  ]
}
```

## The content digest

VERIFIED is bound to what was verified — the content of the project
— not to the identity of the commit that happened to hold it. The
content digest is sha256 over the sorted `git ls-tree -r -z` listing
of the revision's tree, excluding the two places where recording
verification itself writes:

1. Run `git ls-tree -r -z <rev>` and read the output as bytes;
   each record is `<mode> SP <type> SP <sha> TAB <path>`,
   records separated by NUL. The -z matters: without it git quotes
   non-ASCII paths (core.quotePath=true, the default), so one tree
   could hash two ways and a quoted `.orcinus/` path escaped the
   exclusion below.
2. Drop records whose path is under `.orcinus/` or
   `docs/verification/` (exact directory prefixes, with the slash
   — a file named `.orcinus-notes.txt` still counts).
3. Sort the remaining records by path bytes.
4. Join with b"\n" (no trailing newline), sha256 hex.
   The digest is recorded as `sha256:<hex>`.

Format version 2 (round 5): version 1 hashed git's text display
(`ls-tree -r`, no -z), which quotes non-ASCII paths — so a tree
with a Persian filename had a different digest under
core.quotePath=true than under false, and quoted state/evidence
paths were not excluded. Digests computed by v1 on trees with
non-ASCII paths are NOT comparable with v2 digests; on ASCII-only
trees v1 and v2 agree byte for byte, so nothing already recorded
there changes.

Reference implementation: `scripts/content_digest.py` (standard
library only; `python3 scripts/content_digest.py [repo] [--rev REV]`,
`[repo] [rev]` also works). Its docstring states the same algorithm
— keep the two in agreement. scripts/state.py imports it and
recomputes the digest on every transition and validate: the digest
is never a caller-supplied value.

The digest covers committed content only: a dirty working tree is
never VERIFIED, because the digest would not describe what was
verified. Record VERIFIED only when the tree is clean.

## Stages

| Stage | Meaning |
|---|---|
| `BUILDING` | A slice is being built. Nothing in this stage is verified. |
| `VERIFYING` | The verifier is running. The `revision` is the one being checked. |
| `BLOCKED` | Verification found a blocking finding. The `evidence_bundle` says what. |
| `VERIFIED` | The content digest passed verification. Bound to the `evidence_bundle` for that exact content digest. A commit that changes the content digest moves the project back to `BUILDING`; a commit that only records the state file or an evidence bundle leaves the digest unchanged and does not reset the stage. VERIFIED additionally requires a live CI attestation for the revision (or an explicit targeted-rerun proof file) — see Rule 1. |
| `AWAITING_APPROVAL` | Verified, and waiting for the human to approve the next step (release, merge, publish). |
| `RELEASE_READY` | The human approved the verified content digest for release. The `approval` field records who approved, what content digest, and what artifact. |

## Fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `format_version` | integer | yes | 2. Bump when a required field is added or a rule changes. |
| `project` | string | yes | The project name. |
| `stage` | string | yes | One of the six stages above. |
| `revision` | string | yes | The exact commit the stage refers to. Human-readable pointer; the binding is the content digest. |
| `content_digest` | string | yes | `sha256:<hex>` over the tree excluding `.orcinus/` and `docs/verification/` (see "The content digest"). This is what VERIFIED is bound to. |
| `evidence_bundle` | string or null | yes | The path to the evidence bundle (per `skills/orcinus-verify/references/evidence.schema.json`) for the `content_digest`, or null when there is none (BUILDING). |
| `approval` | object or null | yes | When the human approves: `{approved_by, revision, content_digest, artifact, at}`. The approval is bound to a specific content digest and artifact hash — approving one content digest does not approve the next. |
| `history` | array | yes | Every stage transition, with the revision, the content digest, and the time. The history is append-only; a transition is never rewritten. |

## Rules

1. **VERIFIED is bound to a content digest and an evidence bundle.** A
   state file that says VERIFIED without an `evidence_bundle` that
   validates (see `skills/orcinus-verify/scripts/validate_evidence.py`) is corrupt, not
   verified. scripts/state.py enforces this: VERIFIED requires a
   bundle that exists and validates with verdict PASS. A bundle that
   validates locally is provisional: it proves the bundle is complete
   and self-consistent, not that CI ran. Since v0.11.0, VERIFIED
   additionally requires a CI attestation for the revision, checked
   live at transition time (`scripts/verify_attestation.py` —
   `gh attestation verify` on the content digest, pinned to this
   repo's CI workflow and the revision), or an explicit targeted-rerun
   proof file (`--attestation-proof`, produced by
   `scripts/rerun_check.py`). `validate` is local-only and never checks
   attestation: a state file that says VERIFIED and validates locally
   may never have been attested — only the transition gate enforces
   it, at the moment VERIFIED is minted.
2. **A content change resets the stage.** When the content digest
   changes, the stage goes back to BUILDING. A commit that leaves the
   digest unchanged — for example a commit that only records the
   state file or an evidence bundle — does not reset the stage. The
   history keeps the old VERIFIED entry — it is a record, not a
   claim about the new content.
3. **Approval is bound to a content digest and an artifact.** The human
   approves a specific content digest and a specific artifact (a release
   tarball, a commit, a published package). Approving one content digest
   does not approve the next.
4. **The state file is not the enforcement.** In v0.9.1, any agent (or
   human) with write access can edit it. The enforcement layer
   (v1.1, in SCOPE.md) would make transitions checkable — the
   verifier's signature, the evidence bundle's hash, the approval's
   binding. Until then, the state file is a record the human can
   audit, not a lock. Hand-editing is still possible — but the next
   `validate` detects an edited digest, because the stored value is
   compared with the digest recomputed from the revision's tree.
   The v0.11.0 attestation gate does not change this: the attestation
   is checked at transition time and never recorded in the state file,
   so a hand-written VERIFIED stage still validates locally — only a
   fresh transition re-checks attestation.

## Schema and transitions

The machine-readable form of this spec is `scripts/state_schema.json`,
enforced by `scripts/state.py` (standard library only):

- `python3 scripts/state.py validate <state.json> [--repo <repo>]` — checks the file against the schema and recomputes the stored digest from the state's revision (exit 0 when valid).
- `python3 scripts/state.py transition <state.json> --to <stage> --revision <sha> [--expect-digest sha256:<hex>] [--evidence <bundle>] [--attestation-proof <proof>] [--note <text>] [--repo <repo>]` — moves the file to a new stage, appending one history entry. The digest is recomputed from the revision's tree; there is no `--digest` flag anymore (a caller-supplied digest was trusted input — round 7, F-07). `--expect-digest` only asserts against the recomputed digest and is never stored.

Allowed transitions: BUILDING → VERIFYING → BLOCKED / VERIFIED → AWAITING_APPROVAL → RELEASE_READY; any stage returns to BUILDING on rework, and a content-digest change forces BUILDING from any stage (Rule 2). VERIFIED requires an evidence bundle that exists and validates with verdict PASS — the `--evidence` flag, or the stored value when it names an existing validating file (a stale stored path never silently satisfies the gate; the flag is required only when the stored value is absent or blank). VERIFIED additionally requires a live CI attestation for the revision, checked at transition time, or an explicit `--attestation-proof` targeted-rerun proof file; without either, the transition is refused. `validate` does not check attestation. VERIFIED and RELEASE_READY refuse on a dirty tree at HEAD (the digest describes committed content only). RELEASE_READY requires an approval bound to the recomputed content digest. A transition from an invalid state, or to a stage the table does not allow, is refused.

This is a local check, not the v1.1 enforcement layer (Rule 4): it refuses an impossible transition instead of silently recording it, but anyone with write access can still edit the file — and the next `validate` detects an edited digest by recomputation. The attestation gate is enforced only by the transition, not by `validate`: a hand-written VERIFIED stage passes `validate` when its digest and bundle check out, even though no attestation was ever checked.
