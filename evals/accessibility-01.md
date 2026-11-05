# EVAL — accessibility-01

How to check whether `accessibility` works. Run the bundled ultra11y engine on the demo page as it stands, fix what it finds, and re-audit. The demo page itself is never changed — the fix is applied to a throwaway copy. No criterion may be skipped.

## Setup (not part of the score)

- Tool: the bundled engine `skills/accessibility/scripts/ultra11y.mjs` (v5.58.1, self-contained, Node only, no dependencies), run from the repo as shipped.
- Page: the demo page (`/tmp/orcinus-demo-page/index.html`), a static page rendering the demo's weekly summary.
- The engine audits against RGAA 4.1.2 on a WCAG 2.2 AA core. Its report is JSON; each finding carries its rule, criterion, file, line, severity, message, and remediation.

## Case 1 — audit as-is finds the missing landmark

**Input:** `node skills/accessibility/scripts/ultra11y.mjs audit index.html --out <dir> --json` on the demo page as it stands.

**Pass criteria:**

1. The audit reports exactly 1 non-conformity.
2. It names criterion 1.3.1, rule `missing-main-landmark`, severity `majeur`, file `index.html`, line 4, with the remediation "Wrap the main content in a `<main id=\"content\">`".
3. Verdict is FAIL (as expected — the page is not conforming).

**Fail criteria:**

- The audit reports 0 non-conformities on the page as it stands.
- The finding does not name its criterion, location, or remediation.

## Case 2 — fix and re-audit

**Input:** a throwaway copy of the page with the content wrapped in `<main id="content">`, re-audited with the same command.

**Pass criteria:**

1. The re-audit reports 0 non-conformities.
2. The page still renders the same text (checked in a real browser: `#summary` still reads `total: 80, remaining: 20, warned: true, percent: 80`).
3. Verdict is PASS for the engine gate.
4. The 30 manual criteria the engine cannot decide are recorded as not adjudicated — they are a stated gap, not a pass. (Adjudicating all 30 by hand is out of proportion for this demo page; the skill's verdict rule requires a recorded human judgment for manual criteria, and that judgment is not claimed here. Note: criterion 1.3.1 moved from NC to manual after the fix — the engine can see a landmark exists, it cannot judge whether it is the right one.)

**Fail criteria:**

- The re-audit still reports the missing-main-landmark finding.
- The rendered text changed.
- The manual criteria are reported as passed.

## Case 3 — the gate fails and passes

**Input:** `audit --fail-on major` on the page as it stands, then on the fixed copy.

**Pass criteria:**

1. On the page as it stands, the command exits 1 and reports "1 non-conformity(ies) ≥ majeur".
2. On the fixed copy, the command exits 0.
3. Verdict is PASS (the gate works both ways).

**Fail criteria:**

- The command exits 0 on the page as it stands.
- The command exits 1 on the fixed copy.

## Last run

- 2026-11-05: PASS. Case 1: 3/3. Case 2: 4/4. Case 3: 3/3. Real run, not simulated, with the bundled engine as shipped in the repo (v5.58.1) on the demo page. Case 1 (audit as-is): exactly 1 non-conformity — criterion 1.3.1, rule `missing-main-landmark`, severity `majeur`, file `index.html`, line 4, with the remediation "Wrap the main content in a `<main id=\"content\">`"; conformance 96%; verdict FAIL as expected. Case 2 (fix + re-audit, on a throwaway copy with the content wrapped in `<main id="content">`): 0 non-conformities, conformance 100%; the page still renders the same text in a real browser (`#summary` reads "total: 80, remaining: 20, warned: true, percent: 80", `main#content` present). Case 3 (gate): `audit --fail-on major` on the page as it stands exits 1 ("✗ 1 non-conformity(ies) ≥ majeur"); on the fixed copy it exits 0. The demo page itself was never changed. Limit, stated plainly: the 30 manual criteria the engine cannot decide were not adjudicated (criterion 1.3.1 moved from NC to manual after the fix — the engine can see a landmark exists, it cannot judge whether it is the right one); the skill's verdict rule requires a recorded human judgment for manual criteria, and that judgment is not claimed here. Note: a VM restart wiped /tmp after this run (the throwaway copies and the audit outputs are gone); the results above were recorded before the wipe and the artifacts are rebuildable from this eval.
