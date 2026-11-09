# Honest Numbers

This page publishes losing cases alongside wins, with the real
numbers. No marketing. If a skill does not beat its control for a
workload, this page says so — and if nothing has been measured yet,
it says that instead of citing a self-check as a result.

The practice is adapted from JuliusBrussee/caveman (Apache-2.0),
`docs/HONEST-NUMBERS.md`: publish the losing cases, name the
measurement, and tell the reader when to turn the thing off.

## What is measured, and how

- **Router, three-arm eval.** The same 12 routing scenarios
  (`evals/router-01.md`) are recorded under three conditions —
  `__baseline__` (no system prompt), `__terse__` (the terse
  control only), `orcinus` (terse control plus the router skill)
  — and graded by `scripts/router_eval.py`. The honest delta is
  **skill minus terse control**, in scenarios passed. Skill minus
  baseline is also reported, labelled as the conflated comparison
  it is: it credits the skill with the generic "route this" ask.
- **orcinus-verify waza harness-smoke.** The mock-executor suite
  (`evals/waza-orcinus-verify/`) proves the harness (parsing,
  execution, scoring, results JSON, the gate, comparison). It
  does **not** prove the skill being evaluated works: the mock
  executor echoes the prompt, so a task passes when the prompt
  itself contains the expected string. See
  `evals/evidence-eval-01.md`, "Honest limits".
- **finalize / registry-publish / independent-review / handoff
  waza real-executor evals.** The four suites
  (`evals/waza-finalize/`, `evals/waza-registry-publish/`,
  `evals/waza-independent-review/`, `evals/waza-handoff/`) grade
  the skills with a real executor (`copilot-sdk`) and prompts
  that do not state the expected verdict — the agent must read
  the fixture files and decide. They have **never run**: no
  live-agent run exists and no numbers are claimed for them.
  What the repo can execute without a runtime is the grader
  semantics: each suite's `test_*_graders.py` reproduces its code
  assertions in Python against good, cheating, and constant
  outputs. The graders see only output text, so a fabricated
  report can still pass; and for handoff the graders cannot see
  the filesystem at all — whether the file exists, its mode, and
  its sections are the agent's claims, not verified facts.
- **Committed snapshot.** `evals/snapshots/router-results.json`
  holds the expected eval numbers per arm, checked by
  `python3 scripts/router_eval.py --check-snapshot` and by
  `scripts/test_router_eval.py` in CI. A number that no longer
  reproduces from the stored decisions fails until the snapshot
  is updated, so number changes are reviewable as diffs.

## The measured numbers

| What | Number | How measured | Source |
|---|---|---|---|
| Router self-check pin | 12/12 baseline, 12/12 terse, 12/12 orcinus; honest delta 0 | Grading REFERENCE_DECISIONS (the expected answers) under each arm label — a harness pin, **not an agent measurement** | `evals/snapshots/router-results.json` |
| Router live three-arm run | Not measured yet — no live-agent run recorded | — | `evals/router-01.md` |
| orcinus-verify waza harness-smoke (mock) | 2/2, aggregate score 1.00; negative control 0/1 (fails by design) | Mock executor, official waza v0.40.0 binary | `evals/evidence-eval-01.md` Cases 1–2 |
| finalize / registry-publish / independent-review / handoff waza evals (real executor) | Not measured yet — specs exist, no live-agent run recorded | — | `evals/waza-finalize/`, `evals/waza-registry-publish/`, `evals/waza-independent-review/`, `evals/waza-handoff/` |

## When the skill wins

No live three-arm run has been recorded, so no win has been
observed. Do not cite the snapshot's 12/12 as a win: it is the
self-check pin, and every arm scores 12/12 on it by construction.
The same holds for the four waza suites: no live run, so no win
has been observed for finalize, registry-publish,
independent-review, or handoff either.

## When the skill loses (or does not beat the terse control)

No live three-arm run has been recorded, so **no case exists yet
in our evals where a skill does not beat the terse control** —
and no case exists where it does, either. The honest delta for a
real run is unknown. The snapshot's delta of 0 is the self-check
pin, not a result; do not cite it as the skill tying the control.

When the first live three-arm run is recorded, its per-scenario
losses go here — scenario id, what the terse arm got right that
the skill arm got wrong, and the honest delta — alongside the
wins. A skill that does not beat the terse control on a workload
is a finding to record, not a number to hide: the router skill
would need its routing table or its triggers changed, or the
workload would need routing without it.

## What this does not measure

- **Fidelity beyond the grader.** The router grader checks
  stage, routes, mode, and named missing skills. Whether a
  routing decision is actually right for a real repo is left to
  human review of the recorded run. Caveman's fidelity eval
  (`score_fidelity.py`: regex checks on LLM outputs) was not
  adopted: our evals grade recorded decisions, and there are no
  LLM outputs here to score.
- **Latency or cost.** Nothing here measures either.
- **Routing to these four skills.** None of the router eval's
  12 scenarios routes to finalize, registry-publish,
  independent-review, or handoff, so the committed snapshot says
  nothing about routing to them. Extending it needs new scenarios
  in `scripts/router_eval.py` and a regenerated snapshot — a
  change outside the FND-014 fix's file scope — so the snapshot
  was left untouched and still passes its check.
- **Any executable check for these four skills without an agent
  runtime.** None exists beyond the grader-semantics tests above:
  finalize grades report assembly from recorded fixture evidence
  (the live gate re-run stays in `finalize-01.md`);
  registry-publish grades the check from fixture pack lists (no
  live `npm pack`, install, or registry query; no real publish is
  performed in the spec by design); independent-review grades
  verdicts on a fixture diff (the live reviewer run stays in
  `independent-review-01.md`); handoff grades the agent's claims
  about a file the graders cannot see (the file was actually
  inspected only in `handoff-01.md`).
- **Cross-agent behaviour.** Only the run actually recorded is
  measured; a run on another host or model is a different run.

## Measure it yourself

1. Record a three-arm run per `evals/router-01.md` (empty temp
   dir per arm, no MCP config, no installed skills, no session
   persistence between arms), then grade it with
   `python3 scripts/router_eval.py <run.json>`.
2. To publish the numbers, put the recorded run in the
   snapshot's `live` block and refresh the recorded per-arm
   numbers from the grade — `check_router_snapshot` fails until
   they reproduce, so the change is reviewable as a diff.
3. If your run contradicts the numbers on this page, record it
   here — wins and losses alike.
