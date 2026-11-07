# orcinus-demo-scaffold

Demo project built by following the ORCINUS skills: a weekly delivery-budget tracker. First slices: a budget warning at 80% and a weekly summary.

This is the proof artifact for ORCINUS v1 — the demo the README, SCOPE.md and the evals cite. It lives in the repo at `examples/demo/` so the claim "proven on a real demo project" is reproducible: clone the repo, `cd examples/demo`, and run the four commands. The raw output of the latest verification run is in `evals/results/demo-2026-11-06.log`.

Run `npm run build`, `npm run lint`, `npm run typecheck`, `npm test`.

Requires Node 22 or newer (`engines` in `package.json`): the Stryker packages require Node ≥22. CI runs the four gates on Node 22 and 24.

## Known advisories (dev dependencies only, triaged 2026-11-07, round 6)

`npm audit` reports moderate items in the dev-only tooling (no production dependencies exist here, and no attacker-controlled glob patterns or query strings reach these packages — exploitability in this demo is nil). Triage:

- **qs 6.17.1** (via `typed-rest-client`, used by Stryker's local HTTP client): remediated with an `overrides` entry (`"qs": "^6.16.1"` in `package.json`) covering CVE-2026-82417 (stringify `isBuffer` DoS, fixed 6.16.1) and GHSA-6pq8-jhm2-2vcw / CVE-2026-110816 (stringify `arrayFormat: 'comma'` TypeError, fixed 6.16.1). Verified: `npm ci` clean, all four gates green, `npm ls qs` shows `6.17.1 overridden`.
- **minimatch 10.2.6** (via Stryker and eslint): CVE-2026-118764 (MEDIUM, CVSS 4.0 6.9, `**/..` expansion at optimizationLevel ≥2, affects <11.0.1) applies to 10.2.6. Risk accepted: the fix needs a major bump to minimatch 11, which the eslint/Stryker ranges (`^10.2.4`/`~10.2.4`) will not resolve — revisit when upstream adopts minimatch 11. Earlier minimatch CVEs (CVE-2026-26996, CVE-2026-27903, CVE-2026-27904) do not affect 10.2.6. No `npm audit` gate in CI: it would be red by design until upstream bumps minimatch.
