# EVAL — router-01

How to check whether `orcinus` (the router) routes correctly. The router is prose — an LLM following `skills/orcinus/SKILL.md` — so this eval does not run the router: it scores a recorded routing decision against 12 repo-state scenarios with a deterministic grader, `scripts/router_eval.py`. No criterion may be skipped.

## How to run it

Record one routing decision per scenario as JSON — `{scenario id: {"stage": ..., "routes": [...], "mode": "full" | "lite", "missing": [...]}}` — where `stage` is a Stage cell from the router's routing table, `routes` are skill folders, and `missing` names any sub-skill the router reports as not built. Then grade it:

```bash
python3 scripts/router_eval.py <decisions.json>
```

Exit 0 only when all 12 scenarios pass. `python3 scripts/router_eval.py` with no argument grades the reference decisions (the expected answers) as a self-check: 12/12.

## Scenarios (repo state → expected stage and route)

1. **idea-no-repo** — No repo yet, only a rough brief. → Idea capture, `idea-capture`.
2. **idea-needs-sharpening** — A brief exists, but the problem, user, and success criteria are not written down. → Idea, `idea-calibrate`.
3. **idea-no-tree** — An idea exists, but no tree, contract, or invariants yet. → Architecture, `architecture`.
4. **arch-no-build** — Architecture exists, but the project does not build, lint, or test yet. → Scaffold, `scaffold`.
5. **builds-slice** — The project builds; the next slice of work is ready. → Build, `build`.
6. **slice-done** — A slice claims to be done and asks for verification. → Verify, `orcinus-verify`.
7. **slice-done-auth** — A slice claims to be done and touches auth/secrets: a cross-cutting concern on top of the linear stage. → Verify, `orcinus-verify` **and** `security-review` (both routes; routing to Verify alone fails).
8. **web-ui-verify** — A web UI change claims to be done; it needs a real browser run, not unit tests alone. → Verify: web UI, `webapp-testing`.
9. **shipped-uptime** — A service has shipped and needs uptime probes, alerts, and on-call. → Health / monitoring, `monitoring`.
10. **shipped-telemetry** — A service has shipped and needs logs, metrics, traces, and drift detection. → Telemetry / instrumentation, `monitoring-observability`.
11. **typo-patch-lite** — A one-line typo fix in docs; no gate is touched. → Build, `build`, in **Lite** mode (Full mode, or routing to independent review, fails).
12. **benchmark-missing** — The project needs a benchmark run (SWE-bench), which the MAP marks `todo` — no such skill exists in this install. → Evidence / eval, `waza`, with `missing: ["SWE-bench"]` named (routing as if the skill existed, or not naming it, fails).

## Pass criteria

1. Every scenario's stage matches the router's routing-table Stage cell for that repo state.
2. Every scenario's routes match exactly (as a set): no missing cross-cutting route, no extra route.
3. The Lite scenario is routed in Lite mode; every other scenario in Full mode.
4. The missing-sub-skill scenario names the missing skill instead of improvising its procedure.

## Fail criteria — any one of these fails the eval:

- A wrong stage for a scenario (e.g. Verify for a slice that only needs Build).
- A missing or extra route (e.g. Verify alone for the auth slice).
- The Lite scenario routed in Full mode, or with independent review in its routes.
- The benchmark scenario routed without naming SWE-bench as missing.

## Three-arm eval (skill vs terse control)

Adapted from JuliusBrussee/caveman (Apache-2.0), `evals/README.md`:
a skill claim is measured under three conditions, and the honest
delta is skill minus terse control — not skill minus nothing.

| Arm | System prompt for the recorded run |
|-----|-------------------------------------|
| `__baseline__` | none |
| `__terse__` | `Route this repo state to the right stage and skill(s). Reply as JSON with stage, routes, and mode.` |
| `orcinus` | the terse control, then `skills/orcinus/SKILL.md` |

The terse control is adapted, not caveman's literal "Answer
concisely.": that names no task, and this eval grades structured
JSON decisions, so a bare "Answer concisely." could not produce a
gradeable decision — every terse-arm scenario would fail on shape,
not on routing, a vacuous control. The control names the task and
the output shape and nothing else: no routing table, no stage
names, no skill names. `scripts/router_eval.py` defines it as
`TERSE_CONTROL` and the arm prompts as `system_prompt_for_arm()`.

Record one decision set per arm (the same 12 scenarios), as
`{"arms": {"__baseline__": {...}, "__terse__": {...}, "orcinus": {...}}}`,
then grade it:

```bash
python3 scripts/router_eval.py <run.json>
```

It prints per-arm scores and the honest delta (`orcinus` minus
`__terse__`), plus the skill-vs-baseline number labelled as the
conflated comparison it is. Exit 0 only when the skill arm passes
every scenario.

### Host isolation for a recorded run

Each arm is graded in its own fresh empty temp dir
(`grade_arms_isolated()` in `scripts/router_eval.py`), so nothing
carries from one arm to the next. The recording side is a procedure
the recorder must follow — the grader cannot enforce what an
agent's host loads: run each arm from an empty temp dir, with no
project or user settings, no MCP config, no installed skills or
slash commands, and no session persistence between arms.

### Snapshot

`evals/snapshots/router-results.json` holds the expected numbers
per arm. `python3 scripts/router_eval.py --check-snapshot` (and
`scripts/test_router_eval.py` in CI) fails when the recorded
numbers no longer reproduce from the stored decisions — update
the snapshot with the numbers, so a change is reviewable as a
diff. The committed snapshot pins the grader self-check only;
no live-agent run exists yet. Honest numbers, wins and losses:
`docs/verification/HONEST-NUMBERS.md`.

## Last run

- 2026-11-09: three-arm harness added (Track 3, caveman takeaway 3):
  `scripts/router_eval.py` grades three-arm runs and reports the
  honest delta; `evals/snapshots/router-results.json` pins the
  self-check (12/12 per arm on REFERENCE_DECISIONS — not an agent
  measurement). Still no live-agent run: the honest delta for a
  real run is unknown.

- 2026-11-07: grader self-check passes (12/12 reference decisions score PASS; the negative cases — wrong stage, wrong route, dropped cross-cutting route, Full mode on the Lite scenario, unnamed missing skill, unknown route — are all rejected by `scripts/test_router_eval.py`). No live-agent run yet: the 12 scenarios have not been put to a real agent on a host, so this eval is programmatic only until such a run is recorded here.
