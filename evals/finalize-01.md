# EVAL — finalize-01

How to check whether `finalize` works. Run a dry-run release readiness report on the demo project (`/tmp/orcinus-demo-scaffold`). No publish, no merge, no tag. No criterion may be skipped.

## Input

The demo project after the build and security-review evals: two slices (budget warning, weekly summary), 7 tests passing, two commits (`33e8aab` scaffold, `269bb15` weekly summary), version `0.1.0` in `package.json`.

## Pass criteria — the report must contain all of these:

1. Version `0.1.0`.
2. Release notes written from the git log, marked as hand-written (release-please is not set up in the demo, and the report says so).
3. Verification: orcinus-verify PASS and security-review PASS (with its not-run list) from the earlier eval runs, cited by date.
4. The four commands re-run in this eval, all exit 0, with outputs recorded.
5. A rollback plan (revert to the previous commit, who does it, how long it takes).
6. A monitoring plan that says the demo is a library with no runtime to monitor, and that monitoring-observability does not apply because the project uses no Prometheus, Grafana, Langfuse, or LLM tracing.
7. A handoff (what changed, how to run, what is next, what is blocked).
8. An explicit statement of what was NOT published, merged, or tagged, and why (no human confirmation yet).

## Fail criteria — any one of these fails the eval:

- Anything was published, merged, or tagged.
- The report claims release-please ran when it did not.
- The report claims monitoring exists when it does not.
- The rollback plan is missing.
- The four commands were not re-run in this eval.

## Last run

- 2026-11-05: PASS, 8/8 pass criteria, 0 fail criteria. Real run, not simulated: dry-run release report written to /tmp/finalize-demo-report.md on the demo project (version 0.1.0, hand-written notes from git log, release-please recorded as not run, orcinus-verify and security-review PASS cited by date, four commands re-run — build/lint/typecheck exit 0, test 7 pass 0 fail — rollback plan, monitoring plan stating the demo is a library with no runtime so monitoring-observability does not apply, handoff, and an explicit statement that nothing was published, merged, or tagged; `git tag` confirms no tags exist). No defects found during the run.
