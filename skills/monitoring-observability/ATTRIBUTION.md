# ATTRIBUTION — monitoring-observability

This skill was copied from a ready-made, community-tested skill — verbatim body, ORCINUS frontmatter — as agreed: when a skill already answers the need, ORCINUS uses it as-is instead of rewriting it.

- **Source:** https://github.com/yonatangross/orchestkit — `src/skills/monitoring-observability/`
- **Author:** OrchestKit
- **Licence:** MIT — see `LICENSE.txt` in this folder (upstream MIT License, Copyright (c) 2026 OrchestKit Contributors, copied from the upstream repo root).
- **Upstream commit:** `016aefaf62a31bb27e58106c22a13d3e4140ad62` (2026-11-05, "chore(release): pin stable channel to v10.9.0 (#5074)")
- **Upstream version:** 3.0.0 (upstream-version-tested: Langfuse 4.16.0)
- **Files copied:** all 28 files (SKILL.md, references/, rules/, examples/, scripts/, metadata.json, test-cases.json), verified identical to upstream with `diff -r` before and after the copy. A secret-pattern scan of the copied files found nothing.
- **What changed:** only the frontmatter of `SKILL.md` was adapted to the Agent Skills spec (kept `name`, `description`, `license`; removed Claude-Code-only fields such as `compatibility`, `allowed-tools`, `user-invocable`, `disable-model-invocation`, `targets`, `path_patterns`, and `metadata`). The body is byte-for-byte identical to upstream (verified programmatically). The description is the upstream description with the ORCINUS router-only note appended ('Only invoke via the orcinus router.').
- **user-invocable, restored 2026-11-06 (round 3):** frontmatter gained `user-invocable: false` — this restores the upstream value (upstream marks this skill `user-invocable: false`); the earlier adaptation had removed the field to keep the frontmatter spec-pure, but one-install routing needs every sub-skill hidden from the `/` menu. `disable-model-invocation: true` stays removed: the router must be able to invoke this skill itself.
- **Invocation intent (preserved):** upstream marks this skill `user-invocable: false` and `disable-model-invocation: true` — it is a reference skill, loaded by other skills when monitoring is needed, not an entry point the user invokes directly. ORCINUS keeps that intent: the `finalize` skill loads it when a project uses Prometheus, Grafana, Langfuse, or LLM tracing.
- **Scope note:** this skill is specialised for Prometheus metrics, Grafana dashboards, OpenTelemetry, and Langfuse LLM tracing (plus drift detection and silent-failure alerting). It is not a generic health check for every project. When a project does not use those stacks, `finalize` says so and uses minimal health signals instead of claiming this skill applies.
