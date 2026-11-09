# Fixtures for `evals/waza-finalize/`

Recorded evidence, not a live run: the agent reads these files
instead of running the gates. The commits, version, and test
count are the demo's from `evals/finalize-01.md`.

| Folder | Contents | Difference |
| --- | --- | --- |
| `ready/` | `package.json`, `git-log.txt`, `verify-results.txt`, `release-tools.txt` | orcinus-verify PASS |
| `blocked/` | same four files | orcinus-verify FAIL (summary.ts, Math.floor) — the only difference |

Each task's bare `files:` paths belong to its own folder above.
