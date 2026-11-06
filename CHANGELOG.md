# Changelog

All notable changes to ORCINUS are recorded here. Dates are UTC.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
