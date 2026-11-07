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

Usage:
    python3 scripts/router_eval.py
        Grade the reference decisions (self-check against
        REFERENCE_DECISIONS: 12/12 — not an agent measurement).
    python3 scripts/router_eval.py <decisions.json>
        Grade a recorded run: a JSON object mapping scenario id to
        a decision. Prints per-scenario PASS/FAIL and the score;
        exits 0 only when every scenario passes.

Stdlib only. The scenarios are also documented in
evals/router-01.md, which records that no live-agent run has
happened yet: the grader is programmatic, the agent run is open.
"""

import json
import sys
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


def main(argv):
    if len(argv) > 1:
        print(f"usage: {Path(argv[0]).name} [<decisions.json>]", file=sys.stderr)
        return 2
    self_check = not argv
    if argv:
        try:
            decisions = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"cannot read decisions file: {e}", file=sys.stderr)
            return 2
        if not isinstance(decisions, dict):
            print("decisions file must be a JSON object", file=sys.stderr)
            return 2
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
