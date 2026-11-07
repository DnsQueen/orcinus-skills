# Changelog

All notable changes to ORCINUS are recorded here. Dates are UTC.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
