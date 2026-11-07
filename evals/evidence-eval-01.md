# EVAL — evidence-eval-01

How to check whether the Waza evidence/eval setup works. The Waza CLI is the official release binary (v0.40.0), installed from the release page with its checksum verified — it is NOT in this repo (the binary is ~200 MB). The runnable suite is `evals/waza-orcinus-verify/` (eval.yaml + tasks + fixtures), a graded eval for the flagship `orcinus-verify` skill. Run every case with the mock executor unless stated otherwise. No criterion may be skipped.

## Case 1 — the shipped suite runs and scores

**Input:** `evals/waza-orcinus-verify/eval.yaml` (2 tasks: `verify-pass`, `verify-fail`; executor `mock`; global grader `output_nonempty`).

**Pass criteria:**

1. `waza run eval.yaml` exits 0.
2. Both tasks pass: total 2, succeeded 2, failed 0, success rate 100.0%, aggregate score 1.00.
3. The results JSON is well-formed: `summary` with `total_tests`, `succeeded`, `failed`, `success_rate`, `aggregate_score`, and per-task `validations` with a score and feedback each.
4. The fixture file the tasks reference (`fixtures/summary.ts`) exists, so the run produces no "failed to load resource file" warning.

**Fail criteria:**

- The run exits non-zero, a task fails, or the results JSON is missing a field above.
- A resource-file warning appears.

## Case 2 — the gate can fail

**Input:** the same suite plus a control task (`verify-gate-can-fail`) whose `output_contains` string is deliberately absent from any mock response (`zz-no-such-verdict-zz`). The control task lives in the eval workspace only — it is NOT shipped in `evals/waza-orcinus-verify/`, so the shipped suite stays green.

Note (round 7, F-10, 2026-11-08): a negative control is now shipped as a separate suite, `evals/waza-orcinus-verify/control/` (a `code` grader asserting FAIL, whose prompt, name and description omit the word), and CI runs it separately, asserting the failure — the shipped main suite still stays green. Case 2 as written above used the workspace-only `zz-no-such-verdict-zz` control for the 2026-11-06 run; a future run of this case against the shipped control expects 1 test, 0 succeeded, 1 failed, exit 1, instead of the 3-test counts below.

**Pass criteria:**

1. The control task fails with `matched 0/1 required strings; missing: [zz-no-such-verdict-zz]`.
2. The run reports 3 tests, 2 succeeded, 1 failed, success rate 66.7%, aggregate score 0.89.
3. `waza run` exits 1 (checked without a pipe — a pipe hides the exit code).
4. The other two tasks still pass (the failure is isolated to the control task).

**Fail criteria:**

- The control task passes, or the run exits 0 with a failed test.
- A gate that cannot fail is not a gate.

## Case 3 — results can be compared

**Input:** the results JSON from Case 1 (2/2, aggregate 1.00) and from Case 2 (2/3, aggregate 0.89).

**Pass criteria:**

1. `waza compare <results-1> <results-2>` exits 0 and prints an aggregate delta table: Score 1.0000 → 0.8889 (delta -0.1111), Success Rate 100.0% → 66.7% (delta -33.3%).
2. The per-task deltas list both shared tasks at +0.0000 and the control task at 0.6667.

**Fail criteria:**

- `waza compare` fails, or the deltas do not match the two runs.

## Last run

- 2026-11-06: PASS. Case 1: 4/4. Case 2: 4/4. Case 3: 2/2. Real run, not simulated, with the official v0.40.0 release binary (waza-linux-amd64, 204,572,622 bytes, SHA256 `d09117a3c631f44a00a6c362462c951aed83c87751e8c25f39916a77d1013802` verified against the release checksums.txt; `waza version 0.40.0`). Case 1: the shipped suite ran from the repo — 2/2 succeeded, success rate 100.0%, aggregate score 1.00, duration 160ms, exit 0, results JSON well-formed (schemaVersion 1.8, per-task validations with scores and feedback). Case 2: the control task failed exactly as specified (`matched 0/1 required strings; missing: [zz-no-such-verdict-zz]`), the run reported 3 tests / 2 succeeded / 1 failed / success rate 0.667 / aggregate 0.889 / duration 247ms, and `waza run` exited 1. Case 3: `waza compare` printed Score 1.0000 → 0.8889 (-0.1111) and Success Rate 100.0% → 66.7% (-33.3%), with both shared tasks at +0.0000 and the control task at 0.6667. One defect found during the run: the first task draft used `expected: "Verdict PASS..."` (a string) and the binary rejected it (`cannot unmarshal !!str into models.TaskExpectation`) — the correct format is `expected: {output_contains: [...], outcomes: [...], behavior: {...}}` with `inputs.prompt`; the shipped suite uses it, and the same defect exists in the upstream skill's inline example (recorded in the skill's ATTRIBUTION.md). Honest limits: the mock executor returns `Mock response for: <prompt>` — it echoes the prompt, and `output_contains` matching is case-insensitive, so a mock task passes when the prompt itself contains the expected string. A mock run proves the harness (parsing, execution, scoring, results JSON, the gate, comparison) — it does NOT prove the skill being evaluated works. Real grading needs a real executor (`copilot-sdk`) and a real agent run, which was not available here (no Copilot CLI/auth). The first binary download failed because `/tmp` is a 512 MB tmpfs and was 100% full at 132 MB of 204 MB; the binary was downloaded to the workspace instead, and the 204 MB temp dir was removed before committing — the binary is not in the repo.
