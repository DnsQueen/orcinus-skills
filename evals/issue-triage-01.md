# EVAL — issue-triage-01

How to check whether the `issue-triage` skill works. Follow its 3 phases (Audit → opt-in Deep Analysis → validated Actions) on a real public repo — `microsoft/waza` (53 open issues, 25 open PRs, 20 recent closed issues, fetched read-only). The data gathering used the GitHub API, not the `gh` CLI, because `gh auth status` fails in this VM (not logged in) — the skill's own precondition correctly stops the `gh` workflow there, and that failure is recorded, not worked around. No GitHub write was performed at any point. No criterion may be skipped.

## Case 1 — the audit runs on real data and its exact dimensions check out

**Input:** the real backlog (53 open issues, 25 open PRs, 20 closed), analyzed with the skill's 6 dimensions (categorization, PR cross-reference, Jaccard duplicates, risk, staleness, recommendations) by a script implementing the skill's rules (`/tmp/orcinus-demo-triage/audit.py`).

**Pass criteria:**

1. Data gathering is real: 53 open issues (PRs excluded), 25 open PRs, 20 closed issues — matching the live repo.
2. PR cross-reference is exact: 24 issues are linked to an open PR by a `fixes/closes/resolves #N` pattern in a PR body, verified by regex on the real PR bodies (e.g. #895 → PR #896, #894 → PR #897).
3. Staleness is exact: 0 stale, 0 very stale — every issue was updated within 30 days (verified from `updated_at` dates against 2026-11-06).
4. The triage tables and summary are produced (total, Red, PR-linked, duplicates, stale, very stale, unlabeled, recommended actions).

**Fail criteria:**

- Any count disagrees with the live repo, or a PR link is claimed without the pattern in the PR body.
- The audit silently includes PRs as issues, or silently drops issues.

## Case 2 — duplicate detection is measured, with its limit stated

**Input:** a controlled dataset (`/tmp/orcinus-demo-triage/jaccard_test.py`) implementing the skill's Jaccard algorithm exactly (normalize → tokenize → Jaccard, flag ≥ 0.60, older issue canonical).

**Pass criteria:**

1. A near-identical pair (one word changed) scores ≥ 0.60 and is flagged (measured: 0.88).
2. Unrelated pairs score < 0.60 and are not flagged (measured: 0.00, 0.00, 0.04).
3. The reworded duplicate's score is measured and recorded as a known limit (0.42 — missed, because the algorithm has no stemming: "match" vs "matching" and "selector" vs "selectors" do not match, and filler words dilute the score).

**Fail criteria:**

- A near-identical pair is missed, or an unrelated pair is flagged.
- The reworded miss is hidden instead of recorded.

## Case 3 — no action executes without validation, and nothing changes

**Input:** the drafts (`/tmp/orcinus-demo-triage/drafts.md`) generated from the skill's templates, and the target repos' open-issue counts before and after.

**Pass criteria:**

1. Drafts exist and are visible before any execution (an escalation draft for the Red issues, and a Template 2 duplicate draft for the controlled near-identical pair).
2. The validation step catches false positives: both Red flags were checked by reading and found to be false (#770's "vulnerab" is in a Non-goals section; #657 is an Epic about regression testing, not a regression blocking users), so neither escalation is executed.
3. No GitHub write was performed: the repos' open-issue counts are unchanged after drafting (microsoft/waza: 78; florianbruniaux/claude-code-plugins: 1).
4. The `gh` precondition failure is recorded: `gh auth status` fails in this VM, so the skill's `gh`-based workflow would stop at the preconditions — the eval used the read-only API for data gathering instead, and did not log in.

**Fail criteria:**

- Any `gh issue comment/edit/close` runs, or any repo's issue count changes.
- A draft is executed without being shown first, or a false-positive escalation is executed.

## Last run

- 2026-11-06: PASS. Case 1: 4/4. Case 2: 3/3. Case 3: 4/4. Real run, not simulated, on `microsoft/waza` (53 open issues, 25 open PRs, 20 closed). Case 1: the counts match the live repo; 24 PR links verified by regex (e.g. #895 → PR #896, #894 → PR #897); 0 stale / 0 very stale from the real `updated_at` dates; the triage tables and summary were produced (total 53, Red 2 by the keyword pass, PR-linked 24, duplicates 0, unlabeled 3). Case 2: near-identical 0.88 flagged, unrelated 0.00/0.00/0.04 not flagged, reworded 0.42 missed and recorded as a known limit. Case 3: the drafts exist and are visible; both Red flags were checked by reading and found false, so neither escalation was executed; the repos' open-issue counts are unchanged (78 and 1); `gh auth status` fails in this VM and is recorded. Two real defects found during the run: (1) the first risk pass used single-keyword matching and flagged 17 issues Red — mostly perf/feature work that merely mentions "regression" or "validation". The risk function was corrected to the skill's phrase-level criteria ("regression blocking users", not "regression"), which reduced Red to 2 — and reading then showed both of those are also false positives. The lesson is recorded: the skill's categorization and risk dimensions require an agent to READ; a keyword implementation does not reproduce them. A 7-issue reading check found 3 categorization errors (#893 Daily stand-up is a tracker, not a Bug; #892 is a Feature Request, not a Bug; #657 is an Epic, not a Bug) and 2 risk errors (#770, #657). The audit numbers above are therefore the keyword approximation's output, verified on the exact dimensions (data, PR links, Jaccard, staleness) and corrected by reading where the approximation was wrong. (2) The first audit run failed with `KeyError: 'updatedAt'` — the skill's `gh` field is camelCase, but the REST API returns snake_case (`updated_at`). The script was fixed to map the field names; the skill itself is correct for `gh`. Honest limits: the audit's categorization and risk are a keyword approximation, not a reading agent's judgment; Phase 2 (deep analysis with parallel agents) was not run — the duplicate verification was done by the controlled Jaccard test instead; Phase 3 was proven only in its draft-and-stop form (no real `gh` write, because `gh` is not authenticated here and no repo owner authorized a write); the skill defaults to French when no language is given — ORCINUS users must pass the language explicitly.
