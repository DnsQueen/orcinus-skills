---
name: independent-review
description: Review a change independently before it merges, with six focused reviewers reading the diff — not the author's summary. Use before committing, before creating a pull request, and after a logical chunk of work. The implementer is never the final judge. Only invoke via the orcinus router.
license: MIT
---

# INDEPENDENT-REVIEW — the implementer is never the final judge

A change the author reviewed themself is not reviewed. This skill runs an independent review of a change: six focused reviewers read the diff and the code, each from one angle, and their findings are aggregated into one verdict. It does not fix code — fixing is a separate step, one slice at a time, test first.

## Licences

This skill's text is MIT. The bundled reviewer agents and command (`agents/`, `commands/`) are Apache-2.0 — see `ATTRIBUTION.md`. Do not re-license the bundled files.

## Rules

- The reviewer reads the diff and the project's own conventions, never the author's summary. A summary that says "just a refactor" is a claim, not evidence.
- Review only the diff. Never review the whole codebase — that hides the change in noise.
- Only report an issue with confidence ≥ 80. A guess is not a finding.
- Every finding names a file and a line. A finding without a location is not actionable.
- A check that did not run is never reported as passed.

## Steps, in order

### 1. Determine the scope

Pick the mode first, then list the changed files (new files included). That list is the scope. Nothing outside it is reviewed.

- **Local (uncommitted work):** staged + unstaged + untracked files. `git status` alone misses staged changes, and `git diff` alone misses untracked files — list all three.
- **Single commit:** the commit against its parent (`git diff --name-only <commit>^ <commit>`).
- **Pull request:** the head against the merge-base of the target branch (`git diff --name-only $(git merge-base <target> HEAD) HEAD`). In a clean PR worktree without a base, comparing against the branch's merge-base is the only way to see the PR's changes — a plain `git diff` shows nothing.

### 2. Pick the applicable reviewers

- **Always**: code-reviewer (general quality, project guidelines, bugs).
- **If test files changed, or if behaviour changed with no new tests**: pr-test-analyzer (behavioral coverage, critical gaps, test quality). A behaviour change with no new test is itself a coverage finding — do not skip the analyzer because no test file changed.
- **If comments or docs were added**: comment-analyzer (comment accuracy vs code, comment rot).
- **If error handling changed**: silent-failure-hunter (silent failures, catch blocks, fallbacks).
- **If types were added or modified**: type-design-analyzer (encapsulation, invariants).
- **After the review passes**: code-simplifier (clarity, unnecessary complexity — preserves functionality).

### 3. Run the reviewers

The reviewers are the bundled agents in `agents/` (from pr-review-toolkit, Apache-2.0). Run them in parallel when they are independent — they read the same diff from different angles. Each one reads the code, not a summary of it.

Confidence scales, per reviewer:

- **code-reviewer**: 0–100; 91–100 is a critical bug or an explicit convention violation. Report only ≥ 80.
- **pr-test-analyzer**: rates each gap 1–10 (10 = absolutely essential, must add).
- **silent-failure-hunter**: CRITICAL (silent failure, broad catch), HIGH (poor error message, unjustified fallback), MEDIUM (missing context).
- **type-design-analyzer**: rates four dimensions 1–10 — encapsulation, invariant expression, usefulness, enforcement.
- **comment-analyzer**: flags accuracy and rot, with confidence.
- **code-simplifier**: suggests simplifications; it never changes behaviour.

### 4. Aggregate

Collect the findings into one report:

- **Critical Issues** (must fix before merge)
- **Important Issues** (should fix)
- **Suggestions** (nice to have)
- **Positive Observations** (what is good)

A finding appears once, under its highest severity, with the reviewer that found it.

### 5. Action plan

Fix the critical issues first, then the important ones, then consider the suggestions. Re-run the review after the fixes — a fix that is not re-reviewed is not verified.

## Report

Return the report in this form:

- Scope (the changed files, from `git diff`).
- Reviewers run (which ones, and why the others did not apply).
- Critical Issues (every one, with file, line, reviewer, and confidence/severity).
- Important Issues and Suggestions (every one, with file and line).
- Positive Observations.
- Verdict: PASS (no critical issues, and every reviewer that applied ran) or FAIL (a critical issue was found, or a reviewer that applied did not run).

## Scope

Review only. This skill does not write code, does not fix findings, and does not decide the merge — a human does, after the critical issues are fixed and the review is re-run. The bundled agents carry project-specific references from the original author's project (a `CLAUDE.md`, Sentry/Statsig logging functions, an error-ids file). Read the project's own conventions (`AGENTS.md` / `CLAUDE.md`) instead of those hardcoded names; the method transfers, the names do not.

## Sources

Method, in our own words, following pr-review-toolkit (anthropics/claude-plugins-official, Apache-2.0). The six reviewer agents and the `review-pr` command are bundled as-is in `agents/` and `commands/`; see `ATTRIBUTION.md`. No text was copied from the toolkit into this file.
