# EVAL — performance-optimization-01

How to check whether `performance-optimization` works. Apply the skill's own workflow (MEASURE → IDENTIFY → FIX → VERIFY → GUARD) to the demo page and the demo project, with real timings. No criterion may be skipped.

## Budgets (fixed before measuring, per the skill)

- Demo page load (navigation to `#summary` rendered, viewport 1280x720, Chromium Headless Shell): **under 2.5s** (the skill's LCP "good" threshold).
- Demo `npm test` (full suite, 7 tests): **under 10s** wall-clock.

Measurements are repeated 3 times; the mean is compared against the budget, and the delta against run-to-run variance (per the skill's step 4: a gain inside the variance is not a gain).

## Case 1 — measure the baseline

**Input:** the demo page and the demo project as they stand.

**Pass criteria:**

1. Page load is measured 3 times and `npm test` is timed 3 times; all numbers are recorded.
2. Page load mean is under 2.5s and `npm test` mean is under 10s.
3. Verdict is PASS (within budget).

**Fail criteria:**

- A number is reported without measuring it.
- The budget is changed after measuring to make the result pass.

## Case 2 — regression is detected

**Input:** a throwaway copy of the demo page with a deliberate 3-second delay before rendering (the page's script waits 3s, then renders). The demo project itself is untouched.

**Pass criteria:**

1. The slow page is measured and its load mean is over 2.5s.
2. The skill's procedure flags it as a regression (over budget).
3. Verdict is FAIL (as expected — the check can fail).
4. The throwaway copy is deleted afterwards.

**Fail criteria:**

- The slow page is reported as within budget.
- The slowdown is reported as "no measurable change".

## Case 3 — revert is verified

**Input:** the slowdown reverted (the original page restored), per the skill's step 4 rule "worse = revert".

**Pass criteria:**

1. The page is re-measured 3 times and the load mean is under 2.5s again.
2. The before/after numbers are recorded (slow → reverted).
3. Verdict is PASS.

**Fail criteria:**

- The reverted page is not re-measured.
- The revert is claimed without numbers.

## Last run

- 2026-11-05: PASS. Case 1: 3/3. Case 2: 4/4. Case 3: 3/3. Real run, not simulated, on the demo page and the demo project (Chromium Headless Shell via Playwright 1.64.1; page load = navigation until #summary renders, viewport 1280x720). Case 1 (baseline): page load 0.135s / 0.095s / 0.094s, mean 0.108s, under the 2.5s budget; `npm test` 4829ms / 4797ms / 4677ms, mean ~4768ms, under the 10s budget — PASS. Case 2 (throwaway copy with a deliberate 3s delay before rendering; demo project untouched): page load 3.043s / 3.036s / 3.039s, mean 3.040s, over the 2.5s budget — flagged as a regression, FAIL as expected; the throwaway copy was deleted afterwards. Case 3 (slowdown reverted, original page confirmed with no setTimeout): page load 0.158s / 0.109s / 0.099s, mean 0.122s, under budget again — PASS, with before/after numbers recorded (3.040s → 0.122s). No budget was changed after measuring. One real finding during the run: when the measurement script was run through the webapp-testing `with_server.py` helper, its stdout did not appear (only blank lines); run directly against a server started by hand, the same script printed its numbers — so the helper's output handling is unreliable for this use, and the measurements above come from the direct runs. The demo page was left unchanged (original, no setTimeout).
