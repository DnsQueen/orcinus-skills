# ADR 0001 — One integrated nervous system, one install

Date: 2026-11-05
Status: accepted

## Context

A collection of 36 skills could be shipped as a list of independent
skills, each fetched on demand. That is the easy shape: the user
installs a skill when they need it, and the skills never talk to each
other. But the lifecycle (idea 0 → finalize 100) is one continuous
flow, and the stages share language (the glossary), gates (the
evidence bundle), and state (what is verified, what is not). A
skill-dump would make the user re-establish that context at every
stage boundary.

## Decision

ORCINUS is one integrated nervous system, installed whole, in one
install. The router (`skills/orcinus`) loads the focused sub-skills
internally; the user never fetches a sub-skill mid-work. The shared
glossary (`skills/orcinus/references/GLOSSARY.md`), the shared rules
(`skills/orcinus/references/rules.md`), and the evidence bundle
(`skills/orcinus-verify/references/evidence.schema.json`) are the nervous system's common
language — every sub-skill speaks it.

## Consequences

- Good: stage transitions keep their context (a verified slice stays
  verified; a finding stays attached to its file and line). A new
  skill is wired into the router, the manifest, the map, and the
  validator, or it is not part of the system.
- Good: the install is one command (`npx skills@latest add
  DnsQueen/orcinus-skills --all`), not 36.
- Bad: the router is a single point of coupling — a wrong route
  misdirects a whole stage. Mitigated by the validator's stage-range
  and manifest checks and by the router's own eval.
- Bad: the repo is larger than a single skill. Accepted: the size is
  the system, not bloat.
