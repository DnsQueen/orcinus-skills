# Persistent project state — `.orcinus/state.json`

Date: 2026-11-10
Status: spec (v0.12.0), enforced locally by scripts/state.py since
round 7, with the VERIFIED attestation gate added in v0.11.0 and
the RERUN_CONFIRMED stage added in v0.12.0. Nothing else reads or
writes this file: the router does not — no code path calls the state
machine, so there is no router integration to claim. The
enforcement layer that would make it tamper-proof is v1.1 (see
SCOPE.md). This spec defines the file so the router, the verifier,
and the human all agree on what "verified" means. v0.9.1 fixes the
v0.9 self-contradiction: VERIFIED is bound to the *content digest*,
not to the commit SHA (see Rule 2 and "The content digest").
v0.11.0: a local PASS bundle is provisional — structurally valid,
not CI-attested. VERIFIED additionally requires a live CI
attestation for the revision, checked at transition time.
v0.12.0: the targeted-rerun fallback no longer mints VERIFIED at
all. A local rerun mints only RERUN_CONFIRMED, and the gate runs
the rerun itself — there is no proof file a caller can hand in
(the `--attestation-proof` flag is removed: a hand-written proof
JSON with correct values was accepted as VERIFIED in a scratch
repo with no tests at all). `validate` is local-only and does not
check attestation (see Rule 1).

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
digest; the human approves transitions that need approval. On an
install without repo-root `scripts/` (any install other than the
Claude Code plugin), `scripts/state.py` is not present and the
transitions cannot run — file INCOMPLETE for the state-recording
step per the router's Host-incompatible rule and record the stage
and the evidence bundle path in the handoff/session record
instead. The file format in this spec is unchanged: it still
defines what a recorded stage means, wherever it is recorded. It is
never written by hand in the normal flow — but anyone with write
access still can (Rule 4), and the next `validate` detects a
hand-edited digest by recomputation.

```json
{
  "format_version": 3,
  "project": "weekly-budget",
  "stage": "VERIFYING",
  "revision": "b2809bd64f5679ce56eb79a239109978f0c9f06a",
  "content_digest": "sha256:9f2c…",
  "evidence_bundle": "docs/verification/stage-30.json",
  "approval": null,
  "verification_origin": null,
  "rerun": null,
  "history": [
    {
      "stage": "BUILDING",
      "revision": "90a91c8",
      "content_digest": "sha256:41ab…",
      "at": "2026-11-06T14:00:00+03:30",
      "note": "Stage 20 built test-first, 31/31 tests.",
      "origin": null
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

Format version 3 (0.12.0): the state records how it was verified.
Two fields are added — `verification_origin` (`CI_ATTESTED` or
`LOCAL_RERUN`, null before any verification) and `rerun` (the
record of a targeted rerun the gate itself ran) — and every history
entry records the `origin` in force at that transition. The digest
algorithm is unchanged: v2 and v3 digests are identical for the
same tree. A v2 file is migrated by `scripts/state.py migrate`
(see "Schema and transitions"): the new fields are added as null,
and a v2 stage of VERIFIED, AWAITING_APPROVAL, or RELEASE_READY is
demoted to VERIFYING. The demotion is not a judgement on the old
work — it is a fact about the old record: v2 never recorded how
verification happened, so a v2 VERIFIED cannot be classified as
CI-attested or locally rerun, and it must not be grandfathered
into a meaning it never carried. The approval field is preserved
by the migration; approval is a human decision, not a
verification, so it survives the demotion and applies again once
the state is re-verified.

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
| `VERIFIED` | The content digest passed verification and a live CI attestation for the revision was checked at transition time. Bound to the `evidence_bundle` for that exact content digest. A commit that changes the content digest moves the project back to `BUILDING`; a commit that only records the state file or an evidence bundle leaves the digest unchanged and does not reset the stage. VERIFIED is minted only by a live CI attestation — never by a local rerun (see Rule 1). |
| `RERUN_CONFIRMED` | The gate itself ran a targeted rerun of the bundle's fail-first test in a clean worktree at the exact revision, and it passed. A local confirmation, not a CI attestation: this stage never becomes VERIFIED, and must not be mistaken for one. It may move to AWAITING_APPROVAL — the human decides on the rerun record, with the origin visible in the state file. |
| `AWAITING_APPROVAL` | Verified (or rerun-confirmed), and waiting for the human to approve the next step (release, merge, publish). The `verification_origin` says which one it is. |
| `RELEASE_READY` | The human approved the verified content digest for release. The `approval` field records who approved, what content digest, and what artifact. |

## Fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `format_version` | integer | yes | 3. Bump when a required field is added or a rule changes. |
| `project` | string | yes | The project name. |
| `stage` | string | yes | One of the seven stages above. |
| `revision` | string | yes | The exact commit the stage refers to. Human-readable pointer; the binding is the content digest. |
| `content_digest` | string | yes | `sha256:<hex>` over the tree excluding `.orcinus/` and `docs/verification/` (see "The content digest"). This is what VERIFIED is bound to. |
| `evidence_bundle` | string or null | yes | The path to the evidence bundle (per `skills/orcinus-verify/references/evidence.schema.json`) for the `content_digest`, or null when there is none (BUILDING). |
| `approval` | object or null | yes | When the human approves: `{approved_by, revision, content_digest, artifact, at}`. The approval is bound to a specific content digest and artifact hash — approving one content digest does not approve the next. |
| `verification_origin` | string or null | yes | How this content was verified: `CI_ATTESTED` (a live CI attestation for the revision, checked at transition time — the only origin that mints VERIFIED) or `LOCAL_RERUN` (a targeted rerun the gate itself ran — mints RERUN_CONFIRMED, never VERIFIED). Null before any verification. A human approval never changes this value: approval is a decision, not a verification. |
| `rerun` | object or null | yes | The targeted rerun the gate itself ran for this content: `{method: "targeted-rerun", revision, at, tests, junit: {total, passed}, exit_code: 0}`. Non-null exactly when `verification_origin` is `LOCAL_RERUN`; null otherwise. Never a caller-supplied file — the gate runs the rerun and records what it did. |
| `history` | array | yes | Every stage transition, with the revision, the content digest, the time, and the `origin` in force at that transition. The history is append-only; a transition is never rewritten. |

## Rules

1. **VERIFIED is bound to a content digest, an evidence bundle, and a
   live CI attestation.** A state file that says VERIFIED without an
   `evidence_bundle` that validates (see
   `skills/orcinus-verify/scripts/validate_evidence.py`) is corrupt,
   not verified. scripts/state.py enforces this: VERIFIED requires a
   bundle that exists and validates with verdict PASS. A bundle that
   validates locally is provisional: it proves the bundle is complete
   and self-consistent, not that CI ran. Since v0.11.0, VERIFIED
   additionally requires a CI attestation for the revision, checked
   live at transition time (`scripts/verify_attestation.py` —
   `gh attestation verify` on the content digest, pinned to this
   repo's CI workflow and the revision). `validate` is local-only and
   never checks attestation: a state file that says VERIFIED and
   validates locally may never have been attested — only the
   transition gate enforces it, at the moment VERIFIED is minted.
   **Since v0.12.0 there is no fallback that mints VERIFIED.** A
   targeted rerun mints only RERUN_CONFIRMED, and the gate runs the
   rerun itself (`scripts/rerun_check.py`, via subprocess, from a
   clean worktree at the exact revision, using the revision-pinned
   copy of the script — never the working-tree copy) and records
   the proof it produced. There is no proof file a caller can hand
   in: the `--attestation-proof` flag was removed, because a
   hand-written proof JSON with correct values was accepted as
   VERIFIED in a scratch repo with no tests at all — the content
   digest is public and recomputable, so checking JSON fields was
   never a proof that anything ran. The rerun path is fail-closed:
   a timeout, a non-zero exit, a missing script, an unreadable
   proof, or a proof whose fields do not match what the gate just
   ran all refuse the transition.
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
   is checked at transition time and recorded as
   `verification_origin`, so a hand-written VERIFIED stage still
   validates locally — only a fresh transition re-checks attestation.
   The same holds for RERUN_CONFIRMED: a hand-written rerun record
   validates locally, because `validate` does not re-run anything.
   What v0.12.0 closes is the *legitimate-looking* path — a proof
   file the gate itself accepted as VERIFIED. A hand edit was
   always possible and is still honestly labelled as what it is:
   an unaudited record, not a gate decision.

## Schema and transitions

The machine-readable form of this spec is `scripts/state_schema.json`,
enforced by `scripts/state.py` (standard library only):

- `python3 scripts/state.py validate <state.json> [--repo <repo>]` — checks the file against the schema and recomputes the stored digest from the state's revision (exit 0 when valid).
- `python3 scripts/state.py transition <state.json> --to <stage> --revision <sha> [--expect-digest sha256:<hex>] [--evidence <bundle>] [--note <text>] [--repo <repo>]` — moves the file to a new stage, appending one history entry. The digest is recomputed from the revision's tree; there is no `--digest` flag anymore (a caller-supplied digest was trusted input — round 7, F-07). `--expect-digest` only asserts against the recomputed digest and is never stored.
- `python3 scripts/state.py migrate <state.json>` — migrates a format_version 2 file to format 3: adds `verification_origin` and `rerun` as null, adds `origin: null` to history entries, and demotes a stage of VERIFIED, AWAITING_APPROVAL, or RELEASE_READY to VERIFYING (provenance was never recorded in v2, so the old stage cannot be classified). The approval field is preserved. Idempotent: a format 3 file is reported as already migrated and left unchanged.

Allowed transitions: BUILDING → VERIFYING → BLOCKED / VERIFIED / RERUN_CONFIRMED; RERUN_CONFIRMED → AWAITING_APPROVAL or BUILDING; VERIFIED → AWAITING_APPROVAL → RELEASE_READY; any stage returns to BUILDING on rework, and a content-digest change forces BUILDING from any stage (Rule 2). There is no path from RERUN_CONFIRMED (or from AWAITING_APPROVAL) to VERIFIED: a local rerun never becomes a CI attestation. VERIFIED requires an evidence bundle that exists and validates with verdict PASS — the `--evidence` flag, or the stored value when it names an existing validating file (a stale stored path never silently satisfies the gate; the flag is required only when the stored value is absent or blank). VERIFIED additionally requires a live CI attestation for the revision, checked at transition time; RERUN_CONFIRMED additionally requires the gate to run the targeted rerun itself and record the proof it produced. Without the respective check, the transition is refused. `validate` does not check attestation. VERIFIED and RELEASE_READY refuse on a dirty tree at HEAD (the digest describes committed content only). RELEASE_READY requires an approval bound to the recomputed content digest. A transition from an invalid state, or to a stage the table does not allow, is refused.

This is a local check, not the v1.1 enforcement layer (Rule 4): it refuses an impossible transition instead of silently recording it, but anyone with write access can still edit the file — and the next `validate` detects an edited digest by recomputation. The attestation gate is enforced only by the transition, not by `validate`: a hand-written VERIFIED stage passes `validate` when its digest and bundle check out, even though no attestation was ever checked.
