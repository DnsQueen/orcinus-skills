# Third-Party Notices

ORCINUS is mostly original work (MIT, see `LICENSE`). The skills below
contain or depend on third-party content. Each skill's own
`ATTRIBUTION.md` records the upstream source, the exact commit or
version, and what changed; this file is the central index. The
licence in the table is the upstream content's licence.

| Skill | Upstream source | Licence | What was taken |
|---|---|---|---|
| accessibility | maxgfr/ultra11y | MIT | The ultra11y engine (`scripts/ultra11y.mjs`), bundled byte-identical; the method is ORCINUS's own words. |
| api-and-interface-design | addyosmani/agent-skills | MIT | `skills/api-and-interface-design/` copied verbatim (370 lines). |
| ask-questions-if-underspecified | sickn33/Agentic-Awesome-Skills | MIT | The skill copied verbatim. |
| breaking-change | oasdiff/oasdiff | Apache-2.0 | The oasdiff CLI, used as-is (no code copied); the method is ORCINUS's own words. |
| codebase-knowledge-builder | OthmanAdi/codebase-knowledge-builder | MIT | The skill copied verbatim, with 2 references and 1 template. |
| database-designer | alirezarezvani/claude-skills | MIT | `engineering/skills/database-designer/` copied verbatim (15 files), with ORCINUS fixes to the migration generator (see the skill's ATTRIBUTION.md). |
| diagnosing-bugs | mattpocock/skills | MIT | `skills/engineering/diagnosing-bugs/` copied verbatim (SKILL.md + hitl-loop template); the OpenAI agent definition was not copied. |
| frontend-architecture | stareezy-1/frontend-architecture-skill | MIT | The skill copied verbatim (406 lines). |
| frontend-data-contracts | stareezy-1/frontend-architecture-skill | MIT | The skill copied verbatim (318 lines). |
| frontend-optimistic-mutations | stareezy-1/frontend-architecture-skill | MIT | The skill copied verbatim (265 lines). |
| handoff | mattpocock/skills and dariohansson/claude-handoff | MIT | Two MIT handoff skills merged into one, written in own words; neither upstream SKILL.md was copied verbatim. |
| i18n | Marvellbrazil/my-agentic-skills | MIT | The skill copied verbatim, with 9 references. |
| independent-review | anthropics/claude-plugins-official | Apache-2.0 | The pr-review-toolkit plugin's 6 reviewer agents and 1 command, bundled as-is; the method is ORCINUS's own words. |
| issue-triage | florianbruniaux/claude-code-plugins | MIT | `plugins/pr-workflow/skills/issue-triage/` copied verbatim, with 1 template. |
| mcp-builder | anthropics/skills | Apache-2.0 | `skills/mcp-builder/` copied verbatim (SKILL.md, 5 references, 4 scripts). |
| monitoring | ericrisco/rsc-harness | MIT | `skills/monitoring/` copied verbatim (6 files). |
| monitoring-observability | yonatangross/orchestkit | MIT | The skill copied verbatim. |
| performance-optimization | addyosmani/agent-skills | MIT | `skills/performance-optimization/` copied verbatim. |
| refactor | MuhiminOsim/code-refactoring-skill | MIT | The skill copied verbatim, with 11 references. |
| skill-creator | anthropics/skills | Apache-2.0 | `skills/skill-creator/` copied verbatim (19 files). |
| waza | microsoft/waza | MIT | The skill copied verbatim (214 lines). The waza CLI binary itself is NOT in this repo; install it from the official v0.40.0 release, checksum-verified. |
| webapp-testing | anthropics/skills | Apache-2.0 | `skills/webapp-testing/` copied verbatim, with `scripts/with_server.py`. |

## Notes

- The repo's own `LICENSE` is the plain MIT template. It covers the
  ORCINUS-original work (the router, the from-scratch skills, the
  docs, the scripts written for this repo). Subfolders that bundle
  third-party content carry their own `LICENSE.txt`; see the table
  above and each skill's `ATTRIBUTION.md`.
- **mcp-builder, skill-creator, webapp-testing:** the upstream repo
  (anthropics/skills) has a split licence — the example skills are
  Apache-2.0, the document skills are proprietary. Each of these three
  is one of the Apache-2.0 example skills, verified from its own
  `LICENSE.txt`. The table above records the licence of the content
  actually taken (Apache-2.0); the per-skill `ATTRIBUTION.md` records
  the split.
- **independent-review:** the bundled agents and command are
  Apache-2.0, while the method text is ORCINUS's own words (MIT).
  The skill's frontmatter licence is MIT (the text); the bundled
  files' Apache-2.0 licence is in `LICENSE.txt` and in
  `ATTRIBUTION.md`.
- **breaking-change:** the oasdiff CLI is Apache-2.0 and is used
  as-is; no oasdiff code is in this repo. The skill's own text is MIT.
- Run `python3 scripts/validate_repo.py` to check this file against
  every skill's `ATTRIBUTION.md` and frontmatter.
