# Fixtures for `evals/waza-independent-review/`

The diff stands in for a repo the agent would otherwise diff
itself. The three cases are the demo's from
`evals/independent-review-01.md`.

| Folder | Contents | Difference |
| --- | --- | --- |
| `planted/` | `diff.txt`, `discount.ts`, `discount.test.ts` | Comment says 10% off, code returns `total * 0.8`; bare `catch` returns the full total; one happy-path test |
| `clean/` | `diff.txt`, `discount.ts`, `discount.test.ts` | `SAVE10_RATE = 0.9`, unknown codes throw, three tests |
| `misleading/` | `diff.txt`, `budget.ts`, `budget.test.ts`, `author-summary.txt` | Threshold moves 0.8 → 0.9; the summary claims no behavior change; the existing test now fails |

Intentional discrepancy (do not "fix"): the planted happy-path
test asserts only that the discount applies (`< 100`) and does
not pin the rate — that is why the suite passes despite the bug,
and why the rate contradiction must be found by reading the
comment against the code.
