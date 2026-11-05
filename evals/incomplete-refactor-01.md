# EVAL — incomplete-refactor-01

How to check whether `incomplete-refactor` works. Run the checker script on throwaway copies of the demo project, doing a real rename refactor (`budgetWarning` → `checkBudget`) in each case. The demo project itself is never touched. No criterion may be skipped.

## Setup (not part of the score)

- The demo's `budgetWarning` appears in exactly 2 files: `src/budget.ts` (definition) and `tests/budget.test.ts` (import + 3 calls).
- Each case uses a fresh throwaway copy of the demo (in `/tmp/orcinus-demo-refactor/`, without `node_modules`/`dist`, with `node_modules` symlinked from the durable demo so the four commands run).
- The checker is `skills/incomplete-refactor/scripts/check_refactor.py` (stdlib only).

## Case 1 — complete refactor passes

**Input:** rename `budgetWarning` → `checkBudget` in both files (definition + import + 3 calls). Run the checker with `--old budgetWarning`, then run the four commands.

**Pass criteria:**

1. The checker exits 0 and reports clean.
2. The four commands exit 0 (build, lint, typecheck, test 7/7 pass).
3. Verdict is PASS.

**Fail criteria:**

- The checker reports a leftover in a fully renamed copy.
- Any of the four commands fails.

## Case 2 — leftover name is caught while the suite is green

**Input:** rename `budgetWarning` → `checkBudget` in both code files, but leave the old name in a comment in `src/budget.ts` (`// TODO: migrate remaining budgetWarning call sites`) and in `README.md` (`budgetWarning` mentioned as the old name). Run the checker with `--old budgetWarning`, then run the four commands.

**Pass criteria:**

1. The checker exits 1 and reports both leftovers (the comment and the README mention), with file and line.
2. The four commands exit 0 — the suite is green, so the checker is the only thing that catches this.
3. Verdict is FAIL (as expected — the refactor is incomplete).

**Fail criteria:**

- The checker exits 0.
- Either leftover is not reported.
- The four commands fail (the case is designed so they pass).

## Case 3 — dead file is caught while the suite is green

**Input:** rename `budgetWarning` → `checkBudget` in both code files, but leave a copy of the old implementation as `src/budget-old.ts` (the old file, still exporting `budgetWarning`). Run the checker with `--old budgetWarning --removed src/budget-old.ts`, then run the four commands.

**Pass criteria:**

1. The checker exits 1 and reports the removed path still present, and the old identifier inside it.
2. The four commands exit 0 — the dead file compiles, so the suite is green.
3. Verdict is FAIL (as expected — the refactor is incomplete).

**Fail criteria:**

- The checker exits 0.
- The removed path is not reported.
- The four commands fail (the case is designed so they pass).

## Last run

- 2026-11-05: PASS. Case 1: 3/3. Case 2: 3/3. Case 3: 3/3. Real run, not simulated, on throwaway copies of the demo (in /tmp/orcinus-demo-refactor/, with node_modules symlinked from the durable demo). The rename was `budgetWarning` → `checkBudget` in every case. Case 1 (complete rename in src/budget.ts + tests/budget.test.ts): checker clean, exit 0; four commands exit 0, test 7/7 pass — PASS. Case 2 (renamed in code, but the old name left in a TODO comment in src/budget.ts:8 and in README.md:7): checker exit 1, 2 leftovers reported with file and line; the four commands all exit 0 (test 7/7 pass) — the suite was green, so the checker was the only thing that caught it; verdict FAIL as expected. Case 3 (renamed in code, but the old implementation left as src/budget-old.ts): checker exit 1, 2 leftovers reported (removed-path src/budget-old.ts + old-name at src/budget-old.ts:2); the four commands all exit 0 (test 7/7 pass) — the dead file compiles, so the suite was green; verdict FAIL as expected. The demo project itself was never touched (git status clean afterwards; `budgetWarning` still present in the real demo: 1 occurrence in src/budget.ts, 4 in tests/budget.test.ts). The throwaway copies live in /tmp and are rebuildable. The checker script was also smoke-tested on a tiny fixture first (1 leftover found, exit 1; clean fixture, exit 0) and compiles with py_compile.
