# EVAL — independent-review-01

How to check whether `independent-review` works. Run the review method (the six bundled reviewers, from pr-review-toolkit, Apache-2.0) against three changes on a throwaway copy of the demo (`/tmp/orcinus-demo-review/`, base commit `a6e48ac`). Each review is done by a separate reviewer agent that is given ONLY the diff and the code — never a description of what the change does. No criterion may be skipped.

## Case 1 — the review finds planted defects

**Input:** branch `case-1` (`50b2f14`, "Add applyDiscount with SAVE10"): a new `applyDiscount(total, code)` with three planted defects — the comment says "10% off" but the code returns `total * 0.8` (20% off); a bare `catch` swallows the unknown-code error and silently returns the full total; the only test covers the happy path. The suite passes 8/8 as submitted.

**Pass criteria:**

1. Verdict is FAIL.
2. The review names all three planted defects, each with file, line, reviewer, and confidence/severity: the comment/code contradiction on the discount rate (`src/discount.ts:2` vs `:6`/`:13`, comment-analyzer, confidence 95); the silent failure in the bare catch (`src/discount.ts:7-9`, silent-failure-hunter, CRITICAL, confidence 95); the missing unknown-code test (`tests/discount.test.ts`, pr-test-analyzer, gap rating 9/10).
3. The review runs the applicable reviewers (code-reviewer, pr-test-analyzer, comment-analyzer, silent-failure-hunter, type-design-analyzer) and does NOT run code-simplifier (the review did not pass).
4. Verdict is FAIL.

**Fail criteria:**

- Verdict is PASS, or any planted defect is missed.
- A finding names no file or line, or a reviewer that applied did not run.

## Case 2 — a clean change passes

**Input:** branch `case-2-clean` (`903e67e`): a correct `applyDiscount` — `SAVE10_RATE = 0.9`, unknown codes throw `Error("unknown discount code: ...")`, three tests (happy path, unknown code, empty code). The suite passes 10/10.

**Pass criteria:**

1. Verdict is PASS (no critical issues).
2. All applicable reviewers ran, including code-simplifier (the review passed).
3. The review may list important issues and suggestions (for example the missing validation of `total`), but none of them is critical.
4. Verdict is PASS.

**Fail criteria:**

- Verdict is FAIL on a critical issue that does not exist.
- A reviewer that applied did not run.

## Case 3 — the review does not trust the author's summary

**Input:** branch `case-3-misleading` (`c9980c1`, "Refactor budget warning (no behavior change)"): the warning threshold moves from `budget * 0.8` to `budget * 0.9`, with the comment updated to match. The author's summary claims "just a refactor, no behavior change". The suite fails 9 pass / 1 fail on this branch.

**Pass criteria:**

1. Verdict is FAIL.
2. The review names the behavior change from the diff (`src/budget.ts:6`, code-reviewer, confidence 95): `budgetWarning(80, 100)` was `true` and is now `false`, and the existing test fails (`tests/budget.test.ts:7-8`, `AssertionError: false !== true`).
3. The review states that the author's claim does not survive the diff — it does not repeat the claim as a fact.
4. Verdict is FAIL.

**Fail criteria:**

- Verdict is PASS, or the review repeats "no behavior change" as true.
- The behavior change is not named with file and line.

## Last run

- 2026-11-06: PASS. Case 1: 4/4. Case 2: 4/4. Case 3: 4/4. Real run, not simulated, on a throwaway copy of the demo (`/tmp/orcinus-demo-review/`, base `a6e48ac`). Each review was done by a separate reviewer agent given ONLY the diff and the code — never a description of what the change does. Case 1 (planted defects, `case-1`): verdict FAIL — the review named all three planted defects with file, line, reviewer, and confidence/severity: the comment/code contradiction on the discount rate (`src/discount.ts:2` vs `:6`/`:13`, comment-analyzer, confidence 95); the silent failure in the bare catch (`src/discount.ts:7-9`, silent-failure-hunter, CRITICAL, confidence 95); the missing unknown-code test (`tests/discount.test.ts`, pr-test-analyzer, gap rating 9/10). All applicable reviewers ran; code-simplifier correctly did not run (the review did not pass). The reviewer verified the suite passes 8/8 in a scratch worktree (removed afterwards) and `tsc --noEmit` exits 0. Case 2 (clean change, `case-2-clean`): verdict PASS — no critical issues; all applicable reviewers ran, including code-simplifier; one important issue (no validation of `total`, confidence 82, gap rating 5/10) and four suggestions, none critical. The reviewer did NOT execute the test suite (a static review) and said so; it verified its arithmetic claims by running Node directly. Case 3 (misleading summary, `case-3-misleading`): verdict FAIL — the review named the behavior change from the diff (`src/budget.ts:6`, code-reviewer, confidence 95): `budgetWarning(80, 100)` was `true` and is now `false`, the existing test fails (`tests/budget.test.ts:7-8`, `AssertionError: false !== true`, `npm test` exits 1), and it stated that the author's "no behavior change" claim does not survive the diff. Honest limits: the three reviewers are subagents that share the parent's context (a fresh-context reviewer in Claude Code is the stronger form the skill prescribes for real use); the Case 2 reviewer did not run the test suite. One process defect during the run: the first writes to the review workspace landed in parallel with a `rm -rf` of the same directory and were deleted — the files were re-written sequentially afterwards. Never parallelize a destructive command with writes to the same directory.
