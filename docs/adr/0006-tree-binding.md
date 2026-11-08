# ADR 0006 — Tree binding: the validator recomputes revision, digest, and diff

Date: 2026-11-08
Status: accepted

## Context

The round-8 audit (FND-004, High) showed that a PASS bundle is not
bound to any tree, revision, or diff at validation time. The
validator takes only the bundle file: it never reads a repository,
never compares a check revision to the bundle revision, and never
recomputes `content_digest` or `git diff HEAD`. Five hand-authored
bundles, each built with the repo's own test helpers and recorded
captures, all validated with exit 0: bundle revision swapped to
`f`*40; the same bundle filed in a different directory; check
`content_digest` + `revision` forged with a consistently recomputed
`capture_sha256`; a dirty tree with an invented `diff_sha256` of
`0`*64; prose rewritten for another project. The schema's own
description — "every check runs on the bundle revision, so a PASS
cannot be carried from one revision to another" — was a claim the
validator did not enforce.

The same round confirmed three adjacent holes this ADR also closes:
FND-005 (a `test` gate recorded from a command printing "no tests
ran" validates), FND-006 (timestamps dated 2099 validate), and
FND-023 / N-A1 (record_check binds a capture to an empty revision
and the empty digest when git prints nothing with exit 0).

## Decision

The validator gains a `--repo` / `--expected-revision` /
`--expected-diff` argument and recomputes `content_digest` and
`git diff HEAD` at validation time, following the SLSA / in-toto
pattern the round-8 verification report documents: the verifier
takes the expected identity as input, re-reads the object itself
(the working tree / git object DB), recomputes the digest, and
compares it against the claim and the expected policy — instead of
trusting self-declared fields. `slsa-verifier verify-artifact`
recomputes the artifact SHA-256 and compares it against the
provenance subject and the caller-supplied expected source/tag;
`in_toto_verify` re-checks link metadata against the layout and
the actual files. Pattern only — no SLSA or in-toto code is copied
or vendored.

- `validate_bundle()` gains optional keyword arguments `repo=None`,
  `expected_revision=None`, `expected_diff_sha256=None`, and the
  CLI gains `--repo` (default: the working directory),
  `--expected-revision`, and `--expected-diff`. When `repo` is
  None, no tree binding is performed (legacy / in-process
  behaviour, documented as such): the in-process API is unchanged
  for existing callers. (`state.py` passes the resolved repo since
  round 8, FND-007 — an earlier draft of this ADR said it "keeps
  calling without a repo until it passes one"; corrected in round
  9, N-R9-2.)
- When a repo is given, the binding checks are: the bundle revision
  must resolve to a commit in that repo (`git rev-parse --verify
  <rev>^{commit}`, single full SHA); every check's revision —
  including `fail_first.red_check` — must resolve to that same
  commit; every check's `content_digest` must equal the digest
  recomputed from the tree at that revision (via the
  `content_digest.py` bundled beside the validator, so the check
  works in a skills-only install with no repo checkout); a PASS on
  a dirty tree must have its `git diff HEAD` recomputed, and the
  sha256 must match `diff_sha256`; `--expected-revision` /
  `--expected-diff`, when given, must match the bundle revision /
  recomputed diff. A bundle revision of `"working-tree"` binds to
  HEAD, the commit its diff applies to — the check-level revision
  note already allows a dirty-tree difference, and this is the
  check that difference is real.
- When no repo is present, a PASS bundle claiming a revision FAILS
  CLOSED (never silently passes): the CLI defaults `--repo` to the
  working directory, so validating a PASS bundle outside any repo
  — or with `--repo` naming a non-repo — is exit 1. An honest
  FAIL/INCOMPLETE bundle in the same situation is still fileable:
  it is not a success claim. The revision/digest equality checks
  themselves apply to all verdicts when a repo resolves (they are
  facts about a committed tree, stable over time); the diff
  recompute applies to PASS bundles only, matching the existing
  rule that `diff_sha256` presence is a PASS rule.
- The schema stays at v6. No new bundle field is needed for the
  tree binding (it is validator-side only), and the one new field
  this round adds — `test_report`, for FND-005 — is optional: no
  required field is added and no previously structurally valid
  bundle changes version. A bump to v7 would have rejected every
  v6 bundle outright, including the `scripts/test_state.py`
  fixtures that hardcode v6; the version is a contract with those
  bundles, not a changelog. The migration note is this paragraph:
  v6 bundles remain structurally valid, and fail only the new
  semantic rules they violate (a required test gate with no JUnit
  report, a check recorded on another revision than the repo
  given). If a future change adds a required field, that change
  bumps the version.
- FND-005: a PASS with a required `test` gate needs a bundle-level
  `test_report` (`{artifact, sha256, format: "junit-xml"}`), read
  through the same JUnit parser and artifact path as the
  fail-first reports, with tests>0 and passed>0 (an all-skipped
  suite ran no test). The rule applies only when the test gate is
  required — never for a legitimately waived docs-only/config-only
  gate — and only for PASS. The established pattern is the CI
  tools' structured-report gate (`dorny/test-reporter`
  `fail-on-empty: true` by default; `mikepenz/action-junit-report`
  `require_tests` / `require_passed_tests`): parse JUnit XML and
  count, as the validator already does for fail-first.
- FND-006: timestamps more than 5 minutes in the future are
  rejected (all checks plus `fail_first.red_check`). There is
  deliberately no lower bound: a historical bundle must keep
  validating, so only the future is rejected.
- FND-023 / N-A1: the fix is at the revision layer, not by
  requiring a non-empty tree (that would break a legitimately
  empty repo). `record_check._resolve_repo` requires
  `--show-toplevel` to name an existing directory;
  `_resolve_revision` requires `git rev-parse --verify HEAD` to
  succeed with a single-line full SHA (`^[0-9a-f]{40}$` or
  `^[0-9a-f]{64}$`); `content_digest()` distinguishes an empty
  tree from broken git output by confirming the tree object exists
  (`git rev-parse --verify <rev>^{tree}`) before accepting empty
  `ls-tree` output.
- FND-001: `scripts/content_digest.py`'s entry point is
  `sys.exit(main(sys.argv[1:]))` — the auditor's patch, applied as
  proposed and verified by a subprocess test of the real entry
  point (the existing `main([...])` tests omit `argv[0]` and never
  caught it).
- FND-003: a byte-identical copy of `content_digest.py` is bundled
  beside `record_check.py` in `skills/orcinus-verify/scripts/`,
  `_load_content_digest` searches beside itself FIRST (after an
  explicit `--digest-module`), and a pytest test pins the two
  copies byte-identical — it runs in CI. The auditor's FND-003
  patch was evaluated against red-first tests and kept, except its
  bundled copy carried the old FND-001 entry-point bug; the copy
  shipped here is the fixed file. The documented step-4 command
  now works with no `--digest-module` flag in a skills-only
  install.
- The honest limit is stated in the validator docstring, in
  SKILL.md, and here: this binds a bundle to a tree; it does NOT
  prove the command ran. A local writer can run the wrapper on a
  lying command and file the genuine capture, and a fabricated
  JUnit file parses like a real one — the test-report rule closes
  the zero-test hole, not the lying-command hole. The claim stays
  "tamper-evident recording bound to a tree", never "proof of
  execution". What closes the lying-command half is a trust
  boundary the job cannot touch (a hardened builder, a layout
  author distinct from the functionary, a CI runner holding the
  log) — still not built, still not claimed. The prose-rewrite
  half of the FND-004 repro is likewise out of scope: tree binding
  says nothing about the bundle's prose, and no check is added
  that pretends otherwise.

## Consequences

- Good: a PASS can no longer be carried from one revision, tree,
  or diff to another — the five FND-004 repro shapes are all
  rejected, verified by tests that forge each one with a
  consistently recomputed capture hash (so the capture recompute
  passes and only the binding must catch it).
- Good: the CLI's `--repo` default (the working directory) makes
  the common case — validating a bundle in the repo it was
  recorded in — work with no new flag, and makes the failure mode
  loud (a PASS validated elsewhere fails closed) instead of silent.
- Bad: validating a bundle recorded against another repo now
  requires `--repo <that repo>`; a bundle validated from the wrong
  directory fails where it used to pass. That is the intended
  fail-closed behaviour, and SKILL.md says so — but it is a
  behaviour change for anyone scripting the validator, and the
  validator's own tests had to be updated to name the recording
  repo (the CLI verdict-block and self-contained tests).
- Bad: a PASS with a required test gate now needs the agent to run
  the test gate with `--junitxml` and file the report; a bundle
  written before this round fails the new rule. The field is
  optional in the schema, so the failure is the semantic rule, not
  a version rejection — re-running verification produces a
  conforming bundle.
- Recorded: the auditor's FND-004 patch is labelled UNTESTED by the
  auditor and was not applied; this implementation was designed
  and tested here instead. The auditor's FND-001/FND-003 patches
  were evaluated against red-first tests; FND-001 was applied as
  proposed, FND-003 was applied with the bundled copy taken from
  the fixed file, not the patch's stale copy.

## Round 9 — containment: the command must run in the tree (FND-001)

Date: 2026-11-08
Status: accepted

The round-9 audit (FND-001, High) showed the round-8 binding still
has a seam: `record_check.py` accepted `--repo` naming any repo
while running the command wherever `--cwd` pointed, and the
validator never compared a check's `cwd` against the repo. A fake
`pytest` in a scratch directory outside every repo, with `--repo`
at the real repo, produced a PASS bundle that validated with exit
0. The general lying-command hole was already documented (see
"The honest limit" above) — this is a narrower, fixable mechanism
inside it: the validator already held the exposing data (the
recorded `cwd`) and never used it.

Decision (pattern: in-toto's Link records the `workdir` the command
ran in, and verification checks it against the layout; REAPI keys a
result by the input-root digest the worker actually materialised —
pattern only, no code copied):

- `record_check.py` derives the repo from the command's cwd first
  (`rev-parse --show-toplevel`, with the round-8 FND-023
  discipline: non-zero exit, empty, or multi-line output is a
  refusal). An explicit `--repo` is accepted only when it names
  that same repo (resolved paths compared) — a bare repo is
  refused, because `--show-toplevel` fails in one (round 9, N-B:
  the auditor's hardening patch had a bare-repo bypass through an
  unguarded `rev-parse --show-toplevel` whose empty output became
  `Path("") = "."`; this implementation reuses the guarded
  resolver for both paths, so the bypass cannot recur). A
  worktree's root is its own repo here: `--cwd` in a worktree
  binds to the worktree (its base commit).
- The validator mirrors it in `check_tree_binding`: every check's
  `cwd` (including `fail_first.red_check`) must share the repo's
  git common dir when the directory still exists — a subdirectory,
  the repo root, and a live worktree all match; a nested repo, a
  bare repo, and a scratch directory do not. A `cwd` that no
  longer exists (a worktree removed after recording, as SKILL.md
  step 3 instructs) cannot be checked this way: the record-time
  containment is the control there, and the revision/digest
  binding still applies.
- The auditor's hardening patch was evaluated and NOT applied
  verbatim (bare-repo bypass, unguarded git calls, no-git
  traceback); the containment here was designed and tested here
  instead.

Residual, stated honestly (N-R9-1): this narrows FND-001, it does
not close fabrication. A fake command run *inside* the repo still
records and validates — including an untracked fake binary placed
in the repo, which the committed-tree digest does not cover. The
claim stays "tamper-evident recording bound to a tree", never
"proof of execution"; only a trust boundary the job cannot touch
closes the lying-command half.
