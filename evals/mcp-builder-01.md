# EVAL — mcp-builder-01

How to check whether the `mcp-builder` skill works. Follow its 4 phases (Research and Planning → Implementation → Review and Test → Evaluations) to build a TypeScript MCP server (SDK v2, `@modelcontextprotocol/server`) for the demo's domain — the weekly delivery budget — in a throwaway workspace (`/tmp/orcinus-demo-mcp/`). The server exposes two tools, both read-only: `budget_weekly_summary` (wraps `weeklySummary`) and `budget_warning` (wraps `budgetWarning`), with Zod input schemas, `outputSchema` + `structuredContent`, and the four annotations (`readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`, `openWorldHint: false`). No criterion may be skipped.

## Case 1 — the server builds and passes its self-check

**Input:** the server source (`src/index.ts`, `src/budget.ts`, `src/summary.ts`, `tsconfig.json`, `package.json`), built with `npm run build` and checked with the self-check script (`scripts/smoke.mjs`, adapted from the skill's v2 guide: start the built server over stdio with the client SDK, list tools, call them, assert).

**Pass criteria:**

1. `npm run build` (`tsc`) exits 0 and produces `dist/index.js`.
2. The self-check lists exactly the two tools (`budget_weekly_summary`, `budget_warning`).
3. `budget_weekly_summary` with `[20, 30, 30]`/100 returns `structuredContent` `{total: 80, remaining: 20, warned: true, percent: 80}`.
4. `budget_warning` returns `true` for 80/100 and `false` for 79/100.
5. `budget_weekly_summary` with `budget: 0` returns `isError: true` with an actionable message.
6. The self-check prints `SMOKE PASS` and exits 0.

**Fail criteria:**

- The build fails, a tool is missing, or any assertion fails.
- The self-check exits 0 while a check failed.

## Case 2 — the 10-question evaluation passes

**Input:** 10 read-only questions (`scripts/eval.mjs`), each with a single verifiable answer checked by exact string comparison, run against the built server over stdio. The questions follow the skill's Phase 4 rules: independent, read-only, realistic, verifiable, stable.

**Pass criteria:**

1. All 10 questions pass (10/10), each with the exact expected text (e.g. Q1 `[20, 30, 30]`/100 → `total: 80, remaining: 20, warned: true, percent: 80`; Q10 `[1]`/3 → `total: 1, remaining: 2, warned: false, percent: 33`).
2. The eval exits 0.

**Fail criteria:**

- Any question's answer differs from its expected text, or the eval exits non-zero.

## Case 3 — the eval gate can fail

**Input:** the same eval script with one expected answer deliberately changed (Q1's `percent: 80` → `percent: 81`), run in a throwaway copy.

**Pass criteria:**

1. Q1 fails and the eval reports 9/10 passed.
2. The eval exits 1.
3. The other 9 questions still pass (the failure is isolated).

**Fail criteria:**

- The changed answer passes, or the eval exits 0 with a failed question.
- A gate that cannot fail is not a gate.

## Last run

- 2026-11-06: PASS. Case 1: 6/6. Case 2: 2/2. Case 3: 3/3. Real run, not simulated, in `/tmp/orcinus-demo-mcp/` with the MCP SDK v2 (`@modelcontextprotocol/server` ^2.4.0, `@modelcontextprotocol/client` ^2.4.0, `zod` ^4.6.7, `typescript` ^6.0.3). Case 1: `npm run build` exits 0, `dist/index.js` produced; the self-check lists exactly the two tools, the summary returns `{total: 80, remaining: 20, warned: true, percent: 80}`, the warnings are `true` for 80/100 and `false` for 79/100, `budget: 0` returns `isError: true`, and it prints `SMOKE PASS` with exit 0. Case 2: 10/10 questions passed with the exact expected texts, exit 0. Case 3: the control run reported 9/10 with Q1 failing and exited 1; the other 9 passed. Two real defects found during the run: (1) the first `npm install` filled the 512 MB `/tmp` (100% full) and failed with `nospc`; old eval workspaces were removed (all recorded in their eval files) and the install was redone. (2) The same disk-full install left `node_modules/typescript` and `node_modules/@modelcontextprotocol/server` with corrupt `package.json` files (`ERR_INVALID_PACKAGE_CONFIG`); `tsc` silently produced nothing and the typecheck failed with `TS2307`. Fixed by deleting `node_modules` + `package-lock.json` and reinstalling cleanly — after that, `tsc --version` reports 6.0.3 and the typecheck is clean. One finding about the design, not a defect: Zod validates the input schema before the tool handler runs, so `budget: 0` is rejected with the schema's message (`Invalid arguments for tool budget_weekly_summary: budget: Too small: expected number to be >0`), not the domain error (`budget must be greater than 0`) — the domain error is unreachable through the tool. The smoke assertion was corrected to expect the Zod message. Honest limits: only the stdio transport was exercised (no Streamable HTTP, no auth); the bundled `scripts/evaluation.py` was not run (it needs an Anthropic API key, which was not available here) — the eval used the repo's own pattern instead; the MCP Inspector was not used (no browser in this step); only the demo's two-function domain was exposed as tools.
