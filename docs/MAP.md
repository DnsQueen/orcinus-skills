# MAP — 0 to 100

Every micro-step, its best proven source, its licence, and how it enters ORCINUS. Status: `built` (in v1), `covered` (already installed / routed to), `rewrite` (own words), `bundle` (separate licensed module in same install), `todo` (to be written from scratch).

Integration rule: MIT/Apache-2.0 may be copied verbatim with attribution. CC-BY-SA is rewritten or bundled as a separate module, never copied verbatim into an MIT file. Proprietary is reimplemented, never copied. Unverified licence = rewrite until verified.

## A — Idea (0–9)

| Need | Best source | Licence | Integration | Status |
|---|---|---|---|---|
| Fleeting capture | — | — | Write from scratch: skills/idea-capture + scripts/capture.py (Python, stdlib only), one Markdown file per idea in the project's ideas/ store | built |
| Sharpen / brainstorm | egm-brainstorm, egm-draft (installed) | Apache-2.0 | covered | covered |
| Process / grill | grill-me / grilling (installed) | MIT | covered | covered |
| Nurture / manage | phuryn/pm-skills: opportunity-solution-tree, hypothesis | MIT | own-words in idea-calibrate step 3 | built |
| Validate feasibility | phuryn/pm-skills: lean-validation, identify-assumptions | MIT | own-words in idea-calibrate step 4 | built |
| Launch decision | phuryn/pm-skills: pre-mortem, prioritization | MIT | own-words in idea-calibrate step 5 | built |
| Scope v1 / non-goals | improve (installed, advisor-only) | MIT | own-words in idea-calibrate step 6 | built |

## B — Architecture / Setup (10–19)

| Need | Best source | Licence | Integration | Status |
|---|---|---|---|---|
| Stack choice | stack-selector (lysandre001/skills-registry) | unverified | rewrite (own-words ADR in architecture step 1) | built |
| Project tree / invariants | github/spec-kit (specify init, constitution) | MIT | own-words in architecture (tree, invariants, layer rules) + scaffold step 2-3 | built |
| Codebase map | repomix | MIT | bundle (CLI, invoked as-is via npx in architecture step 4) | built |
| Scaffolding | create-mercato-app | MIT | own-words in scaffold | built |
| Repo / git / PR | git-workflow-agent-skill (qubernetic) | MIT claimed, LICENSE unverified | own-words in scaffold step 5 | built (basic: init + first commit) |
| Env / secrets setup | devops-secret-management (hexatonic-lab) | unverified | own-words in scaffold step 4 | built (basic: .env.example + .gitignore) |
| Dependency licence | audit-license-compliance (sir-chawakorn/sanook-cli) | unverified | rewrite (own-words licence check in architecture step 5 + checker) | built |
| Authoring new skills | anthropics/skills: skill-creator | Apache-2.0 | copied verbatim (19 files, frontmatter adapted to spec only), licence verified from the skill's own LICENSE.txt, commit ca45fc4 | built |

## C — Coding (20–39)

| Need | Best source | Licence | Integration | Status |
|---|---|---|---|---|
| Clean code | wondelai/skills: clean-code | MIT | own-words in build (ponytail: smallest complete change) | built |
| Task breakdown / slices | addyosmani/agent-skills: planning-and-task-breakdown; obra/superpowers: executing-plans | MIT | own-words in build step 1 | built |
| Step-by-step implementation | ponytail, tdd (installed) | MIT | covered, routed via build | covered |
| API design (MCP) | anthropics/skills: mcp-builder | Apache-2.0 | copy, keep LICENSE.txt | todo |
| API design (REST/GraphQL) | addyosmani/agent-skills: api-and-interface-design | MIT | copy | built |
| API consumption / contract tests | stareezy-1/frontend-architecture-skill: skills/frontend-data-contracts | MIT | copied verbatim (1 file, frontmatter licence normalized to MIT), licence verified from primary LICENSE, commit d7f0c53; the map's "write from scratch" plan was superseded — the skill was found after the first round | built |
| Breaking-change detection | oasdiff | Apache-2.0 | bundle (CLI), own-words wrapper, licence verified from primary LICENSE | built |
| State | stareezy-1/frontend-architecture-skill: skills/frontend-architecture + skills/frontend-optimistic-mutations | MIT | copied verbatim (1 file each, frontmatter licence normalized to MIT), licence verified from primary LICENSE, commit d7f0c53, 10 stars | built |
| Database / schema / migration | alirezarezvani/claude-skills: engineering/skills/database-designer | MIT | copied verbatim (15 files, frontmatter adapted to spec only) + one minimal fix to migration_generator.py (upstream bug: failed on any schema change), licence verified from primary LICENSE, commit 8f08254; scripts audited (stdlib only, no network/DB/exec) | built |
| i18n | Marvellbrazil/my-agentic-skills: i18n | MIT | copied verbatim (10 files, frontmatter adapted to spec only), licence verified from primary LICENSE, commit 42203fd | built |
| Accessibility | maxgfr/ultra11y | MIT | own-words wrapper + engine bundled as-is (upstream SKILL.md is 522 lines, over the spec's 500-line guidance, so not copied verbatim), licence verified from primary LICENSE, commit b245094 | built |

## D — Testing / Verification (40–59)

| Need | Best source | Licence | Integration | Status |
|---|---|---|---|---|
| Unit / integration | tdd (installed) | MIT | covered | covered |
| E2E | anthropics/skills: webapp-testing | Apache-2.0 | copied verbatim (6 files, frontmatter adapted to spec only), licence verified from the skill's own LICENSE.txt, commit ca45fc4 | built |
| Mutation (JS/TS) | Stryker | Apache-2.0 | own-words skill, Stryker used as-is (command runner for node:test), licence verified from primary LICENSE | built |
| Mutation beyond JS/TS | mutmut (boxed/mutmut) | BSD-3-Clause | own-words skill, mutmut used as-is (Python proof), licence verified from primary LICENSE, 3.8.1 | built |
| Independent review | anthropics/claude-plugins-official: pr-review-toolkit | Apache-2.0 | own-words skill, 6 reviewer agents + review-pr command bundled as-is, licence verified from the plugin's own LICENSE file (the README's "MIT" line is an error in the README) | built |
| Evidence / eval | microsoft/waza | MIT | skill injected verbatim + official v0.40.0 CLI as-is (binary not in repo), runnable suite evals/waza-orcinus-verify/ | built |
| Benchmark | SWE-bench | MIT | benchmark, not a skill | todo |
| Sandbox runtime | SWE-agent/swe-rex | MIT | bundle, container isolation only | todo |
| Skill eval | openai/plugins: plugin-eval | per-plugin, repo licence not declared | do not copy verbatim | todo |

## E — Security / Health (50–79, cross-cutting)

| Need | Best source | Licence | Integration | Status |
|---|---|---|---|---|
| Secrets scan | gitleaks/gitleaks | MIT | own-words in security-review (thin scan + gitleaks when installed) | built |
| Prompt-injection defence | getsentry/skills: skill-scanner | Apache-2.0 | own-words in security-review step 3 | built |
| Supply-chain | google/osv-scanner | Apache-2.0 | own-words in security-review step 4 (npm audit + osv-scanner when installed) | built |
| Static analysis | trailofbits/skills: static-analysis | CC-BY-SA-4.0 | own-words in security-review step 5, never copied | built (manual + Semgrep/CodeQL when available) |
| Performance budgets | addyosmani/agent-skills: performance-optimization | MIT | copy | built |
| Health / monitoring | ericrisco/rsc-harness: monitoring | MIT | copied verbatim (6 files, frontmatter adapted to spec), licence verified from primary LICENSE, commit 111532c; the outside view (probes, SLO burn, on-call) — complements monitoring-observability (the telemetry side) | built |

## F — Debugging / Refactor (50–79)

| Need | Best source | Licence | Integration | Status |
|---|---|---|---|---|
| Debugging loop | diagnosing-bugs (installed) | MIT | covered | covered |
| Tech-debt cleanup | ponytail-debt (installed) | MIT | covered | covered |
| Simplification | pr-review-toolkit: code-simplifier | Apache-2.0 | code-simplifier agent bundled as-is in independent-review (runs after a review passes); no separate SKILL.md written | built |
| Incomplete refactoring | — | — | Write from scratch (detector for orphaned consumers) | built |
| Generic refactoring | MuhiminOsim/code-refactoring-skill | MIT | skill + 11 references injected verbatim, licence verified from primary LICENSE (Copyright 2026 Muhiminul Islam Osim), 12 stars, content read and checked before copying | built |

## G — Finalize / Post-publish (80–100)

| Need | Best source | Licence | Integration | Status |
|---|---|---|---|---|
| Docs / handoff | handoff (installed); anthropics/skills: doc-coauthoring (licence unclear) | MIT / unclear | covered; rewrite doc-coauthoring | covered |
| Long-context handoff | claude-handoff (dariohansson) | MIT | merge into installed handoff | todo |
| Onboarding contributor | codebase-onboarding (kart-rc) | unverified | rewrite | todo |
| Release | googleapis/release-please | Apache-2.0 | used as-is in finalize (CLI + Action), licence verified from primary LICENSE | built |
| Registry publish | — | — | Write from scratch (release-please does not publish to registries) | built |
| Monitoring after publish | yonatangross/orchestkit: monitoring-observability | MIT | copied verbatim (28 files, frontmatter adapted to spec only), licence verified from primary LICENSE, commit 016aefa | built |
| Bug triage / feedback | florianbruniaux: issue-triage | CC-BY-SA-4.0 | separate module, not verbatim into MIT | todo |
| Clarification / escalation | sickn33/antigravity-awesome-skills: ask-questions-if-underspecified | MIT | copied verbatim (1 file, frontmatter adapted to spec only), licence verified from primary LICENSE, commit 739c841 | built |
| Visual regression | microsoft/playwright | Apache-2.0 | own-words wrapper, Playwright used as-is, licence verified from primary LICENSE | built |

## Must write from scratch (v1 or v2)

(none remaining — every item on this list now has a proven answer.)

Built already (kept here for the record, not as remaining work): dedicated incomplete-refactor detector, package-registry publish, resilient API client consumption and contract-test execution (answered by frontend-data-contracts, injected verbatim), mutation testing beyond JS/TS (answered by mutation-testing-python, mutmut as-is), fleeting raw-idea capture store (answered by idea-capture, with a script), dedicated performance/health skill (answered by monitoring, injected verbatim from rsc-harness, with a proven eval).

## Do not use

- `openai/skills` — deprecated, points to `openai/plugins`.
- Anthropic document skills (`docx`/`pdf`/`pptx`/`xlsx`) — proprietary / source-available, not open source.
- `anthropics/claude-plugins-official` code-review plugin — Apache-2.0 (its own LICENSE file, verified 2026-11-06; the old note calling it proprietary was wrong — that claim was about a different repo, `anthropics/claude-code`, not this plugin). Not bundled: pr-review-toolkit already provides the independent-review capability, and bundling both would duplicate it. Its parallel-review + confidence-filter pattern is a future alternative, not a current gap.
- Any candidate whose LICENSE was not read directly — rewrite until verified.

## Sources that shaped this map

Anthropic: Effective Harnesses for Long-Running Agents (26 Nov 2025); Agent Skills; code-review / pr-review-toolkit. OpenAI: Harness Engineering (11 Feb 2026); How We Monitor Internal Coding Agents (Mar 2026); plugin-eval. Columbia DAPLab: 9 Critical Failure Patterns (8 Jan 2026). METR: Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity (arXiv:2507.09089). Microsoft: Waza, AgentRC (experimental). Trail of Bits, Sentry, SWE-bench, SWE-ReX.
