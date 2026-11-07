"""Tests for scripts/router_eval.py — the programmatic router eval
(round 6, 2-R1).

The router itself is prose (an LLM following skills/orcinus/SKILL.md),
so this eval cannot run the router: it scores a recorded routing
decision (JSON: stage, routes, mode, missing) against 12 repo-state
scenarios with a deterministic grader. A scenario's expected stage
and route come from the repo's own routing table, stages.json, and
skill-status — the test below pins the scenarios to those sources,
so an expectation that drifts from the router fails here.

Run: python3 -m pytest scripts/test_router_eval.py -q
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import router_eval as rev  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _manifest_skills():
    manifest = json.loads((REPO / "skills" / "manifest.json").read_text(encoding="utf-8"))
    return set(manifest["skills"])


def _routing_table_stages():
    text = (REPO / "skills" / "orcinus" / "SKILL.md").read_text(encoding="utf-8")
    table = text[text.index("## Routing") : text.index("\n## ", text.index("## Routing") + 1)]
    stages = set()
    for line in table.splitlines():
        if line.startswith("|") and "---" not in line and "Stage" not in line:
            stages.add(line.strip().strip("|").split("|")[0].strip())
    return stages


def test_twelve_scenarios_grounded_in_repo():
    """~12 scenarios (reviewer 2's ask), each grounded: every expected
    route is a real skill, every expected stage is a Stage cell in
    the router's own routing table."""
    assert len(rev.SCENARIOS) == 12
    skills = _manifest_skills()
    stages = _routing_table_stages()
    kinds = set()
    for scenario in rev.SCENARIOS:
        assert scenario["expected_stage"] in stages, scenario["id"]
        assert scenario["expected_routes"], scenario["id"]
        for route in scenario["expected_routes"]:
            assert route in skills, (scenario["id"], route)
        kinds.add(scenario["id"])
    assert len(kinds) == 12  # ids unique
    # The required coverage: a cross-cutting scenario, a Lite-mode
    # scenario, and a missing-sub-skill scenario.
    by_id = {s["id"]: s for s in rev.SCENARIOS}
    assert len(by_id["slice-done-auth"]["expected_routes"]) == 2
    assert by_id["typo-patch-lite"]["expected_mode"] == "lite"
    assert by_id["benchmark-missing"]["expected_missing"] == ["SWE-bench"]


def test_reference_decisions_all_pass():
    """The reference decision for every scenario grades PASS — the
    grader accepts a correct routing."""
    result = rev.grade_run(rev.REFERENCE_DECISIONS)
    assert result["passed"] == 12 and result["failed"] == []


def test_wrong_stage_fails():
    decision = dict(rev.REFERENCE_DECISIONS["builds-slice"])
    decision["stage"] = "Verify"
    ok, problems = rev.grade_decision(rev.SCENARIOS[4], decision)
    assert not ok and any("stage" in p for p in problems)


def test_wrong_route_fails():
    decision = dict(rev.REFERENCE_DECISIONS["builds-slice"])
    decision["routes"] = ["scaffold"]
    ok, problems = rev.grade_decision(rev.SCENARIOS[4], decision)
    assert not ok and any("route" in p for p in problems)


def test_missing_cross_cutting_route_fails():
    """A slice that touches auth routed to Verify alone — without the
    security-review leg — fails: cross-cutting is a second route,
    not an ambiguity to drop."""
    decision = dict(rev.REFERENCE_DECISIONS["slice-done-auth"])
    decision["routes"] = ["orcinus-verify"]
    scenario = next(s for s in rev.SCENARIOS if s["id"] == "slice-done-auth")
    ok, problems = rev.grade_decision(scenario, decision)
    assert not ok and any("security-review" in p for p in problems)


def test_lite_mode_mismatch_fails():
    """A typo patch routed in Full mode (or with independent review
    in its routes) fails the Lite scenario."""
    scenario = next(s for s in rev.SCENARIOS if s["id"] == "typo-patch-lite")
    decision = dict(rev.REFERENCE_DECISIONS["typo-patch-lite"])
    decision["mode"] = "full"
    ok, _ = rev.grade_decision(scenario, decision)
    assert not ok
    decision = dict(rev.REFERENCE_DECISIONS["typo-patch-lite"])
    decision["routes"] = ["build", "independent-review"]
    ok, _ = rev.grade_decision(scenario, decision)
    assert not ok


def test_missing_subskill_unreported_fails():
    """The benchmark scenario must name the missing skill (SWE-bench,
    status todo) instead of silently routing as if it existed."""
    scenario = next(s for s in rev.SCENARIOS if s["id"] == "benchmark-missing")
    decision = dict(rev.REFERENCE_DECISIONS["benchmark-missing"])
    decision.pop("missing")
    ok, problems = rev.grade_decision(scenario, decision)
    assert not ok and any("SWE-bench" in p for p in problems)


def test_unknown_route_fails():
    decision = dict(rev.REFERENCE_DECISIONS["builds-slice"])
    decision["routes"] = ["build", "no-such-skill"]
    ok, problems = rev.grade_decision(rev.SCENARIOS[4], decision)
    assert not ok and any("no-such-skill" in p for p in problems)


def test_grade_run_scores_partial():
    decisions = dict(rev.REFERENCE_DECISIONS)
    wrong = dict(decisions["builds-slice"])
    wrong["stage"] = "Verify"
    decisions["builds-slice"] = wrong
    result = rev.grade_run(decisions)
    assert result["passed"] == 11 and result["total"] == 12
    assert [f["id"] for f in result["failed"]] == ["builds-slice"]


def test_cli_no_args_grades_reference_decisions(capsys):
    assert rev.main([]) == 0
    assert "12/12" in capsys.readouterr().out


def test_cli_no_args_labels_self_check_not_an_agent_measurement(capsys):
    """Round 7, F-19: the default run grades REFERENCE_DECISIONS —
    the expected answers, written out so the grader can be
    self-checked — so its output must say so, and must not be
    citable as agent performance."""
    assert rev.main([]) == 0
    out = capsys.readouterr().out
    assert "self-check" in out
    assert "not an agent measurement" in out


def test_cli_decisions_file_has_no_self_check_label(tmp_path, capsys):
    """The label belongs to the default self-check only: grading a
    recorded run prints the plain score."""
    path = tmp_path / "decisions.json"
    path.write_text(json.dumps(rev.REFERENCE_DECISIONS), encoding="utf-8")
    assert rev.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "12/12" in out
    assert "not an agent measurement" not in out


def test_cli_decisions_file(tmp_path, capsys):
    decisions = dict(rev.REFERENCE_DECISIONS)
    wrong = dict(decisions["builds-slice"])
    wrong["routes"] = ["scaffold"]
    decisions["builds-slice"] = wrong
    path = tmp_path / "decisions.json"
    path.write_text(json.dumps(decisions), encoding="utf-8")
    assert rev.main([str(path)]) == 1
    assert "builds-slice" in capsys.readouterr().out


def test_router_eval_doc_exists():
    """The eval lives where the repo's other evals live: evals/."""
    doc = REPO / "evals" / "router-01.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8")
    assert "router_eval.py" in text
    assert "12" in text
