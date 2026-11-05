# EVAL — api-consumption-01

How to check whether `frontend-data-contracts` works. Build a typed API client per the skill (one client as the only fetch boundary, parse-don't-validate with Zod, one normalized `ApiError`, branded IDs) against the demo API — the same API `api-and-interface-design` designed — and prove it against a live server. The client lives in a throwaway workspace (`/tmp/orcinus-demo-api-client/`, its own package.json with TypeScript and Zod); the server is the throwaway demo API in `/tmp/orcinus-demo-api/` (Node, no dependencies, using the demo's built `summary.js`). The demo project itself is never touched. No criterion may be skipped.

## Setup (not part of the score)

- The demo API: `GET /api/v1/weekly-summary?spending=20,30,30&budget=100` → 200 `{"total":80,"remaining":20,"warned":true,"percent":80}`; `budget=0` → 422 `{"error":{"code":"VALIDATION_ERROR","message":"budget must be greater than 0 and spending must be numbers"}}`. `GET /api/v1/spending` → 200 `{"data":[3 items],"pagination":{"page":1,"pageSize":20,"totalItems":3,"totalPages":1}}`. `POST /api/v1/spending` with an invalid body → 422 with per-field errors (`fields: {"amount":["must be a positive number"]}`). An unknown route → 404 with the same error shape. A test hook, `?variant=broken` on the summary endpoint, returns the contract drift: `{"total":"80","left":20,"warned":true,"percent":80}` (total as a string, `remaining` renamed to `left`).
- The client: `src/api-client/` (client, error, types, barrel) is the only place that calls `fetch`. Domain types and Zod schemas live in `src/spending.ts`. `SpendingId` is a branded number, `WeekId` a branded string.

## Case 1 — one client is the only fetch boundary

**Input:** the eval workspace, checked by grep, then the client run live against the demo API.

**Pass criteria:**

1. No `fetch(`/`axios`/`XMLHttpRequest` appears outside `src/api-client/`.
2. `getWeeklySummary` returns the typed value `{total: 80, remaining: 20, warned: true, percent: 80}`.
3. `listSpending` returns 3 typed rows and the pagination `{page: 1, pageSize: 20, totalItems: 3, totalPages: 1}`.
4. Verdict is PASS.

**Fail criteria:**

- A `fetch` call exists outside the client.
- Either call returns an untyped value or the wrong numbers.

## Case 2 — parse, don't validate: contract drift is caught at the boundary

**Input:** the client run against the `?variant=broken` response, and against the valid response.

**Pass criteria:**

1. The valid response parses to the typed value (same numbers as Case 1).
2. The broken response (`total` as a string, `remaining` renamed to `left`) is rejected at the boundary: the client throws a typed `ApiError` with code `CONTRACT_DRIFT`, and no bad value reaches the caller.
3. Verdict is PASS.

**Fail criteria:**

- The broken response parses successfully, or reaches the caller as a value.
- The error is untyped (a raw `Error` or a raw response body).

## Case 3 — one error type, and branded IDs

**Input:** the client run against the 422 per-field error, against a stopped server, and a TypeScript file that misuses a branded ID (compiled with `tsc --noEmit`).

**Pass criteria:**

1. The 422 returns a typed `ApiError` with `code: "VALIDATION_ERROR"`, `status: 422`, and `fields: {"amount":["must be a positive number"]}`.
2. With the server stopped, the same call throws an `ApiError` with code `NETWORK_ERROR` — the same shape, not a different error type.
3. `tsc --noEmit` fails on the misuse file (a plain number passed where a `SpendingId` is expected, and a `WeekId` passed where a `SpendingId` is expected), naming the type error.
4. Verdict is PASS.

**Fail criteria:**

- Any failure mode produces a different error shape.
- The misuse file compiles.

## Last run

- 2026-11-06: PASS. Case 1: 3/3. Case 2: 1/1. Case 3: 3/3. Real run, not simulated, against a live demo API server (Node, no dependencies, in /tmp/orcinus-demo-api/) with a typed client built per the skill (TypeScript + Zod, in /tmp/orcinus-demo-api-client/). Case 1 (one boundary): no `fetch`/`axios`/`XMLHttpRequest` outside `src/api-client/`; `getWeeklySummary` returns the typed value `{"total":80,"remaining":20,"warned":true,"percent":80}`; `listSpending` returns 3 typed rows `[20,30,30]` and the pagination `{"page":1,"pageSize":20,"totalItems":3,"totalPages":1}`. Case 2 (parse, don't validate): the `?variant=broken` response (`total` as a string, `remaining` renamed to `left`) is rejected at the boundary with a typed `ApiError{code: CONTRACT_DRIFT, status: 200}` — no bad value reaches the caller. Case 3 (one error, branded IDs): the 422 returns `ApiError{code: VALIDATION_ERROR, status: 422, fields: {"amount":["must be a positive number"]}}`; with the server stopped the same call throws `ApiError{code: NETWORK_ERROR, status: 0, message: "network failure"}` — the same shape, not a different error type; `tsc --noEmit` fails on the misuse file with exactly two errors, both TS2345 (a plain number is not a `SpendingId`; a `WeekId` is not a `SpendingId`). Two real findings during the run: (1) the first draft of the list parse was wrong — the client unwraps `{data}` before parsing, so the list schema (which expects `{data, pagination}`) would have failed on the unwrapped array; the unwrap rule was corrected to unwrap only a bare `{data}` envelope, and the list schema parses the whole body. That correction is itself the envelope finding: the demo API returns three shapes (bare payload, `{data, pagination}`, `{data}`), and the client has to carry that inconsistency because the API has no single envelope. Aligning the API to one envelope is a breaking change under `breaking-change` and belongs in a new API version. (2) The branded-ID check needs `tsc --ignoreConfig --types node` — without `--ignoreConfig` tsc refuses to compile a single file while a tsconfig exists (TS5112), and without `--types node` it reports a spurious `process` error from the client. The demo project itself was never touched. The server, the client workspace, and the zod dependency live in /tmp and are rebuildable.
