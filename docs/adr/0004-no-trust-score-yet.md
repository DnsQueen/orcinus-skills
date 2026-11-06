# ADR 0004 — No single Trust Score in v1

Date: 2026-11-06
Status: accepted

## Context

Two external reviewers proposed an "Engineering Trust Score" — one
number summarising how trustworthy a change is. It is an attractive
idea: a single number is easy to compare and easy to gate on. But a
score is only as good as its weights, and the weights for "how much
does a passing test count versus a clean security scan versus a
reviewer's confidence" are arbitrary. An arbitrary score is gameable:
an agent (or a human) can optimise the number without improving the
change. A score that can be gamed will be gamed, and then it is worse
than no score — it gives a false sense of safety.

## Decision

ORCINUS does **not** ship a single Trust Score in v1. Instead it
ships the components a score would be built from, each independently
checkable:

- the structured evidence bundle (`evals/evidence.schema.json`) —
  every check, its exit code, its revision, its verdict;
- the fail-first proof (a test that failed before the fix and passes
  after it);
- the mutation score (a lower bound, with the reporting quirk
  documented, not a single number to optimise);
- the independent review (a verdict with named files and evidence,
  not a confidence number).

A human reads those components and decides. If a score is added
later, it must be derived from these components with published
weights, and the derivation must be auditable — the score is a
summary of the evidence, never a replacement for it.

## Consequences

- Good: no false precision. A PASS means "every check ran and
  passed on this revision", which is a checkable claim, not "the
  change scores 87".
- Good: the components are useful on their own (the evidence bundle
  is the audit trail; the mutation score is the test-quality signal).
- Bad: a user who wants one number to compare two changes does not
  get it. Accepted for v1; the components make a future score
  honest, if one is ever built.
- Recorded: the reviewers' proposal is kept in SCOPE.md's v1.1
  section (Engineering Trust Score, deferred), not deleted.
