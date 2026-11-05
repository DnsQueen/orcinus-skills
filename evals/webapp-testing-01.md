# EVAL — webapp-testing-01

How to check whether `webapp-testing` works. Run a real E2E check on a minimal demo page that renders the demo project's weekly summary, using the skill's own procedure (read the HTML, identify selectors, run the Playwright script through `with_server.py`). No criterion may be skipped.

## Setup (not part of the score)

- Demo project: `~/workspace/orcinus-demo-scaffold` (rebuilt 2026-11-05 after a VM restart wiped `/tmp`; four commands exit 0, 7/7 tests pass).
- Demo page: `/tmp/orcinus-demo-page/index.html` — static HTML that imports the built `summary.js` and renders `weeklySummary([20, 30, 30], 100)` into `#summary`. Expected rendered text: `total: 80, remaining: 20, warned: true, percent: 80`.
- Browser: Chromium Headless Shell 156.0.8078.4 via Playwright 1.64.1 (installed in `/tmp/pw-venv` for this eval; the system Python is externally managed, so the install used a venv, not `--break-system-packages`).

## Pass criteria

1. `with_server.py --help` runs first, as the skill instructs, and the server is managed by the helper (not started by hand in the background).
2. The Playwright script navigates to the page, waits for networkidle, and reads `#summary`.
3. The rendered text is exactly `total: 80, remaining: 20, warned: true, percent: 80`.
4. A screenshot is captured to disk.
5. Console logs and page errors are collected; none are errors.
6. The script exits 0 and prints PASS.

## Fail criteria — any one of these fails the eval:

- The rendered text differs from the expected value.
- A console error or page error is present and unreported.
- No screenshot is captured.
- The browser step is skipped or reported as passed when it did not run.

## Last run

- 2026-11-05: PASS, 6/6 pass criteria, 0 fail criteria. Real run, not simulated: a minimal demo page (/tmp/orcinus-demo-page/index.html) rendering the demo project's weekly summary was checked in a real Chromium Headless Shell 156.0.8078.4 via Playwright 1.64.1, using the skill's own procedure — `with_server.py --help` ran first, the helper managed the server, the script navigated, waited for networkidle, and read `#summary`. Rendered text was exactly `total: 80, remaining: 20, warned: true, percent: 80`; console errors and page errors were both empty; a screenshot was captured (13,810 bytes, 1280x720 PNG); the script printed PASS and exited 0. Two real findings during the run: (1) a VM restart had wiped `/tmp`, so the demo project was gone — it was rebuilt from the scaffold + build skills into a durable location `~/workspace/orcinus-demo-scaffold` (four commands exit 0, 7/7 tests pass, 2 commits) instead of `/tmp`; (2) the upstream helper `with_server.py` reports "All servers stopped" but leaves the `http.server` child running — a lingering server (first PID 3318, then 3624) had to be killed by hand, and one intermediate run failed with ERR_EMPTY_RESPONSE because of it. The skill is used as-is, but this helper leak is recorded here as a known limitation.
