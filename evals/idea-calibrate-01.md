# EVAL — idea-calibrate-01

How to check whether `idea-calibrate` works. Run it on the input below, in a fresh conversation, and score the brief against the criteria. No criterion may be skipped.

## Case 1 — vague idea

**Input (verbatim, as the user gives it):**

> I want an app that helps people save money.

**Pass criteria — the brief must contain all of these:**

1. A problem in one sentence, naming who hurts and what happens if nothing changes.
2. One specific user (a person, not "everyone" or "users").
3. A current workaround (what that person does today).
4. An opportunity tree: one problem, at least two opportunities, at least one solution per opportunity.
5. At least two assumptions, ranked, each with a cheapest test and what evidence would change the decision.
6. A pre-mortem with three causes and three preventions.
7. v1 scope: must-have, nice-to-have, and non-goals, all written down.
8. Measurable success criteria (a number and a date).
9. One first slice (one behaviour, one test).

**Fail criteria — any one of these fails the eval:**

- The brief picks a tech stack, a database, or a framework.
- The brief contains code.
- An assumption is stated as a fact, with no test.
- The user is "everyone" or "users".
- Success is "better" with no number.

## Case 2 — feature request with a hidden assumption

**Input:**

> Add a share button so more people find the app.

**Pass criteria:**

1. The brief asks what problem sharing solves, for whom, before accepting the button.
2. At least one assumption is named (for example, that users want to share, or that sharing brings new users) with a cheapest test.
3. The brief names a non-goal (what sharing will not do in v1).

**Fail criteria:**

- The button is accepted as the solution without asking the problem first.

## Last run

- 2026-11-05: PASS. Case 1: 9/9 pass criteria, 0 fail criteria. Case 2: 3/3 pass criteria, 0 fail criteria. Run by the author following the skill on the two inputs, with simulated test-user answers (labelled TEST-USER in the test brief, not a real user decision). No stack, database, framework, or code in the brief body; the only matches for those words are in the score summary line itself.
