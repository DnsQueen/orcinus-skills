# SCOPE

## In v1

- One entry and router (`skills/orcinus`).
- One flagship verification skill (`skills/orcinus-verify`).
- One idea-calibration skill (`skills/idea-calibrate`), with a scored eval (`evals/idea-calibrate-01.md`).
- One scaffold skill (`skills/scaffold`), with a scored eval (`evals/scaffold-01.md`) proven on a real demo project.
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
