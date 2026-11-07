# ATTRIBUTION — i18n

This skill was copied from a ready-made, community-tested skill — verbatim body, ORCINUS frontmatter — as agreed: when a skill already answers the need, ORCINUS uses it as-is instead of rewriting it.

- **Source:** https://github.com/Marvellbrazil/my-agentic-skills — `skills/i18n/`
- **Author:** Marvello Faisal
- **Licence:** MIT — see `LICENSE.txt` in this folder (upstream MIT License, Copyright (c) 2026 Marvello Faisal, copied from the upstream repo root).
- **Upstream commit:** `42203fde5eb692ba254e058168ee1af75855fcb4` (2026-10-23, "feat(modularize): expand workflow and add structure, architecture, and decoupling references")
- **Files copied:** 10 files (`SKILL.md`, 9 files under `references/`), verified identical to upstream with `diff -r` before the copy. A secret-pattern scan of the copied files found nothing.
- **What changed:** only the frontmatter of `SKILL.md` was adapted to the Agent Skills spec (kept `name` and `description`, removed the Claude-Code-only `allowed-tools` field, added `license: MIT`). The body is byte-for-byte identical to upstream (verified programmatically). The description was shortened 2026-11-07 (round 6, R8) from the upstream 613-char list of all nine domains to a short trigger description; the domains live in the skill body, not the description. The ORCINUS router-only note ('Only invoke via the orcinus router.') is kept.
- **user-invocable, added 2026-11-06 (round 3):** frontmatter gained `user-invocable: false` — only the router is a user entry point; sub-skills hide from the `/` menu and are invoked by the router. A Claude Code extension field; other hosts ignore it.
- **Wiring:** the ORCINUS router loads this skill when a project needs to support another language, locale, or writing direction — see the router's shared rules.
