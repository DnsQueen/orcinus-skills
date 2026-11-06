# Changelog

All notable changes to ORCINUS are recorded here. Dates are UTC.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
