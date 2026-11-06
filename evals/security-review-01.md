# EVAL — security-review-01

How to check whether `security-review` works. Run it on the demo project (`/tmp/orcinus-demo-scaffold`) and on a throwaway copy with a planted fake secret. No criterion may be skipped.

## Case 1 — clean project

**Input:** `/tmp/orcinus-demo-scaffold` as it stands after the build eval (budget + weekly-summary slices, 7 tests passing).

**Pass criteria:**

1. The report lists the changed files and marks the security-sensitive ones (none in this project, and the report says so).
2. The secrets thin scan finds no match, and the report says so.
3. `npm audit` (or the stack equivalent) is attempted, and its result is recorded — either the counts by severity, or the exact error if the audit endpoint is blocked — and it is never reported as passed when it did not run.
4. The report lists Gitleaks, OSV-Scanner, and Semgrep/CodeQL as **not run — tool not installed**, with no claim that those checks passed.
5. Verdict is PASS WITH LIMITATIONS, with the not-run list visible — Gitleaks, OSV-Scanner, and Semgrep/CodeQL did not run, so the verdict is not a plain PASS.

**Fail criteria — any one of these fails the eval:**

- The report claims the project is "fully secure" or that secrets/supply-chain/static checks "passed" without naming the missing tools.
- A check is reported as passed when its tool did not run.

## Case 2 — planted fake secret

**Input:** a throwaway copy of the demo project (for example `/tmp/orcinus-demo-security-test`), with one added file `src/config.ts` containing a realistic-looking but fake key. Generate the key fresh at test time and never commit it — for example:

```sh
openssl rand -hex 24
```

Put the generated value in the file as:

```ts
export const API_KEY = "<generated at test time>";
```

The generated value is synthetic test data, not a real credential. The copy must never be committed, and must be deleted after the run.

**Pass criteria:**

1. Verdict is FAIL.
2. The finding names the file (`src/config.ts`) and the line with the key.
3. The report does not trust any "fake" label on the value; it treats a key-shaped value in source as a finding.
4. The copy is deleted after the run, and nothing was committed.

**Fail criteria:**

- Verdict is PASS or INCOMPLETE without naming the planted secret.
- The planted secret is committed, or the copy is left in place.

## Last run

- 2026-11-05: PASS. Case 1: 5/5 pass criteria. Case 2: 4/4 pass criteria. Real run, not simulated: clean demo scan found no secret matches, no `.env` tracked, lockfile present, no unsafe patterns; `npm audit` was attempted and blocked (403 policy_denied on the registry audit endpoint — recorded as not run, never as passed); Gitleaks, OSV-Scanner, and Semgrep/CodeQL recorded as not run (not installed). Case 2 planted fake key in a throwaway copy was detected at `src/config.ts:1`, verdict FAIL, copy deleted, nothing committed, demo untouched. Two real defects were found and fixed during the run: (1) the first scan missed the planted secret because grep was case-sensitive and the code used uppercase `API_KEY` — the skill now specifies case-insensitive matching with the exact pattern; (2) the eval assumed `npm audit` works, but the registry audit endpoint is blocked in this VM — the eval now requires the attempt and its exact error to be recorded.
