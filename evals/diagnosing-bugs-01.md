# Eval: diagnosing-bugs-01

How to check whether `diagnosing-bugs` works. The skill is a phased
loop: Phase 1 builds a tight, red-capable feedback loop that has
actually been run at least once, before any hypothesis. A diagnosis is
only a PASS when the root cause is named (not just the symptom) and the
fix is verified by a test that fails without it.

## Case 1 — the check_architecture relative-path false pass

**Input:** `check_architecture.py --root .` reports OK on a project
that has a layer violation and a circular import, while an absolute
`--root` correctly FAILs with 2 violations.

**The loop, run for real:**
1. **Reproduce (Phase 1):** a fixture with `src/a.ts` ↔ `src/b.ts`
   (a cycle) and `src/c.ts` importing `../tests/helper.js`. Ran the
   checker with `--root .` (OK, exit 0) and with an absolute root
   (FAIL, 2 violations). The loop is red-capable: it distinguishes
   the broken state from the fixed state.
2. **Isolate:** the only difference between the two runs is the root
   argument. Reading the code: `main()` keeps `root` as given
   (`./src`), while `resolve_import()` normalises targets with
   `normpath` (so a target becomes `src/x.ts`, without the `./`).
   `os.path.commonpath(["src/x.ts", "./tests"])` yields `""`, so the
   layer check and the graph-edge insertion silently miss.
3. **Hypothesis:** the root is not normalised, so the comparisons fail.
4. **Fix:** absolutise and normalise the root at the start of `main()`.
5. **Verify:** the regression test
   (`test_relative_root_finds_the_same_violations_as_absolute`) passes
   — `--root .` and an absolute root now report the same 2 violations —
   and the checker passes on the demo and on weekly-budget with both
   forms of root.

**Verdict:** PASS. The root cause was named (unnormalised root vs
normalised targets), not just the symptom (OK on a bad project), and
the fix is verified by a test that fails without it.

## Case 2 — the capture.py CRLF silent failure

**Input:** an idea file with CRLF line endings vanishes from `list`
and `search` — silently, with no error.

**The loop, run for real:**
1. **Reproduce (Phase 1):** wrote a CRLF idea file into a store and
   ran `list` — the idea was absent. The loop is red-capable: the
   same file with LF endings appears.
2. **Isolate:** `read_frontmatter` requires the file to start with
   `"---\n"`; a CRLF file starts with `"---\r\n"`, so it raises
   `ValueError`, and `_all_ideas` swallows it with `continue`.
3. **Hypothesis:** the frontmatter parser does not normalise line
   endings, and the caller hides the failure.
4. **Fix:** normalise `\r\n` to `\n` when reading, and report a
   malformed file to stderr instead of silently skipping it.
5. **Verify:** the tests `test_crlf_file_is_listed_not_silently_skipped`
   and `test_malformed_file_is_reported_not_silently_skipped` pass.

**Verdict:** PASS. The root cause was named (the parser's line-ending
assumption plus the silent swallow), and the fix is verified by tests
that fail without it.

## Result

- 2026-11-06: PASS. Case 1: 1/1. Case 2: 1/1. Both diagnoses named
  the root cause and were verified by tests. The skill's Phase 1 rule
  (a tight, red-capable loop run at least once before any hypothesis)
  was followed in both cases, and it is what made the isolation
  possible: without a reproducer that distinguishes broken from fixed,
  the first hypothesis would have been a guess.
