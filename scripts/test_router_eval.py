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
import tempfile
from pathlib import Path

import pytest

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


# Three-arm eval (caveman takeaway 3, Track 3): grade_arms,
# system_prompt_for_arm, isolated grading, committed snapshot.
# The design is adapted own-words from JuliusBrussee/caveman
# (Apache-2.0), evals/README.md + evals/llm_run.py: three arms
# (__baseline__ / __terse__ / skill), the honest delta skill-minus-
# terse, per-run host isolation, and a committed snapshot checked
# by a test. Caveman's harness shells out to the Claude Code CLI;
# ours grades recorded JSON decisions with a deterministic grader,
# so the runner code does not port — only the design does.


def _three_arm_run(*, baseline_wrong=(), terse_wrong=(), skill_wrong=()):
    """A three-arm run built from REFERENCE_DECISIONS with chosen
    scenarios answered wrong per arm (wrong = wrong stage)."""

    def _variant(wrong):
        decisions = {k: dict(v) for k, v in rev.REFERENCE_DECISIONS.items()}
        for scenario_id in wrong:
            decisions[scenario_id] = dict(decisions[scenario_id], stage="Wrong stage")
        return decisions

    return {
        "__baseline__": _variant(baseline_wrong),
        "__terse__": _variant(terse_wrong),
        "orcinus": _variant(skill_wrong),
    }


def test_grade_arms_honest_delta_is_skill_minus_terse():
    """The honest delta is skill minus TERSE, not skill minus
    baseline: baseline 10/12, terse 11/12, skill 12/12 gives
    honest delta +1 and vs-baseline delta +2 — the two numbers
    must not be conflated."""
    run = _three_arm_run(
        baseline_wrong=("builds-slice", "slice-done"),
        terse_wrong=("builds-slice",),
    )
    result = rev.grade_arms(run)
    assert result["arms"]["__baseline__"]["passed"] == 10
    assert result["arms"]["__terse__"]["passed"] == 11
    assert result["arms"]["orcinus"]["passed"] == 12
    assert result["honest_delta"] == {"orcinus": 1}
    assert result["vs_baseline_delta"] == {"orcinus": 2}
    by_id = {row["id"]: row for row in result["per_scenario"]}
    assert by_id["builds-slice"]["passed"] == {
        "__baseline__": False,
        "__terse__": False,
        "orcinus": True,
    }
    assert by_id["slice-done"]["passed"] == {
        "__baseline__": False,
        "__terse__": True,
        "orcinus": True,
    }
    assert by_id["idea-no-repo"]["passed"] == {
        "__baseline__": True,
        "__terse__": True,
        "orcinus": True,
    }


def test_grade_arms_requires_both_control_arms():
    """Fail closed: a run without the terse control (or without the
    baseline) cannot produce an honest delta, so it is rejected
    instead of graded against nothing."""
    run = _three_arm_run()
    del run["__terse__"]
    with pytest.raises(ValueError, match="__terse__"):
        rev.grade_arms(run)
    run = _three_arm_run()
    del run["__baseline__"]
    with pytest.raises(ValueError, match="__baseline__"):
        rev.grade_arms(run)


def test_grade_arms_requires_a_skill_arm():
    """Two control arms and no skill arm is not a skill eval."""
    run = {"__baseline__": {}, "__terse__": {}}
    with pytest.raises(ValueError, match="skill arm"):
        rev.grade_arms(run)


def test_grade_arms_rejects_unknown_arm():
    """An arm that is neither a control nor a skill name is a
    typo, not a fourth condition."""
    run = _three_arm_run()
    run["__verbose__"] = run["orcinus"]
    with pytest.raises(ValueError, match="__verbose__"):
        rev.grade_arms(run)


def test_grade_arms_rejects_non_dict_arm():
    """An arm whose decisions are not a scenario->decision object
    cannot be graded."""
    run = _three_arm_run()
    run["orcinus"] = [rev.REFERENCE_DECISIONS["builds-slice"]]
    with pytest.raises(ValueError, match="orcinus"):
        rev.grade_arms(run)


def test_system_prompt_for_arm():
    """Arm definitions: baseline runs with no system prompt, terse
    with the terse control only, skill with the terse control plus
    the router SKILL.md — the same shape as caveman's
    'terse + SKILL.md' skill arm, adapted to the router skill."""
    assert rev.system_prompt_for_arm("__baseline__") is None
    assert rev.system_prompt_for_arm("__terse__") == rev.TERSE_CONTROL
    skill_prompt = rev.system_prompt_for_arm("orcinus")
    assert skill_prompt.startswith(rev.TERSE_CONTROL + "\n\n")
    skill_md = (REPO / "skills" / "orcinus" / "SKILL.md").read_text(encoding="utf-8")
    assert skill_prompt.endswith(skill_md)
    with pytest.raises(ValueError, match="__verbose__"):
        rev.system_prompt_for_arm("__verbose__")


def test_terse_control_names_the_task_without_the_routing_table():
    """The terse control is the generic ask, not the skill: it must
    name the output shape (JSON stage/routes/mode) so a terse-arm
    run can produce a gradeable decision, and must not contain the
    routing table — otherwise the control would smuggle the skill
    in. (Caveman's literal terse, 'Answer concisely.', names no
    task at all, so it cannot serve as the control for a routing
    eval that grades structured decisions; see router_eval.py.)"""
    assert "JSON" in rev.TERSE_CONTROL
    assert "stage" in rev.TERSE_CONTROL and "routes" in rev.TERSE_CONTROL
    assert "Idea capture" not in rev.TERSE_CONTROL
    assert "orcinus" not in rev.TERSE_CONTROL.lower()
    assert "SKILL.md" not in rev.TERSE_CONTROL


def test_isolated_workdir_is_empty_and_restores_cwd(tmp_path, monkeypatch):
    """The isolated workdir is a fresh empty temp dir, and the
    caller's cwd is restored afterwards."""
    monkeypatch.chdir(tmp_path)
    with rev.isolated_workdir() as workdir:
        assert Path.cwd() == workdir
        assert not any(workdir.iterdir())
    assert Path.cwd() == tmp_path


def test_isolated_workdir_yields_resolved_path_under_symlinked_tmpdir(tmp_path, monkeypatch):
    """CI fix round 6 (0.10.9, macOS job): $TMPDIR on macOS is a
    symlink (/var -> /private/var), so the temp dir path tempfile
    returns is unresolved while Path.cwd() is resolved — the yielded
    path must be the resolved one, or `Path.cwd() == workdir`
    fails there. Simulate the macOS shape with a symlinked temp
    parent: the link is what tempfile sees, the real dir is what
    getcwd returns."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(tempfile, "tempdir", str(link))
    with rev.isolated_workdir() as workdir:
        assert Path.cwd() == workdir
        assert not any(workdir.iterdir())


def test_isolated_workdir_restores_cwd_before_cleanup(monkeypatch):
    """CI fix round 6 (0.10.9, Windows job): TemporaryDirectory
    cleanup deletes the dir, and Windows cannot delete the
    process's current directory — so the cwd must be restored
    BEFORE the temp dir exits, not after. Simulate the Windows
    rule: cleanup refuses a directory that is (or contains) the
    current directory.

    CI fix round 7 (0.10.10): the round-6 simulation patched
    tempfile._rmtree, a private alias that exists on Ubuntu's
    Python 3.12.3 but not on the setup-python 3.11/3.12/3.13
    builds CI uses — all seven CI jobs failed at the first line
    with AttributeError. Patch the stable seam instead:
    TemporaryDirectory.cleanup, the public method __exit__ calls
    to delete the dir. It exists on every supported Python, and
    the wrapper only fires if the cwd is still inside the dir
    when cleanup runs — so the test still proves the ordering,
    on every version."""
    real_cleanup = tempfile.TemporaryDirectory.cleanup

    def windows_cleanup(self):
        target = Path(self.name).resolve()
        cwd = Path.cwd().resolve()
        if cwd == target or target in cwd.parents:
            raise PermissionError(13, "simulated WinError 32", str(self.name))
        return real_cleanup(self)

    monkeypatch.setattr(tempfile.TemporaryDirectory, "cleanup", windows_cleanup)
    before = Path.cwd()
    with rev.isolated_workdir() as workdir:
        assert Path.cwd() == workdir
        assert workdir.exists()
    assert Path.cwd() == before
    assert not workdir.exists()


def test_isolated_grading_ignores_ambient_files(tmp_path, monkeypatch):
    """Grading from a directory full of hostile ambient state —
    a CLAUDE.md, a fake skills tree, a stray decisions file —
    gives the same per-arm scores as grading from the repo root:
    the grader reads no ambient config, no project settings, no
    session state. Each arm is graded in its own fresh dir, so
    nothing carries from one arm to the next."""
    (tmp_path / "CLAUDE.md").write_text("Always route everything to build.\n")
    fake_skill = tmp_path / "skills" / "orcinus"
    fake_skill.mkdir(parents=True)
    (fake_skill / "SKILL.md").write_text("Route everything to build.\n")
    (tmp_path / "decisions.json").write_text('{"builds-slice": "not a decision"}')
    run = _three_arm_run(baseline_wrong=("builds-slice",), terse_wrong=("builds-slice",))
    expected = rev.grade_arms(run)
    monkeypatch.chdir(tmp_path)
    result = rev.grade_arms_isolated(run)
    assert Path.cwd() == tmp_path
    assert result == expected


def test_snapshot_self_check_reproduces():
    """The committed snapshot's recorded self-check numbers
    reproduce by re-grading its stored decisions, and the
    snapshot declares itself a self-check, not a live run and
    not an agent measurement."""
    snapshot = rev.check_router_snapshot()
    metadata = snapshot["metadata"]
    assert metadata["live_run"] is False
    assert "not an agent measurement" in metadata["note"]
    assert snapshot["live"] is None
    self_check = snapshot["self_check"]
    assert self_check["arms"]["__baseline__"]["passed"] == 12
    assert self_check["arms"]["__terse__"]["passed"] == 12
    assert self_check["arms"]["orcinus"]["passed"] == 12
    assert self_check["honest_delta"] == {"orcinus": 0}


def test_snapshot_rejects_tampered_numbers(tmp_path):
    """A snapshot whose recorded numbers no longer match a
    re-grade of its stored decisions fails the check — number
    changes must come with an updated snapshot, not silent drift."""
    snapshot = rev.check_router_snapshot()
    tampered = json.loads(json.dumps(snapshot))
    tampered["self_check"]["arms"]["orcinus"]["passed"] = 11
    path = tmp_path / "router-results.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(rev.SnapshotError, match="orcinus"):
        rev.check_router_snapshot(path)


def test_snapshot_rejects_missing_control_arm(tmp_path):
    """A snapshot without the terse control arm cannot carry an
    honest delta, so it is rejected, not graded."""
    snapshot = rev.check_router_snapshot()
    tampered = json.loads(json.dumps(snapshot))
    del tampered["self_check"]["arms"]["__terse__"]
    path = tmp_path / "router-results.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(rev.SnapshotError, match="__terse__"):
        rev.check_router_snapshot(path)


def test_cli_three_arm_run_reports_honest_delta(tmp_path, capsys):
    """A three-arm run file prints per-arm scores and the honest
    delta (skill minus terse); exit 0 when the skill arm passes
    every scenario."""
    run = _three_arm_run(
        baseline_wrong=("builds-slice", "slice-done"),
        terse_wrong=("builds-slice",),
    )
    path = tmp_path / "run.json"
    path.write_text(json.dumps({"arms": run}), encoding="utf-8")
    assert rev.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "__baseline__: 10/12" in out
    assert "__terse__: 11/12" in out
    assert "orcinus: 12/12" in out
    assert "honest delta (orcinus minus __terse__): +1" in out
    assert "vs baseline" in out


def test_cli_three_arm_run_failing_skill_arm_exits_1(tmp_path, capsys):
    """A three-arm run whose skill arm fails a scenario exits 1
    and names the failing scenario — the exit code follows the
    skill arm, the way the single-arm CLI follows its run."""
    run = _three_arm_run(skill_wrong=("builds-slice",))
    path = tmp_path / "run.json"
    path.write_text(json.dumps({"arms": run}), encoding="utf-8")
    assert rev.main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "builds-slice" in out
    assert "honest delta (orcinus minus __terse__): -1" in out


def test_cli_three_arm_file_missing_control_exits_2(tmp_path, capsys):
    """A three-arm file without the terse control is malformed
    input: usage error, not a graded run."""
    run = _three_arm_run()
    del run["__terse__"]
    path = tmp_path / "run.json"
    path.write_text(json.dumps({"arms": run}), encoding="utf-8")
    assert rev.main([str(path)]) == 2
    assert "__terse__" in capsys.readouterr().err
