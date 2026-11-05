# EVAL — mutation-testing-python-01

How to check whether `mutation-testing-python` works. Run mutmut (boxed/mutmut, BSD-3-Clause) on a small Python demo that mirrors the TypeScript demo's domain (weekly delivery budget) with pytest tests carrying literal expected values. The Python demo lives in `/tmp/orcinus-demo-py/` (a venv with mutmut 3.8.1 and pytest, in `/tmp/mutmut-venv/`); the TypeScript demo itself is never touched. No criterion may be skipped.

## Setup (not part of the score)

- The Python demo: `src/demo_budget/budget.py` — `budget_warning(spent, budget)` (warns at ≥80% of the budget, raises `ValueError("budget must be greater than 0")` on a non-positive budget) and `weekly_summary(spending, budget)` (returns `{total, remaining, warned, percent}`, percent rounded). Tests in `tests/test_budget.py` with literal expected values, including `[20, 30, 30]`/100 → `{80, 20, true, 80}` and `[]`/100 → `{0, 100, false, 0}`.
- Config (`setup.cfg`, `[mutmut]`): `source_paths = src/demo_budget/budget.py`, `pytest_add_cli_args_test_selection = tests`.

## Case 1 — baseline green, full run, score with exact numbers

**Input:** `pytest tests -q`, then `mutmut run`, then `mutmut export-cicd-stats`.

**Pass criteria:**

1. The baseline is green (all tests pass).
2. mutmut runs to completion and `export-cicd-stats` reports the exact numbers: total 34, killed 34, survived 0, timeout 0, suspicious 0, skipped 0, no_tests 0 — score 100.00%.
3. At least one killed mutant is named with file, line, and change (for example `x_budget_warning__mutmut_1`: `budget <= 0` → `budget < 0`, killed).
4. Verdict is PASS.

**Fail criteria:**

- The baseline is not green.
- mutmut does not run, or the numbers are not recorded.
- No killed mutant is named.

## Case 2 — the gate can fail: weak tests let mutants survive

**Input:** the first run, before the tests were strengthened (8 tests, using `pytest.raises(ValueError, match=...)` and no small-budget case), then the strengthened tests (10 tests) and a re-run.

**Pass criteria:**

1. The first run reports 30 killed and 4 survived, with all four named: `x_budget_warning__mutmut_2` and `x_weekly_summary__mutmut_2` (`budget <= 0` → `budget <= 1` — no test exercised a budget of 1), and `x_budget_warning__mutmut_4` and `x_weekly_summary__mutmut_4` (the error message mutated to `XXbudget must be greater than 0XX` — `match` is a substring search, so it still matched).
2. The tests are strengthened (not weakened): two new tests for small positive budgets (`budget_warning(1, 1)`, `weekly_summary([1], 1)`), and the message assertions changed to exact equality (`str(excinfo.value) == "budget must be greater than 0"`).
3. The re-run kills all 34 mutants (0 survived).
4. Verdict is PASS.

**Fail criteria:**

- The first run's survivors are not named, or the fix weakens a test.
- The re-run still has survivors.

## Case 3 — the run is honest and reproducible

**Input:** a second `mutmut run` on the strengthened suite, and the config as written.

**Pass criteria:**

1. The second run reports the same numbers: total 34, killed 34, survived 0, timeout 0, suspicious 0.
2. The run prints no deprecation warnings (the config uses the current keys `source_paths` and `pytest_add_cli_args_test_selection`, not the deprecated `paths_to_mutate` / `tests_dir`, and no `test_command` — mutmut 3.x ignores it).
3. Verdict is PASS.

**Fail criteria:**

- The numbers differ between runs without a code or test change.
- A deprecation warning appears, or a timeout is hidden in the score.

## Last run

- 2026-11-06: PASS. Case 1: 4/4. Case 2: 4/4. Case 3: 3/3. Real run, not simulated, on a small Python demo that mirrors the TypeScript demo's domain (`/tmp/orcinus-demo-py/`, mutmut 3.8.1 and pytest in `/tmp/mutmut-venv/`). Case 1 (baseline + full run): pytest 10/10 pass; `mutmut export-cicd-stats` reports total 34, killed 34, survived 0, timeout 0, suspicious 0, skipped 0, no_tests 0 — score 100.00%; killed mutants named, including `x_budget_warning__mutmut_1` (`budget <= 0` → `budget < 0`) and `x_weekly_summary__mutmut_1` (same change). Case 2 (the gate can fail): the first run, with 8 tests, reported 30 killed and 4 survived, all four named — `x_budget_warning__mutmut_2` and `x_weekly_summary__mutmut_2` (`budget <= 0` → `budget <= 1`, no test exercised a budget of 1) and `x_budget_warning__mutmut_4` and `x_weekly_summary__mutmut_4` (the error message mutated to `XXbudget must be greater than 0XX`, and `pytest.raises(..., match=...)` still matched because `match` is a substring search). The tests were strengthened, not weakened: two new tests for small positive budgets (`budget_warning(1, 1)`, `weekly_summary([1], 1)`) and exact message assertions (`str(excinfo.value) == "budget must be greater than 0"`); the re-run killed all 34 mutants. Case 3 (honest and reproducible): a second `mutmut run` reports the same numbers (34 killed, 0 survived, 0 timeout, 0 suspicious) and prints no deprecation warnings. Three real defects found during the run: (1) mutmut's trampoline rejects a module imported as `src.budget` (`Module name starts with 'src.', which is invalid`) — the demo was restructured into a real package (`src/demo_budget/budget.py`, imported as `demo_budget.budget`); (2) the first `setup.cfg` used the deprecated keys `paths_to_mutate` and `tests_dir` and set `test_command`, which mutmut 3.x silently ignores — the config now uses the current keys (`source_paths`, `pytest_add_cli_args_test_selection`) and no `test_command`; (3) `mutmut junit` does not exist in mutmut 3.x (it was a 2.x command) — the exact numbers come from `mutmut export-cicd-stats`, not from a junit report. The TypeScript demo itself was never touched. The Python demo and the venv live in /tmp and are rebuildable.
