# EVAL — monitoring-01

How to check whether `monitoring` works. Run the bundled gate (`skills/monitoring/scripts/verify.sh`) against a good and a bad monitoring config, and run a live throwaway service with the health-endpoint contract the skill requires. The service (`/tmp/orcinus-demo-health/server.mjs`, Node, no dependencies) serves the demo's weekly-summary API plus `/livez` (process only) and `/readyz` (a dependency flag file, `db.ok`; remove it and readiness degrades). No criterion may be skipped.

## Case 1 — the gate passes a good config

**Input:** `bash skills/monitoring/scripts/verify.sh /tmp/orcinus-demo-health/monitoring.yaml` — a config with the 4 layers: an external probe on the critical journey (`/api/v1/weekly-summary`, not just `/`), `/livez` split from `/readyz`, two burn-rate alerts with two windows each (14.4 over [1h, 5m] → page, 6 over [6h, 30m] → ticket), a runbook reference on every alert, and an on-call escalation (primary + secondary + manager, 10-minute ack).

**Pass criteria:**

1. `verify.sh` exits 0.
2. It prints PASS for: liveness split from readiness, a symptom/SLO alert with two windows, alerts referencing a runbook.
3. Verdict is PASS.

**Fail criteria:**

- `verify.sh` exits non-zero, or any check FAILs.

## Case 2 — the gate can fail: a bad config is caught

**Input:** `bash skills/monitoring/scripts/verify.sh /tmp/orcinus-demo-health/bad/monitoring.yaml` — a config with a homepage-only monitor (`url: "/"`), one `/health` that cascades to the database (no liveness/readiness split), CPU-only and memory-only alerts, no runbook, and Opsgenie as the on-call tool.

**Pass criteria:**

1. `verify.sh` exits 1.
2. It names all five failures: no liveness/readiness split, only cause-based thresholds, no runbook reference, Opsgenie as a new setup (EOL 2027-04-05), homepage-only monitor.
3. Verdict is PASS.

**Fail criteria:**

- `verify.sh` exits 0, or a failure is not named.

## Case 3 — the live wire: the split and the probe, for real

**Input:** start the service with `db.ok` present; probe `/livez`, `/readyz`, and the critical journey; remove `db.ok`; probe again; stop the service; probe again.

**Pass criteria:**

1. Service up: `/livez` returns 200 in under 100ms (`0.018s` measured) with `{"status":"alive"}`; `/readyz` returns 200 with `{"status":"ready","checks":{"db":true}}`; the critical journey returns 200 with `{"total":80,"remaining":20,"warned":true,"percent":80}`.
2. Dependency dies: `/readyz` returns 503 with `{"status":"degraded","checks":{"db":false}}`, while `/livez` still returns 200 with `{"status":"alive"}` — the split holds, no cascade, no restart loop.
3. Service stops: the probe fails (curl exit 7, connection refused) — downtime is detected.
4. Verdict is PASS.

**Fail criteria:**

- `/livez` is slow (≥100ms) or checks a dependency.
- `/readyz` stays 200 after the dependency dies, or `/livez` fails with it.
- The probe succeeds after the service stops.

## Last run

- 2026-11-06: PASS. Case 1: 3/3. Case 2: 3/3. Case 3: 4/4. Real run, not simulated, with the bundled gate (`skills/monitoring/scripts/verify.sh`) and a live throwaway service (`/tmp/orcinus-demo-health/server.mjs`, Node, no dependencies). Case 1 (good config): `verify.sh` exits 0, PASS for liveness split from readiness, a symptom/SLO alert with two windows, and a runbook on every alert. Case 2 (bad config): `verify.sh` exits 1 naming all five failures — no liveness/readiness split, only cause-based thresholds (cpu/memory), no runbook reference, Opsgenie as a new setup (EOL 2027-04-05), homepage-only monitor. Case 3 (live wire): service up — `/livez` 200 in 0.018s with `{"status":"alive"}`, `/readyz` 200 with `{"status":"ready","checks":{"db":true}}`, the critical journey 200 with `{"total":80,"remaining":20,"warned":true,"percent":80}`; dependency dies (db.ok removed) — `/readyz` 503 with `{"status":"degraded","checks":{"db":false}}` while `/livez` still 200 with `{"status":"alive"}`; service stops — the probe fails (curl exit 7, connection refused). One real defect found during the run: the first bad config's comments mentioned the keywords the gate greps for ("no liveness/readiness split", "no runbook", "critical journey"), so three checks passed vacuously on the comments; the comments were removed and the gate then failed all five checks honestly. Honest limit: the page landing on a phone is NOT proven here — no PagerDuty/incident.io is connected in this environment; what is proven is detection (the probe fails), the config gate, and the endpoint split. The service, the configs, and the server live in /tmp and are rebuildable.
