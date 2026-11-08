#!/usr/bin/env python3
"""Programmatic eval for the ORCINUS router (round 6, 2-R1).

The router is prose — an LLM following skills/orcinus/SKILL.md — so
no code here runs the router. This module scores a recorded routing
decision against 12 repo-state scenarios with a deterministic grader:
each scenario names a repo state, the expected stage (a Stage cell
from the router's routing table), the expected route(s) (skill
folders from skills/manifest.json), the expected mode, and — for the
missing-sub-skill scenario — the skill the decision must name as
missing instead of silently routing as if it existed.

A decision is a dict: {"stage": str, "routes": [skill, ...],
"mode": "full" | "lite", "missing": [skill, ...]}. Routes are
compared as a set: a cross-cutting concern is a second route, not
an ambiguity to drop, and an extra route is a wrong route.

Three-arm eval (Track 3, caveman takeaway 3). The design is adapted
own-words from JuliusBrussee/caveman (Apache License 2.0),
evals/README.md and evals/llm_run.py: the same prompts are run under
three conditions and the honest delta is skill vs terse control, not
skill vs nothing. The arm names "__baseline__" and "__terse__" are
ported verbatim from caveman's evals/llm_run.py (its plan arm names);
the grading, isolation, and snapshot code in this file is
ORCINUS-original, because caveman's harness shells out to the Claude
Code CLI while ours grades recorded JSON decisions with a
deterministic grader — the runner does not port, only the design.

    __baseline__  no system prompt at all
    __terse__     the terse control only (TERSE_CONTROL below)
    orcinus       the terse control plus skills/orcinus/SKILL.md

The honest delta is orcinus-minus-terse in scenarios passed.
Comparing the skill arm to the no-system-prompt baseline conflates
the skill with the generic "route this" ask, which is what the
single-arm grader did before: it could only say whether one set of
decisions was right, never how much of that came from the skill.

The terse control is adapted, not copied: caveman's literal terse
is "Answer concisely.", which names no task at all. A routing eval
grades structured JSON decisions (stage/routes/mode); a bare
"Answer concisely." could not produce a gradeable decision, so
every terse-arm scenario would fail on shape, not on routing — a
vacuous control. TERSE_CONTROL is therefore the generic routing
ask in own words: it names the task and the output shape, and
nothing else — no routing table, no stage names, no skill names.

Host isolation per run. Caveman runs each `claude -p` call with
--setting-sources project --strict-mcp-config
--disable-slash-commands --no-session-persistence from an empty
temp dir. The equivalents here, and what is code vs procedure:

    * empty temp dir per arm (code: grade_arms_isolated grades
      each arm inside its own fresh isolated_workdir, and asserts
      it is empty) — no project settings, no CLAUDE.md, no
      installed skills can reach the grading, because the grader
      reads no files from the working directory at all: it takes
      only the decisions dict it is handed.
    * no session persistence (code): each arm gets its own fresh
      dir; nothing is shared or carried from one arm to the next,
      and grade_run is a pure function of its input.
    * no MCP, no slash commands, no user settings (procedure):
      the grader itself makes no MCP calls, loads no settings,
      and reads no environment variables, so nothing can leak
      into a grade — but the *recording* of a live run happens
      on a host the grader cannot control. Whoever records a
      run must follow the procedure in evals/router-01.md
      (empty temp dir, no MCP config, slash commands disabled,
      no session persistence); this module cannot enforce what
      an agent's host loads, and does not claim to.

Committed snapshot. evals/snapshots/router-results.json holds the
expected eval numbers per arm. check_router_snapshot() loads it,
validates its shape fail-closed (both control arms, at least one
skill arm, honest delta recomputed as skill-minus-terse), and
re-grades its stored decisions, so a number that no longer
reproduces fails until the snapshot is updated. The committed
snapshot pins the grader self-check only (see its metadata): no
live-agent run has been recorded yet, so there is no live honest
delta. scripts/test_router_eval.py runs the check in CI.

Usage:
    python3 scripts/router_eval.py
        Grade the reference decisions (self-check against
        REFERENCE_DECISIONS: 12/12 — not an agent measurement).
    python3 scripts/router_eval.py <decisions.json>
        Grade a recorded run: a JSON object mapping scenario id to
        a decision. Prints per-scenario PASS/FAIL and the score;
        exits 0 only when every scenario passes.
    python3 scripts/router_eval.py <run.json>
        Grade a recorded three-arm run: a JSON object
        {"arms": {"__baseline__": {...}, "__terse__": {...},
        "orcinus": {...}}} mapping each arm to its decisions.
        Prints per-arm scores and the honest delta (skill minus
        terse); exits 0 only when every skill arm passes every
        scenario.
    python3 scripts/router_eval.py --check-snapshot
        Check the committed snapshot reproduces (see above);
        exits 0 only when it does.

Stdlib only. The scenarios are also documented in
evals/router-01.md, which records that no live-agent run has
happened yet: the grader is programmatic, the agent run is open.
"""

import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCENARIOS = [
    {
        "id": "idea-no-repo",
        "repo_state": "No repo yet, only a rough brief.",
        "expected_stage": "Idea capture",
        "expected_routes": ["idea-capture"],
        "expected_mode": "full",
    },
    {
        "id": "idea-needs-sharpening",
        "repo_state": "A brief exists, but the problem, user, and success criteria are not written down.",
        "expected_stage": "Idea",
        "expected_routes": ["idea-calibrate"],
        "expected_mode": "full",
    },
    {
        "id": "idea-no-tree",
        "repo_state": "An idea exists, but no tree, contract, or invariants yet.",
        "expected_stage": "Architecture",
        "expected_routes": ["architecture"],
        "expected_mode": "full",
    },
    {
        "id": "arch-no-build",
        "repo_state": "Architecture exists, but the project does not build, lint, or test yet.",
        "expected_stage": "Scaffold",
        "expected_routes": ["scaffold"],
        "expected_mode": "full",
    },
    {
        "id": "builds-slice",
        "repo_state": "The project builds; the next slice of work is ready.",
        "expected_stage": "Build",
        "expected_routes": ["build"],
        "expected_mode": "full",
    },
    {
        "id": "slice-done",
        "repo_state": "A slice claims to be done and asks for verification.",
        "expected_stage": "Verify",
        "expected_routes": ["orcinus-verify"],
        "expected_mode": "full",
    },
    {
        "id": "slice-done-auth",
        "repo_state": "A slice claims to be done and touches auth/secrets — a cross-cutting concern on top of the linear stage.",
        "expected_stage": "Verify",
        "expected_routes": ["orcinus-verify", "security-review"],
        "expected_mode": "full",
    },
    {
        "id": "web-ui-verify",
        "repo_state": "A web UI change claims to be done; it needs a real browser run, not unit tests alone.",
        "expected_stage": "Verify: web UI",
        "expected_routes": ["webapp-testing"],
        "expected_mode": "full",
    },
    {
        "id": "shipped-uptime",
        "repo_state": "A service has shipped and needs uptime probes, alerts, and on-call.",
        "expected_stage": "Health / monitoring",
        "expected_routes": ["monitoring"],
        "expected_mode": "full",
    },
    {
        "id": "shipped-telemetry",
        "repo_state": "A service has shipped and needs logs, metrics, traces, and drift detection.",
        "expected_stage": "Telemetry / instrumentation",
        "expected_routes": ["monitoring-observability"],
        "expected_mode": "full",
    },
    {
        "id": "typo-patch-lite",
        "repo_state": "A one-line typo fix in docs; no gate is touched.",
        "expected_stage": "Build",
        "expected_routes": ["build"],
        "expected_mode": "lite",
    },
    {
        "id": "benchmark-missing",
        "repo_state": "The project needs a benchmark run (SWE-bench), which the MAP marks todo — no such skill exists in this install.",
        "expected_stage": "Evidence / eval",
        "expected_routes": ["waza"],
        "expected_mode": "full",
        "expected_missing": ["SWE-bench"],
    },
]

# The reference decisions: the expected answer for every scenario,
# written out so the grader can be self-checked (12/12).
REFERENCE_DECISIONS = {
    s["id"]: {
        "stage": s["expected_stage"],
        "routes": list(s["expected_routes"]),
        "mode": s["expected_mode"],
        **({"missing": list(s["expected_missing"])} if "expected_missing" in s else {}),
    }
    for s in SCENARIOS
}

# Three-arm eval. Control arm names ported verbatim from
# JuliusBrussee/caveman (Apache-2.0), evals/llm_run.py: the plan
# there names its arms "__baseline__" and "__terse__", and the
# skill arms by skill id. Our skill arm is the router skill id.
CONTROL_ARMS = ("__baseline__", "__terse__")
SKILL_ARM = "orcinus"
# The terse control, own-words (see the module docstring for why
# caveman's literal "Answer concisely." does not port to a routing
# eval): the generic routing ask, with no routing table in it.
TERSE_CONTROL = (
    "Route this repo state to the right stage and skill(s). "
    "Reply as JSON with stage, routes, and mode."
)

SNAPSHOT_PATH = ROOT / "evals" / "snapshots" / "router-results.json"


class SnapshotError(ValueError):
    """The committed router snapshot is absent, malformed, or stale:
    its recorded numbers do not reproduce from its stored
    decisions, or it lacks the arms an honest delta needs."""


def grade_decision(scenario, decision):
    """Grade one decision against one scenario. Returns (passed,
    problems): problems is empty exactly when the decision matches
    the scenario's expected stage, routes (as a set), mode, and
    missing skills."""
    problems = []
    if not isinstance(decision, dict):
        return False, ["decision is not an object"]
    if decision.get("stage") != scenario["expected_stage"]:
        problems.append(
            f"stage is {decision.get('stage')!r}, expected {scenario['expected_stage']!r}"
        )
    routes = decision.get("routes")
    if not isinstance(routes, list) or not all(isinstance(r, str) for r in routes):
        problems.append("routes is not a list of skill names")
        routes = []
    expected_routes = set(scenario["expected_routes"])
    if set(routes) != expected_routes:
        missing_routes = sorted(expected_routes - set(routes))
        extra_routes = sorted(set(routes) - expected_routes)
        if missing_routes:
            problems.append(f"route missing: {', '.join(missing_routes)}")
        if extra_routes:
            problems.append(f"route not expected: {', '.join(extra_routes)}")
    if decision.get("mode") != scenario["expected_mode"]:
        problems.append(f"mode is {decision.get('mode')!r}, expected {scenario['expected_mode']!r}")
    expected_missing = scenario.get("expected_missing", [])
    reported_missing = decision.get("missing", [])
    if not isinstance(reported_missing, list):
        problems.append("missing is not a list")
        reported_missing = []
    for name in expected_missing:
        if name not in reported_missing:
            problems.append(f"missing sub-skill not named: {name}")
    return not problems, problems


def grade_run(decisions):
    """Grade a whole run: {scenario id: decision}. Returns
    {"total", "passed", "failed": [{"id", "problems"}]}."""
    by_id = {s["id"]: s for s in SCENARIOS}
    failed = []
    for scenario in SCENARIOS:
        passed, problems = grade_decision(scenario, decisions.get(scenario["id"]))
        if not passed:
            failed.append({"id": scenario["id"], "problems": problems})
    unknown = sorted(set(decisions) - set(by_id))
    for scenario_id in unknown:
        failed.append({"id": scenario_id, "problems": ["unknown scenario id"]})
    known_failed = {f["id"] for f in failed if f["id"] in by_id}
    return {"total": len(SCENARIOS), "passed": len(SCENARIOS) - len(known_failed), "failed": failed}


def system_prompt_for_arm(arm):
    """The system prompt one arm of a recorded run is recorded
    under, or None for the baseline (no system prompt). The terse
    arm gets TERSE_CONTROL only; the skill arm gets the terse
    control plus the router SKILL.md — the same shape as caveman's
    skill arm ("Answer concisely.\\n\\n{SKILL.md}"), with the
    control text adapted (see the module docstring). Only the
    router skill has a defined arm here: any other name is a
    typo, not a second skill arm. Raises ValueError."""
    if arm == "__baseline__":
        return None
    if arm == "__terse__":
        return TERSE_CONTROL
    if arm != SKILL_ARM:
        raise ValueError(f"unknown arm: {arm!r} (arms are __baseline__, __terse__, {SKILL_ARM})")
    skill_md = (ROOT / "skills" / "orcinus" / "SKILL.md").read_text(encoding="utf-8")
    return f"{TERSE_CONTROL}\n\n{skill_md}"


def _skill_arms(run):
    """Validate a three-arm run's arm names and return its skill
    arms. Fail closed: both control arms are required, at least
    one skill arm is required, and dunder names other than the
    controls are reserved (a typo, not a fourth condition)."""
    if not isinstance(run, dict):
        raise ValueError("three-arm run must be a JSON object mapping arm to decisions")
    for control in CONTROL_ARMS:
        if control not in run:
            raise ValueError(f"three-arm run is missing control arm {control!r}")
    skill_arms = []
    for arm, decisions in run.items():
        if arm in CONTROL_ARMS:
            continue
        if arm.startswith("__"):
            raise ValueError(f"unknown control arm: {arm!r}")
        if not isinstance(decisions, dict):
            raise ValueError(f"arm {arm!r} decisions must be an object")
        skill_arms.append(arm)
    if not skill_arms:
        raise ValueError("three-arm run has no skill arm")
    for control in CONTROL_ARMS:
        if not isinstance(run[control], dict):
            raise ValueError(f"arm {control!r} decisions must be an object")
    return skill_arms


def _assemble_arms_result(arm_results):
    """Per-arm grade_run results plus the per-scenario pass/fail
    table and the deltas. The honest delta is skill-minus-terse;
    the vs-baseline delta is reported alongside it, labelled as
    the conflated comparison it is."""
    by_id = {s["id"]: s for s in SCENARIOS}
    per_scenario = []
    for scenario in SCENARIOS:
        passed = {}
        for arm, result in arm_results.items():
            failed_ids = {f["id"] for f in result["failed"] if f["id"] in by_id}
            passed[arm] = scenario["id"] not in failed_ids
        per_scenario.append({"id": scenario["id"], "passed": passed})
    terse_passed = arm_results["__terse__"]["passed"]
    baseline_passed = arm_results["__baseline__"]["passed"]
    honest_delta = {}
    vs_baseline_delta = {}
    for arm, result in arm_results.items():
        if arm in CONTROL_ARMS:
            continue
        honest_delta[arm] = result["passed"] - terse_passed
        vs_baseline_delta[arm] = result["passed"] - baseline_passed
    return {
        "arms": arm_results,
        "per_scenario": per_scenario,
        "honest_delta": honest_delta,
        "vs_baseline_delta": vs_baseline_delta,
    }


def grade_arms(run):
    """Grade a three-arm run: {arm: {scenario id: decision}}.
    Returns {"arms": {arm: grade_run result}, "per_scenario":
    [{id, passed: {arm: bool}}], "honest_delta": {skill arm:
    skill passed - terse passed}, "vs_baseline_delta": {skill
    arm: skill passed - baseline passed}}. Fail closed via
    _skill_arms: a run without both controls, without a skill
    arm, or with an unknown arm is rejected, not graded."""
    _skill_arms(run)  # fail closed before grading anything
    arm_results = {arm: grade_run(run[arm]) for arm in run}
    return _assemble_arms_result(arm_results)


@contextlib.contextmanager
def isolated_workdir(prefix="orcinus-router-eval-"):
    """A fresh empty temp dir as the working directory, restored
    afterwards. This is the host-isolation half the harness can
    enforce: grading happens with a cwd that holds no project
    settings, no CLAUDE.md, no installed skills — and the grader
    reads no files from the cwd at all."""
    previous = Path.cwd()
    try:
        with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
            os.chdir(tmp)
            yield Path(tmp)
    finally:
        os.chdir(previous)


def grade_arms_isolated(run):
    """Grade a three-arm run with host isolation: each arm is
    graded inside its own fresh empty temp dir (asserted empty),
    so no state is shared or carried from one arm to the next —
    no session persistence across arms. Returns the same shape
    as grade_arms."""
    _skill_arms(run)
    arm_results = {}
    for arm in run:
        with isolated_workdir() as workdir:
            if any(workdir.iterdir()):
                raise RuntimeError(f"isolated workdir is not empty: {workdir}")
            arm_results[arm] = grade_run(run[arm])
    return _assemble_arms_result(arm_results)


def _check_snapshot_arms(arms, *, total, where):
    """Shape of one recorded arm block: both control arms, at
    least one skill arm, each {"passed": int, "total": total}.
    Returns the skill arms. Raises SnapshotError."""
    if not isinstance(arms, dict):
        raise SnapshotError(f"{where}: arms must be an object")
    for control in CONTROL_ARMS:
        if control not in arms:
            raise SnapshotError(f"{where}: required control arm {control!r} is missing")
    skill_arms = []
    for arm, numbers in arms.items():
        if arm in CONTROL_ARMS:
            continue
        if arm.startswith("__"):
            raise SnapshotError(f"{where}: unknown control arm {arm!r}")
        skill_arms.append(arm)
    if not skill_arms:
        raise SnapshotError(f"{where}: no skill arm recorded")
    for arm, numbers in arms.items():
        if not isinstance(numbers, dict):
            raise SnapshotError(f"{where}: arm {arm!r} numbers must be an object")
        passed = numbers.get("passed")
        if isinstance(passed, bool) or not isinstance(passed, int):
            raise SnapshotError(f"{where}: arm {arm!r} passed must be an integer")
        if not 0 <= passed <= total:
            raise SnapshotError(f"{where}: arm {arm!r} passed {passed} is outside 0..{total}")
        if numbers.get("total") != total:
            raise SnapshotError(f"{where}: arm {arm!r} total must be {total}")
    return skill_arms


def _check_snapshot_deltas(arms, honest_delta, vs_baseline_delta, *, where):
    """The recorded deltas must equal the deltas recomputed from
    the recorded per-arm numbers — a delta that disagrees with
    its own arms is a stale snapshot, not a result."""
    if not isinstance(honest_delta, dict) or not isinstance(vs_baseline_delta, dict):
        raise SnapshotError(f"{where}: honest_delta and vs_baseline_delta must be objects")
    terse = arms["__terse__"]["passed"]
    baseline = arms["__baseline__"]["passed"]
    for arm, numbers in arms.items():
        if arm in CONTROL_ARMS:
            continue
        if honest_delta.get(arm) != numbers["passed"] - terse:
            raise SnapshotError(
                f"{where}: honest_delta for {arm!r} is {honest_delta.get(arm)!r}, "
                f"expected {numbers['passed'] - terse}"
            )
        if vs_baseline_delta.get(arm) != numbers["passed"] - baseline:
            raise SnapshotError(
                f"{where}: vs_baseline_delta for {arm!r} is {vs_baseline_delta.get(arm)!r}, "
                f"expected {numbers['passed'] - baseline}"
            )


def _regrade_snapshot_block(block, *, where):
    """Re-grade a snapshot block's stored decisions per arm and
    check the recorded passed counts reproduce. The self-check
    block stores one decisions dict shared by all arms (keyed by
    scenario id); a live block stores one per arm (keyed by arm
    name). The two shapes are disjoint — arm names never collide
    with scenario ids — so anything matching neither is malformed
    and is rejected, not guessed at."""
    decisions = block.get("decisions")
    if not isinstance(decisions, dict) or not decisions:
        raise SnapshotError(f"{where}: decisions must be a non-empty object")
    arms = block["arms"]
    scenario_ids = {s["id"] for s in SCENARIOS}
    if set(decisions) <= set(arms) and all(isinstance(v, dict) for v in decisions.values()):
        per_arm = decisions
    elif set(decisions) <= scenario_ids:
        per_arm = {arm: decisions for arm in arms}
    else:
        raise SnapshotError(
            f"{where}: decisions are neither one dict shared by all arms nor one per arm"
        )
    for arm in arms:
        if arm not in per_arm:
            raise SnapshotError(f"{where}: no stored decisions for arm {arm!r}")
        graded = grade_run(per_arm[arm])
        recorded = arms[arm]["passed"]
        if graded["passed"] != recorded:
            raise SnapshotError(
                f"{where}: arm {arm!r} recorded {recorded}/{graded['total']} but "
                f"re-grading its stored decisions gives {graded['passed']}/{graded['total']} "
                "— update the snapshot"
            )


def validate_router_snapshot(data):
    """Fail-closed shape check for evals/snapshots/router-results.json.
    Requires metadata (live_run bool, total_scenarios matching the
    grader, and — while no live run exists — a note saying the
    numbers are not an agent measurement), a self_check block with
    both control arms and at least one skill arm whose recorded
    deltas recompute from its recorded numbers, and a live block
    that is null or carries the same shape. Returns the data.
    Raises SnapshotError."""
    if not isinstance(data, dict):
        raise SnapshotError("snapshot must be a JSON object")
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        raise SnapshotError("snapshot metadata must be an object")
    for field in ("generated_at", "generated_by", "harness", "eval", "note"):
        if not isinstance(metadata.get(field), str) or not metadata[field]:
            raise SnapshotError(f"snapshot metadata.{field} must be a non-empty string")
    live_run = metadata.get("live_run")
    if not isinstance(live_run, bool):
        raise SnapshotError("snapshot metadata.live_run must be a boolean")
    total = metadata.get("total_scenarios")
    if total != len(SCENARIOS):
        raise SnapshotError(
            f"snapshot metadata.total_scenarios is {total!r}, expected {len(SCENARIOS)}"
        )
    if not live_run and "not an agent measurement" not in metadata["note"]:
        raise SnapshotError(
            "snapshot with live_run false must say its numbers are not an agent measurement"
        )
    self_check = data.get("self_check")
    if not isinstance(self_check, dict):
        raise SnapshotError("snapshot self_check must be an object")
    _check_snapshot_arms(self_check.get("arms"), total=total, where="self_check")
    _check_snapshot_deltas(
        self_check["arms"],
        self_check.get("honest_delta"),
        self_check.get("vs_baseline_delta"),
        where="self_check",
    )
    live = data.get("live", None)
    if live is not None:
        if not isinstance(live, dict):
            raise SnapshotError("snapshot live must be null or an object")
        _check_snapshot_arms(live.get("arms"), total=total, where="live")
        _check_snapshot_deltas(
            live["arms"],
            live.get("honest_delta"),
            live.get("vs_baseline_delta"),
            where="live",
        )
    return data


def check_router_snapshot(path=SNAPSHOT_PATH):
    """Load the committed router snapshot and check it: shape
    (validate_router_snapshot) plus reproduction — the recorded
    per-arm numbers must equal a re-grade of the stored
    decisions, for the self-check block and for a live block when
    one exists. Raises SnapshotError; returns the snapshot."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SnapshotError(f"cannot read {path}: {e}") from e
    validate_router_snapshot(data)
    _regrade_snapshot_block(data["self_check"], where="self_check")
    if data.get("live") is not None:
        _regrade_snapshot_block(data["live"], where="live")
    return data


def _print_three_arm_result(result):
    """Per-arm scores, the honest delta, and the skill arm's
    failures, for a graded three-arm run."""
    for arm, graded in result["arms"].items():
        print(f"{arm}: {graded['passed']}/{graded['total']} scenarios pass")
    for skill, delta in result["honest_delta"].items():
        terse = result["arms"]["__terse__"]["passed"]
        skill_passed = result["arms"][skill]["passed"]
        print(
            f"honest delta ({skill} minus __terse__): {delta:+d} "
            f"scenario{'s' if abs(delta) != 1 else ''} ({skill_passed} - {terse})"
        )
        baseline = result["arms"]["__baseline__"]["passed"]
        vs_baseline = result["vs_baseline_delta"][skill]
        print(
            f"skill vs baseline ({skill} minus __baseline__): {vs_baseline:+d} "
            f"scenarios ({skill_passed} - {baseline}) — conflated comparison, "
            "not the honest delta"
        )
    for row in result["per_scenario"]:
        passed = row["passed"]
        skill_arms = [a for a in passed if a not in CONTROL_ARMS]
        for skill in skill_arms:
            if passed[skill] != passed["__terse__"]:
                terse_word = "PASS" if passed["__terse__"] else "FAIL"
                skill_word = "PASS" if passed[skill] else "FAIL"
                print(f"DELTA {row['id']}: __terse__ {terse_word}, {skill} {skill_word}")
    for skill in result["honest_delta"]:
        for failed in result["arms"][skill]["failed"]:
            print(f"FAIL {failed['id']}: {'; '.join(failed['problems'])}")


def main(argv):
    if argv == ["--check-snapshot"]:
        try:
            snapshot = check_router_snapshot()
        except SnapshotError as e:
            print(f"snapshot check failed: {e}", file=sys.stderr)
            return 1
        self_check = snapshot["self_check"]
        arms = ", ".join(
            f"{arm} {numbers['passed']}/{numbers['total']}"
            for arm, numbers in self_check["arms"].items()
        )
        live = "no live run recorded" if snapshot.get("live") is None else "live run recorded"
        print(f"snapshot OK: self-check {arms}; {live}")
        return 0
    if len(argv) > 1:
        print(
            f"usage: {Path(argv[0]).name} [<decisions.json>|<run.json>|--check-snapshot]",
            file=sys.stderr,
        )
        return 2
    self_check = not argv
    if argv:
        try:
            data = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"cannot read decisions file: {e}", file=sys.stderr)
            return 2
        if not isinstance(data, dict):
            print("decisions file must be a JSON object", file=sys.stderr)
            return 2
        if "arms" in data:
            if set(data) != {"arms"}:
                print("three-arm run file must contain only an 'arms' object", file=sys.stderr)
                return 2
            try:
                result = grade_arms_isolated(data["arms"])
            except ValueError as e:
                print(f"invalid three-arm run: {e}", file=sys.stderr)
                return 2
            _print_three_arm_result(result)
            skill_failed = any(result["arms"][skill]["failed"] for skill in result["honest_delta"])
            return 0 if not skill_failed else 1
        decisions = data
    else:
        decisions = REFERENCE_DECISIONS
    result = grade_run(decisions)
    for scenario in SCENARIOS:
        failed = next((f for f in result["failed"] if f["id"] == scenario["id"]), None)
        if failed is None:
            print(f"PASS {scenario['id']}")
        else:
            print(f"FAIL {scenario['id']}: {'; '.join(failed['problems'])}")
    for failed in result["failed"]:
        if failed["id"] not in {s["id"] for s in SCENARIOS}:
            print(f"FAIL {failed['id']}: {'; '.join(failed['problems'])}")
    if self_check:
        # Round 7, F-19: the default run grades REFERENCE_DECISIONS,
        # the expected answers written out in this file — label it
        # so the score cannot be cited as agent performance. A
        # mock-style self-check proves the grader runs, not that an
        # agent routes correctly.
        print(
            f"{result['passed']}/{result['total']} scenarios pass "
            "(self-check against REFERENCE_DECISIONS — not an agent measurement)"
        )
    else:
        print(f"{result['passed']}/{result['total']} scenarios pass")
    return 0 if not result["failed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
