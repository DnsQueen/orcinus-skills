# ADR 0003 — Use ready skills verbatim, with attribution, or rewrite

Date: 2026-11-05
Status: accepted

## Context

The 0–100 lifecycle needs many capabilities (capture, architecture,
testing, security, refactor, publish). Most already exist as
community-tested skills. Rewriting them would duplicate work and
lose the testing they already carry. Copying them without checking
the licence would violate it.

## Decision

When a skill already answers the need, ORCINUS uses that same skill —
it does not rewrite it. The rule, by licence:

- **MIT / Apache-2.0:** copy verbatim, with attribution
  (`ATTRIBUTION.md` + the upstream `LICENSE.txt` in the skill folder).
  Adapt only the frontmatter to the Agent Skills spec (keep the name
  and the upstream description verbatim, set the real licence).
- **CC-BY-SA:** bundle as a separate licensed module, or rewrite in
  own words. Never copy verbatim into an MIT file.
- **Proprietary / unclear / unverified:** rewrite from scratch.
  Never copy verbatim until the candidate's primary LICENSE is read
  directly.
- **Tools (CLIs, binaries):** use as-is, never copy. The skill
  instructs the agent to install the tool from its official release
  and to verify the checksum.

Every injection is verified: the primary LICENSE is read live first,
the files are fetched exactly, `diff -r` confirms they are identical
to upstream, a secret-pattern scan runs, and the skill gets a real
eval before it is wired into the router.

## Consequences

- Good: 20 of the 36 skills are proven upstream work, not rewrites.
  The collection inherits their testing.
- Good: the drift check (`scripts/check_drift.py`) catches any
  accidental change to a vendored file — 128 files, byte-identical.
- Bad: vendored files carry upstream style (unused imports, f-strings
  without placeholders) that the linter would flag. Accepted: the
  ruff config excludes pure vendored copies. `migration_generator.py`
  is the exception — ORCINUS maintains it with fixes, so it is
  linted and its drift hash is updated when it changes.
- Bad: an upstream skill can be wrong, outdated, or a bad fit. The
  eval for each skill is the check, and the skill's ATTRIBUTION.md
  records the limits found.
