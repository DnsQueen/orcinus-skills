# EVAL — ask-questions-01

How to check whether `ask-questions-if-underspecified` works. Apply the skill's own decision procedure (step 1: decide whether the request is underspecified) to each input below, and record the outcome. No criterion may be skipped.

## Case 1 — vague request

**Input:** "make the app faster"

**Pass criteria:**

1. Verdict: underspecified (objective, done, scope, constraints, and environment are all unclear).
2. 1–5 must-have questions are produced, numbered, with multiple-choice options and a marked default where appropriate.
3. No implementation, no code, and no plan that depends on the unknowns is produced.

**Fail criteria:**

- The skill proceeds to implement or plan without asking.
- More than 5 questions are asked in the first pass.

## Case 2 — hidden assumption

**Input:** "add a share button to the demo"

**Pass criteria:**

1. Verdict: underspecified (what is shared, share target, and where the button goes are all unclear).
2. The questions name the missing details (share target, button placement, what is shared).
3. No implementation is produced before the answers arrive.

**Fail criteria:**

- The skill guesses a share target (for example, assumes X/Twitter or WhatsApp) and implements it.
- The questions miss the share target entirely.

## Case 3 — well-specified request

**Input:** the weekly-summary slice spec from the build eval: `weeklySummary(spending, budget)` in `src/summary.ts`, returning `{ total, remaining, warned, percent }` (percent rounded; budget ≤ 0 throws `Error("budget must be greater than 0")`), with literal expected values including `[20,30,30]`/100 → `{80, 20, true, 80}` and `[]`/100 → `{0, 100, false, 0}`.

**Pass criteria:**

1. Verdict: specified — the skill is NOT used.
2. No questions are asked. Proceed decision recorded.

**Fail criteria:**

- Any question is asked about this request.

## Case 4 — answerable by a discovery read

**Input:** "what version of TypeScript does the demo use?"

**Pass criteria:**

1. Verdict: answerable by a quick, low-risk discovery read — the skill is NOT used.
2. The answer comes from reading the demo's `package.json` (record the version found).
3. No question is asked.

**Fail criteria:**

- A question is asked instead of reading the file.
- The version is guessed without reading the file.

## Last run

- 2026-11-05: PASS. Case 1: 3/3. Case 2: 3/3. Case 3: 2/2. Case 4: 3/3. Real run, not simulated: the skill's own decision procedure was applied to each input. Case 1 ("make the app faster") judged underspecified — 3 numbered questions produced (which part, what "faster" means, how much faster measured how), with options and defaults and a `defaults` fast-path, no implementation or plan. Case 2 ("add a share button to the demo") judged underspecified — 3 questions naming the missing details (what is shared, share to where, where the button goes), no share target guessed, no implementation. Case 3 (weekly-summary spec) judged specified — skill not used, proceed, no questions. Case 4 (TypeScript version) judged answerable by discovery read — answered from the demo's package.json (`^6.0.3`, Node v24.22.1), no question asked, nothing guessed. No fail criteria triggered.
