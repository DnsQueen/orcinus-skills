# EVAL — build-01

How to check whether `build` works. Run it on the demo project (`/tmp/orcinus-demo-scaffold`, scaffolded by the scaffold eval) and score the result. No criterion may be skipped.

## Slice (from idea-calibrate Case 1, Opportunity C)

Weekly summary. Add `weeklySummary(spending, budget)` in `src/summary.ts`, returning `{ total, remaining, warned, percent }`:

- `total` = sum of spending.
- `remaining` = budget − total.
- `warned` = total is at least 80% of the budget.
- `percent` = total / budget × 100, rounded to the nearest whole number.
- A budget of 0 or less throws `Error("budget must be greater than 0")`.

Seam (confirmed with the test author before writing any test): the exported `weeklySummary` function. Tests observe only its return value and its throw, never internals.

## Test cases (expected values are literals, not recomputed)

1. spending `[20, 30, 30]`, budget `100` → `{ total: 80, remaining: 20, warned: true, percent: 80 }`.
2. spending `[10, 20]`, budget `100` → `{ total: 30, remaining: 70, warned: false, percent: 30 }`.
3. spending `[]`, budget `100` → `{ total: 0, remaining: 100, warned: false, percent: 0 }`.
4. budget `0` → throws `Error("budget must be greater than 0")`.

## Pass criteria

1. The test was written first and shown failing (record the failure output) before any implementation.
2. The implementation is minimal: only `src/summary.ts` and `tests/summary.test.ts` added or changed.
3. All four commands exit 0, in order: build, lint, typecheck, test (full suite, including the earlier budget tests).
4. orcinus-verify gives PASS on the change.
5. One commit, on `main`, naming the slice. No unrelated files changed.

## Fail criteria — any one of these fails the eval:

- The test passes before any implementation exists.
- An assertion recomputes the expected value the way the code does (tautological).
- The implementation hard-codes a return for the test inputs.
- A test was weakened, deleted, or skipped to get a pass.
- Extra features or files beyond the slice.
- Any of the four commands fails, or orcinus-verify gives FAIL.

## Last run

- 2026-11-05: PASS. 5/5 pass criteria, 0 fail criteria. Real run, not simulated: followed the skill on `/tmp/orcinus-demo-scaffold` to build the weekly-summary slice. Test written first and shown failing (TS2307, exit 2) before any implementation. Only `src/summary.ts` and `tests/summary.test.ts` added. Four commands exit 0 (build, lint, typecheck, test 7/7 pass, including the 3 earlier budget tests). orcinus-verify re-ran the four checks itself and gave PASS (no scope creep, no weakened tests, no hard-coding — the only "80" in the implementation is a comment). One commit `269bb15` on `main`.
