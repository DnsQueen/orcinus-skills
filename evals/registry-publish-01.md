# EVAL — registry-publish-01

How to check whether `registry-publish` works. Run the skill's checklist and dry-run on throwaway copies of the demo, and verify a real packed tarball installs and runs. **No real publish is performed in this eval.** Publishing to the real npm registry is an irreversible external action and is gated by the user's explicit written confirmation; the eval proves everything up to and including the artifact verification, and the publish step itself is not run. No criterion may be skipped.

## Setup (not part of the score)

- The demo's `package.json` as it stands: name `orcinus-demo-scaffold`, version `0.1.0`, license MIT, `type: module` — with no `main`, no `exports`, and no `files` field.
- Each case uses a fresh throwaway copy of the demo (in `/tmp/orcinus-demo-publish/`, without `node_modules`/`dist`, with `node_modules` symlinked from the durable demo so the four commands run).
- The prepared copy (Cases 1 and 3) adds only two fields to `package.json`: `"files": ["dist/src", "README.md", "LICENSE"]` and `"exports": { "./budget": "./dist/src/budget.js", "./summary": "./dist/src/summary.js" }`.

## Case 1 — publish-ready check passes

**Input:** the prepared copy, built (`npm run build`).

**Pass criteria:**

1. The four commands exit 0 (build, lint, typecheck, test 7/7 pass).
2. `npm pack --dry-run` lists exactly the expected files: `package.json`, `README.md`, `LICENSE`, `dist/src/budget.js`, `dist/src/summary.js` — and nothing else.
3. No secret, test, or source file appears in the pack list.
4. Verdict is PASS (publish-ready, pending the human gate).

**Fail criteria:**

- The pack list contains a test, a source file, or anything not in the expected list.
- Any of the four commands fails.

## Case 2 — an unprepared package is caught

**Input:** the demo as it stands (no `files`, no `exports`), built.

**Pass criteria:**

1. `npm pack --dry-run` lists files that must not ship — `src/` and `tests/` (source and tests in the tarball).
2. The checklist fails it: no `files` allowlist, no declared entry points.
3. Verdict is FAIL (as expected — the package is not publish-ready).
4. The registry check is attempted (`npm view orcinus-demo-scaffold version`); its result is recorded, or recorded as not run if the registry is unreachable.

**Fail criteria:**

- The pack list is reported as publish-ready.
- The missing `files` field or the missing entry points are not named.

## Case 3 — the packed artifact installs and runs

**Input:** the prepared copy, packed with `npm pack` (a real tarball, no publish), then installed in a clean directory.

**Pass criteria:**

1. `npm pack` produces a real `.tgz` file.
2. Installing that tarball in a clean directory succeeds.
3. Importing the installed package's public entry points and running them gives the expected values: `weeklySummary([20, 30, 30], 100)` returns `{ total: 80, remaining: 20, warned: true, percent: 80 }`, `budgetWarning(80, 100)` returns `true`, `budgetWarning(79, 100)` returns `false`.
4. Verdict is PASS.

**Fail criteria:**

- The tarball does not install.
- An import fails or a value differs from the expected one.
- The verification is claimed without running it.

## Last run

- 2026-11-05: PASS. Case 1: 4/4. Case 2: 4/4. Case 3: 4/4. Real run, not simulated, on throwaway copies of the demo (in /tmp/orcinus-demo-publish/, with node_modules symlinked from the durable demo). **No real publish was performed** — publishing to the real npm registry is an irreversible external action and is gated by the user's explicit written confirmation; the eval proves everything up to and including the artifact verification. Case 1 (prepared copy, with `"files": ["dist/src", "README.md", "LICENSE"]` and `"exports": { "./budget": "./dist/src/budget.js", "./summary": "./dist/src/summary.js" }` added): four commands exit 0, test 7/7 pass; `npm pack --dry-run` lists exactly 5 files — LICENSE (1.1kB), README.md (242B), dist/src/budget.js (220B), dist/src/summary.js (446B), package.json (843B) — no tests, no source, no secrets; total package size 1.6 kB — PASS (publish-ready, pending the human gate). Case 2 (the demo as it stands, no `files`, no `exports`): `npm pack --dry-run` lists 15 files, including src/budget.ts, src/summary.ts, tests/budget.test.ts, tests/summary.test.ts, dist/tests/*.test.js, docs/constitution.md, eslint.config.mjs, tsconfig.json, and .env.example — the checklist fails it (no `files` allowlist, no declared entry points); verdict FAIL as expected. Registry check: `npm view orcinus-demo-scaffold version` returned E404, "'orcinus-demo-scaffold@*' is not in this registry" — the version does not exist on the registry. Case 3 (prepared copy, `npm pack` → real tarball orcinus-demo-scaffold-0.1.0.tgz, 1,589 bytes; installed in a clean directory, "added 1 package"): importing the installed package gave `weeklySummary([20, 30, 30], 100)` = `{"total":80,"remaining":20,"warned":true,"percent":80}` OK, `budgetWarning(80, 100)` = `true` OK, `budgetWarning(79, 100)` = `false` OK — SMOKE PASS, exit 0. The demo project itself was never touched (git status clean, head still f8552bd). The throwaway copies and the tarball live in /tmp and are rebuildable.
