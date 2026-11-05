# EVAL — architecture-01

How to check whether `architecture` works. Follow the skill's own procedure on a throwaway copy of the demo: write the missing architecture (stack ADR, public contract), produce a codebase map, check the licences, and run the checker — then break the rules and confirm the checker catches it. The demo project itself is never touched. No criterion may be skipped.

## Setup (not part of the score)

- The demo already has `docs/constitution.md` (from the scaffold step) and a tree, but it has no stack ADR and no written public contract — those are the missing pieces this eval writes, on a throwaway copy (in `/tmp/orcinus-demo-arch/`, with `node_modules` symlinked from the durable demo so the licence check reads real installed packages).
- Stack decision to record: TypeScript 6.0.3, Node 24, npm, `node:test`, eslint — chosen in the scaffold eval; the ADR must name the reasons and the rejected alternatives.
- Layer rules for the demo: `src/` never imports from `tests/`; `tests/` may import from `src/`; no circular import among `src/` files.
- Allowed licences: MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, ISC (the checker's default).

## Case 1 — the architecture is complete and the map is clean

**Input:** the throwaway copy with the stack ADR (`docs/adr/0001-stack-typescript-node-test.md`) and the public contract (`docs/contract.md`) written, and a repomix map produced with `npx --yes repomix --output <path>`.

**Pass criteria:**

1. The ADR names the stack with versions, the reasons, and at least one rejected alternative with why it lost.
2. The contract names the public surface (the two modules and their exports), the error shape (one format), and the versioning rule.
3. The tree in the report matches the actual files (every directory's purpose stated, no directory missing).
4. The repomix map contains the source (`src/budget.ts`, `src/summary.ts`), the tests, and the constitution — and contains no packed file under `node_modules/`, `dist/`, or `reports/`, and no `.env` file.
5. Verdict is PASS.

**Fail criteria:**

- The ADR does not name a rejected alternative.
- The map contains a build artifact, a secret, or a `.env` file.
- The tree does not match the actual files.

## Case 2 — dependency licences are all allowed

**Input:** the checker's licence check run on the throwaway copy.

**Pass criteria:**

1. The checker lists all 7 direct devDependencies and their licences: `@eslint/js` MIT, `@stryker-mutator/core` Apache-2.0, `@stryker-mutator/typescript-checker` Apache-2.0, `@types/node` MIT, `eslint` MIT, `typescript` Apache-2.0, `typescript-eslint` MIT.
2. The checker exits 0 (no licence violation).
3. Verdict is PASS.

**Fail criteria:**

- A dependency's licence is not listed or is wrong.
- The checker exits 1 on the clean copy.

## Case 3 — violations are caught

**Input:** the throwaway copy with two deliberate violations: (a) `src/shadow.ts` importing from `tests/budget.test.ts` (a layer violation), and (b) `src/a.ts` importing `src/b.ts` while `src/b.ts` imports `src/a.ts` (a circular import).

**Pass criteria:**

1. The checker exits 1 and names both violations: the layer violation (file, and the import) and the circular import (the cycle).
2. The four commands on the copy all exit 0 (the imports are valid TypeScript, so the suite stays green) — the checker is the only thing that catches them.
3. Verdict is FAIL (as expected).

**Fail criteria:**

- The checker exits 0 with the violations present.
- A violation is not named.
- The suite fails (then the checker is not the thing that caught it).

## Last run

- 2026-11-05: PASS. Case 1: 5/5. Case 2: 3/3. Case 3: 3/3. Real run, not simulated, on a throwaway copy of the demo (in /tmp/orcinus-demo-arch/, with node_modules symlinked from the durable demo). Case 1 (architecture complete): the ADR `docs/adr/0001-stack-typescript-node-test.md` names the stack with versions (TypeScript 6.0.3 strict, Node 24, npm 10.9.4, `node:test`, eslint 10.14.0), the reasons, and three rejected alternatives with why each lost (Vitest/Jest, Python, no lint); the contract `docs/contract.md` names the public surface (the two modules and their exports), the error shape (`Error("budget must be greater than 0")`), and the versioning rule; the tree matches the copy's actual files (src/, tests/, docs/, docs/adr/); the repomix map (v1.18.1, `npx --yes repomix`) contains 14 files — source, tests, constitution, ADR, contract — and no packed file under `node_modules/`, `dist/`, or `reports/`, and no `.env` file. (The copy was made without `.gitignore`, a hidden file not in the copy list, so the map has 14 files, not 15.) Case 2 (licences): the checker exits 0 and lists all 7 direct devDependencies with their licences — `@eslint/js` MIT, `@stryker-mutator/core` Apache-2.0, `@stryker-mutator/typescript-checker` Apache-2.0, `@types/node` MIT, `eslint` MIT, `typescript` Apache-2.0, `typescript-eslint` MIT. Case 3 (violations): the checker exits 1 and names both — `src/shadow.ts: layer violation — imports from tests/ (../tests/budget.test.js)` and `circular import: src/a.ts -> src/b.ts -> src/a.ts`; the four commands on the copy all exit 0 (build, lint, typecheck, test 7/7 pass) — the suite is green, so the checker is the only thing that catches them. Two real defects were found and fixed during the run: (1) the checker's first version missed the circular import because its resolver did not map a `.js` import to its `.ts` source (TypeScript NodeNext resolution) — the graph nodes did not match the real files, so no cycle was detected; the resolver now tries `.ts`/`.mts`/`.cts` for `.js`/`.mjs`/`.cjs` imports. (2) The first circular-import form used `const` (`export const a = b + 1`), which the typechecker itself rejects (TS7022, implicitly any) — so the eval uses the function form, which the typechecker accepts and only the checker catches. The demo project itself was never touched (git status clean). The throwaway copy and the repomix output live in /tmp and are rebuildable.
