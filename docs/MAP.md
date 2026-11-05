# MAP — 0 to 100

Every micro-step, its best proven source, its licence, and how it enters ORCINUS. Status: `built` (in v1), `covered` (already installed / routed to), `rewrite` (own words), `bundle` (separate licensed module in same install), `todo` (to be written from scratch).

Integration rule: MIT/Apache-2.0 may be copied verbatim with attribution. CC-BY-SA is rewritten or bundled as a separate module, never copied verbatim into an MIT file. Proprietary is reimplemented, never copied. Unverified licence = rewrite until verified.

## A — Idea (0–9)

| Need | Best source | Licence | Integration | Status |
|---|---|---|---|---|
| Fleeting capture | — | — | Write from scratch (persistent store); in-session capture is in idea-calibrate step 1 | built (in-session), todo (store) |
| Sharpen / brainstorm | egm-brainstorm, egm-draft (installed) | Apache-2.0 | covered | covered |
| Process / grill | grill-me / grilling (installed) | MIT | covered | covered |
| Nurture / manage | phuryn/pm-skills: opportunity-solution-tree, hypothesis | MIT | own-words in idea-calibrate step 3 | built |
| Validate feasibility | phuryn/pm-skills: lean-validation, identify-assumptions | MIT | own-words in idea-calibrate step 4 | built |
| Launch decision | phuryn/pm-skills: pre-mortem, prioritization | MIT | own-words in idea-calibrate step 5 | built |
| Scope v1 / non-goals | improve (installed, advisor-only) | MIT | own-words in idea-calibrate step 6 | built |

## B — Architecture / Setup (10–19)

| Need | Best source | Licence | Integration | Status |
|---|---|---|---|---|
| Stack choice | stack-selector (lysandre001/skills-registry) | unverified | rewrite | todo |
| Project tree / invariants | github/spec-kit (specify init, constitution) | MIT | own-words in scaffold step 2-3 | built |
| Codebase map | repomix | MIT | bundle (CLI) | todo |
| Scaffolding | create-mercato-app | MIT | own-words in scaffold | built |
| Repo / git / PR | git-workflow-agent-skill (qubernetic) | MIT claimed, LICENSE unverified | own-words in scaffold step 5 | built (basic: init + first commit) |
| Env / secrets setup | devops-secret-management (hexatonic-lab) | unverified | own-words in scaffold step 4 | built (basic: .env.example + .gitignore) |
| Dependency licence | audit-license-compliance (sir-chawakorn/sanook-cli) | unverified | rewrite | todo |
| Authoring new skills | anthropics/skills: skill-creator | Apache-2.0 | copy, keep LICENSE.txt | todo |

## C — Coding (20–39)

| Need | Best source | Licence | Integration | Status |
|---|---|---|---|---|
| Clean code | wondelai/skills: clean-code | MIT | own-words in build (ponytail: smallest complete change) | built |
| Task breakdown / slices | addyosmani/agent-skills: planning-and-task-breakdown; obra/superpowers: executing-plans | MIT | own-words in build step 1 | built |
| Step-by-step implementation | ponytail, tdd (installed) | MIT | covered, routed via build | covered |
| API design (MCP) | anthropics/skills: mcp-builder | Apache-2.0 | copy, keep LICENSE.txt | todo |
| API design (REST/GraphQL) | addyosmani/agent-skills: api-and-interface-design | MIT | copy | todo |
| API consumption / contract tests | — | — | Write from scratch | todo |
| Breaking-change detection | oasdiff | Apache-2.0 | bundle (CLI), own-words wrapper | todo |
| State | frontend-architecture (stareezy-1) | MIT, 10 stars | copy, with caution | todo |
| Database / schema / migration | database-designer (alirezarezvani) | MIT | copy, audit scripts first | todo |
| i18n | Marvellbrazil/my-agentic-skills: i18n | MIT | copy single skill only | todo |
| Accessibility | maxgfr/ultra11y | MIT | copy | todo |

## D — Testing / Verification (40–59)

| Need | Best source | Licence | Integration | Status |
|---|---|---|---|---|
| Unit / integration | tdd (installed) | MIT | covered | covered |
| E2E | anthropics/skills: webapp-testing | Apache-2.0 | copy, keep LICENSE.txt | todo |
| Mutation (JS/TS) | Stryker | Apache-2.0 | bundle (CLI) | todo |
| Mutation beyond JS/TS | — | — | Write from scratch / per-language CLI unverified | todo |
| Independent review | anthropics/claude-plugins-official: pr-review-toolkit | MIT vs Apache-2.0 — verify per-plugin LICENSE.txt | copy after check | todo |
| Evidence / eval | microsoft/waza | MIT | bundle (CLI) | todo |
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
| Performance budgets | addyosmani/agent-skills: performance-optimization | MIT | copy | todo |
| Health / monitoring | ericrisco/rsc-harness: monitoring | MIT per secondary, verify LICENSE | copy after verify | todo |

## F — Debugging / Refactor (50–79)

| Need | Best source | Licence | Integration | Status |
|---|---|---|---|---|
| Debugging loop | diagnosing-bugs (installed) | MIT | covered | covered |
| Tech-debt cleanup | ponytail-debt (installed) | MIT | covered | covered |
| Simplification | pr-review-toolkit: code-simplifier; getsentry: code-simplifier | Apache-2.0 | rewrite as SKILL.md | todo |
| Incomplete refactoring | — | — | Write from scratch (detector for orphaned consumers) | todo |
| Generic refactoring | MuhiminOsim/code-refactoring-skill | MIT, 12 stars | copy, with caution | todo |

## G — Finalize / Post-publish (80–100)

| Need | Best source | Licence | Integration | Status |
|---|---|---|---|---|
| Docs / handoff | handoff (installed); anthropics/skills: doc-coauthoring (licence unclear) | MIT / unclear | covered; rewrite doc-coauthoring | covered |
| Long-context handoff | claude-handoff (dariohansson) | MIT | merge into installed handoff | todo |
| Onboarding contributor | codebase-onboarding (kart-rc) | unverified | rewrite | todo |
| Release | googleapis/release-please | Apache-2.0 | used as-is in finalize (CLI + Action), licence verified from primary LICENSE | built |
| Registry publish | — | — | Write from scratch (release-please does not publish to registries) | todo |
| Monitoring after publish | yonatangross/orchestkit: monitoring-observability | MIT | copied verbatim (28 files, frontmatter adapted to spec only), licence verified from primary LICENSE, commit 016aefa | built |
| Bug triage / feedback | florianbruniaux: issue-triage | CC-BY-SA-4.0 | separate module, not verbatim into MIT | todo |
| Clarification / escalation | sickn33/antigravity-awesome-skills: ask-questions-if-underspecified | MIT | copy | todo |
| Visual regression | microsoft/playwright | Apache-2.0 | own-words wrapper, do not copy code | todo |

## Must write from scratch (v1 or v2)

- Fleeting raw-idea capture store.
- Resilient API client consumption and contract-test execution.
- Dedicated incomplete-refactor detector.
- Mutation testing beyond JS/TS.
- Package-registry publish.
- Dedicated performance/health skill (candidate found in second round; still needs a proven eval).

## Do not use

- `openai/skills` — deprecated, points to `openai/plugins`.
- Anthropic document skills (`docx`/`pdf`/`pptx`/`xlsx`) — proprietary / source-available, not open source.
- `anthropics/claude-code` code-review — proprietary ("All rights reserved"); rewrite its parallel-review + confidence pattern if used.
- Any candidate whose LICENSE was not read directly — rewrite until verified.

## Sources that shaped this map

Anthropic: Effective Harnesses for Long-Running Agents (26 Nov 2025); Agent Skills; code-review / pr-review-toolkit. OpenAI: Harness Engineering (11 Feb 2026); How We Monitor Internal Coding Agents (Mar 2026); plugin-eval. Columbia DAPLab: 9 Critical Failure Patterns (8 Jan 2026). METR: Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity (arXiv:2507.09089). Microsoft: Waza, AgentRC (experimental). Trail of Bits, Sentry, SWE-bench, SWE-ReX.
