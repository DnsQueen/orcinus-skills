# SCOPE

## In v1

- One entry and router (`skills/orcinus`).
- One flagship verification skill (`skills/orcinus-verify`).
- One idea-calibration skill (`skills/idea-calibrate`), with a scored eval (`evals/idea-calibrate-01.md`).
- One scaffold skill (`skills/scaffold`), with a scored eval (`evals/scaffold-01.md`) proven on a real demo project.
- One build skill (`skills/build`), with a scored eval (`evals/build-01.md`) proven on the demo project.
- One security-review skill (`skills/security-review`), with a scored eval (`evals/security-review-01.md`) proven on the demo project and on a planted fake secret.
- One finalize skill (`skills/finalize`), with a scored eval (`evals/finalize-01.md`) proven as a dry-run release on the demo project, using ready tools as-is (release-please, Waza, handoff, monitoring-observability).
- One injected ready skill (`skills/monitoring-observability`), copied verbatim from OrchestKit (MIT, 28 files, frontmatter adapted to the Agent Skills spec only), with its `ATTRIBUTION.md` and `LICENSE.txt`.
- One injected ready skill (`skills/ask-questions-if-underspecified`), copied verbatim from Agentic Awesome Skills (MIT, 1 file, frontmatter adapted to the Agent Skills spec only), with its `ATTRIBUTION.md` and `LICENSE.txt`, and wired into the router's shared rules and routing table. Eval (`evals/ask-questions-01.md`) passed on 4 real cases.
- One injected ready skill (`skills/webapp-testing`), copied verbatim from Anthropic (Apache-2.0, 6 files, frontmatter adapted to the Agent Skills spec only), with its `ATTRIBUTION.md` and `LICENSE.txt`, and wired into the router's shared rules. Eval (`evals/webapp-testing-01.md`) passed on a real Chromium E2E run (6/6).
- One mutation-testing skill (`skills/mutation-testing`), written in our own words, using Stryker as-is (Apache-2.0). Eval (`evals/mutation-testing-01.md`) passed on a real Stryker run on the demo (score 100.00, 26 killed, 0 survived, 0 timeout).
- One visual-regression skill (`skills/visual-regression`), written in our own words, using Playwright as-is (Apache-2.0). Eval (`evals/visual-regression-01.md`) passed on a real screenshot comparison on the demo page (0.00% unchanged, 2.70% on a visual change, 0.00% after a confirmed baseline update).
- One performance-optimization skill (`skills/performance-optimization`), copied verbatim from addyosmani/agent-skills (MIT). Eval (`evals/performance-optimization-01.md`) passed on real timings on the demo (page load mean 0.108s vs a 2.5s budget, `npm test` mean ~4768ms vs a 10s budget; a deliberate 3s delay measured 3.040s and was flagged as a regression; after revert the load was 0.122s again).
- One api-and-interface-design skill (`skills/api-and-interface-design`), copied verbatim from addyosmani/agent-skills (MIT). Eval (`evals/api-and-interface-design-01.md`) passed on a real live server built from the demo (valid request 200 with the exact body, invalid input 422 with the structured error shape, list endpoint paginated; a breaking-change proposal and a bare-array list design were both flagged and rejected).
- The full 0–100 map (`docs/MAP.md`) with source, licence, and integration method for every micro-step.
- Shared glossary and boundaries.
- Eval scenarios for the flagship, run on a demo repo.

## Out of v1

- Full implementations of every sub-skill in the map. They are added one at a time, each proven before it ships.
- Auto-merge, auto-publish to a registry, and any irreversible action without human approval.
- A claim that ORCINUS makes any model correct. ORCINUS makes mistakes checkable; it does not remove them.

## Foundation complete means

- The router, gates, glossary, evidence bundle, and eval harness exist.
- Every stage 0–100 has a present entry in the map — no empty stage.
- Some sub-skills are thin in v1. Depth grows in later versions; the structure does not change.

## Non-goals

- A dump of 2,000 skills to pick from. ORCINUS is one unit.
- Copying CC-BY-SA or proprietary text verbatim into MIT files.
- Rebuilding what ponytail, tdd, and diagnosing-bugs already do well. ORCINUS routes to them where they fit and focuses new work on the gaps: independent verification, security, and eval.
