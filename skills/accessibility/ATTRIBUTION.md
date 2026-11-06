# ATTRIBUTION — accessibility

This skill's method is written in ORCINUS's own words, using the ultra11y engine as-is, as agreed: when a ready tool answers the need, ORCINUS uses it as-is instead of rewriting it.

- **Source of the engine:** https://github.com/maxgfr/ultra11y — `skills/ultra11y/scripts/ultra11y.mjs`
- **Author:** maxgfr
- **Licence:** MIT — see `LICENSE.txt` in this folder (upstream MIT License, Copyright (c) 2026 maxgfr, copied from the upstream repo root).
- **Upstream commit:** `b245094b7528f8624cfbf84d00ee05422aeac24e` (2026-11-03, "chore(release): 5.58.1 [skip ci]")
- **Engine:** `scripts/ultra11y.mjs` is bundled verbatim from upstream (a self-contained, install-free Node script, version 5.58.1), verified identical to upstream with `diff` before the copy. A secret-pattern scan of the copied file found nothing. It runs 102 static checks tied to success criteria.
- **Why the SKILL.md is not a verbatim copy:** the upstream `skills/ultra11y/SKILL.md` is 522 lines, over the Agent Skills spec's guidance to keep `SKILL.md` under 500 lines, and it is one file of a 44-file system built around RGAA 4.1.2 (the French State's accessibility standard). Copying it verbatim would put a non-compliant skill in this repo. So the `SKILL.md` here is written in our own words, under 500 lines, and uses the engine as-is. The upstream `review-a11y` skill was not copied (it is scoped to diffs and PRs, not to this skill's audit).
- **user-invocable, added 2026-11-06 (round 3):** frontmatter gained `user-invocable: false` — only the router is a user entry point; sub-skills hide from the `/` menu and are invoked by the router. A Claude Code extension field; other hosts ignore it.
- **Standard:** the engine audits against RGAA 4.1.2 on a WCAG 2.2 AA core; other country standards are pluggable packs. This skill states that scope plainly and does not claim a broader standard than the engine checks.
- **Wiring:** the ORCINUS router loads this skill when a web UI changes or ships — see the router's shared rules.
