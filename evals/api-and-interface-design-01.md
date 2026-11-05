# EVAL — api-and-interface-design-01

How to check whether `api-and-interface-design` works. Design a REST API for the demo project's domain (weekly delivery budget) following the skill, then verify it against the skill's own verification checklist — and run it live. No criterion may be skipped.

## The design (Case 1)

Contract-first, versioned, plural nouns, camelCase, structured errors, validation at the boundary, pagination on list endpoints:

- `GET /api/v1/weekly-summary?spending=20,30,30&budget=100` → 200 `{ total, remaining, warned, percent }`
- `GET /api/v1/spending?page=1&pageSize=20` → 200 `{ data: [...], pagination: { page, pageSize, totalItems, totalPages } }`
- Errors: one structured shape everywhere — `{ error: { code, message } }`; invalid input → 422 `VALIDATION_ERROR`; unknown route → 404 `NOT_FOUND`.

## Case 1 — design and live check

**Input:** the design above, implemented as a minimal live server (Node, no dependencies, using the demo's built `summary.js`).

**Pass criteria:**

1. Every endpoint has a typed input and output (the design states both).
2. The live server returns 200 with the exact body `{ total: 80, remaining: 20, warned: true, percent: 80 }` for `spending=20,30,30&budget=100`.
3. The live server returns 422 with the structured shape `{ error: { code: "VALIDATION_ERROR", message } }` for `budget=0`.
4. The list endpoint returns the paginated shape (`data` + `pagination` with `page`, `pageSize`, `totalItems`, `totalPages`).
5. The server is stopped afterwards; nothing is committed to the demo project.

**Fail criteria:**

- A live response does not match the designed contract.
- An error response uses a different shape than the success/error format.
- A list endpoint returns a bare array with no pagination.

## Case 2 — breaking change is flagged

**Input:** a proposed change to the same `/v1` API: rename `remaining` to `left` and remove `percent`, with no new version.

**Pass criteria:**

1. The skill's red flags catch it: breaking changes to existing fields (a rename and a removal).
2. Verdict is FAIL (the design is rejected as proposed).
3. The correct alternative is named: add the new field as additive and optional, or ship a new version.

**Fail criteria:**

- The change is accepted as-is under the same version.
- The change is called "backward compatible".

## Case 3 — list without pagination is flagged

**Input:** a proposed list endpoint `GET /api/v1/spending` that returns a bare array, with no `page`, `pageSize`, or `pagination`.

**Pass criteria:**

1. The skill's verification checklist fails it (list endpoints support pagination).
2. Verdict is FAIL (the design is rejected as proposed).
3. After adding pagination, the live server returns the paginated shape (verified in Case 1).

**Fail criteria:**

- The bare-array design is accepted.
- Pagination is called "not needed for now".

## Last run

- 2026-11-05: PASS. Case 1: 5/5. Case 2: 3/3. Case 3: 3/3. Real run, not simulated: the design was implemented as a minimal live server (Node, no dependencies, using the demo's built `summary.js`) and checked with curl. Case 1: valid request `GET /api/v1/weekly-summary?spending=20,30,30&budget=100` returned 200 with the exact body `{"total":80,"remaining":20,"warned":true,"percent":80}`; `budget=0` returned 422 with the structured shape `{"error":{"code":"VALIDATION_ERROR","message":"budget must be greater than 0 and spending must be numbers"}}`; the list endpoint returned 200 with `data` (3 items) + `pagination` `{page:1, pageSize:20, totalItems:3, totalPages:1}`; an unknown route returned 404 with the same error shape `{"error":{"code":"NOT_FOUND","message":"route not found"}}` — one error format everywhere. The server was stopped afterwards and the demo project is untouched (git status clean, head still f8552bd). Case 2: the proposed rename `remaining` → `left` plus removing `percent` under the same `/v1` was caught by the skill's red flag "Breaking changes to existing fields (type changes, removals)" and its principle "Prefer addition over modification" — verdict FAIL, design rejected; the correct alternative was named (add `left` as an additive optional field, or ship a new version). Case 3: the proposed bare-array list endpoint was caught by the skill's verification checklist ("List endpoints support pagination") and its red flag "List endpoints without pagination" — verdict FAIL, design rejected; after adding pagination, the live check in Case 1 returned the paginated shape. The eval server lives in /tmp/orcinus-demo-api/ (ephemeral, rebuildable) and was not committed anywhere.
