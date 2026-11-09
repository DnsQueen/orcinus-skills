# Fixtures for `evals/waza-registry-publish/`

Recorded evidence, not a live run: the agent reads these files
instead of running `npm pack`, the install, or the registry
query. The pack lists and the E404 are the demo's from
`evals/registry-publish-01.md` (Cases 1–2).

| Folder | Contents | Difference |
| --- | --- | --- |
| `prepared/` | `package.json`, `pack-dry-run.txt`, `commands.txt`, `registry-check.txt`, `changelog.txt` | `files` allowlist + `exports`; dry-run lists exactly 5 files |
| `unprepared/` | same five files | no `files`, no entry points; dry-run lists 15 files, incl. `src/` and `tests/` |

Each task's bare `files:` paths belong to its own folder above.
No real publish is performed in either task.
