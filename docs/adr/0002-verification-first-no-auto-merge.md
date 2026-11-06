# ADR 0002 — Verification-first, no auto-merge, no test weakening

Date: 2026-11-05
Status: accepted

## Context

Coding agents are good at producing code that looks done. The failure
mode is not "no code" but "code that passes a weakened test, or a
claim of done with no evidence". A system that auto-merges, or that
lets the implementer judge its own work, will ship that failure mode
at scale.

## Decision

- **Failing test first.** For any behaviour change, a test must fail
  before the fix and pass after it (proved in a separate worktree,
  never by stashing on a dirty tree). A test added after the code and
  never shown failing is unproven.
- **Independent verification.** The verifier is never the
  implementer. It runs in a fresh context with only the requirement,
  the diff, and the code — not the implementer's summary.
- **No auto-merge.** A verification PASS is a recommendation, not a
  merge. The human decides.
- **No test weakening.** A test deleted, an assertion weakened, a CI
  check disabled, or a test changed to always pass is a blocking
  finding. If a test looks wrong, the verifier explains why with
  evidence and gets agreement first.
- **Evidence, not claims.** Every claim points to a command, an
  output, or a file, in the structured bundle
  (`evals/evidence.schema.json`), bound to the exact revision it ran
  on. A PASS is bound to that revision only.

## Consequences

- Good: "done" means verifiable, not "the agent said so". The
  weekly-budget dogfood (Stage 30) closed on this rule: mutation
  71.31 as a lower bound, with the Stryker reporting quirk proven by
  hand.
- Bad: verification is slower than generation. Accepted: speed that
  ships unproven code is not speed.
- Bad: the fail-first rule cannot be proved for a change with no
  behaviour to test (docs, config). The evidence schema's
  `fail_first.method: not-applicable` covers that, with a note saying
  why — it must not be used to skip the rule for real behaviour.
