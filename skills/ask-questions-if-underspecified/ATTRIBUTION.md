# ATTRIBUTION — ask-questions-if-underspecified

This skill was copied from a ready-made, community-tested skill — verbatim body, ORCINUS frontmatter — as agreed: when a skill already answers the need, ORCINUS uses it as-is instead of rewriting it.

- **Source:** https://github.com/sickn33/antigravity-awesome-skills (now titled Agentic Awesome Skills) — `skills/ask-questions-if-underspecified/SKILL.md`
- **Licence:** MIT — see `LICENSE.txt` in this folder (upstream MIT License, Copyright (c) 2026 Antigravity User, copied from the upstream repo root).
- **Upstream commit:** `739c841480587361c3cb2047f5b34cdca69a0623` (2026-11-05, "chore: release v20.6.0 (#2286)")
- **Files copied:** 1 file (`SKILL.md`, 92 lines), verified identical to upstream with `diff` before the copy. A secret-pattern scan of the copied file found nothing.
- **What changed:** only the frontmatter of `SKILL.md` was adapted to the Agent Skills spec (kept `name` and `description`, added `license: MIT`; removed non-spec fields `risk`, `source`, and `date_added`). The body is byte-for-byte identical to upstream (verified programmatically). The description is the upstream description with the ORCINUS router-only note appended ('Only invoke via the orcinus router.').
- **user-invocable, added 2026-11-06 (round 3):** frontmatter gained `user-invocable: false` — only the router is a user entry point; sub-skills hide from the `/` menu and are invoked by the router. A Claude Code extension field; other hosts ignore it.
- **Wiring:** the ORCINUS router loads this skill whenever a request is underspecified, before any implementation — see the router's shared rules and routing table.
