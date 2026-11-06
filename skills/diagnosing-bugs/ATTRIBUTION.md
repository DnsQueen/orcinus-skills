# ATTRIBUTION — diagnosing-bugs

- **Source:** https://github.com/mattpocock/skills — `skills/engineering/diagnosing-bugs/`
- **Licence:** MIT — see `LICENSE.txt` in this folder (upstream MIT License, Copyright (c) 2026 Matt Pocock, copied from the upstream repo root).
- **Upstream commit:** `4ae2317ddb22b046e26455e4f9c9b3aaaf62212d` (2026-10-31, "software-factory: glossary skill for designing a factory (#1316)").
- **Files copied:** 2 files (`SKILL.md` 138 lines, `scripts/hitl-loop.template.sh`), verified identical to upstream with `diff -r` before the copy. A secret-pattern scan of the copied files found nothing.
- **What changed:** only the frontmatter of `SKILL.md` was adapted to the Agent Skills spec (added `license: MIT`; the description is the upstream description with the ORCINUS router-only note appended). The body is byte-for-byte identical to upstream.
- **user-invocable, added 2026-11-06 (round 3):** frontmatter gained `user-invocable: false` — only the router is a user entry point; sub-skills hide from the `/` menu and are invoked by the router. A Claude Code extension field; other hosts ignore it.
- **What was NOT copied:** `agents/openai.yaml` — a Codex/OpenAI agent definition, not usable in Muse (and not usable in Claude Code's Agent Skills format). The skill's method does not depend on it.
- **Scope notes:** the skill is a phased diagnosis loop (Phase 1 builds a tight, red-capable feedback loop that has actually been run at least once, before any hypothesis). It redacts every secret as `<REDACTED>`. The human-in-the-loop template (`scripts/hitl-loop.template.sh`) is a template, not a script that runs on its own. The skill references `tdd` for the test-first loop; in ORCINUS, `tdd` is external-optional (see the router's fallbacks), so the regression test in Phase 5 goes at a correct seam or is documented as not possible.
- **Evals:** the repo's own eval is `evals/diagnosing-bugs-01.md` — two real bugs diagnosed with the loop (the check_architecture relative-path false pass and the capture.py CRLF silent failure), each with the root cause identified and the fix verified by tests.
