# ATTRIBUTION — performance-optimization

This skill was copied verbatim from a ready-made, community-tested skill, as agreed: when a skill already answers the need, ORCINUS uses it as-is instead of rewriting it.

- **Source:** https://github.com/addyosmani/agent-skills — `skills/performance-optimization/`
- **Author:** Addy Osmani
- **Licence:** MIT — see `LICENSE.txt` in this folder (upstream MIT License, Copyright (c) 2025 Addy Osmani, copied from the upstream repo root).
- **Upstream commit:** `301b02b12bff98e4688e6984af6556802322bbde` (2026-11-01, "Merge #736: validate review findings against code and baseline")
- **Files copied:** 2 files (`SKILL.md`, `references/optimization-patterns.md`), verified identical to upstream with `diff -r` before the copy. A secret-pattern scan of the copied files found nothing.
- **What changed:** only the frontmatter of `SKILL.md` was adapted to the Agent Skills spec (kept `name` and `description`, added `license: MIT`). The description text and the entire body are byte-for-byte identical to upstream (verified programmatically).
- **Wiring:** the ORCINUS router loads this skill when a performance requirement exists or a change is suspected of introducing a regression — see the router's shared rules.
