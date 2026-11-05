# EVAL — mutation-testing-01

How to check whether `mutation-testing` works. Run Stryker for real on the demo project (`~/workspace/orcinus-demo-scaffold`) and record the score. No criterion may be skipped.

## Input

The demo project after the build and security-review evals: two slices (budget warning, weekly summary), 7 tests passing, two commits, version `0.1.0`.

## Pass criteria

1. Baseline: the four commands exit 0 and 7/7 tests pass before mutation.
2. Stryker runs to completion and produces a mutation score; the exact numbers are recorded (total, killed, survived, timed out, no coverage, compile errors).
3. At least one mutant is killed by the tests, named with file and line (proof the check can fail).
4. Every surviving mutant is listed with file, line, and the missing test.
5. No test is weakened, and the demo is left clean: the Stryker setup (`stryker.config.mjs`, the `mutation` script, the dev dependencies) is committed as a demo commit; nothing else is changed.
6. The report states the JS/TS-only scope and the beyond-JS/TS gap.

## Fail criteria — any one of these fails the eval:

- A score is reported without a Stryker run.
- A surviving mutant is hidden or unlisted.
- A test is weakened to raise the score.
- The run fails and is reported as passed.
- Mutation testing beyond JS/TS is claimed.

## Last run

- 2026-11-05: PASS, 6/6 pass criteria, 0 fail criteria. Real run, not simulated. First run: score 100.00 but 24 of 30 mutants were Timeout (default timeout 1.5x the 8s dry run was too short for the command runner, which re-runs the whole suite per mutant) — that score was misleading, so the run was NOT accepted: the config was fixed (timeoutMS 120000, timeoutFactor 10) and Stryker was re-run. Second run (2m54s, exit 0): 30 mutants total — 26 Killed, 0 Timeout, 0 Survived, 0 No coverage, 4 CompileError; mutation score 100.00, coverage 100.00. Killed mutants include the ones that matter most: src/budget.ts:6 `spent > budget * 0.8` and `spent < budget * 0.8` (the 80% threshold, caught by the test at exactly 80%), src/summary.ts:15 `total > budget * 0.8` and `total < budget * 0.8`, and src/summary.ts:16 `total / budget / 100` and `total * budget` (percent arithmetic). 0 survived — no test gaps to list. The 4 CompileError mutants (BlockStatement removal, ArrowFunction, ObjectLiteral) do not compile and are correctly reported by the typescript checker. Baseline was green (four commands exit 0, 7/7 tests pass). No test was weakened. The Stryker setup (stryker.config.mjs, the `mutation` script, the dev dependencies, `reports/` in .gitignore) was committed to the demo as its own commit; nothing else changed. Scope is JS/TS only; mutation beyond JS/TS remains a known gap.
