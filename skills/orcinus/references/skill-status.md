# Skill status — GENERATED, do not edit by hand

Generated from `docs/MAP.md` by `scripts/generate_router_resources.py`.
Re-run the script after any change to `docs/MAP.md`.

The canonical MAP lives in the ORCINUS repo. This copy travels with the
router skill so a standalone install — which has no `docs/` — still has
the decision table. Never read the user's own `docs/MAP.md`: that is the
user's file, not ORCINUS's.

Status: `built` (in this install), `external-optional` (not in this repo;
the fallback is in `references/rules.md`, "Fallbacks for external-optional
skills"), `todo` (not built yet: say so plainly, do the closest covered
step, record the gap).

## A — Idea (0–9)

| Need | Best source | Status |
|---|---|---|
| Fleeting capture | — | built |
| Sharpen / brainstorm | egm-brainstorm, egm-draft | external-optional |
| Process / grill | grill-me / grilling | external-optional |
| Nurture / manage | phuryn/pm-skills: opportunity-solution-tree, hypothesis | built |
| Validate feasibility | phuryn/pm-skills: lean-validation, identify-assumptions | built |
| Launch decision | phuryn/pm-skills: pre-mortem, prioritization | built |
| Scope v1 / non-goals | improve (installed, advisor-only) | built |

## B — Architecture / Setup (10–19)

| Need | Best source | Status |
|---|---|---|
| Stack choice | stack-selector (lysandre001/skills-registry) | built |
| Project tree / invariants | github/spec-kit (specify init, constitution) | built |
| Codebase map | repomix | built |
| Scaffolding | create-mercato-app | built |
| Repo / git / PR | git-workflow-agent-skill (qubernetic) | built (basic: init + first commit) |
| Env / secrets setup | devops-secret-management (hexatonic-lab) | built (basic: .env.example + .gitignore) |
| Dependency licence | audit-license-compliance (sir-chawakorn/sanook-cli) | built |
| Authoring new skills | anthropics/skills: skill-creator | built |

## C — Coding (20–39)

| Need | Best source | Status |
|---|---|---|
| Clean code | wondelai/skills: clean-code | built |
| Task breakdown / slices | addyosmani/agent-skills: planning-and-task-breakdown; obra/superpowers: executing-plans | built |
| Step-by-step implementation | ponytail, tdd | external-optional |
| API design (MCP) | anthropics/skills: mcp-builder | built |
| API design (REST/GraphQL) | addyosmani/agent-skills: api-and-interface-design | built |
| API consumption / contract tests | stareezy-1/frontend-architecture-skill: skills/frontend-data-contracts | built |
| Breaking-change detection | oasdiff | built |
| State | stareezy-1/frontend-architecture-skill: skills/frontend-architecture + skills/frontend-optimistic-mutations | built |
| Database / schema / migration | alirezarezvani/claude-skills: engineering/skills/database-designer | built |
| i18n | Marvellbrazil/my-agentic-skills: i18n | built |
| Accessibility | maxgfr/ultra11y | built |

## D — Testing / Verification (40–59)

| Need | Best source | Status |
|---|---|---|
| Unit / integration | tdd | external-optional |
| E2E | anthropics/skills: webapp-testing | built |
| Mutation (JS/TS) | Stryker | built |
| Mutation beyond JS/TS | mutmut (boxed/mutmut) | built |
| Independent review | anthropics/claude-plugins-official: pr-review-toolkit | built |
| Evidence / eval | microsoft/waza | built |
| Benchmark | SWE-bench | todo |
| Sandbox runtime | SWE-agent/swe-rex | todo |
| Skill eval | openai/plugins: plugin-eval | todo |

## E — Security / Health (50–79, cross-cutting)

| Need | Best source | Status |
|---|---|---|
| Secrets scan | gitleaks/gitleaks | built |
| Prompt-injection defence | getsentry/skills: skill-scanner | built |
| Supply-chain | google/osv-scanner | built |
| Static analysis | trailofbits/skills: static-analysis | built (manual + Semgrep/CodeQL when available) |
| Performance budgets | addyosmani/agent-skills: performance-optimization | built |
| Health / monitoring | ericrisco/rsc-harness: monitoring | built |

## F — Debugging / Refactor (50–79, cross-cutting)

| Need | Best source | Status |
|---|---|---|
| Debugging loop | mattpocock/skills (engineering/diagnosing-bugs) | built |
| Tech-debt cleanup | ponytail-debt | external-optional |
| Simplification | pr-review-toolkit: code-simplifier | built |
| Incomplete refactoring | — | built |
| Generic refactoring | MuhiminOsim/code-refactoring-skill | built |

## G — Finalize / Post-publish (80–100)

| Need | Best source | Status |
|---|---|---|
| Docs / handoff | mattpocock/skills: handoff; dariohansson/claude-handoff | built |
| Long-context handoff | claude-handoff (dariohansson) | built |
| Onboarding contributor | OthmanAdi/codebase-knowledge-builder | built |
| Release | googleapis/release-please | built |
| Registry publish | — | built |
| Monitoring after publish | yonatangross/orchestkit: monitoring-observability | built |
| Bug triage / feedback | florianbruniaux/claude-code-plugins: plugins/pr-workflow/skills/issue-triage | built |
| Clarification / escalation | sickn33/antigravity-awesome-skills: ask-questions-if-underspecified | built |
| Visual regression | microsoft/playwright | built |
