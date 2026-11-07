# ADR 0005 — Recorded checks: a wrapper transcript with one binding hash, no signing

Date: 2026-11-08
Status: accepted

## Context

The round-7 live-agent audit (F-01, High) showed that a wholly
fabricated evidence bundle — invented commands, exit codes,
timestamps, red and green runs, distinct identities — validated with
exit 0, in a non-git directory. The validator proves a bundle is
complete and self-consistent; it does not prove the commands ran.
That limit was disclosed (validator docstring, SKILL.md), but the
README headline ("done when the evidence says so") claimed more than
the mechanism delivered.

The auditor's roadmap proposed two steps: Option A, narrow the claim
(XS), now; Option B-2, a wrapper-produced transcript (M-L), next
release — and explicitly forbade signing/PKI. Niloufar authorised the
bigger work, including B-2, as part of the round-7 fix pass. The
question was what the wrapper should record, and what it may honestly
claim.

## Decision

ORCINUS ships `skills/orcinus-verify/scripts/record_check.py`, a
thin wrapper in the in-toto Link shape, and requires its captures for
a PASS bundle (evidence schema v6):

- The wrapper runs one command from an argv list (a shell string only
  behind an explicit `--shell` flag, run as `["sh", "-c", <string>]`
  and recorded as `shell: true`), captures stdout/stderr as bytes,
  writes them as `<name>.stdout` / `<name>.stderr` beside the bundle
  (reusing the validator's artifact, containment, symlink, and 10 MiB
  size-cap rules), and prints a check fragment for pasting into the
  bundle. It exits with the command's exit code, so a failing gate is
  a recorded failure, not a missing recording.
- The fragment carries `command_argv`, `shell`, `cwd`, `started_at` /
  `finished_at` (UTC), `exit_code`, both stream sha256s,
  `content_digest` + `revision` of the tree at run time (computed by
  the existing `content_digest` function — imported, never
  reimplemented), and `recorded_by: "record_check.py/1"`.
- One binding hash, `capture_sha256`, is taken over canonical JSON
  (`sort_keys`, compact separators, UTF-8) of exactly: format,
  command argv, shell, cwd, started_at, finished_at, exit_code,
  stdout_sha256, stderr_sha256, content_digest, revision. The stream
  hashes are hashes of the raw stream bytes — never of inline text or
  a pretty-printed rendering. The hash function lives in
  `record_check.py` and the validator imports it: one definition.
- The validator recomputes the hash from the stored fields and the
  artifact files on disk for every check in a PASS bundle, including
  `fail_first.red_check`, and rejects mismatches, absent recorded
  fields, and a command string that is not the canonical rendering of
  the recorded argv. The same capture under two different content
  digests is reported as a forgery. FAIL/INCOMPLETE bundles are
  exempt from the requirement (they are not success claims), but a
  binding present there must still recompute.
- No signing or PKI is built, and no per-check materials/products
  hashing, no SLSA `builder.id`, and no HMAC with a repo-readable key
  (see Alternatives: each would add a field that proves nothing
  here).
- The honest limit is stated in the module docstring, in SKILL.md,
  and in the README: a local writer can run the wrapper on a lying
  command (`record_check.py -- true`, or a script printing fake
  pytest output and exiting 0) and file the genuine capture. No local
  hash distinguishes that. The claim stays "tamper-evident
  recording", never "proof of execution". Option A (narrow the claim
  where it is made) ships alongside, in the same fix pass.

Pattern sources (pattern only — no code copied or vendored):
in-toto's Link (in-toto/in-toto; Link struct in
in-toto/in-toto-golang; docs at in-toto.readthedocs.io) — `name`,
argv-list `command`, `materials`/`products` as `{path: {sha256,
sha512}}`, `byproducts` (stdout, stderr, return value),
`environment` (workdir). SLSA v1 provenance (slsa.dev/spec/v1.0/
provenance) — the same shape build-flavoured, whose spec states the
trust model explicitly ("the builder is trusted to have faithfully
recorded the provenance"). Bazel's Remote Execution API `ActionResult`
— exit code, stdout/stderr by digest, outputs referenced by hash,
executor-produced. Waza's recorded-evidence model (platform docs) —
output text, transcript, session digest, workspace directory handed
to the grader — whose docs state the trust model directly ("the
grader program and other processes running as the same user are
trusted": same-user tampering is out of scope).

## Consequences

- Good: fabrication now requires deliberately invoking the wrapper on
  a fake command instead of typing JSON — a higher, auditable bar.
  Accidental inconsistency (wrong exit code, wrong tree, timestamps
  out of order, stdout that does not match the claimed gate) is
  caught mechanically. Capture reuse across trees is caught by the
  digest inside the hash.
- Good: the PASS fixtures in the validator's own tests are generated
  by running `record_check.py` itself, not hand-written — the test
  suite eats its own cooking, and no exemption for test fixtures
  exists.
- Bad: schema v6 is a breaking change. Bundles written under v5 or
  earlier are rejected outright; the validator answers with an
  explicit migration message ("re-run verification with the current
  validator") instead of the flat const error, but it does not
  migrate them.
- Bad: a PASS with checks now requires a git repository (the digest
  is of a committed tree) and a `content_digest.py` the wrapper can
  import. A non-git project can still file FAIL/INCOMPLETE bundles,
  and a docs-only PASS with every gate waived can still file with no
  checks — but it cannot file a PASS with checks. In an npx-skills
  install the repo-root `scripts/` do not travel, so the wrapper
  needs `--digest-module <path>` there.
- Bad: the binding does not cover `tool_version` or the check's
  `verdict` — those are the agent's statements, added when the
  fragment is pasted into the bundle, and the wrapper does not know
  the tool. A recorded check that also carries inline
  `stdout_text`/`stderr_text` is rejected: a recorded check's output
  is its artifacts, so there is one source of output truth.
- Recorded: the remaining gap closes only with a trust boundary the
  job cannot touch (a hardened builder holding the key, a layout
  author distinct from the functionary, a remote executor, a CI
  runner holding the log). Harness-executed evidence — the harness
  itself running the commands and writing the bundle — is still not
  built and is not claimed.
