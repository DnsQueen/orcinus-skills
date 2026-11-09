# Changelog

All notable changes to ORCINUS are recorded here. Dates are UTC.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.11.1] — 2026-11-09

Two fixes to the 0.11.0 targeted re-run checker, both caught by CI
before any 0.11.0 release (no 0.11.0 tag exists).

### Fixed

- **Windows worktree-path comparison:** `git worktree list
  --porcelain` prints paths with forward slashes even on Windows,
  while `str(Path)` uses backslashes there, so the
  no-lingering-worktree assertion in
  `test_honest_rerun_writes_exact_proof_shape` failed only on
  `windows-latest`. Both sides are now compared with
  `Path.as_posix()`; the check itself is unchanged.
- **Fail-first nodeid passed twice:** when the fail-first test's
  file was already among the changed test files, `select_targets`
  named the nodeid twice, which pytest 8.4.2 runs twice (9.0.3
  dedupes), so proof JUnit totals over-counted distinct tests
  under older pytest. The nodeid is now dropped from the pytest
  argv when its file is already a target (the file run covers it
  once); the nodeid is still returned and still used for the
  presence check.

## [0.11.0] — 2026-11-09

Attested verification: a local validator PASS is now provisional —
structurally valid, not CI-attested. VERIFIED requires an
independent observer: a live CI attestation for the revision, or an
explicit targeted-rerun proof file.

### Added

- **CI attestation gate for VERIFIED:** CI gains an `attest` job
  (`needs: [test]`) that attests the tree content digest with
  `actions/attest@v4.2.2` (SLSA L2 — the direct action, not the
  `attest-build-provenance` wrapper, per current GitHub guidance),
  so an attestation existing for a run implies the test job passed
  in that same run. `scripts/state.py` refuses a VERIFIED
  transition without a live attestation check
  (`scripts/verify_attestation.py`: `gh attestation verify` on the
  content digest, pinned to this repo's CI workflow and the
  revision; exit 0 verified / 1 not verified / 2 unavailable) or
  an explicit `--attestation-proof` targeted-rerun proof file. No
  silent fallback: without `gh`/network and without a proof file
  the transition is refused. The check never trusts `gh`'s exit
  code alone — the JSON subjects must contain the file's sha256
  (CVE-2025-25204 defence: older `gh` returned exit 0 with no
  attestations present).
- **Targeted re-run checker (`scripts/rerun_check.py`):** the
  offline fallback for consumers with no CI. Re-runs only the
  bundle's fail-first test and the changed test files in a clean
  worktree at the exact revision (SWE-bench FAIL_TO_PASS /
  PASS_TO_PASS style, never the full suite), compares the rerun's
  own JUnit against its own stdout summary (parsed the same way
  the validator parses it — reused, not duplicated), and writes a
  targeted-rerun proof file the VERIFIED gate consumes. A bundle
  whose fabricated JUnit claims a nodeid passed that fails in the
  rerun is caught (exit 1, no proof); un-runnable inputs fail
  closed (exit 2).

### Changed

- A local validator PASS is provisional: `orcinus-verify` and the
  router now say so ("structurally valid, not CI-attested").
  `validate` is local-only and never checks attestation; only the
  transition gate enforces it, at the moment VERIFIED is minted.

### Known limits (documented, not fixed)

- The tamper-proof layer is still NOT built (v1.1, see SCOPE.md):
  anyone with write access can still edit the state file, and a
  hand-written VERIFIED stage still validates locally. 0.11.0 adds
  an independent-observer check on minting VERIFIED, not a lock
  on the file afterwards.
- Offline / no-`gh`: without `gh` authenticated and network access
  the live check is unavailable (exit 2) and VERIFIED is refused
  unless a targeted-rerun proof file is supplied; offline
  verification from a downloaded bundle still needs a cached
  Sigstore trusted root (`--custom-trusted-root`).
- Forks: the attestation is derived from the repo's origin remote,
  so a fork's attestation proves a run in that fork's CI, not
  upstream's.
- Targeted re-run limits: no transitive test discovery — only the
  fail-first test plus the changed test files run, so a change
  that breaks an unlisted test is not caught; only pytest stdout
  summaries are reconciled against JUnit; the rerun verifies the
  claim that the tests pass, not the artifacts' provenance — a
  fabricated JUnit that exactly matches what a real run would
  produce still agrees with the rerun.
- No live attested transition has been observed yet in this
  environment (`gh` unauthenticated here; the `attest` job first
  runs on the next CI run after merge) — no numbers are claimed
  (see `docs/verification/HONEST-NUMBERS.md`).

## [0.10.13] — 2026-11-09

CI follow-up to the round 11 fix pass. 0.10.12 was never tagged or
released, so 0.10.13 is the first pushed version containing the
fixes below — the 0.10.12 entry underneath describes the fix pass
itself, and this entry only the follow-up that got Windows CI
green.

### Fixed

- **Windows CI, shell paths:** a `sh -c` string recorded on
  Windows carries drive-letter backslash paths, and POSIX
  `shlex.split` mangled them (`C:\Users\...` -> `C:Users...`), so
  the validator rejected an honest Windows recording as
  INCOMPLETE — the runner was not detected and the `--junitxml`
  report did not match. `_shell_segments` now normalises
  backslashes to `/` in unquoted drive-letter tokens before the
  split; quoted paths (including a drive-letter path inside a
  `-c "..."` string) are left alone, and `echo green.xml` still
  names no path. The shell-gate test builds its shell string with
  forward-slash paths (`sys.executable.replace("\\", "/")`,
  `Path.as_posix()`), so the recording itself runs under Git Bash
  `sh` instead of failing with exit 127. The 4d0de4f validator
  change covered list-form argv only; this completes shell
  strings.
- **Python 3.13 fixture shadowing (from 4d0de4f):** the fixture
  `code.py` shadowed stdlib `code` (pytest inserts the repo root
  on `sys.path`), breaking pytest's own configure with
  INTERNALERROR / exit 3 on Python 3.13; renamed to `sample.py`.

## [0.10.12] — 2026-11-09

Round 11 audit fix pass (audit of v0.10.11/3f06ffa, 14 findings:
13 confirmed, 1 partial — FND-013's count was wrong on one skill —
0 refuted). Every finding is fixed or honestly limited below; no
test was weakened, skipped, deleted, or rewritten to make code pass.

### Fixed

- **FND-001 (High):** the `test` gate must now invoke a recognised
  test runner — a command that never runs a test is INCOMPLETE, not
  PASS, and the state machine stays at VERIFYING. Shell strings are
  parsed (shlex, per shell segment) and fail closed unless a runner
  is invoked as an actual command; the substring `-m` fallback is
  gone. `tool_version` must agree with the invoked runner when it
  names one. The repo's own fixtures no longer use a printing
  one-liner as a `test` gate: `_good_bundle` runs a real pytest once
  per module and reuses its real stdout and JUnit.
- **FND-002:** a behaviour change whose changed test files contain
  no assertions (AST count: `assert`, `assert*` calls,
  `pytest.raises`/`warns`) is INCOMPLETE. The verification plan
  gains an optional `mutation_gate` (`{check, min_score?}`); when
  declared, a passing recorded mutation check must exist.
- **FND-003:** the JUnit report must be the output of the recorded
  test command — its artifact path must appear in the test check's
  `command_argv`, and its counts must agree with the pytest summary
  in the recorded stdout; mismatch is INCOMPLETE.
- **FND-004:** `record_check.py` is signal-safe — the child runs in
  its own process group (`start_new_session`), SIGTERM/SIGINT kill
  the group (SIGTERM, 5 s grace, then SIGKILL), and temp captures
  are unlinked on any exit path. The wrapper dies by the signal it
  received.
- **FND-005:** the router's Gates section now names the three
  `scripts/state.py transition` commands verbatim, and
  `validate_repo.py` asserts they are present.
- **FND-006:** `mcp-builder` and `monitoring-observability` declare
  their dependencies (`compatibility` frontmatter + install notes);
  the host-app scripts are declared in place as examples, not moved.
- **FND-007:** `fail_first.red_check` accepts the verbatim
  `record_check.py` fragment (`name` added to the schema, still v6).
- **FND-008:** the bundled-digest test skips when the repo-root
  file is absent (skills-only install) instead of failing.
- **FND-013:** `compatibility` frontmatter added for
  breaking-change (oasdiff), mutation-testing-python (mutmut), and
  accessibility (Node); `doctor.py` probes oasdiff, Stryker, and
  mutmut (MISS, never a hard fail). `mutation-testing` already had
  one — the auditor's "none of the four" was wrong on that skill.

### Added

- Waza eval specs (real executor, never run, no numbers claimed)
  for `finalize`, `registry-publish`, `independent-review`, and
  `handoff`, plus router-snapshot coverage for all four (16/16 per
  arm, self-check pin, `live` still null).
- `doctor.py` checks the Hermes bundle (parses, lists only the
  router, version matches the repo version); the bundle now carries
  `version: 0.10.12`.
- README: the three-verdict findings contract and the validator
  hard limits in "What it is"; HONEST-NUMBERS.md and the router
  snapshot in the doc inventory; the "only harness-scored evals"
  sentence corrected. `plugin.json` now says bundles are
  tamper-evident, not proof of execution, with the runner rule and
  its residual stated.

### Changed

- `# nosec B608` at all 14 sites in `migration_generator.py`
  (FND-010, false positives — only `quote_literal()`/`quote_ident()`
  output is interpolated); `hashlib.md5(..., usedforsecurity=False)`
  at both non-security step-id sites (FND-011).
- The trust-root residual is documented, not fixed (FND-012): the
  SHA-256 pin `doctor.py` gates the /tmp waza fallback on lives in
  this same repo, so a repo compromise could replace the hash and
  the binary together.

### Known limits (documented, not fixed)

- A command that runs a real runner and then fabricates consistent
  artifacts (JUnit + stdout summary agreeing) can still validate;
  bundles are tamper-evident, not proof of execution.
- `mutation_gate` is opt-in; the validator does not measure the
  50-line threshold and does not parse `min_score` from output.
- Only pytest's stdout summary format is reconciled (FND-003);
  other runners never reject on an unparseable summary.
- `record_check.py --timeout` kill is still leader-only
  (pre-existing); the Windows signal branch is untested here.
- No live-agent run exists for any eval (Phase 9, n=0); the four
  new waza suites have never run.

## [0.10.11] — 2026-11-09

CI fix for the 0.10.10 failures (run 42534376893: 7 of 14 jobs,
all failing on one test only).

### Fixed

- The round-6 Windows simulation patched `tempfile._rmtree`, a
  private alias that exists on Ubuntu's Python 3.12.3 but not on
  the setup-python 3.11/3.12/3.13 builds CI uses, so every CI
  job failed at the test's first line with `AttributeError`. The
  test now patches the stable seam instead —
  `TemporaryDirectory.cleanup`, the public method `__exit__`
  calls — and still proves the cwd is restored before cleanup.

## [0.10.10] — 2026-11-09

CI fix for the 0.10.9 macOS and Windows failures (run 42532295528:
`test (macos-latest, 3.12)` failed 1 test and `test
(windows-latest, 3.12)` failed 4, all in the new caveman Track 3
host isolation).

### Fixed

- `isolated_workdir` had one structural bug with two faces: on
  macOS `$TMPDIR` is a symlink (`/var` → `/private/var`), so the
  yielded temp path was unresolved while `Path.cwd()` is resolved;
  on Windows the cwd was restored only after
  `TemporaryDirectory` cleanup, and Windows cannot delete the
  process's current directory (`WinError 32`). The yielded path
  is now resolved and the cwd is restored inside the
  `TemporaryDirectory` block, before cleanup runs.

## [0.10.9] — 2026-11-09

Two takeaways from the 15-repo evaluation (2026-11-09), implemented
with attribution to their MIT/Apache sources.

### Added

- Validator hard limits, ported from Cloudflare's
  `security-audit-skill` (MIT): bundle input capped at 5 MiB, JSON
  nesting depth 64, 1000 array items, 100 validation errors; a
  hostile bundle can no longer OOM the validator, recurse it to
  death, or flood its output. Windows reserved names (`con`,
  `prn`, `nul`, `com1`–`com9`, …) are rejected for artifact paths
  and capture names, and diagnostics are escaped so terminal-control
  or bidi characters cannot make a FAIL read as a PASS.
- Three-verdict findings contract, adapted from Cloudflare's
  `confirmed` / `needs_validation` / `rejected`: a finding that was
  not validated is reported as `needs_validation` with no severity
  and forces the bundle to INCOMPLETE — never PASS, never FAIL.
  This is the machine-checked form of "a check that did not run is
  never reported as passed" (schema stays v6).
- Three-arm eval, adapted from caveman (Apache-2.0): every skill
  claim is measured as baseline vs terse control vs skill, and the
  honest delta is skill minus terse control, not skill minus
  nothing. Runs are graded in host isolation with a committed
  snapshot (`evals/snapshots/router-results.json`), and
  `docs/verification/HONEST-NUMBERS.md` publishes wins and losses
  side by side (no live-agent run exists yet — none fabricated).

## [0.10.8] — 2026-11-09

CI fix for the 0.10.7 Windows failure (run 42523335956:
`test (windows-latest, 3.12)` failed at "Run the script tests" —
1 failed, 781 passed, 12 skipped).

### Fixed

- The round-4 regression test itself double-converted line
  endings on Windows: it built the CRLF form by expanding the
  working-tree read, which is already CRLF there, so each CRLF
  became CRCRLF and the recorded hash matched neither the LF nor
  the CRLF form — the validator was right to reject it. The test
  now normalises to LF first, then expands. A guard test pins the
  equivalence class: a CRCRLF hash is still rejected, so the
  round-4 canonicalisation cannot silently become a loosening.

## [0.10.7] — 2026-11-09

CI fix for the 0.10.6 Windows failure (run 42520748232:
`test (windows-latest, 3.12)` failed at "Run the script tests" —
12 failed, 770 passed, 11 skipped).

### Fixed

- The round-9 two-target binding false-rejected genuine Windows
  recordings: the fixture writes the test file with `write_text`,
  which translates LF to CRLF on Windows, so the recorded
  `test_file_sha256` was the CRLF hash while the green tree holds
  the LF blob (git normalises on commit). The validator now
  compares under git's line-ending canonicalisation — the LF hash
  or the CRLF hash of the same file. Any other byte change still
  fails, so the material binding is not weakened.
- `test_pid_is_alive_posix` is POSIX-only (a reaped child still
  reads alive on Windows while its Popen holds a handle) and is
  now skipped on win32, the repo's established pattern.
- `test_stale_lock_note_still_fires_after_contention` simulated
  contention from another fd in the same process, which does not
  conflict on Windows (msvcrt locking is per-process); it now
  holds the lock from a separate process, the production shape.

## [0.10.6] — 2026-11-09

CI fix for the 0.10.5 Windows failure (run 42518738682:
`test (windows-latest, 3.12)` failed at "Validate the repo" —
"README skill table is stale").

### Fixed

- The round-9 FND-004 enumeration built repo-relative `.py` paths
  with `f"skills/{rel}"`, and `str(Path)` uses backslashes on
  Windows, so the generated skill-table comment differed from the
  committed README there and the validator reported it stale. The
  paths are now formatted with `rel.as_posix()`, identical on every
  platform; a regression test simulates Windows `str(Path)` with
  `PureWindowsPath`.

## [0.10.5] — 2026-11-08

Round-9 fix pass for the audit v3 of v0.10.4 (10 findings: 9
confirmed, 1 partial, 0 refuted), plus three items from a friend's
static review of v0.10.4. Every fix is red-first with a regression
test; pytest 786 passed + 6 skipped (baseline 752 + 6), all gates
green.

### Fixed

- FND-001 (High): `record_check.py` derives the repo from the cwd
  and refuses a `--repo` that is not that repo, including bare
  repos; the validator rejects any check, including `red_check`,
  whose resolved cwd is outside the claimed repo. Residual,
  documented in ADR 0006 and the SKILL.md Known limits: a fake run
  inside the repo, including an untracked fake binary the
  committed-tree digest does not cover, still validates —
  fabrication is narrowed, not closed.
- FND-002 (High): two-target binding — green checks bind to the
  bundle revision; `fail_first.red_check` binds to its own
  revision/digest. Worktree: the red revision must be the base
  (parent of the fix commit when committed; HEAD when uncommitted).
  Revert-at-smallest-scope binds via a recorded `red_diff_sha256`.
  `fail_first.test_file_sha256` records the copied-in test file and
  must match the test file in the green tree. New optional v6
  fields, no schema bump: `fail_first.base_revision`,
  `fail_first.red_diff_sha256`, `fail_first.test_file_sha256`.
- FND-003 (Medium): the verdict is pinned —
  `test_security_finding_cannot_be_non_blocking` now asserts
  `expected_verdict == FAIL` and the specific message; the M2
  mutant (deleting the auto-blocking rule) fails the test.
- FND-006 (Low) + N-F6x: a dedicated `check_stop_reason` rejects a
  non-empty `stop_reason` unless the verdict is INCOMPLETE with
  empty checks, on all three verdicts; a genuine FAIL carrying one
  is not misclassified.
- F1 (friend's review): `check_tree_binding` recomputes the
  working-tree state from `git status --porcelain=v1 -z -uall`
  instead of trusting the bundle's claim; a bundle claiming
  "clean" on a dirty tree is rejected, and a PASS is rejected
  while untracked files exist (`git diff HEAD` does not cover
  them).
- F2 (friend's review): `record_check.py` streams captures to temp
  files with a live 10 MiB cap (kill on exceed) instead of
  buffering the whole output in RAM and checking afterwards.
- F3 (friend's review): captures are written atomically (temp file
  + `os.replace`) and a pre-planted symlink at the bundle
  directory or either destination file is refused.
- FND-005 (Low): `state.py` no longer prints the stale-lock note
  when the flock was free on first try; the note fires only after
  genuine contention. N-F5x: `_pid_is_alive` on win32 probes with
  `ctypes` `OpenProcess` instead of always returning True.
- FND-004 (Low): the README `.py` counts (43 total, 32 under
  per-skill `scripts/`, 11 outside) are generated into the
  skill-table block, so they cannot drift again.
- FND-007: the README Status states Agent Evaluation is designed
  but not yet demonstrated, until a real-executor run exists.
- FND-010 + N-C: the README Hermes install section carries its own
  untested caveat in-section.
- N-A: SCOPE.md v1.1 now carries the ≥5-trials-per-task plan the
  README points to. N-R9-2: ADR 0006's stale `state.py` sentence
  corrected.
- FND-008 and FND-009: no change (verification report: already
  disclosed / no code fix).

## [0.10.4] — 2026-11-08

CI fix, round 2, for the 0.10.3 Windows failure (run 42501954616:
`test (windows-latest, 3.12)` still failed at "Run the script tests"
— the same 3 stub-git tests; the 2 signal tests now skip correctly).

### Fixed

- The round-1 fix's premise was wrong: it planted a `git.bat` stub
  on the claim that CreateProcess consults PATHEXT. It does not —
  CreateProcess appends only `.exe` to an extensionless name and a
  batch file needs cmd.exe to run it, so the stub was silently
  ignored and the real `git.exe` ran (both CI logs show this). The
  tests now stub git by faking `subprocess.run` instead — a canned
  `CompletedProcess` for `argv[0] == "git"`, with every other call
  delegated to the real run, so the check command still executes
  for real. One mechanism on every platform; no production code
  changed. The three tests also pin which git calls were made and
  which guard rejected the output, so they cannot pass without
  reaching the code they claim to test.

## [0.10.3] — 2026-11-08

CI fix for the 0.10.2 Windows failure (run 42499224528: `test
(windows-latest, 3.12)` failed at "Run the script tests" — 5 failed,
745 passed). All 5 were round-8-new tests, never green on Windows.

### Fixed

- Stub `git` is now executable on Windows: the tests planted an
  extensionless `git` file with a `#!/bin/sh` body on PATH, which
  Windows never executes (CreateProcess only tries the exact name and
  the PATHEXT extensions), so the real `git.exe` ran and the stub was
  silently ignored. The stubs now write `git.bat` on win32 and the
  extensionless `sh` stub elsewhere (same rule the repo documents for
  `bash` in `test_verify_sh.py`). Also fixed the bad-SHA stub's
  positional check: `--show-toplevel` is `$4`/`%4` (`git -C <repo>
  rev-parse ...`), not `$3` — with `$3` the test passed via
  `_resolve_repo` instead of exercising `_resolve_revision`.
- The FND-024 signal guarantee is POSIX-only: on Windows
  `Popen.send_signal(SIGTERM)` is TerminateProcess (returncode 1, no
  handler/atexit/finally ever runs, so no cleanup is possible) and
  `send_signal(SIGINT)` raises `ValueError` in the stdlib. Both
  signal tests are now skipped on win32; POSIX coverage is unchanged.

## [0.10.2] — 2026-11-08

Round-8 fix pass for the second independent audit of v0.10.1
(27 findings: 24 confirmed, 2 partial, 1 not reproducible here,
0 refuted; plus 9 new findings found during verification and 17
auditor corrections). Every confirmed defect is fixed, each with
a red-first regression test.

### Fixed

- Evidence binding (FND-004, High): the validator gains `--repo`
  (defaults to the working directory), `--expected-revision` and
  `--expected-diff`, and recomputes `content_digest` and
  `git diff HEAD` at validation time. A PASS bundle whose revision,
  check digests, or diff do not match the tree is rejected; with
  no repo resolvable a PASS bundle fails closed. The schema stays
  at v6. `state.py` passes the resolved repo to the validator, and
  the bundle must also have been recorded on the state's own
  revision. The trust boundary is unchanged and documented (ADR
  0006): this binds a bundle to a tree; it does not prove the
  command ran.
- Skills-only installs (FND-003, High): `content_digest.py` is
  bundled beside `record_check.py`, so the Verifier's mandatory
  recording step works with the documented command and no
  `--digest-module` flag; a test pins the two copies byte-identical.
- `content_digest.py` CLI (FND-001): the entry point no longer
  passes `argv[0]` as the repo argument; a test now exercises the
  real entry point via subprocess.
- Vacuous passes (FND-005): a required `test` gate needs a JUnit
  report with tests > 0 and passed > 0 (new optional bundle field
  `test_report`); an all-skipped suite cannot pass. A lying command
  printing fake output is still not detectable — documented, not
  claimed fixed.
- Future timestamps (FND-006): timestamps more than 5 minutes in
  the future are rejected.
- `state.py` (FND-007/008/009): `--repo` defaults to the caller's
  working directory (also for `transition`); `validate` gains
  `--require-head` (default on) and transitions to VERIFIED /
  RELEASE_READY at a stale revision are refused; concurrent
  transitions are serialised with a lockfile + flock, and the
  dirty-tree gate no longer skips non-HEAD revisions.
- `record_check.py` git validation (FND-023): empty or garbage
  `git` output is rejected at the revision layer
  (`rev-parse --verify`, full-SHA shape, existing toplevel);
  `content_digest()` confirms the tree object exists before
  accepting empty `ls-tree` output, so a genuinely empty tree
  still digests.
- Monitoring `verify.sh` (FND-012): a runbook is now required per
  alert, not haystack-wide; `--require-config` makes a target with
  no monitoring candidates INCOMPLETE instead of a vacuous PASS.
- `doctor.py` (FND-025): git and node versions are parsed, and an
  unreadable version is incompatible instead of `[ok]`.
- `clean_copy_check.py` (FND-024): SIGTERM now cleans up the temp
  copy (handler + `atexit`); SIGKILL still cannot be caught.
- `idea-capture` (FND-013): secret-like text is refused unless
  `--allow-secret` is given, and the slug is derived from the
  redacted form so no secret fragment leaks into the filename.
- Docs and install (FND-002/010/011/014/015/016/017/018/019/020/
  026/027/028): the invalid-`--agent` exit code is corrected to 1
  (verified by a real `npx skills@1.7.6` run); `hermes curator
  lock` is version-scoped (new in Hermes 0.23.0, not in 0.19.0);
  stale v0.9 mentions updated to v0.10 with historical items
  labelled; the state-machine wording is explicit-invocation-only;
  the dead `${CLAUDE_PLUGIN_ROOT}` links are removed; the
  installer is pinned to `skills@1.7.6`; the demo log is
  regenerated (8 tests).
- Pinned pytest 8.4.2 → 9.0.3 (FND-021, PYSEC-2026-1845), with
  regenerated hashes in `requirements-ci.txt`.

## [0.10.1] — 2026-11-08

CI fixes for the 0.10.0 head: the first CI run on the round-7
changes failed two jobs, so this release carries the fixes. (0.10.0
was never tagged or released; 0.10.1 is the release that ships the
round-7 work.)

### Fixed

- Clean-install job: the validator tests recorded evidence captures
  against the checkout, which has no `.git` in a git-archive clean
  copy — all 24 recording tests failed there. Captures are now
  recorded against a throwaway git repo beside the bundle directory.
  `record_check.py` itself is unchanged: failing outside a git repo
  is a deliberate property of the execution binding, not a bug.
- Windows test job: the `record_check` tests pinned LF bytes from
  `print('ok')`, which emits CRLF on Windows. The tests now use raw
  `sys.stdout.buffer.write` output, and a new test asserts CRLF bytes
  are recorded verbatim — the recorder must never normalise them.
- Windows test job: a temp-dir cleanup race (WinError 32) in the
  bare-revision test — the test changed the working directory into a
  temporary directory that was deleted while still the cwd. The
  directory change is now scoped so the cwd is restored first.

## [0.10.0] — 2026-11-08

Round-7 fix pass: every confirmed defect from the independent
live-agent audit of v0.9.8 is fixed, including the High finding
(F-01) with the execution binding the auditor deferred to a later
release. The evidence schema moves v5 → v6, which is a breaking
change (see Changed below).

### Added

- Execution binding for evidence bundles (F-01): a new
  `record_check.py` wrapper runs each check, writes its stdout and
  stderr as artifacts beside the bundle, and prints a check fragment
  (command, cwd, timestamps, exit code, stream hashes, content
  digest, revision, `recorded_by`, `capture_sha256`) for pasting into
  the bundle. The validator recomputes the binding hash from the
  fragment's fields and the artifact files, so a tampered transcript
  is rejected. This makes a recorded check tamper-evident; it does
  not prove the commands ran — a wrapper transcript is not signing,
  and no signing or PKI was added. ADR 0005 records the decision.

### Fixed

- Evidence validator: check commands that mask a failing exit code
  are rejected (`|| true`, `; exit 0`, `; :`, `python -c 'pass'` and
  the like) (F-02, N1); the fail-first proof now needs structured
  JUnit XML reports, with the test identified by its pytest nodeid —
  no report means no PASS (F-03); verifier and implementer
  identities are compared after normalising case and whitespace on
  both sides (F-04); a PASS for a behaviour change requires a
  non-empty `files_changed` (F-06); the time-order check is guarded
  against unvalidated timestamps, so it cannot raise on malformed
  input (F-11).
- State and content digest: `state.py` recomputes the content digest
  in-process and never trusts a caller-supplied one — the `--digest`
  flag is removed, use `--expect-digest` only to assert against the
  recomputed value (F-07); VERIFIED now requires an evidence bundle
  that exists and validates with verdict PASS, and VERIFIED /
  RELEASE_READY are refused on a dirty tree (F-07, N2);
  `content_digest.py` takes the revision as `--rev` and rejects a
  bare positional revision (F-15).
- Evals: the agent-suite grader assertions are inlined using only
  waza-documented names (`re` plus the closed built-in list), so the
  suite no longer raises `NameError` under the real waza binary
  (F-05, N3); the mock suite gains a negative control as a separate
  suite whose prompt, name, and description all omit the verdict
  word, so the suite can fail (F-10); the router self-eval default
  is labelled as a self-check, not an agent measurement (F-19); the
  mutation-testing skill records that Stryker generates no
  `Math.round` mutant, so a 100.00 mutation score does not cover the
  rounding class (N6).
- Docs, install, and architecture: the per-skill `scripts/` travel
  claim is corrected — per-skill folders are copied whole on
  npx/Hermes, only repo-root `scripts/` does not travel (F-09); the
  install docs state the Node ≥ 22.20 requirement next to the npx
  command and warn that an invalid `--agent` name exits 0 while
  installing nothing (F-12); "focused sub-skill" is defined (the
  router plus 35 focused sub-skills make 36 skills) and the
  validator now checks the Status count against it (F-14); the stale
  Windows/macOS CI comment is updated to record the green run on
  v0.9.8 (F-20); the architecture checker states its npm-only scope
  and exits 2 when nothing was checked (F-08, F-13); the dead
  Related Skills links in monitoring-observability are fixed (N5).
- Demo: a non-divisible percent test (79.6 of 100 rounds to 80, not
  79) closes the rounding hole the demo tests missed (F-16); the
  Stryker break threshold moves from 0 to 80, so the mutation gate
  can now fail on score (F-17). The threshold is enforced in CI:
  the demo job runs `npm run mutation` on Node 22 and 24 (about
  3 minutes per run; verified locally: 30 mutants, 26 killed,
  0 survived, score 100.00).
- The "done when the evidence says so" claim is narrowed to what
  the bundle proves (F-01, Option A): the headline no longer claims
  more than the validator mechanism delivers.

### Changed

- BREAKING: evidence schema v5 → v6. A v5 (or older) bundle is
  rejected with an explicit migration message ("re-run verification
  with the current validator"); old bundles are rejected, not
  migrated (F-24). PASS bundles now require recorded checks
  (hand-written PASS evidence no longer validates); fail-first now
  requires JUnit reports; `state.py --digest` is removed (use
  `--expect-digest` to assert).

## [0.9.8] — 2026-11-07

Follow-up to the unreleased 0.9.7: the first CI run on 0.9.7 failed
on one job (macOS), and the fix below changes a shipped file, so the
releasable version moves to 0.9.8 (the version-bump gate requires an
increase whenever shipped content changes).

### Fixed

- CI: the macOS job failed the same 12 `with_server` tests. Root
  cause found by research into how other repos handle macOS CI:
  `HTTPServer.server_bind` calls `socket.getfqdn()` after binding,
  a reverse DNS lookup that stalls on hosts without working reverse
  DNS (e.g. GitHub Actions macOS runners) before the server can
  accept a single request. The fixture server is now a
  `LoopbackHTTPServer` subclass whose `server_bind` calls
  `TCPServer.server_bind` and sets `server_name`/`server_port`
  from the literal address, so it never resolves its own hostname
  (same fix as ikamensh/kodo and pywbem/pywbem, both of which hit
  this on GitHub Actions macOS). The Local Network / TCC prompt and
  the application firewall were investigated and ruled out as the
  cause. Whether `getfqdn` actually hangs on the macOS 26 runner
  is still unproven from this VM — the 0.9.8 CI run is the
  confirmation: green macOS confirms the diagnosis, the same stall
  refutes it.
- CI: the tool's readiness polling connected to `"localhost"`,
  which on macOS can resolve `::1` first and add a per-poll
  connect delay before falling back to `127.0.0.1`. The three
  connection targets in `with_server.py` now use the literal
  `127.0.0.1`.

## [0.9.7] — 2026-11-07

Follow-up to the unreleased 0.9.6: the first CI run on 0.9.6 failed
on two jobs (macOS, Windows), and the fixes below change shipped
files, so the releasable version moves to 0.9.7 (the version-bump
gate requires an increase whenever shipped content changes).

### Fixed

- CI: the Windows job failed 14 script tests. The two new
  `with_server` tests failed on Windows themselves — they called
  `os.getpgid` and `signal.SIGKILL` unconditionally in their own
  setup and cleanup. The doctor now trusts the token's
  default-owner SID as well as the user SID, so a trusted waza
  fallback binary is no longer reported "incompatible". The
  `verify.sh` fake `bash` stub is now a `.cmd` resolved
  PATHEXT-aware (an extensionless stub can never execute on
  Windows, so real Git Bash ran it and returned the wrong code).
  Idea-capture reads the lock PID from offset 1 and probes dead
  PIDs without `os.kill(pid, 0)`; `package_skill` only prompts when
  stdin and stdout are both terminals (the NUL device reports
  `isatty()` on Windows) and its fixtures write exact bytes.
- CI: the macOS job failed the same 11 `with_server` tests. The
  cause is still unproven, but the 0.9.6 diagnostics narrowed it:
  the log-heavy test's 2000 lines print after `import http.server`
  and before the constructor, so the import chain completes and the
  stall is inside the `HTTPServer` constructor, at or before
  `listen()` returns. This version adds startup-step markers
  (`after-import`, `socket-created`, `bound`, `listening`, `READY`)
  plus a raw-socket probe, so the next failure names the exact
  stalled step.

## [0.9.6] — 2026-11-07

Follow-up to the unreleased 0.9.5: the first CI run on 0.9.5 failed
on two jobs (macOS, Windows), and the fixes below change shipped
files, so the releasable version moves to 0.9.6 (the version-bump
gate requires an increase whenever shipped content changes).

### Fixed

- CI: the Windows job failed 40 script tests — POSIX assumptions
  throughout the scripts and their tests. Archive and plan keys are
  now forward-slash on every platform (`package_skill`); `os.getuid`,
  `signal.SIGKILL` and `fcntl` have Windows equivalents (doctor,
  clean_copy_check, idea-capture locking); `verify.sh` runs under
  Git Bash instead of the WSL launcher; `run_eval` resolves `claude`
  with `shutil.which` (PATHEXT-aware) and pumps stdout with a reader
  thread instead of `select`; fixtures write exact bytes and the MCP
  builder emits UTF-8; `with_server` kills the whole process tree
  with `taskkill /T /F` instead of only the shell.
- CI: the macOS job failed the same 8 `with_server` tests — the
  server never becomes ready, stays alive, and prints nothing. The
  cause is still unproven (no macOS in this VM to reproduce it), so
  this version adds diagnostics instead of another timeout: a
  readiness failure now prints the server's recent output, and the
  test servers print a `READY` marker once they are listening, so
  the next failure distinguishes 'stuck before listen' from
  'listening but unreachable'.

## [0.9.5] — 2026-11-07

Follow-up to the unreleased 0.9.4: the first CI run on 0.9.4 failed
on two jobs (macOS, Windows), and the fixes below change shipped
files, so the releasable version moves to 0.9.5 (the version-bump
gate requires an increase whenever shipped content changes).

### Fixed

- CI: the Windows job reported all 130 vendored files 'unrecorded'
  and 129 'drifted'. Two causes: `build_manifest()` in
  `scripts/check_drift.py` built manifest keys with `str()`, which
  uses backslashes on Windows and never matched the forward-slash
  recorded manifest — keys are now normalised with `as_posix()` —
  and, with no `.gitattributes`, a Windows checkout converts LF to
  CRLF, so every text file's bytes differed from the recorded hash.
  The repo now forces LF checkouts (`* text=auto eol=lf`).
- CI: the macOS job failed 8 `with_server` tests — the test server
  never became ready within 15s. The startup waits in the tests
  are now 30s, the tool's own default, and a server that crashes on
  startup now reports its stderr instead of looking like a slow
  start ('never listened' with no clue why).

## [0.9.4] — 2026-11-07

The sixth review round (three independent reviewers on 0.9.3):
every confirmed bug is fixed here, each with a red-first
regression test, and the first CI run on the new code surfaced two
further fixes (mypy, Windows install) that ship in this version
too. No new skills; the 36-skill system stays whole.

### Fixed

- Migration safety: SQL injection in the migration generator
  (parameterised identifiers), the `tablez` schema typo, the
  zero-downtime data-loss bug (a backfilled value was reverted by
  the migration), and the index-validation query that used MySQL's
  `information_schema.statistics` instead of PostgreSQL's.
- Validator: artifact paths can no longer escape the bundle,
  `red_check` fails first on a failing gate, graders are
  programmatic instead of keyword-matching, and vacuous witnesses
  are rejected.
- Secret scanning: the allowlist regex no longer misses real
  secrets or flags `sk-` false positives; skill packaging no
  longer includes `.env` files or follows symlinks out of the
  bundle; the accessibility gate no longer passes silently on
  missing input; the capture lock race is closed; the doctor gates
  the waza binary by hash instead of running whatever sits in
  `/tmp`.
- Verifier: evidence is checked against the bundle instead of
  trusted, test names must exist, empty witnesses are rejected,
  and the verdict block is compared programmatically.
- Router: the `fa` locale no longer falls through to French, the
  state schema is enforced, and the router eval is runnable.
- Evaluation: fixtures are runnable, graders reject invalid
  verdict blocks, and unproven claims are labelled unproven.
- Scripts, security, CI: `with_server` readiness, `verify.sh`
  false passes, the MCP builder, Python 3.10 removal, the demo CI
  jobs, CodeQL, Dependabot, and CODEOWNERS.
- `quick_validate`: the ORCINUS frontmatter field
  `user-invocable` is accepted again (it rejected 35 of 36
  skills).
- CI: `mypy` failed with `import-not-found` for `tomli` in
  `scripts/clean_copy_check.py` — the fallback import for Python
  < 3.11, which no supported Python needs since 3.10 was dropped
  (round 6, 2-S7). The fallback is removed; `tomllib` from the
  standard library is used directly.
- CI: the Windows job failed because `tzdata` — a Windows-only
  dependency of `psycopg[binary]` — was not pinned, so `pip
  install --require-hashes` rejected it. It is now pinned with
  hashes in `requirements-ci.in` and `requirements-ci.txt`.

## [0.9.3] — 2026-11-07

Follow-up to the unreleased 0.9.2: the 0.9.2 tree was pushed to main
but never tagged, and the follow-up below changes shipped files, so
the releasable version moves to 0.9.3 (the version-bump gate requires
an increase whenever shipped content changes).

### Fixed

- CI dependencies: `exceptiongroup` is pinned with hashes. It is
  pytest's dependency on Python < 3.11 only, so `pip-compile` on 3.12
  omitted it — the Python 3.10 CI job resolved it unpinned, which
  `--require-hashes` rejects (run 42300115306, right after the same
  failure for `tomli` in run 42298838900). Together the two pins close
  the complete set of Python < 3.11 conditional dependencies in the CI
  tree.

## [0.9.2] — 2026-11-06

The fifth review round (reviewers 3 and 4 re-reviewed 0.9.1): every
concrete claim was verified by running the code, and every confirmed
bug is fixed here, each with a red-first regression test. No new
skills; this release closes the holes the previous round's fixes left
in the checking machinery itself.

### Fixed

- Migration generator: a foreign key to a column (or unique) added by
  the same migration is deferred to a late-FK phase — a new table with
  an FK to a new column on an existing table no longer fails on
  PostgreSQL (proven on real PostgreSQL 16); the same deferral
  applies to a new column's own FK and to the zero-downtime path. The
  rollback test now executes the generated `sql_rollback` and compares
  the schema, instead of proving only transactional rollback.
- Content digest: `git ls-tree -r -z` with byte-exact parsing, so a
  non-ASCII filename can no longer escape the `.orcinus/` and
  `docs/verification/` exclusions; the digest format is versioned
  (v2; v1 digests on non-ASCII trees are not comparable).
- Version-bump gate: changed files are read with `git diff -z`, so a
  non-ASCII filename can no longer bypass the bump; `scripts/` counts
  as shipped content; the version must now INCREASE past the base and
  past the latest release tag, so a downgrade or a re-release fails;
  the CI fetch no longer hides its error behind `|| true`, and the
  release tags are fetched for the tag check.
- Evidence contract (schema v3): every check that ran must carry its
  output — an artifact file with its sha256, or inline text — so a
  PASS with no reviewable output is rejected, and an artifact whose
  hash does not match its file is rejected; a bundle with no checks at
  all is valid only as INCOMPLETE with a `stop_reason`; the verdict
  block and the bundle now share one vocabulary (PASS/FAIL/INCOMPLETE).
- Router self-containment: the status table and the project-state spec
  travel with the router skill (generated from `docs/MAP.md` and
  `docs/project-state.md`, checked by the validator), so a standalone
  install — which has no `docs/` — still has the decision table and
  the state spec, and the router never reads the user's own
  `docs/MAP.md`.
- Clean-copy check: a timed-out gate, a corrupt manifest, and a
  timed-out `git archive` fail their step with a FAIL line and a
  controlled exit code, never a traceback; the check now runs the
  same seven gates as CI (`ruff format --check` and `mypy` added) and
  CI runs it in release mode; CI installs Python packages with
  `--require-hashes` from `requirements-ci.txt` (13 pins, 191 hashes)
  and the Claude Code CLI with `npm ci` from `package-lock.json`.
- Drift check: the `test_*.py` exclusion is an explicit allowlist of
  the four ORCINUS-authored test files (verified absent from upstream
  at the pinned commits); `agents/` and `commands/` are glob-scanned,
  so a new file under either directory is reported unrecorded.
- Licences and wording: the ATTRIBUTION "description verbatim" claims
  are corrected — the ORCINUS router-only note appended to 35 of 36
  descriptions is now recorded in every one, and the wording is
  "verbatim body, ORCINUS frontmatter"; every modified Apache-2.0
  file carries its change notice in the file itself (Apache-2.0
  §4(b)), checked by the validator; the i18n description no longer
  tells the user to type `/i18n`; the router description now triggers
  on the user asking for the ORCINUS lifecycle; the validator checks
  that coarse stage ranges contain the router's fine ranges, and
  accessibility is documented as cross-cutting with a pre-ship gate.
- Idea-capture lock: the lock file records the holder PID, so a lock
  left by a dead process is recognised as stale, removed with a note,
  and the change succeeds; a live holder still blocks with a truthful
  error naming its PID; a lock with no readable PID is never stolen.
- README: the skill list is a table generated from `manifest.json`
  (checked by the validator); a 5-line quick start; the default
  Agent Skills install is the interactive pick, not `--all`; the fake
  key in the security-review eval is replaced by a generate-at-test-time
  instruction; ORCINUS is presented as a guided workflow, and the
  verifier's independence is reported with its level (same agent
  session, not a separate process).
- CI dependencies: `tomli` is pinned with hashes. It is mypy's
  dependency on Python < 3.11 only, so `pip-compile` on 3.12 omitted
  it — and the Python 3.10 CI job then resolved it unpinned, which
  `--require-hashes` rejects. The 3.10 job failed on the install step
  for exactly that reason; the other Python versions never needed it.

## [0.9.1] — 2026-11-06

The fourth review round (reviewers 3 and 4 re-reviewed 0.9.0): every
concrete claim was verified by running the code, and every confirmed
bug is fixed here, each with a red-first regression test. No new
skills; this release makes the checking machinery itself trustworthy.

### Fixed

- Evidence validator: `fail_first` is now required for a PASS verdict
  (a behaviour change without a red run cannot pass); `change_type`
  is an enum; every canonical gate (build, lint, typecheck, test)
  must be a required gate or waived with a reason; a behaviour-change
  PASS needs the `test` gate; findings without a `severity` are
  blocking (fail-closed); checks require `tool_version`,
  `started_at`, `finished_at`; a check's `finished_at` must not
  precede its `started_at`; artifact paths must exist; dates are
  strict RFC 3339 (identical on Python 3.10–3.13); an honest
  INCOMPLETE bundle is valid — only PASS carries the strict rules.
- Project state: VERIFIED and approval are now bound to a content
  digest (sha256 over the committed tree, excluding `.orcinus/` and
  `docs/verification/`), not to a commit SHA — a commit that only
  records state no longer resets the stage. Reference implementation
  in `scripts/content_digest.py`.
- Manifest: a required `integration` field (`verbatim`, `wrapper`,
  `merged`, `from-scratch`); non-from-scratch skills need a full
  GitHub source URL and a 40-hex upstream commit; all sources
  normalized; `handoff` and `codebase-knowledge-builder` stages
  corrected to `0-100`; `mutation-testing-python` gained its
  ATTRIBUTION and licence.
- Router and handoff honesty: SCOPE no longer claims a single entry
  point is "enforced"; the three React-scoped frontend skills load
  only for React/React Native projects; handoff files are
  router-proposed and user-confirmed, named `orcinus-handoff-*`;
  the router states what to do when a sub-skill is missing, optional,
  or not built.
- Migration generator: table creation follows foreign-key dependency
  order (proven on real PostgreSQL 16 — the old order fails there);
  FK cycles defer to post-create ADD CONSTRAINT steps; the comparator
  resets on every call; all set iterations are sorted; the generator
  declares its PostgreSQL dialect; a `postgres-migration` CI job runs
  the new tests against postgres:16.
- Tooling: SECURITY.md says 0.9.x (it said 1.0.x while the plugin was
  0.9.0) and the validator now checks the table; `doctor.py` finds a
  ruff binary on PATH, its waza fallback is Linux-only, and its exit
  codes are documented (1 incomplete, 2 incompatible); the clean-copy
  check never renames the source (two modes: working-tree copy,
  release via `git archive`); the version-bump check enforces two
  rules and its CI job runs on pull requests; the waza download uses
  `curl -fsSL`; `registry-publish` distinguishes E404 from
  FETCH_ERROR/E401/E403 and publishes the exact smoke-tested tarball.
- Format and typecheck are now CI gates: `ruff format --check` over
  ORCINUS-owned code (vendored files excluded) and `mypy` over 25
  owned Python files, with 8 type errors fixed.
- Eval graders: the agent-behavior suite (9 tasks) requires the
  structured verdict block; 3 new PASS tasks stop an always-FAIL
  policy from passing (4/9) and an always-PASS policy from passing
  (1/9); the suite's own eval.yaml was unparseable since round 3 and
  is fixed.

## [0.9.0] — 2026-11-06

The first public release — a pre-1.0 version. ORCINUS is one integrated nervous system for the
0–100 software lifecycle: a router (`orcinus`) plus 35 focused
sub-skills, a shared glossary, evidence bundles, and independent
review. No auto-merge, no weakened tests. It is 0.9.0, not 1.0.0,
because the whole system has not yet run 0–100 end-to-end on one
real project — that proof is the work before 1.0.0.

### Added

- 36 skills covering idea → architecture → scaffolding → coding →
  testing → security → debugging → verification → finalize → publish,
  each with a scored eval in `evals/`.
- `docs/MAP.md`: the 0–100 stage map with the source, licence and
  status of every row.
- `GLOSSARY.md`: the shared language, also bundled in
  `skills/orcinus/references/` so it travels with the router.
- `examples/demo/`: the demo project the evals cite, so "proven on a
  real demo project" is reproducible from the repo.
- `evals/results/`: raw verification logs (the demo's four commands).
- `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`:
  install as a Claude Code plugin (`/plugin marketplace add
  DnsQueen/orcinus-skills`, then `/plugin install
  orcinus-skills@orcinus`), or with the skills CLI (`npx skills@latest
  add DnsQueen/orcinus-skills --all`).
- `.github/workflows/ci.yml` and `scripts/validate_repo.py`: CI
  validates frontmatter, licences, the glossary copy, stage ranges,
  the plugin manifests and relative links, and runs the script tests
  and the waza harness-smoke suite.
- `THIRD_PARTY_NOTICES.md`: the central licence index.
- `scripts/check_drift.py` and `scripts/drift-manifest.json`: a drift
  check for the vendored files (128 recorded SHA256 checksums) — CI
  fails if a vendored file changes without its ATTRIBUTION.md being
  updated.
- `CONTRIBUTING.md` and `SECURITY.md`.

### Fixed (from four independent external reviews, 2026-11-06)

- The README install commands pointed at the wrong owner
  (`orcinus/orcinus-skills`); they now point at
  `DnsQueen/orcinus-skills`, and the `--all` flag installs every skill.
- The from-scratch scripts had real bugs and no tests; `capture.py`,
  `check_architecture.py`, `check_refactor.py`,
  `migration_generator.py` and `with_server.py` are fixed and covered
  by pytest tests (see the per-skill `ATTRIBUTION.md` files for the
  upstream files and the fixes).
- Verification tools could report a false pass: `check_architecture.py`
  returned OK with a relative `--root`, a unique-only migration
  produced an empty ALTER, and the waza eval tasks leaked the expected
  verdict in the prompt. All three are fixed.
- The security review's verdict is now PASS, PASS WITH LIMITATIONS,
  INCOMPLETE or FAIL — never PASS when a scanner did not run.
- The "covered" rows that depended on skills installed on the
  builder's own machine are now honest: `diagnosing-bugs` is bundled,
  the rest are marked external-optional with router fallbacks.

### Known limits (not fixed in v0.9.0)

- The whole system has not yet run 0–100 end-to-end on one real
  project; the weekly-budget dogfood run is in progress. The waza
  agent-behavior suite (real executor, no verdict in the prompt)
  exists in `evals/waza-orcinus-verify-agent/` and is not yet run.
- The enforcement layer (skill manifest, persistent project state,
  structured evidence, version-bound approval) is v1.1 work; v0.9.0
  ships the INCOMPLETE status and the structured evidence schema.
- See `SCOPE.md` for the full list of recorded limits.
