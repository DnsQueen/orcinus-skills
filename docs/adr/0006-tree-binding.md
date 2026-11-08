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

## Round 9 — two-target binding: the red run binds to its own revision (FND-002)

Date: 2026-11-08
Status: accepted

The round-9 audit (FND-002, High) showed the round-8 binding
defeated the documented fail-first procedure: `check_tree_binding`
put `fail_first.red_check` in the same single-target list as every
green check, so a red run recorded in a worktree at the pre-fix
commit was rejected (its revision and digest differ from the bundle
revision by construction) — while the same red run recorded with
`--repo` at the fixed tree validated, claiming the fixed tree for a
run that happened on the pre-fix tree. The procedure in SKILL.md
step 3 could not produce a valid bundle for a committed fix; only
the uncommitted (dirty-tree) shape validated, where the red revision
is HEAD either way.

Decision (pattern: CI's two-runs-two-SHAs pairing — a red and a
green are two separate runs on two SHAs, paired by test name, never
one run claiming two revisions; in-toto's input materials for the
test file; SLSA-style caller-supplied expected revision for the
optional base_revision — pattern only, no code copied):

- Green checks bind to the bundle revision, unchanged.
  `fail_first.red_check` binds to its own revision and digest,
  recomputed from the tree at the red revision.
- For method "worktree" the red revision must be the base the fix
  is built on: a strict ancestor of the bundle revision when the
  fix is committed (the parent of the fix commit, or an earlier
  commit for a multi-commit fix), ancestor-or-equal when the bundle
  revision is "working-tree" (an uncommitted fix, whose base is
  HEAD). A red on the bundle revision itself is rejected for a
  committed fix — that is the mislabelled shape. A red on a
  revision that is not an ancestor at all is rejected too.
- `fail_first.base_revision` is an optional declared base (schema
  v6, no version bump): when present, the red revision must equal
  it and it must resolve to a commit.
- `fail_first.test_file_sha256` records the test file as a
  material: the sha256 of the test file as copied into the red
  worktree, required for a PASS with method "worktree" or
  "revert-at-smallest-scope", and it must match the test file in
  the green tree (`git show <revision>:<path>`, or the working-tree
  file when the bundle revision is "working-tree"). The committed
  content digest does not cover the copied-in file, so without
  this the red run is not tied to any test file.

  Amendment (CI fix round 4, 2026-11-09): the match is under git's
  line-ending canonicalisation, not byte-for-byte. A file copied
  on Windows has CRLF line endings while the green tree holds the
  LF blob (git normalises on commit), so a byte comparison false-
  rejected every genuine Windows recording (CI 0.10.6, 10 tests).
  The validator now accepts the LF hash or the CRLF hash of the
  same file — git treats those as the same text file, and any
  other byte change still fails, so the material binding is not
  weakened.
- For method "revert-at-smallest-scope" the red run sits on the
  bundle revision itself (the revert is a dirty-tree change and
  the digest covers committed content only), so its revision must
  equal the bundle revision and it binds via the recorded
  `red_diff_sha256` (the sha256 of `git diff HEAD` in the reverted
  tree at red-run time), required for a PASS with that method. The
  validator cannot recompute that diff after the fix is re-applied,
  so the recorded hash binds the red run to a diff a reviewer can
  reproduce by re-applying the revert — stated here as the honest
  limit of that binding, not as a recomputed check.
- No schema version bump: all three new fields are optional in
  schema v6; the validator enforces them as PASS rules, the same
  way the JUnit reports are required for a PASS without being
  required fields.

## Round 9 — the dirty-tree binding gap: recompute the working-tree state (F1)

Date: 2026-11-08
Status: accepted

A friend's static review of v0.10.4 found the round-8 binding
trusted the bundle's own claim about the tree:
`check_tree_binding` recomputed `git diff HEAD` only when the
bundle itself claimed `working_tree_state == "dirty"`, and
`check_dirty_files` only cross-checked the bundle's own
self-declared fields — it never ran `git status --porcelain`
independently. A bundle claiming "clean" on a dirty tree
validated, and `_git_diff_sha256` is `git diff HEAD` only, so
untracked files were never covered by any binding at all.

Decision (pattern: in-toto's input materials — a result is bound
to the inputs it actually ran on, and an input the digest does
not cover is either hashed as a material or the result is refused;
pattern only, no code copied):

- When a repo is given, `check_tree_binding` recomputes the real
  working-tree state from `git status --porcelain=v1 -z` (the -z
  form keeps non-ASCII paths raw, the round-5 quoting lesson).
  A bundle claiming "clean" on a dirty tree — or "dirty" on a
  clean one — is rejected, on any verdict: the state claim is
  part of the binding, not a label. The diff is bound whenever
  the tree is actually dirty, whatever the bundle claims.
- Untracked files: a PASS is rejected while untracked files exist
  in the repo. `git diff HEAD` does not cover them, so a PASS
  cannot be bound to them — including a new fix file the agent
  forgot to commit. Hashing them as materials was considered and
  rejected: it would change what `diff_sha256` means (the sha256
  of `git diff HEAD`, recorded by the agent's procedure), and the
  strong remedy is already available — commit the files, remove
  them, or file for a clean tree. The rejection is the binding,
  not a workaround.
- Carve-outs, and only these: uncommitted files under `.orcinus/`
  and `docs/verification/` are not dirt — the same exclusions as
  the content digest and the state machine's own dirt gate
  (state.py `_tree_is_dirty`, F-07): those are the two places
  where recording verification itself writes, so committing the
  state file or an evidence bundle never counts as dirt, and the
  validator's dirt rule and the state gate must agree, or a
  bundle could validate but never transition (or the reverse).
  Untracked files inside the bundle directory are likewise
  excluded when the bundle lives elsewhere in the repo: they are
  the evidence artifacts themselves (captures, JUnit reports),
  written there during verification and verified separately by
  their sha256s. The bundle-directory exclusion does not apply
  when the bundle sits at the repo root, where it would swallow
  the whole tree. Untracked files anywhere else — a scratch file,
  a new source file — still block a PASS; the remedy is to commit
  them or move them out. The exclusions apply to tracked
  modifications in those directories too, for the same reason:
  they are verification's workspace, not the tree under
  verification, and the content digest excludes them as well.
- When git cannot report the status, a PASS fails closed (its
  tree cannot be bound); a FAIL/INCOMPLETE bundle is still
  fileable, and the diff binding falls back to the bundle's claim.
  `check_dirty_files` is unchanged: it remains the self-declared
  cross-check for the no-repo path.

Residual, stated honestly: this closes the state claim and the
untracked gap for PASS bundles validated against a repo. It does
not touch the lying-command half (a fake command run inside the
repo still records — N-R9-1) or the revert `red_diff_sha256`
limit above (recorded, not recomputed).
