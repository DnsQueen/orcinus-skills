# EVAL — onboarding-01

How to check whether the `codebase-knowledge-builder` skill works. Follow its 4 phases (Reconnaissance → Deep-Dive Study → Artifact Authoring → Validation and Delivery) on an unfamiliar real repo — `eabait/codebase-onboarding-skill` (Apache-2.0, SKILL.md v2.2), which the evaluator had not studied before. The research question: how does this skill turn a codebase into an onboarding wiki, and what is the architecture of its analyzer? The target was cloned once (bounded checkout, depth 1); the study was read-only except for one authorized run of the target's own analyzer, with its output written outside the target. No criterion may be skipped.

## Case 1 — reconnaissance produces a bounded, accurate map

**Input:** the target repo at revision `1723ff4a248ed0ac125d9f3cf478ace896f48d92` (branch `main`, 52 tracked files, 696K), studied per Phase 1 (metadata-only preflight, recon checklist, inventory).

**Pass criteria:**

1. The artifact's Provenance section is complete and accurate: repo, source URL, exact revision, branch, shallow-clone note, timestamp with timezone, question, included/excluded scope, budget, method, validation, confidence.
2. The inventory names the real entry surfaces (`scripts/analyze.py`, `SKILL.md`, `evals/run.sh`) and the real manifests (only `scripts/requirements.txt`, four optional packages).
3. Exclusions are stated with reasons (the 31 generated wiki pages at depth 5–6; history, because the clone is shallow).

**Fail criteria:**

- Provenance is missing, wrong, or undated; or the inventory names files that do not exist.
- An excluded area is silently treated as studied.

## Case 2 — the deep dive is evidence-traced, and its citations check out

**Input:** the analyzer subsystem traced per Phase 2 (entry surface `main()` → `analyze()` → 7 phases), with every observed claim cited as `relative/path:line` and labelled `observed` / `inferred` / `unknown` / `not applicable`.

**Pass criteria:**

1. Every citation in the artifact exists at the inspected revision and says what the artifact claims — verified programmatically (11 distinct citations, 0 bad).
2. The 7-phase pipeline is described correctly with its functions and line numbers.
3. At least one finding is honestly labelled `unknown` (not fabricated): the README's 95.3/100 eval claim, and the history (shallow clone).
4. The analyzer was actually run (not just read): its output is a real JSON report, and the graceful-degradation claim is proven by the run (all optional deps absent, exit 0, skipped phases recorded with install commands as reasons).

**Fail criteria:**

- Any citation fails to check out, or any claim is stated without a label.
- A claim the study did not verify is presented as a verified fact.

## Case 3 — the artifact is written outside the target, clean, and the target is unchanged

**Input:** the artifact (`/tmp/orcinus-demo-onboard/artifact.md`) and the analyzer output (`/tmp/orcinus-demo-onboard/analyze-output.json`), both outside the target; the target's worktree status before and after.

**Pass criteria:**

1. Both files live outside the target (`/tmp/orcinus-demo-onboard/`), not inside it.
2. The artifact contains no secrets and no fabricated functions, configuration, history, or diagrams.
3. The target's worktree is clean before and after the study (`git status` empty at preflight and after).
4. The artifact states its confidence and its unresolved questions.

**Fail criteria:**

- Any file is written inside the target, a secret is present, or the worktree changed.
- The artifact claims certainty it did not earn.

## Last run

- 2026-11-06: PASS. Case 1: 3/3. Case 2: 4/4. Case 3: 4/4. Real run, not simulated, on `eabait/codebase-onboarding-skill` at `1723ff4a` (52 files, 696K). Case 1: the Provenance section is complete (repo, URL, exact revision, branch, shallow-clone note, timestamp, question, scope, exclusions, budget, method, validation, confidence); the inventory names the real entry surfaces and the only manifest (`scripts/requirements.txt`, four optional packages); the exclusions are stated with reasons. Case 2: all 11 distinct citations verified programmatically against the inspected revision (0 bad) — each is the function definition claimed; the 7-phase pipeline is described correctly; two findings are honestly `unknown` (the README's 95.3/100 score; history); the analyzer was run and exited 0 with all optional deps absent, producing a real report (`file_count` 21, `languages_source` "fallback", symbols and key_entities skipped with install commands as reasons, `capabilities_active` `["tomllib (TOML)"]`, 0 warnings). Case 3: both outputs live outside the target; no secrets; the target's worktree was clean before and after; the artifact states its confidence (high for the pipeline, medium for the wiki-generation step) and its open questions. Two real findings during the run: (1) the analyzer's default `max_depth=4` silently excludes the 31 deep wiki result files — the report lists 21 of 52 files, and the depth limit is the cause, verified by counting files at depth ≤ 4; (2) the artifact's first timestamp was wrong (the Tehran wall time was recorded as UTC) — caught by the validation check and corrected to `2026-11-05T22:02:00Z`. One misreading caught before writing: `git_insights` does not report branch/commit at all (it reports hotspots, contributors, ownership, recent activity), so the report's absent `branch`/`commit` keys are expected, not a defect. Honest limits: only the analyzer subsystem was traced in depth (the SKILL.md's wiki-generation phases were read, not traced); the eval harness (`evals/run.sh`, `scripts/eval.py`) was not run; the optional dependencies (tree-sitter, networkx, pathspec) were not installed, so the symbol-extraction and ranking phases were proven only in their skipped form.
