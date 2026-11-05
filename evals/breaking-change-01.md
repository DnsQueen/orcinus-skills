# EVAL — breaking-change-01

How to check whether `breaking-change` works. Run oasdiff on real OpenAPI specs for the demo API: the v1 baseline from the api-and-interface-design eval, a breaking candidate, and an additive candidate. No criterion may be skipped.

## Setup (not part of the score)

- Tool: oasdiff v1.35.0 (official linux/amd64 release binary, SHA256 verified against the release `checksums.txt`, in `/tmp/oasdiff-bin/` — ephemeral, rebuildable).
- Specs (in `/tmp/orcinus-demo-api/specs/`, ephemeral, rebuildable):
  - `openapi-v1.yaml` — the demo API as designed (GET /api/v1/weekly-summary, GET /api/v1/spending with pagination, structured errors).
  - `openapi-v2-breaking.yaml` — the same API, but `remaining` renamed to `left` and `percent` removed, under the same `/v1` (the Case 2 proposal from the api-and-interface-design eval).
  - `openapi-v2-additive.yaml` — the same API, plus an optional `currency` field on the weekly-summary response, everything else unchanged.
- Each spec is validated with `oasdiff validate` before any comparison.

## Case 1 — no change

**Input:** `oasdiff breaking openapi-v1.yaml openapi-v1.yaml`.

**Pass criteria:**

1. The command exits 0.
2. No breaking changes are reported.
3. Verdict is PASS.

**Fail criteria:**

- A breaking change is reported for two identical specs.

## Case 2 — breaking change is detected

**Input:** `oasdiff breaking --fail-on ERR openapi-v1.yaml openapi-v2-breaking.yaml`.

**Pass criteria:**

1. The command exits 1.
2. The output names the rename (`remaining` → `left`, reported as the removal of the required property `remaining`) and the removal (`percent`), with their locations (GET /api/v1/weekly-summary, 200 response).
3. Verdict is FAIL (as expected — the change is rejected under the same version).

**Fail criteria:**

- The command exits 0.
- The rename or the removal is not reported.
- The change is reported as non-breaking.

## Case 3 — additive change passes

**Input:** `oasdiff breaking openapi-v1.yaml openapi-v2-additive.yaml`.

**Pass criteria:**

1. The command exits 0.
2. No breaking changes are reported.
3. Verdict is PASS.

**Fail criteria:**

- The command exits non-zero.
- The added optional field is reported as breaking.

## Last run

- 2026-11-05: PASS. Case 1: 3/3. Case 2: 3/3. Case 3: 3/3. Real run, not simulated, with oasdiff v1.35.0 (official linux/amd64 release binary, SHA256 verified against the release `checksums.txt`). All three specs validated first with `oasdiff validate` (all valid). Case 1 (v1 vs v1): "No changes detected", exit 0 — PASS. Case 2 (v1 vs v2-breaking): 2 changes, 2 errors — `response-required-property-removed` for `percent` and for `remaining`, at GET /api/v1/weekly-summary, 200 response — exit 1 with `--fail-on ERR`, FAIL as expected (the change is rejected under the same version). Case 3 (v1 vs v2-additive, optional `currency` added): "No breaking changes to report, but the specs are different.", exit 0 — PASS. One real finding during the run, and the reason the skill was corrected before the eval was scored: the first draft of the skill said `oasdiff breaking` exits non-zero when breaking changes exist — it does not. Without `--fail-on ERR` it prints the errors and still exits 0 (verified: the first Case 2 run printed both errors with exit 0). The skill and the eval were corrected to require `--fail-on ERR`, and all three cases were re-run with it. A gate that cannot fail is not a gate. The specs live in /tmp/orcinus-demo-api/specs/ (ephemeral, rebuildable) and were not committed anywhere.
