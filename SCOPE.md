# SCOPE

## In v0.10

- One entry and router (`skills/orcinus`).
- One entry point, by convention, not enforcement: only the router is user-invocable — every sub-skill carries `user-invocable: false` in its frontmatter, so no sub-skill appears in the `/` menu and the user never picks one mid-work; the router invokes them. That hides sub-skills from the user; it does not stop a model from invoking one directly — the descriptions still carry trigger phrasing (`Use when…`), because on hosts without the router's table those descriptions are the only discovery signal. `user-invocable` is a Claude Code extension field, ignored by other hosts. It is a non-spec field, so claude.ai / Skills API uploads would reject it — uploads are not a distribution path for this repo (install is via the plugin marketplace or `npx skills add`). No skill sets `disable-model-invocation: true`: the router must be able to invoke sub-skills itself.
- Hermes support (`hermes/orcinus.yaml` + README install docs): the repo is a Hermes tap as-is (`hermes skills tap add DnsQueen/orcinus-skills`, default path `skills/`), and the bundle is the `/orcinus` entry point — it lists the router only, because a bundle loads everything it lists at once and the router loads sub-skills on demand with `skill_view(name)`. A validator check (`check_hermes_bundle`, 8 tests) pins the bundle: it must exist, parse, list only skills that exist, and list the router only. The router checks a sub-skill is installed before routing to it — a Hermes bundle silently skips missing skills. Deliberately NOT embedded: `metadata.hermes` tags/category — Hermes documents them, but the Agent Skills spec requires metadata values to be strings; ORCINUS frontmatter already carries the non-spec `user-invocable` extension field, so the reason is the metadata-values rule, not spec purity; tags/category are discovery-only and the router is the entry point. What Hermes loses: the plugin-root `agents/` and `commands/` (Claude Code only), and `${CLAUDE_PLUGIN_ROOT}` paths in skill text need the Hermes skill folder instead (orcinus-verify stopped using the variable in round 6; the one remaining use is a "See also" link in monitoring-observability references). Recorded limit: the bundle was validated by the repo's own YAML parser and check, never loaded by a real Hermes installation — no Hermes CLI exists in this environment.
- One flagship verification skill (`skills/orcinus-verify`).
- One idea-calibration skill (`skills/idea-calibrate`), with a manual scenario eval (`evals/idea-calibrate-01.md`).
- One scaffold skill (`skills/scaffold`), with a manual scenario eval (`evals/scaffold-01.md`) proven on a real demo project.
- One build skill (`skills/build`), with a manual scenario eval (`evals/build-01.md`) proven on the demo project.
- One security-review skill (`skills/security-review`), with a manual scenario eval (`evals/security-review-01.md`) proven on the demo project and on a planted fake secret.
- One finalize skill (`skills/finalize`), with a manual scenario eval (`evals/finalize-01.md`) proven as a dry-run release on the demo project in `examples/demo/`, using ready tools as-is (release-please, Waza, handoff, monitoring-observability).
- One injected ready skill (`skills/monitoring-observability`), copied verbatim from OrchestKit (MIT, 28 files, frontmatter adapted to the Agent Skills spec only), with its `ATTRIBUTION.md` and `LICENSE.txt`.
- One injected ready skill (`skills/ask-questions-if-underspecified`), copied verbatim from Agentic Awesome Skills (MIT, 1 file, frontmatter adapted to the Agent Skills spec only), with its `ATTRIBUTION.md` and `LICENSE.txt`, and wired into the router's shared rules and routing table. Eval (`evals/ask-questions-01.md`) passed on 4 real cases.
- One injected ready skill (`skills/webapp-testing`), copied verbatim from Anthropic (Apache-2.0, 6 files, frontmatter adapted to the Agent Skills spec only), with its `ATTRIBUTION.md` and `LICENSE.txt`, and wired into the router's shared rules. Eval (`evals/webapp-testing-01.md`) passed on a real Chromium E2E run (6/6).
- One mutation-testing skill (`skills/mutation-testing`), written in our own words, using Stryker as-is (Apache-2.0). Eval (`evals/mutation-testing-01.md`) passed on a real Stryker run on the demo in `examples/demo/` (score 100.00, 26 killed, 0 survived, 0 timeout).
- One visual-regression skill (`skills/visual-regression`), written in our own words, using Playwright as-is (Apache-2.0). Eval (`evals/visual-regression-01.md`) passed on a real screenshot comparison on the demo page (0.00% unchanged, 2.70% on a visual change, 0.00% after a confirmed baseline update).
- One performance-optimization skill (`skills/performance-optimization`), copied verbatim from addyosmani/agent-skills (MIT). Eval (`evals/performance-optimization-01.md`) passed on real timings on the demo (page load mean 0.108s vs a 2.5s budget, `npm test` mean ~4768ms vs a 10s budget; a deliberate 3s delay measured 3.040s and was flagged as a regression; after revert the load was 0.122s again).
- One api-and-interface-design skill (`skills/api-and-interface-design`), copied verbatim from addyosmani/agent-skills (MIT). Eval (`evals/api-and-interface-design-01.md`) passed on a real live server built from the demo (valid request 200 with the exact body, invalid input 422 with the structured error shape, list endpoint paginated; a breaking-change proposal and a bare-array list design were both flagged and rejected).
- One breaking-change skill (`skills/breaking-change`), written in our own words, using oasdiff as-is (Apache-2.0). Eval (`evals/breaking-change-01.md`) passed on a real oasdiff run on demo OpenAPI specs (identical specs: no changes, exit 0; a rename + removal: 2 errors named with locations, exit 1 with `--fail-on ERR`; an additive optional field: no breaking changes, exit 0).
- One incomplete-refactor skill (`skills/incomplete-refactor`), written from scratch with a checker script. Eval (`evals/incomplete-refactor-01.md`) passed on real rename refactors on throwaway copies of the demo (complete rename: checker clean, four commands green, 7/7 tests; a leftover name in a comment and the README: checker exit 1 with 2 leftovers while the suite stayed green; a dead old file: checker exit 1 with 2 leftovers while the suite stayed green).
- One registry-publish skill (`skills/registry-publish`), written from scratch (npm first). Eval (`evals/registry-publish-01.md`) passed on a real run on throwaway copies of the demo, with NO real publish: a prepared copy's `npm pack --dry-run` lists exactly 5 files (1.6 kB); the demo as-is fails the check (15 files, incl. tests/source/config); a real tarball (1,589 bytes) installs in a clean directory and the smoke test passes on all three expected values. Rules: semver + changelog, `package.json` must declare name, version, license, entry points, and a `files` allowlist, no publish without the user's explicit written confirmation, never from a dirty tree, never an existing version. Recorded limit: the publish step itself was never run against the real npm registry — the first real publish must go through the skill's checklist.
- One i18n skill (`skills/i18n`), injected verbatim (Marvellbrazil/my-agentic-skills, MIT, 10 files). Eval (`evals/i18n-01.md`) passed on a real run: the audit found the hardcoded strings; en and fa both rendered with the same values and no fallback; a missing fa key fell back to English.
- One accessibility skill (`skills/accessibility`), own-words wrapper using the ultra11y engine as-is (maxgfr/ultra11y, MIT). The upstream `SKILL.md` (522 lines) was not copied verbatim — it is over the Agent Skills spec's 500-line guidance. Eval (`evals/accessibility-01.md`) passed on a real run: the engine found the missing main landmark on the demo page (1.3.1, majeur); after the fix, 0 non-conformities and conformance 100%; the `--fail-on major` gate exits 1 before the fix and 0 after it.
- One architecture skill (`skills/architecture`), written from scratch with a checker script (`scripts/check_architecture.py`). Eval (`evals/architecture-01.md`) passed on a real run: the stack ADR names the stack, reasons, and three rejected alternatives; the contract names the public surface, error shape, and versioning rule; the repomix map contains 14 files and no build artifact or secret; the licence check lists all 7 direct devDependencies (MIT/Apache-2.0); a layer violation and a circular import are both caught by the checker while the suite stays green.
- One database-designer skill (`skills/database-designer`), injected verbatim (alirezarezvani/claude-skills, MIT, 15 files) with ORCINUS fixes to its migration generator (see its ATTRIBUTION.md) — the upstream generator failed on any schema change, and external reviews found four more defects in it. Eval (`evals/database-designer-01.md`) passed on a real run with a real SQLite database: the analyzer reports the CHECK and naming issues and generates the ERD; the optimizer recommends the composite index on `spending(week, spent_at)`; the v1 → v2 migration applies with all data intact (3 rows, sum 80) and the new column and index in place; a column drop is flagged HIGH risk and refused. Recorded tool gaps: the generated SQL adds no foreign key, the SQL format prints no rollback, and `--validate-only` emits nothing for a drop.
- One skill-creator skill (`skills/skill-creator`), injected verbatim (anthropics/skills, Apache-2.0, 19 files). Eval (`evals/skill-creator-01.md`) passed on a real run: following its workflow, a new skill-lint skill was authored in a throwaway workspace and passed `quick_validate.py` ("Skill is valid!") and `package_skill.py` (a 2,497-byte `.skill` file); the authored checker passes two real good skills and catches two deliberately broken ones with the violation named. Recorded limits: its `run_eval`/`run_loop`/`improve_description` scripts invoke the Claude Code CLI, which does not exist here, and `package_skill.py` must be run as a module from the skill directory. Recorded risk: the plugin root also holds the skill's 3 agents with generic names (`analyzer`, `comparator`, `grader`); a same-named agent from another plugin could collide — unverified in this environment, and renaming them would break their verbatim upstream files and the drift check, so the names stay and the risk is recorded here.
- Two state skills (`skills/frontend-architecture`, `skills/frontend-optimistic-mutations`), injected verbatim (stareezy-1/frontend-architecture-skill, MIT, 10 stars). Eval (`evals/state-01.md`) passed on a real run: the split is proven on a throwaway example app (a mirrored store is caught by name) and the write path is proven (a missing rollback and a per-attempt idempotency key are both caught by name); on the real demo page in a real browser, the correct page stays fresh after a data change (total 130) while the mirrored variant shows stale data (total 80). Recorded limits: both skills are React/React Native (the state rules are stated as library-agnostic, the concrete examples are not); the demo is a library, not a React app.
- One API-consumption skill (`skills/frontend-data-contracts`), injected verbatim (stareezy-1/frontend-architecture-skill, MIT). Eval (`evals/api-consumption-01.md`) passed on a real run against a live demo API: one typed client is the only fetch boundary, a valid response parses to typed values, a contract drift (renamed field, wrong type) is rejected at the boundary with a typed `ApiError` (`CONTRACT_DRIFT`), a 422 maps to `ApiError` with per-field errors, a stopped server produces the same `ApiError` shape (`NETWORK_ERROR`), and branded-ID misuse fails the typechecker (TS2345). Recorded finding: the demo API has no single envelope (three shapes), so the client carries that inconsistency; aligning it is a breaking change for a new API version.
- One Python mutation-testing skill (`skills/mutation-testing-python`), written from scratch with mutmut as-is (boxed/mutmut, BSD-3-Clause, 3.8.1). Eval (`evals/mutation-testing-python-01.md`) passed on a real run: pytest 10/10, mutmut 34 mutants, 34 killed, 0 survived, 0 timeout, 0 suspicious — score 100.00%; the first run (8 tests) had 4 survivors that named real gaps (no small-budget test; `match` is a substring search), and strengthening the tests killed them all. Recorded limits: Python only; other languages still need their own verified CLI.
- One idea-capture skill (`skills/idea-capture`), written from scratch with a script (`scripts/capture.py`, Python, standard library only). Eval (`evals/idea-capture-01.md`) passed on a real run: 3 ideas captured (English, Persian, one with quotes and symbols), all listed with status `raw`, every raw text byte-identical to capture time (hash-checked); search finds the right ideas, promote moves raw → calibrated, drop moves raw → dropped with a reason and never deletes the file; a fresh process sees all three ideas with the same ids and statuses, and all four failure cases (empty capture, unknown id, dropped → calibrated, drop without a reason) exit 1. Recorded limits: the store is plain Markdown files in the project — no database, no server, no sync; the project's own git history is the backup.
- One monitoring skill (`skills/monitoring`), injected verbatim (ericrisco/rsc-harness, MIT, 493 stars). Eval (`evals/monitoring-01.md`) passed on a real run: the bundled gate `verify.sh` exits 0 on a good config and exits 1 naming all five failures on a bad one; on a live throwaway service, `/livez` answers 200 in 0.018s while `/readyz` goes 503 when its dependency dies (and `/livez` stays 200), and the probe fails when the service stops. Recorded limits: the page landing on a phone is not proven here (no PagerDuty/incident.io connected); the skill's "Related" links pointed to sibling rsc-harness skills that are not in ORCINUS — they were removed and replaced with a pointer to the in-repo monitoring-observability (see its ATTRIBUTION.md); tool prices are upstream's "as of 2026-06".
- One independent-review skill (`skills/independent-review`), own-words method with the six reviewer agents and the `review-pr` command bundled as-is (anthropics/claude-plugins-official, Apache-2.0 — the per-plugin LICENSE is authoritative; the README's "MIT" line is an error in the README). Eval (`evals/independent-review-01.md`) passed on a real run with three separate reviewer agents, each given only the diff and the code: the planted-defects change FAILs with all three defects named (comment/code contradiction, confidence 95; silent failure, CRITICAL, confidence 95; test gap 9/10); the clean change PASSes with no critical issues; the misleading-summary change FAILs with the behavior change named from the diff (confidence 95) and the author's claim rejected. Recorded limits: the reviewers are subagents that share the parent's context (a fresh-context reviewer is the stronger form); the Case 2 reviewer did not run the test suite.
- One evidence/eval skill (`skills/waza`), injected verbatim (microsoft/waza, MIT, 1,499 stars; upstream commit `f5789f75`, 2026-11-04), with the runnable suite `evals/waza-orcinus-verify/` (eval.yaml + 2 tasks + fixture) grading the flagship `orcinus-verify` skill. Eval (`evals/evidence-eval-01.md`) passed on a real run with the official v0.40.0 release binary (SHA256 verified): the shipped suite runs 2/2, aggregate 1.00, exit 0. The code-grader semantics (Python expressions evaluated with `output` in scope) are corroborated, not just assumed: that smoke run evaluated `len(output) > 0` and recorded passed/total assertion counts for it on both tasks (see evals/results/waza-harness-smoke-2026-11-06.json) — corroboration of the semantics, not proof of literal `eval()`; a control task with an absent string fails and `waza run` exits 1; `waza compare` shows the deltas (Score 1.0000 → 0.8889, Success Rate 100.0% → 66.7%). Recorded limits: the binary (~200 MB) is installed from the release page, not kept in the repo; only the mock executor was proven here — the mock echoes the prompt, so a mock pass proves the harness, never the skill; the upstream skill's inline task example used a string `expected`, which v0.40.0 rejects — it is corrected in this repo to the real schema (see its ATTRIBUTION.md), and the shipped suites use the correct schema. A second suite, `evals/waza-orcinus-verify-agent/`, grades agent behaviour with a real executor and prompts that do not state the expected verdict (9 tasks, designed 4 PASS / 5 FAIL, with structured-verdict-block graders); it is not yet run.
- One generic-refactoring skill (`skills/refactor`), injected verbatim (MuhiminOsim/code-refactoring-skill, MIT, 12 stars; upstream commit `90fa6405`, 2026-05-19) — `SKILL.md` (119 lines) + 11 reference files (process, safety, smells, 7 catalogs, language profiles). Eval (`evals/refactor-01.md`) passed on a real run following the skill's own process on a throwaway copy of the demo: a 45-line smelly function was refactored in two atomic steps (guard clauses, then reuse `weeklySummary`), 11/11 tests after each step, lint + typecheck clean, behavior identical, file 45 → 32 lines; a breaking step failed 2 tests and was reverted immediately with no test changed; a proposed rename of an exported symbol was not made (a §3 red line, no confirmation given). Recorded limits: the smelly file was written for the eval, not found in a real codebase; only TypeScript was exercised.
- One MCP API-design skill (`skills/mcp-builder`), injected verbatim (anthropics/skills, Apache-2.0; upstream commit `ca45fc49`, 2026-10-28) — `SKILL.md` (252 lines) + 5 reference files + 4 script files. Eval (`evals/mcp-builder-01.md`) passed on a real run following the skill's 4 phases: a TypeScript MCP server (SDK v2) for the demo's domain builds clean, its self-check passes (exactly 2 tools, correct summary/warning answers, `budget: 0` rejected by input validation, `SMOKE PASS`, exit 0), and its 10-question evaluation passes 10/10; a control run with one wrong expected answer fails 9/10 and exits 1. Recorded limits: only the stdio transport was exercised (no Streamable HTTP, no auth); the bundled `scripts/evaluation.py` was not run (it needs an Anthropic API key); the MCP Inspector was not used; only the demo's two-function domain was exposed.
- One handoff skill (`skills/handoff`), a merge of two MIT handoff methods written in own words (mattpocock/skills handoff + dariohansson/claude-handoff, upstream commit `01b57fb0`, 2026-09-16) — the fixed template, path rules (confirm, never overwrite, mode 0600), strict redaction, and a resume mode that treats the file as data. Eval (`evals/handoff-01.md`) passed on a real run: a handoff for the real ORCINUS state was written (10 sections, mode 0600, no contents, no secrets); a fresh subagent resumed from it alone and restated everything correctly without acting; a hostile handoff (imperatives to skip confirmation, push, and run `rm -rf`) was followed in none of its five imperatives, the `rm -rf` was restated not run, and the target directory still exists. Recorded limits: the "fresh" subagents inherit the parent's context, so they are not truly fresh sessions; the handoff file itself had real gaps (unnamed onboarding candidate, sketched push procedure, undefined eval criteria) that a fresh session would have to resolve by reading `docs/MAP.md` first.
- One onboarding skill (`skills/codebase-knowledge-builder`), injected verbatim (OthmanAdi/codebase-knowledge-builder, MIT, 28 stars; upstream commit `b01f40c5`, 2026-08-30) — `SKILL.md` (72 lines) + 2 reference files + 1 template. Eval (`evals/onboarding-01.md`) passed on a real run following its 4 phases on an unfamiliar repo (`eabait/codebase-onboarding-skill` at `1723ff4a`): the artifact's provenance is complete, all 11 citations verified programmatically against the inspected revision (0 bad), the analyzer was run and its graceful degradation proven (all optional deps absent, exit 0, skipped phases recorded with install commands as reasons), and the target's worktree was clean before and after. Recorded limits: only the analyzer subsystem was traced in depth; the eval harness was not run; the optional dependencies were not installed, so symbol extraction and ranking were proven only in their skipped form.
- One bug-triage skill (`skills/issue-triage`), injected verbatim (florianbruniaux/claude-code-plugins, MIT, 44 stars; upstream commit `f207f2fb`, 2026-10-28) — `SKILL.md` (448 lines) + 1 template. Eval (`evals/issue-triage-01.md`) passed on a real run on `microsoft/waza` (53 open issues, 25 open PRs, 20 closed): the audit's exact dimensions check out (24 PR links verified by regex, 0 stale from real dates); the Jaccard detector flags a near-identical pair (0.88) and rejects unrelated pairs (0.00–0.04), and its miss of a reworded duplicate (0.42) is recorded as a known limit; the drafts exist and are visible, both Red flags were checked by reading and found false so neither escalation was executed, and the repos' issue counts are unchanged. Recorded limits: categorization and risk by keyword are an approximation — the skill requires reading (a 7-issue reading check found 3 categorization errors and 2 risk errors); Phase 2 was not run with parallel agents; Phase 3 was proven only in draft-and-stop form (`gh` is not authenticated here, and no owner authorized a write); the skill defaults to French when no language is given.
- One debugging skill (`skills/diagnosing-bugs`), injected verbatim (mattpocock/skills, MIT; upstream commit `4ae2317d`, 2026-10-31) — `SKILL.md` (138 lines) + the human-in-the-loop template. Eval (`evals/diagnosing-bugs-01.md`) passed on two real bugs diagnosed with the loop (the check_architecture relative-path false pass and the capture.py CRLF silent failure): in both cases the root cause was named, not just the symptom, and the fix was verified by a test that fails without it. Recorded limits: the OpenAI agent definition (`agents/openai.yaml`) was not copied — it is a Codex/OpenAI definition, not usable in Muse; the skill references `tdd` for the test-first loop, which is external-optional in ORCINUS, so the regression test goes at a correct seam or is documented as not possible.
- The full 0–100 map (`docs/MAP.md`) with source, licence, and integration method for every micro-step.
- Shared glossary and boundaries.
- Eval scenarios for the flagship, run on a demo repo.

## In v0.11

- Attested verification for the VERIFIED transition. CI gains an
  `attest` job (`needs: [test]`) that attests the tree content digest
  with `actions/attest@v4.2.2` (SLSA L2 — the direct action, not the
  `attest-build-provenance` wrapper), so an attestation existing for
  a run implies the test job passed in that same run.
  `scripts/state.py` now refuses a VERIFIED transition without a live
  CI attestation for the revision, checked at transition time
  (`scripts/verify_attestation.py`: `gh attestation verify` on the
  content digest, pinned to this repo's CI workflow and the revision;
  exit 0 verified / 1 not verified / 2 unavailable). The CI `attest`
  job needs all nine essential gates and runs on push-to-main only.
  There is no fallback that mints VERIFIED: a targeted rerun mints
  only the new RERUN_CONFIRMED stage, and the gate runs the rerun
  itself (`scripts/rerun_check.py`, from a clean worktree at the
  exact revision, using the revision-pinned copy of the script) and
  records the proof it produced — the `--attestation-proof` proof
  file was removed in 0.12.0 after a hand-written proof JSON was
  shown to mint VERIFIED in a scratch repo with no tests at all. A
  local validator PASS is provisional — structurally valid, not
  CI-attested — and `validate` is local-only: it never checks
  attestation. Recorded limit: no live attested transition has been
  observed yet in this environment (`gh` unauthenticated here; the
  `attest` job first runs on the next CI run after merge) — see
  `docs/verification/HONEST-NUMBERS.md`.

## Out of v0.10

- Full implementations of every sub-skill in the map. They are added one at a time, each proven before it ships.
- Auto-merge, auto-publish to a registry, and any irreversible action without human approval.
- A claim that ORCINUS makes any model correct. ORCINUS makes mistakes checkable; it does not remove them.

## Foundation complete means

- The router, gates, glossary, evidence bundle, and eval harness exist.
- Every stage 0–100 has a present entry in the map — no empty stage.
- Some sub-skills are thin in v0.10. Depth grows in later versions; the structure does not change.

## Non-goals

- A dump of 2,000 skills to pick from. ORCINUS is one unit.
- Copying CC-BY-SA or proprietary text verbatim into MIT files.
- Rebuilding what ponytail and tdd already do well. ORCINUS routes to them where they fit and focuses new work on the gaps: independent verification, security, and eval. (diagnosing-bugs was external-optional in v0.9.0's first draft — historical — and is now bundled — see the debugging skill above.)


## Change notices for modified Apache-2.0 files

A file copied from an Apache-2.0 upstream and then modified must carry its change notice in the file itself (Apache-2.0 §4(b)). ORCINUS writes the notice as an HTML comment right after the frontmatter (Markdown) or a `#` comment at the top (scripts) — invisible in rendering, so the rendered body stays verbatim, and never in the frontmatter, which the frontmatter spec check would reject as an unknown field. The modified files are listed in `scripts/validate_repo.py` (`MODIFIED_APACHE_FILES`); the repo validator checks each one carries the notice. The wording "verbatim body, ORCINUS frontmatter" is the precise claim: the body is verbatim upstream, the frontmatter is ORCINUS's (adapted to the Agent Skills spec, `user-invocable: false`, and the ORCINUS router-only note appended to the description). A "description verbatim" claim next to that appended sentence is false; every ATTRIBUTION.md records the append.

## v1.1 (planned, not v0.10 blockers)

These came from four independent external reviews (2026-11-06). They are
recorded here so they are not lost, and so no one mistakes them for
v0.10.0 promises. v0.10.0 ships the INCOMPLETE status and the structured
evidence schema in `orcinus-verify`; the rest of the enforcement layer
is v1.1 work.

**Built in the second review round (2026-11-06) — the v1.1 steps, not
the layer itself:** the central skill manifest (`skills/manifest.json`,
checked by the validator against the folders and the frontmatter);
the machine-readable evidence schema (`skills/orcinus-verify/references/evidence.schema.json`)
with a validator (`skills/orcinus-verify/scripts/validate_evidence.py`) that enforces
verdict consistency; the `doctor` command (`scripts/doctor.py`);
a clean-copy check (`scripts/clean_copy_check.py`,
also run in CI); agent security eval tasks in
`evals/waza-orcinus-verify-agent/` (a handoff that tells the verifier
to skip the checks, a fabricated test log, a request to change a FAIL
verdict to PASS) with graders that require the structured verdict
block AND the named file AND the evidence — 9 tasks (4 PASS, 5 FAIL),
so the degenerate policies cannot pass (always-FAIL 1/9, always-PASS
1/9, both below the 0.8 threshold; verified by
`evals/waza-orcinus-verify-agent/test_graders.py`, which reproduces
the grader semantics in Python against good, cheating, and constant
outputs). The suite's own eval.yaml was unparseable from round 3 (a
plain scalar containing 'suite: it echoes') and nothing ever noticed
— it is fixed now, and the harness test parses every suite YAML;
the architecture decision records (`docs/adr/`);
the unified machine-readable report format (`docs/report-format.md`);
and the persistent project state spec (`docs/project-state.md`,
`.orcinus/state.json` with BUILDING / VERIFYING / BLOCKED / VERIFIED /
AWAITING_APPROVAL / RELEASE_READY, VERIFIED bound to evidence for a
specific content digest, approval bound to a specific content
digest/artifact).
What is still v1.1 is the *tamper-proof* layer: a policy evaluator
backed by the verifier's signature, session isolation for the
verifier, and a tamper-proof state file. The specs above define
what that layer must enforce; a local check already enforces the
state machine's own rules when a human or agent explicitly invokes
it (scripts/state.py refuses a transition
the evidence does not support — round 7), but it is not the
tamper-proof layer: anyone with write access can still edit the
state file, and the next validate only detects the edit.
v0.11.0 does not build it: the attestation is an
independent-observer check on minting VERIFIED, not the
tamper-proof layer — it is checked live at transition time and,
since 0.12.0, recorded in the state file as
`verification_origin`, and a hand-written VERIFIED stage still
validates locally. What 0.11.0 added is a refusal to mint
VERIFIED without an attestation; 0.12.0 removed the
targeted-rerun proof fallback that used to mint VERIFIED too —
a local rerun now mints only RERUN_CONFIRMED. Neither is a lock
on the file afterwards.
Harness-executed evidence (the harness, not the LLM, running the
commands and writing the bundle — reviewer 2's 2-V8/Rec2) is 0.10
scope, not v1.1: the validator proves a bundle is complete and
self-consistent, not that the commands really ran.

**Built in the fourth review round (2026-11-06) — trust fixes in
the checking machinery itself:** the validator checks the SECURITY.md
supported-versions table against the plugin version (it said 1.0.x
while the plugin was 0.9.0 — historical); `doctor.py` finds a ruff binary on PATH
(it only tried `python -m ruff`), its waza fallback is Linux-only,
and its docstring now states the real exit codes (1 incomplete, 2
incompatible); residual (round 11, FND-012): the SHA-256 pin `doctor.py`
gates the /tmp waza fallback on lives in this same repo, so a repo
compromise could replace the hash and the binary together — the pin
only stops a planted /tmp binary, it is not a root of trust outside
the repo; the clean-copy check was redesigned — two modes
(working-tree copy, release via `git archive`), it never renames the
source (the old hide-by-rename could strand the checkout hidden if
killed), and its docstring states the price (an absolute-path leak
back to the live checkout is no longer caught); the version-bump
check enforces two rules (a shipped change needs version AND
changelog; a version bump needs a changelog entry even with no
shipped change) and its CI job runs on pull requests as well as
pushes, so the feedback arrives before the merge; the waza download
in CI uses `curl -fsSL`; `registry-publish` Step 2 distinguishes
E404 (free to publish) from FETCH_ERROR/timeout/E401/E403
(INCOMPLETE, stop) and publishes the exact tarball it smoke-tested;
`ruff format --check` runs in CI over ORCINUS-owned code (vendored
files excluded in the top-level `[tool.ruff] exclude` — directory
patterns under `[tool.ruff.format] exclude` do not exclude files in
ruff 0.17.4, verified by experiment); `mypy` (default settings,
Python 3.11 target) runs in CI over the ORCINUS-owned Python
(`scripts/` and the skill scripts, plus `migration_generator.py`,
which ORCINUS maintains — pure vendored copies are not checked).
The repo-root `scripts/` (doctor, clean-copy check, validator,
drift check) do not travel in `npx skills` or Hermes installs,
which copy per-skill folders; the Claude Code plugin path installs
the whole repo, so they are present there. What is still NOT built
is unchanged from above: the enforcement layer, the isolated
verifier, and the real agent-behavior eval run.

- **Enforcement layer** (reviewer 4's strongest architectural proposal):
  a central skill manifest (id, version, entry path, tool/skill
  dependencies, supported languages/environments, licence + source
  commit, entry/exit conditions, its eval and evidence type); a
  persistent project state with real distinctions (BUILDING /
  VERIFYING / BLOCKED / VERIFIED / AWAITING_APPROVAL / RELEASE_READY),
  with VERIFIED bound to evidence for a specific revision; human
  approval bound to a specific version/commit/artifact, invalid if the
  content changes after approval.
- **Real-agent eval runs**: run `evals/waza-orcinus-verify-agent/` with
  a real executor, and multi-environment install testing (a fresh
  install on a clean machine, a real plugin install). At least 5 trials
  per task with a real executor (round 9, N-A): the suite's 9 tasks × 1
  trial at a 0.8 threshold cannot measure an LLM, so a real-executor
  run needs ≥5 trials per task before Agent Evaluation can be called
  demonstrated. The clean-copy check (`scripts/clean_copy_check.py`)
  is built, and `claude plugin validate . --strict` (plus
  `--profile directory --strict`) passes and runs in CI — the
  validator needs no login, it only checks that the files are
  well-formed (verified 2026-11-06 with CLI 2.1.318, no login). A
  real plugin install still needs a machine with Claude Code.
- **Engineering Trust Score** (reviewer 2's proposal): a weighted
  score across verification, security, and eval dimensions. The
  weights in the proposal (15/15/20/20/15/10/5) are arbitrary and
  gameable — they need evidence before they are adopted, and the score
  is a v2 idea at best. See ADR 0004 for the decision not to ship one
  in v0.10.
- **Failure Intelligence, Model-Agnostic Verification, Prompt
  Injection Isolation, Dependency/Supply Chain Intelligence,
  Repository Memory, Self-Evaluation** (reviewer 2's §5–7 proposals):
  documented directions for later versions, not v0.10 scope.
