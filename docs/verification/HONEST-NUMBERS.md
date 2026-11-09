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
| CI-attested VERIFIED transition | Observed twice — 1 attestation for revision `697707b` (CI run 42690744707) and 1 attestation for revision `fe6f432` (v0.12.0, CI run 42707325198, all 15 jobs success), each verified via the GitHub attestations API: subject `content-digest.txt` sha256 matches the tree digest, SLSA v1 predicate, workflow `.github/workflows/ci.yml` | GitHub attestations API, 2026-11-09 | `scripts/verify_attestation.py`, `.github/workflows/ci.yml` (`attest` job) |
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

## CI-attested verification (0.11.0 → 0.12.0)

What is now proven: a CI-attested test run for a revision — since
0.12.0 the `attest` job needs all nine essential gates (test, waza,
demo, waza-fixtures, shellcheck, clean-install, version-bump,
plugin-validate, postgres-migration) and runs on push-to-main only,
so an attestation existing for a run implies every one of them
passed in that same run. The check is live: `gh attestation
verify` on the tree content digest, pinned to this repo's CI
workflow and the revision — and it never trusts `gh`'s exit code
alone (the JSON subjects must contain the file's sha256).

What 0.12.0 closed: the targeted-rerun proof file. A hand-written
proof JSON with correct values (method `targeted-rerun`, matching
revision, content digest recomputed from the real bundle, exit
code 0, junit 2/2) was shown to mint VERIFIED through
`--attestation-proof` in a scratch repo with no tests at all,
without `rerun_check.py` ever running — the content digest is
public and recomputable, so checking JSON fields was never a proof
that anything ran. The flag is removed: the gate now runs the
rerun itself (from a clean worktree at the exact revision, using
the revision-pinned copy of the script) and records the proof it
produced, and a local rerun mints only RERUN_CONFIRMED, never
VERIFIED. The verifier's exact experiment (scratch repo, no tests,
hand-written proof) is now refused: there is no flag left to hand
it to.

What is still NOT proven: correctness or safety of the code;
safety of the dependencies; the agent's writing process; and that
the bundle's artifacts are the ones the runner produced — the
targeted re-run (`scripts/rerun_check.py`) verifies the claim that
the selected tests pass at the revision, not the artifacts'
provenance. A fabricated JUnit that exactly matches what a real
run would produce still agrees with the rerun. And the remaining
ceiling, stated plainly: local minting is still not tamper-proof
against an agent with write access to the repo — a hand-written
RERUN_CONFIRMED record still validates locally, because
`validate` does not re-run anything. What 0.12.0 closed was the
legitimate-looking path (a proof file the gate itself accepted as
VERIFIED); the tamper-proof layer is v1.1, not this release.

Measurement: two live attested transitions have now been observed —
for revision `697707b` (CI run 42690744707, 2026-11-09) and for
revision `fe6f432` (v0.12.0, CI run 42707325198, 2026-11-09, all 15
jobs success including `attest`, which since 0.12.0 needs all nine
essential gates). In each case the attestations API returns exactly
one attestation whose subject is `content-digest.txt` with the
sha256 of that revision's tree digest, an SLSA v1 predicate, and
the CI workflow as its builder. For `fe6f432`: tree digest
`sha256:1d936c3c8c150a69a03b8800c2c44049700f7f97cd8858e6393f2bb7faf73651`,
subject sha256
`8bb64b7c1fe034ff432e80648ee7f7de0568a0e42429e32ec03121e74aaa1668`,
builder `.github/workflows/ci.yml` on `refs/heads/main`, invocation
run 42707325198 attempt 1. What is still NOT observed in this
environment: the `verify_attestation.py` live exit-0 path itself —
`gh` is unauthenticated here, so the script's `gh attestation
verify` call has not yet returned exit 0 against a real
attestation. No numbers beyond these two observations are claimed.

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
