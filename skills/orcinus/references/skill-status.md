# Skill status — GENERATED, do not edit by hand

Generated from `docs/MAP.md` by `scripts/generate_router_resources.py`.
Re-run the script after any change to `docs/MAP.md`.

The canonical MAP lives in the ORCINUS repo. This copy travels with the
router skill so a standalone install — which has no `docs/` — still has
the decision table. Never read the user's own `docs/MAP.md`: that is the
user's file, not ORCINUS's.

Status: `built` (the need is covered in this install), `external-optional`
(not in this repo; the fallback is in `references/rules.md`, "Fallbacks for
external-optional skills"), `todo` (not built yet: say so plainly, do the
closest covered step, record the gap).

`Best source` is the source of inspiration for the need — it may be an
external tool that is not installed here. `Implemented in` names the
ORCINUS skill folder(s) that cover the need in this install (for an
external-optional row, the skill the router falls back to; `—` when
nothing covers it yet). A `built` row always names a real folder: the
validator checks it.

## A — Idea (0–9)

| Need | Best source | Implemented in | Status |
|---|---|---|---|
| Fleeting capture | — | idea-capture | built |
| Sharpen / brainstorm | egm-brainstorm, egm-draft | idea-calibrate | external-optional |
| Process / grill | grill-me / grilling | idea-calibrate | external-optional |
| Nurture / manage | phuryn/pm-skills: opportunity-solution-tree, hypothesis | idea-calibrate | built |
| Validate feasibility | phuryn/pm-skills: lean-validation, identify-assumptions | idea-calibrate | built |
| Launch decision | phuryn/pm-skills: pre-mortem, prioritization | idea-calibrate | built |
| Scope v1 / non-goals | improve (installed, advisor-only) | idea-calibrate | built |

## B — Architecture / Setup (10–19)

| Need | Best source | Implemented in | Status |
|---|---|---|---|
| Stack choice | stack-selector (lysandre001/skills-registry) | architecture | built |
| Project tree / invariants | github/spec-kit (specify init, constitution) | architecture, scaffold | built |
| Codebase map | repomix | architecture | built |
| Scaffolding | create-mercato-app | scaffold | built |
| Repo / git / PR | git-workflow-agent-skill (qubernetic) | scaffold | built (basic: init + first commit) |
| Env / secrets setup | devops-secret-management (hexatonic-lab) | scaffold | built (basic: .env.example + .gitignore) |
| Dependency licence | audit-license-compliance (sir-chawakorn/sanook-cli) | architecture | built |
| Authoring new skills | anthropics/skills: skill-creator | skill-creator | built |

## C — Coding (20–39)

| Need | Best source | Implemented in | Status |
|---|---|---|---|
| Clean code | wondelai/skills: clean-code | build | built |
| Task breakdown / slices | addyosmani/agent-skills: planning-and-task-breakdown; obra/superpowers: executing-plans | build | built |
| Step-by-step implementation | ponytail, tdd | build | external-optional |
| API design (MCP) | anthropics/skills: mcp-builder | mcp-builder | built |
| API design (REST/GraphQL) | addyosmani/agent-skills: api-and-interface-design | api-and-interface-design | built |
| API consumption / contract tests | stareezy-1/frontend-architecture-skill: skills/frontend-data-contracts | frontend-data-contracts | built |
| Breaking-change detection | oasdiff | breaking-change | built |
| State | stareezy-1/frontend-architecture-skill: skills/frontend-architecture + skills/frontend-optimistic-mutations | frontend-architecture, frontend-optimistic-mutations | built |
| Database / schema / migration | alirezarezvani/claude-skills: engineering/skills/database-designer | database-designer | built |
| i18n | Marvellbrazil/my-agentic-skills: i18n | i18n | built |
| Accessibility | maxgfr/ultra11y | accessibility | built |

## D — Testing / Verification (40–59)

| Need | Best source | Implemented in | Status |
|---|---|---|---|
| Unit / integration | tdd | build | external-optional |
| E2E | anthropics/skills: webapp-testing | webapp-testing | built |
| Mutation (JS/TS) | Stryker | mutation-testing | built |
| Mutation beyond JS/TS | mutmut (boxed/mutmut) | mutation-testing-python | built |
| Independent review | anthropics/claude-plugins-official: pr-review-toolkit | independent-review | built |
| Evidence / eval | microsoft/waza | waza | built |
| Benchmark | SWE-bench | — | todo |
| Sandbox runtime | SWE-agent/swe-rex | — | todo |
| Skill eval | openai/plugins: plugin-eval | — | todo |

## E — Security / Health (50–79, cross-cutting)

| Need | Best source | Implemented in | Status |
|---|---|---|---|
| Secrets scan | gitleaks/gitleaks | security-review | built |
| Prompt-injection defence | getsentry/skills: skill-scanner | security-review | built |
| Supply-chain | google/osv-scanner | security-review | built |
| Static analysis | trailofbits/skills: static-analysis | security-review | built (manual + Semgrep/CodeQL when available) |
| Performance budgets | addyosmani/agent-skills: performance-optimization | performance-optimization | built |
| Health / monitoring | ericrisco/rsc-harness: monitoring | monitoring | built |

## F — Debugging / Refactor (50–79, cross-cutting)

| Need | Best source | Implemented in | Status |
|---|---|---|---|
| Debugging loop | mattpocock/skills (engineering/diagnosing-bugs) | diagnosing-bugs | built |
| Tech-debt cleanup | ponytail-debt | refactor | external-optional |
| Simplification | pr-review-toolkit: code-simplifier | independent-review | built |
| Incomplete refactoring | — | refactor | built |
| Generic refactoring | MuhiminOsim/code-refactoring-skill | refactor | built |

## G — Finalize / Post-publish (80–100)

| Need | Best source | Implemented in | Status |
|---|---|---|---|
| Docs / handoff | mattpocock/skills: handoff; dariohansson/claude-handoff | handoff | built |
| Long-context handoff | claude-handoff (dariohansson) | handoff | built |
| Onboarding contributor | OthmanAdi/codebase-knowledge-builder | codebase-knowledge-builder | built |
| Release | googleapis/release-please | finalize | built |
| Registry publish | — | registry-publish | built |
| Monitoring after publish | yonatangross/orchestkit: monitoring-observability | monitoring-observability | built |
| Bug triage / feedback | florianbruniaux/claude-code-plugins: plugins/pr-workflow/skills/issue-triage | issue-triage | built |
| Clarification / escalation | sickn33/antigravity-awesome-skills: ask-questions-if-underspecified | ask-questions-if-underspecified | built |
| Visual regression | microsoft/playwright | visual-regression | built |
