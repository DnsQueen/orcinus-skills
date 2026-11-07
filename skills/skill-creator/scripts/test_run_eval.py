"""Tests for skills/skill-creator/scripts/run_eval.py.

Round 6 (2026-11-07), 3-R3-06: with `claude` removed from PATH,
run_eval converted the FileNotFoundError into False, so a
should_trigger: false case got pass: true and exit 0 — and the
machine-readable JSON contained no error field at all. Trial
results are now three-state (TRIGGERED / NOT_TRIGGERED / ERROR):
an infrastructure error never counts as NOT_TRIGGERED, rates are
computed only over valid trials, and errors are surfaced in the
JSON output.

Run: python3 -m pytest skills/skill-creator/scripts/test_run_eval.py -q
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_eval as re_mod  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


def _fake_claude(bin_dir, body):
    """A fake `claude` executable running the given Python body."""
    script = bin_dir / "claude"
    script.write_text("#!/usr/bin/env python3\nimport sys\n" + body, encoding="utf-8")
    script.chmod(0o755)
    return script


def _run_one(tmp_path, bin_dir, timeout=10):
    """Run one query against the fake (or missing) claude on PATH.

    The bin dir comes first so the fake wins; /usr/bin:/bin stay
    so the fake's `#!/usr/bin/env python3` shebang still resolves.
    There is no real `claude` in /usr/bin:/bin in this VM, so the
    missing-CLI test still reproduces.
    """
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env.pop("CLAUDECODE", None)
    old_path = os.environ.get("PATH")
    os.environ["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    try:
        return re_mod.run_single_query(
            "how do I write a haiku about the sea",
            "demo-skill",
            "Does things.",
            timeout,
            str(tmp_path),
        )
    finally:
        if old_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = old_path


def test_missing_claude_is_error_not_not_triggered(tmp_path):
    # 3-R3-06: FileNotFoundError used to become False (NOT_TRIGGERED).
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    status, error = _run_one(tmp_path, bin_dir)
    assert status == "ERROR"
    assert error and "claude" in error


def test_other_tool_is_not_triggered(tmp_path):
    # Control: the model using a different tool is a real negative,
    # not an infrastructure error.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_claude(
        bin_dir,
        'import json\n'
        'print(json.dumps({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Bash"}}}))\n',
    )
    status, error = _run_one(tmp_path, bin_dir)
    assert status == "NOT_TRIGGERED"
    assert error is None


def test_failed_claude_exit_is_error(tmp_path):
    # A non-zero exit with no trigger is an infrastructure failure,
    # not a negative result.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_claude(bin_dir, 'import sys\nprint("auth failed", file=sys.stderr)\nsys.exit(1)\n')
    status, error = _run_one(tmp_path, bin_dir)
    assert status == "ERROR"
    assert error and "1" in error


def test_claude_timeout_is_error(tmp_path):
    # A query that never answers is an infrastructure failure, not
    # a negative result.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_claude(bin_dir, 'import time\ntime.sleep(30)\n')
    status, error = _run_one(tmp_path, bin_dir, timeout=1)
    assert status == "ERROR"
    assert error and "timed out" in error.lower()


def _fake_runner(query, skill_name, description, timeout, project_root, model=None):
    """Module-level fake trial runner (picklable for the process pool):
    the haiku query never triggers, the skill query always does, and
    the broken query always errors."""
    if "broken" in query:
        return ("ERROR", "fake infra failure")
    if "haiku" in query:
        return ("NOT_TRIGGERED", None)
    return ("TRIGGERED", None)


def test_run_eval_rates_exclude_errors_and_error_never_passes():
    # 3-R3-06, aggregation: the negative case with only error trials
    # must not pass, rates cover valid trials only, and errors are
    # surfaced per result and in the summary.
    eval_set = [
        {"query": "how do I write a haiku about the sea", "should_trigger": False},
        {"query": "broken query that errors", "should_trigger": False},
        {"query": "use the demo skill to do the thing", "should_trigger": True},
    ]
    output = re_mod.run_eval(
        eval_set=eval_set,
        skill_name="demo-skill",
        description="Does things.",
        num_workers=1,
        timeout=10,
        project_root=Path("/tmp"),
        runs_per_query=2,
        runner=_fake_runner,
    )
    by_query = {r["query"]: r for r in output["results"]}
    negative = by_query["how do I write a haiku about the sea"]
    assert negative["pass"] is True
    assert negative["trigger_rate"] == 0.0
    assert negative["valid_runs"] == 2
    broken = by_query["broken query that errors"]
    assert broken["pass"] is False
    assert broken["trigger_rate"] is None
    assert broken["valid_runs"] == 0
    assert broken["errors"] == ["fake infra failure", "fake infra failure"]
    positive = by_query["use the demo skill to do the thing"]
    assert positive["pass"] is True
    assert positive["trigger_rate"] == 1.0
    assert output["summary"]["errored"] == 1


def _cli_eval_set(tmp_path):
    skill = tmp_path / "demo-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Does things.\n---\n\n# Demo\n",
        encoding="utf-8",
    )
    eval_set = tmp_path / "eval.json"
    eval_set.write_text(
        json.dumps(
            [
                {"query": "how do I write a haiku about the sea", "should_trigger": False},
                {"query": "use the demo skill to do the thing", "should_trigger": True},
            ]
        ),
        encoding="utf-8",
    )
    return skill, eval_set


def test_cli_missing_claude_negative_case_does_not_pass(tmp_path):
    # 3-R3-06, end to end (the reviewer's repro): with `claude`
    # removed from PATH the negative case must not pass, the JSON
    # must carry the errors, and the process must exit non-zero.
    skill, eval_set = _cli_eval_set(tmp_path)
    env = dict(os.environ)
    env["PATH"] = "/usr/bin:/bin"
    env["PYTHONPATH"] = str(REPO_ROOT / "skills" / "skill-creator")
    env.pop("CLAUDECODE", None)
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "skills" / "skill-creator" / "scripts" / "run_eval.py"),
            "--eval-set", str(eval_set),
            "--skill-path", str(skill),
            "--num-workers", "1",
            "--runs-per-query", "1",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=120,
    )
    output = json.loads(proc.stdout)
    by_query = {r["query"]: r for r in output["results"]}
    negative = by_query["how do I write a haiku about the sea"]
    assert negative["pass"] is False
    assert negative["trigger_rate"] is None
    assert negative["errors"], "the JSON must surface the infra error, not only stderr"
    assert output["summary"]["errored"] >= 1
    assert proc.returncode != 0, proc.stdout + proc.stderr
