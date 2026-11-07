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
import select
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_eval as re_mod  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


def _fake_claude(bin_dir, body):
    """A fake `claude` executable running the given Python body.

    Plants both the POSIX script (`claude`, shebang + exec bit) and
    the Windows form (`claude.cmd` forwarding to `fake_claude.py`
    via the current interpreter): Windows cannot execute an
    extensionless file — CreateProcess only tries the exact name
    and `.exe`, never PATHEXT — so the script alone is never
    started there and every trial failed with "could not start
    'claude': [WinError 2]". run_eval resolves the tool with
    shutil.which (PATHEXT-aware), so it finds the .cmd.
    """
    text = "#!/usr/bin/env python3\nimport sys\n" + body
    script = bin_dir / "claude"
    script.write_text(text, encoding="utf-8")
    script.chmod(0o755)
    impl = bin_dir / "fake_claude.py"
    impl.write_text(text, encoding="utf-8")
    wrapper = bin_dir / "claude.cmd"
    wrapper.write_text(
        f"@echo off\r\n\"{sys.executable}\" \"%~dp0fake_claude.py\" %*\r\n",
        encoding="utf-8",
    )
    return script


def _run_one(tmp_path, bin_dir, timeout=10):
    """Run one query against the fake (or missing) claude on PATH.

    The bin dir comes first so the fake wins; /usr/bin:/bin stay
    so the fake's `#!/usr/bin/env python3` shebang still resolves.
    There is no real `claude` in /usr/bin:/bin in this VM, so the
    missing-CLI test still reproduces. The PATH is built with
    os.pathsep: the old `f"{bin_dir}:/usr/bin:/bin"` was one
    unparsable entry on Windows, so the fake was never on PATH
    there at all.
    """
    if sys.platform == "win32":
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        path_entries = [
            str(bin_dir),
            os.path.join(system_root, "System32"),
            system_root,
        ]
    else:
        path_entries = [str(bin_dir), "/usr/bin", "/bin"]
    path = os.pathsep.join(path_entries)
    env = dict(os.environ)
    env["PATH"] = path
    env.pop("CLAUDECODE", None)
    old_path = os.environ.get("PATH")
    os.environ["PATH"] = path
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


def test_run_single_query_does_not_depend_on_select(tmp_path, monkeypatch):
    # Windows: select.select only accepts sockets, so waiting on the
    # claude stdout pipe raises OSError [WinError 10038] and the
    # trial crashed instead of returning NOT_TRIGGERED. Simulate
    # that here: run_single_query must not depend on select at all.
    def _boom(*args, **kwargs):
        raise OSError(10038, "An operation was attempted on something that is not a socket")

    monkeypatch.setattr(select, "select", _boom)
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


def test_fake_claude_is_planted_windows_runnable(tmp_path):
    # Windows cannot execute an extensionless file: CreateProcess
    # only tries the exact name and `.exe`, never PATHEXT, so the
    # `claude` script alone is never started there. The fake must
    # also be planted as `claude.cmd` forwarding to the Python impl.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_claude(bin_dir, 'print("hi")\n')
    wrapper = bin_dir / "claude.cmd"
    assert wrapper.is_file()
    assert "fake_claude.py" in wrapper.read_text(encoding="utf-8")
    assert (bin_dir / "fake_claude.py").is_file()


def test_resolve_claude_wraps_batch_file_on_windows(monkeypatch):
    # The npm-installed `claude` on Windows is a `claude.cmd` shim:
    # shutil.which finds it via PATHEXT, but CreateProcess cannot
    # run a .cmd directly — it has to go through cmd.exe.
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", lambda cmd: r"C:\fake\bin\claude.cmd")
    monkeypatch.setenv("ComSpec", r"C:\Windows\System32\cmd.exe")
    assert re_mod._resolve_claude() == [
        r"C:\Windows\System32\cmd.exe",
        "/c",
        r"C:\fake\bin\claude.cmd",
    ]


def test_resolve_claude_returns_executable_directly(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/claude")
    assert re_mod._resolve_claude() == ["/usr/bin/claude"]


def test_resolve_claude_returns_none_when_missing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    assert re_mod._resolve_claude() is None


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


def test_skill_tool_use_is_triggered(tmp_path):
    # The TRIGGERED path through the reader thread: the fake reads
    # the command file run_single_query wrote (its stem is the skill
    # name claude was told to read) and emits a Skill tool_use for
    # it. Guards the event-parser move into _feed (a missing
    # nonlocal would break exactly this path).
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_claude(
        bin_dir,
        'from pathlib import Path\n'
        'import glob, json\n'
        'cmds = sorted(glob.glob(".claude/commands/*.md"))\n'
        'name = Path(cmds[0]).stem if cmds else "missing"\n'
        'print(json.dumps({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Skill"}}}))\n'
        'print(json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": json.dumps({"skill": name})}}}))\n',
    )
    status, error = _run_one(tmp_path, bin_dir)
    assert status == "TRIGGERED"
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
