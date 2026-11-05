# EVAL — state-01

How to check whether `frontend-architecture` (the state split) and `frontend-optimistic-mutations` (the write path) work. The skills are React/React Native, so the eval uses a throwaway React-shaped example app in TypeScript (`/tmp/orcinus-demo-state/`) with a minimal query/cache layer — no framework is installed, the modules mirror the skill's shapes — plus the real demo page in a real browser. The demo project itself is never touched. No criterion may be skipped.

## Setup (not part of the score)

- Example app (throwaway, in `/tmp/orcinus-demo-state/`): the demo's domain (weekly delivery spending). `queryClient.ts` is the minimal cache (cancelQueries / getQueryData / setQueryData / invalidateQueries). `spendingStore.ts` holds only UI state (the selected week filter, whether the add dialog is open). `SpendingPage.ts` reads server data from a data hook and UI state from the store selector. `addSpending.ts` is the mutation. `check_state.py` is a small checker that implements the skills' rules mechanically: a store file must not import the API client or hold fetched entities; a component must not call the network client directly; a mutation must contain all five beats (cancel, snapshot, patch, rollback, invalidate); an idempotency key must be created once at form init, not per attempt.
- Demo page (real, in `/tmp/orcinus-demo-page/`): renders the demo library's `weeklySummary([20, 30, 30], 100)` — that summary is server state, computed from the domain — and a locale toggle (en/fa) — that toggle is UI state, local and ephemeral. A button adds a spending of 50 to the underlying data.

## Case 1 — the split: server state and UI state never overlap

**Input:** `check_state.py` on the example app, then on a variant where the fetched spending list is mirrored into the store.

**Pass criteria:**

1. The correct app passes every check: the store holds only UI state, no component calls the network client, server data is read from a data hook.
2. The mirrored variant fails, and the checker names the rule (server state mirrored into a client store).
3. Verdict is PASS.

**Fail criteria:**

- The correct app fails any check.
- The mirrored variant passes, or fails without naming the rule.

## Case 2 — the write path: the five-beat lifecycle and the idempotency key

**Input:** `check_state.py` on the correct mutation, then on two broken variants: one with no rollback, and one whose idempotency key is generated per attempt (inside the submit handler) instead of once at form init.

**Pass criteria:**

1. The correct mutation passes: all five beats present (cancel, snapshot, patch, rollback verbatim, invalidate) and the key created once at form init.
2. The no-rollback variant fails, naming the missing beat.
3. The per-attempt-key variant fails, naming the idempotency rule.
4. Verdict is PASS.

**Fail criteria:**

- The correct mutation fails any check.
- Either broken variant passes, or fails without naming the rule.

## Case 3 — the demo page: mirrored state goes stale, the split stays fresh

**Input:** the real demo page in a real browser (Chromium Headless Shell via Playwright), in two variants: the correct page (the summary is re-rendered from the library on every data change; the locale is local UI state) and a mirrored variant (the summary is copied into a local store at load and rendered from it).

**Pass criteria:**

1. Before the change, both pages render `total: 80, remaining: 20, warned: true, percent: 80`.
2. After clicking "add spending 50", the correct page renders `total: 130, remaining: -30, warned: true, percent: 130`.
3. After the same click, the mirrored variant still renders `total: 80` — stale — proving the failure the rule exists to prevent.
4. Switching the locale on the correct page changes the labels (en ↔ fa) without changing the numbers.
5. Verdict is PASS.

**Fail criteria:**

- The correct page shows stale numbers after the change.
- The mirrored variant shows fresh numbers (the demonstration fails).
- The locale switch changes the numbers.

## Last run

- 2026-11-06: PASS. Case 1: 2/2. Case 2: 3/3. Case 3: 4/4. Real run, not simulated. Case 1 (the split, on a throwaway React-shaped example app in /tmp/orcinus-demo-state/ with a minimal query/cache layer): the correct app passes every check — the store holds only UI state (the selected week filter, whether the add dialog is open), no component calls the network client, server data is read from a data hook. The variant that mirrors the fetched spending list into the store fails with the rule named ("S1: spendingStore.ts holds server state — a store imports the API client — server state is never mirrored into a client store"). Case 2 (the write path): the correct mutation passes — all five beats present (cancel, snapshot, patch, rollback verbatim, invalidate) and the idempotency key created once at form init. The no-rollback variant fails naming the missing beat ("S3: addSpending.ts is missing the 'rollback' beat"), and the per-attempt-key variant fails naming the idempotency rule ("S4: addSpending.ts generates the idempotency key per attempt"). Case 3 (the real demo page in a real browser, Chromium Headless Shell via Playwright 1.64.1): before the change both pages render "total: 80, remaining: 20, warned: true, percent: 80"; after clicking "Add spending 50" the correct page renders "total: 130, remaining: -30, warned: true, percent: 130" while the mirrored variant still renders "total: 80" — stale, proving the failure the rule exists to prevent; switching the locale on the correct page changes the labels to Persian ("مجموع: 130, باقی‌مانده: -30, هشدار: true, درصد: 130") without changing the numbers. Two real defects found during the run: (1) the first variant build copied the correct tree INTO the variant directories (`mirrored/correct/...`) instead of into them, so the checker ran on empty directories and passed vacuously — the checker now fails when the expected files are missing ("no store files found (nothing was checked)"), and the variants were rebuilt properly; (2) the checker itself initially passed an empty directory, which is the same class of error as a gate that cannot fail. The demo project itself was never touched. The example app, the checker, and the pages live in /tmp and are rebuildable.
