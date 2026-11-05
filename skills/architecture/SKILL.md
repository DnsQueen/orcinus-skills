---
name: architecture
description: Define a project's architecture before any code is written — stack choice as a decision record, file tree and invariants, public contract, layer rules, and dependency licences — and enforce it with a checker. Use when a calibrated brief exists and the project does not yet have a written architecture, or when a structural change is proposed. No code before the architecture is written.
---

# ARCHITECTURE — decide the shape before building it

Most of the 31 common coding-agent mistakes are architecture mistakes made early: a stack chosen silently, a tree that grows without a rule, a module that depends on the wrong layer, a dependency whose licence nobody checked. This skill makes those decisions explicit, written, and checked — before the first slice is built.

## Rules

- No code before the architecture is written. Scaffold needs a confirmed brief *and* a written architecture.
- No stack without a decision record. A stack chosen silently is a stack nobody can question.
- A layer violation is a FAIL even if the suite is green. The suite does not know the layers.
- A decision record names what was rejected and why. A record that only describes the winner is a press release, not a decision.
- A check that did not run is never reported as passed.

## Steps, in order

### 1. Record the stack choice as an ADR

Write `docs/adr/0001-stack-<name>.md` with: context (what the project must do), decision (the stack, with versions), reasons (why this stack fits this project), rejected alternatives (what was considered and why it lost), consequences (what this choice costs later). The user confirms the stack; the ADR records the decision. If the stack changes, write a new ADR that supersedes the old one — never edit the old one silently.

### 2. Define the tree and the invariants

Write `docs/constitution.md` (or extend it) with the invariants: one slice at a time, no test weakening, no secrets, and the layer rules for this project. Write the file tree: every directory's purpose, in one line each. The tree must match the actual files — a tree that does not match reality is worse than no tree.

### 3. Define the public contract

Write `docs/contract.md`: the public surface (what a consumer may import), the error shape (one format everywhere), and the versioning rule (what counts as breaking). This is the contract the breaking-change check enforces later.

### 4. Produce a codebase map

```bash
npx --yes repomix --output <path-outside-the-repo>
```

Repomix (MIT) packs the repository into one file. Read the packed file list: it must contain the source, the tests, and the docs — and it must not contain `node_modules/`, `dist/`, `reports/`, or a `.env`. (`.env.example` is a placeholder and belongs in the map.) If the map contains a secret or a build artifact, the tree is wrong, not the map.

### 5. Check dependency licences

List every direct dependency in `package.json` and read its licence from `node_modules/<dep>/package.json`. Allowed by default: MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, ISC. A copyleft licence (GPL, AGPL, LGPL) or an unknown licence is a FAIL until a decision is recorded in an ADR — the project does not ship a licence nobody looked at.

### 6. Run the checker

```bash
python3 skills/architecture/scripts/check_architecture.py --root <project>
```

The checker verifies what is mechanically checkable: no source file imports from the test directory, no circular import among source files, and every direct dependency's licence is allowed. It does not verify the tree, the ADR, or the contract — those are verified by reading them, in the report below.

## Report

Return the report in this form:

- The stack ADR (file, decision, rejected alternatives).
- The tree (as it stands) and the invariants.
- The contract (public surface, error shape, versioning rule).
- The codebase map (file count, what is in it, what is not).
- The licence check (each direct dependency and its licence).
- The checker result (command, exit code, violations named).
- Verdict: PASS or FAIL, and what remains.

## Scope

This skill defines the architecture; `scaffold` builds it and `build` implements slices within it. It does not choose the stack for the user, and it does not draw diagrams (that is archify). The spec-kit method (constitution, specification, plan) inspired the shape of this skill; the spec-kit CLI itself is not run here, because its runner is not installed in this environment — the method is used, the tool is not. Repomix is invoked as-is.

## Sources

Written from scratch for ORCINUS, in our own words. No ready skill was found for this in the 0–100 research: spec-kit and repomix are tools, not `SKILL.md` files, and no verified architecture skill was identified. Spec-kit (github/spec-kit, MIT) and repomix (MIT) are used as-is where they run; no text was copied from either.
