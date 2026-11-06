# ATTRIBUTION — api-and-interface-design

This skill was copied from a ready-made, community-tested skill — verbatim body, ORCINUS frontmatter — as agreed: when a skill already answers the need, ORCINUS uses it as-is instead of rewriting it.

- **Source:** https://github.com/addyosmani/agent-skills — `skills/api-and-interface-design/`
- **Author:** Addy Osmani
- **Licence:** MIT — see `LICENSE.txt` in this folder (upstream MIT License, Copyright (c) 2025 Addy Osmani, copied from the upstream repo root).
- **Upstream commit:** `301b02b12bff98e4688e6984af6556802322bbde` (2026-11-01, "Merge #736: validate review findings against code and baseline")
- **Files copied:** 1 file (`SKILL.md`), verified identical to upstream with `diff` before the copy. A secret-pattern scan of the copied file found nothing.
- **What changed:** only the frontmatter of `SKILL.md` was adapted to the Agent Skills spec (kept `name` and `description`, added `license: MIT`). The body is byte-for-byte identical to upstream (verified programmatically). The description is the upstream description with the ORCINUS router-only note appended ('Only invoke via the orcinus router.').
- **user-invocable, added 2026-11-06 (round 3):** frontmatter gained `user-invocable: false` — only the router is a user entry point; sub-skills hide from the `/` menu and are invoked by the router. A Claude Code extension field; other hosts ignore it.
- **Wiring:** the ORCINUS router loads this skill when designing or changing an API, a module boundary, or any public interface — see the router's shared rules.
