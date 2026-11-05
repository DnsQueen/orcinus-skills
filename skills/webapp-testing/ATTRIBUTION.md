# ATTRIBUTION — webapp-testing

This skill was copied verbatim from a ready-made, community-tested skill, as agreed: when a skill already answers the need, ORCINUS uses it as-is instead of rewriting it.

- **Source:** https://github.com/anthropics/skills — `skills/webapp-testing/`
- **Licence:** Apache-2.0 — see `LICENSE.txt` in this folder (upstream Apache License, Version 2.0, copied from the skill folder). Note the licence split in the upstream repo: the example skills (including this one) are Apache-2.0; the document skills (pdf, docx, pptx, xlsx) are proprietary/source-available and were NOT copied.
- **Upstream commit:** `ca45fc496a3436251f191354091d557da31c15b5` (2026-10-28, "Update mcp-builder skill: teach v2 of the MCP TypeScript SDK (#2087)")
- **Files copied:** 6 files (SKILL.md, LICENSE.txt, examples/console_logging.py, examples/element_discovery.py, examples/static_html_automation.py, scripts/with_server.py), verified identical to upstream with `diff -r` before the copy. A secret-pattern scan of the copied files found nothing.
- **What changed:** only the frontmatter of `SKILL.md` was adapted to the Agent Skills spec (kept `name` and `description`; changed `license: Complete terms in LICENSE.txt` to `license: Apache-2.0`, the actual licence). The description text and the entire body are byte-for-byte identical to upstream (verified programmatically).
- **Scope note:** this skill tests local web applications with Playwright (Python) and needs a browser. Upstream says these skills are for demonstration/education and should be tested in the user's own environment before being relied on for critical work.
