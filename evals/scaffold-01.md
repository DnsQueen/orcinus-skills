# EVAL — scaffold-01

How to check whether `scaffold` works. Run it on the input below, in a fresh directory, and score the result against the criteria. No criterion may be skipped.

## Input

A confirmed calibrated brief (from idea-calibrate Case 1):

- Problem: a 28-year-old office worker in Tehran overspends on food delivery and runs out of money before month-end.
- User: Sara, 28, office worker, paid monthly.
- First slice: set a weekly delivery budget and see a warning at 80%.
- Stack confirmed by the test user: TypeScript with `tsc` and Node's built-in test runner.

## Pass criteria — the project must have all of these:

1. `package.json` with scripts named exactly `build`, `lint`, `typecheck`, `test`.
2. `src/` with one minimal module that compiles.
3. `tests/` with one passing test.
4. `docs/constitution.md` with the test-integrity rule (no test weakening) written down.
5. `.gitignore` containing `node_modules/`, `dist/`, and `.env`.
6. `.env.example` with placeholder names only, no real values.
7. `README.md` naming the four commands.
8. Git initialised on `main`, with a first commit.
9. All four commands exit 0, in order: build, lint, typecheck, test.

## Fail criteria — any one of these fails the eval:

- Any of the four commands fails or is missing.
- A real secret is committed, or `.env` is tracked.
- No test file exists.
- The stack was chosen without user confirmation.
- The first commit happened while a check was failing.

## Last run

- 2026-11-05: PASS. 9/9 pass criteria, 0 fail criteria. Real run, not simulated: the skill was followed to scaffold `/tmp/orcinus-demo-scaffold` (TypeScript, stack confirmed by the test author, not a real user). Build exit 0, lint exit 0, typecheck exit 0, test exit 0 (3 tests pass). First commit `33e8aab` on `main`, 11 files, no `.env` tracked. Two real defects were found and fixed during the run: (1) `@types/node` was missing and TypeScript 6 did not auto-include it, fixed by installing `@types/node` and adding `"types": ["node"]` to `tsconfig.json`; (2) Node 24 type-stripping does not resolve a `.js` import to a `.ts` source when running a `.ts` test directly, fixed by making the test script compile first (`tsc && node --test dist/tests/*.test.js`).
