# EVAL — visual-regression-01

How to check whether `visual-regression` works. Run a real screenshot comparison on the demo page (`/tmp/orcinus-demo-page/index.html`, rebuilt from the durable demo project). No criterion may be skipped.

## Setup (not part of the score)

- Demo page: static HTML that imports the built `summary.js` and renders `weeklySummary([20, 30, 30], 100)` into `#summary`. Viewport 1280x720, animations disabled.
- Browser: Chromium Headless Shell 156.0.8078.4 via Playwright 1.64.1 (in `/tmp/pw-venv`).
- Comparison: pixel diff with PIL — the percentage of pixels that differ, and a diff image with the changed areas highlighted.

## Case 1 — no change

**Input:** the demo page, unchanged.

**Pass criteria:**

1. A baseline screenshot is captured.
2. A second capture of the same page differs by 0% of pixels.
3. Verdict is PASS.

**Fail criteria:**

- The diff is above 0% on an unchanged page (flaky capture — animations, fonts, or timing not fixed).

## Case 2 — visual change

**Input:** the demo page with a visual change: the heading text changed and a red background added to `#summary`.

**Pass criteria:**

1. The diff is above 0% of pixels (record the exact percentage).
2. A diff image is saved, and the changed areas are visible in it.
3. The difference is classified as unintended (it was not in any brief).
4. Verdict is FAIL.

**Fail criteria:**

- The diff is 0% on a changed page (the comparison missed the change).
- No diff image is saved.
- The change is reported as intended without a recorded confirmation.

## Case 3 — baseline update on confirmation

**Input:** the same changed page as Case 2, after the change is confirmed as intended (confirmation recorded here as the test author's, not a real user's).

**Pass criteria:**

1. The baseline is updated, with the confirmation recorded.
2. A re-run comparison differs by 0% of pixels.
3. Verdict is PASS.

**Fail criteria:**

- The baseline is updated without a recorded confirmation.
- The re-run still differs above 0%.

## Last run

- 2026-11-05: PASS. Case 1: 3/3. Case 2: 4/4. Case 3: 3/3. Real run, not simulated, on the demo page (viewport 1280x720, animations disabled, Chromium Headless Shell via Playwright 1.64.1, pixel diff with PIL). Case 1 (unchanged page): diff 0.00% — PASS. Case 2 (heading text changed, red background added to #summary): diff 2.70% (24,872 of 921,600 pixels), diff image saved (10,406 bytes, 1280x720 PNG), classified as unintended (not in any brief) — FAIL as expected. Case 3 (baseline updated after a recorded confirmation by the test author, not a real user): re-run diff 0.00% — PASS. The demo page was restored to its original afterwards. One real finding during the run: `pkill -f "http.server 8123"` matched the shell's own command line and killed the exec session (SIGTERM) — the run was recovered by killing the lingering server by port instead (fuser). The with_server.py helper's stop behaviour (leaves the child running) is already recorded in the webapp-testing eval.
