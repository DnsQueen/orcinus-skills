"""Tests for record_check.py (the execution-binding wrapper, round 7, F-01).

record_check.py runs one check command and records a transcript the
validator can recompute: argv, cwd, timestamps, exit code, the raw
stdout/stderr files with their sha256, and the content digest +
revision of the tree at run time, all bound by one hash
(capture_sha256) over canonical JSON. The tests run the wrapper for
real, in a throwaway git repo, and check the fragment and the files
it writes — never a hand-written fragment.

Run: python3 -m pytest skills/orcinus-verify/scripts/test_record_check.py -q
"""

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import record_check as rc  # noqa: E402
import validate_evidence as ve  # noqa: E402

_RECORD_CHECK = Path(__file__).resolve().parent / "record_check.py"
_SCHEMA = ve.load_schema(
    Path(__file__).resolve().parent.parent / "references" / "evidence.schema.json"
)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@orcinus.local")
    _git(repo, "config", "user.name", "ORCINUS Test")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "code")
    return repo


def _head_sha(repo):
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _run_record(repo, out_dir, name, argv, extra=()):
    """Run record_check.py for real; return (proc, fragment-or-None)."""
    proc = subprocess.run(
        [
            sys.executable,
            str(_RECORD_CHECK),
            "--name",
            name,
            "--out-dir",
            str(out_dir),
            "--repo",
            str(repo),
            *extra,
            "--",
            *argv,
        ],
        capture_output=True,
        text=True,
        cwd=repo,
        timeout=60,
    )
    fragment = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc, fragment


def test_recorded_check_fragment(tmp_path):
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    proc, fragment = _run_record(repo, out_dir, "test", [sys.executable, "-c", "print('ok')"])
    assert proc.returncode == 0, proc.stderr
    assert fragment is not None
    assert fragment["name"] == "test"
    assert fragment["command_argv"] == [sys.executable, "-c", "print('ok')"]
    assert fragment["shell"] is False
    assert fragment["cwd"] == str(repo.resolve())
    assert fragment["exit_code"] == 0
    assert fragment["recorded_by"] == "record_check.py/1"
    assert fragment["content_digest"].startswith("sha256:")
    assert fragment["revision"] == _head_sha(repo)
    assert fragment["stdout_sha256"] == hashlib.sha256(b"ok\n").hexdigest()
    assert fragment["stderr_sha256"] == hashlib.sha256(b"").hexdigest()
    assert fragment["stdout_artifact"] == "test.stdout"
    assert fragment["stderr_artifact"] == "test.stderr"
    assert len(fragment["capture_sha256"]) == 64


def test_capture_files_hash_correctly(tmp_path):
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    proc, fragment = _run_record(repo, out_dir, "test", [sys.executable, "-c", "print('ok')"])
    assert proc.returncode == 0, proc.stderr
    stdout = (out_dir / "test.stdout").read_bytes()
    stderr = (out_dir / "test.stderr").read_bytes()
    assert stdout == b"ok\n"
    assert stderr == b""
    assert hashlib.sha256(stdout).hexdigest() == fragment["stdout_sha256"]
    assert hashlib.sha256(stderr).hexdigest() == fragment["stderr_sha256"]


def test_shell_flag_records_shell_true(tmp_path):
    import shutil

    if shutil.which("sh") is None:
        import pytest

        pytest.skip("sh is not installed")
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    proc, fragment = _run_record(repo, out_dir, "lint", ["echo hi"], extra=("--shell",))
    assert proc.returncode == 0, proc.stderr
    assert fragment["shell"] is True
    assert fragment["command_argv"] == ["sh", "-c", "echo hi"]
    assert fragment["command"] == "echo hi"
    assert (out_dir / "lint.stdout").read_bytes() == b"hi\n"


def test_nonzero_exit_code_captured_faithfully(tmp_path):
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    proc, fragment = _run_record(
        repo,
        out_dir,
        "test",
        [sys.executable, "-c", "import sys; sys.exit(3)"],
    )
    # The wrapper exits with the command's exit code, and still
    # prints the fragment: a failing gate is a recorded failure,
    # not a missing recording.
    assert proc.returncode == 3, proc.stderr
    assert fragment is not None
    assert fragment["exit_code"] == 3


def test_output_over_cap_fails_without_fragment(tmp_path):
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    proc, fragment = _run_record(
        repo,
        out_dir,
        "test",
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('x' * (10 * 1024 * 1024 + 1))",
        ],
    )
    assert proc.returncode == 2, proc.stderr
    assert fragment is None
    assert "larger than" in proc.stderr
    assert not (out_dir / "test.stdout").exists()
    assert not (out_dir / "test.stderr").exists()


def test_timestamps_are_utc(tmp_path):
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    proc, fragment = _run_record(repo, out_dir, "test", [sys.executable, "-c", "print('ok')"])
    assert proc.returncode == 0, proc.stderr
    for field in ("started_at", "finished_at"):
        value = fragment[field]
        assert value.endswith("Z"), value
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timezone.utc.utcoffset(None)
    started = datetime.fromisoformat(fragment["started_at"].replace("Z", "+00:00"))
    finished = datetime.fromisoformat(fragment["finished_at"].replace("Z", "+00:00"))
    assert finished >= started


def test_timeout_kills_a_hanging_command(tmp_path):
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    proc, fragment = _run_record(
        repo,
        out_dir,
        "test",
        [sys.executable, "-c", "import time; time.sleep(5)"],
        extra=("--timeout", "1"),
    )
    assert proc.returncode == 2, proc.stderr
    assert fragment is None
    assert "timed out" in proc.stderr


def test_missing_command_fails_without_fragment(tmp_path):
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    proc, fragment = _run_record(repo, out_dir, "test", ["definitely-not-a-command-xyz"])
    assert proc.returncode == 2, proc.stderr
    assert fragment is None


def test_name_rejects_path_traversal(tmp_path):
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    for bad_name in ("../evil", "a/b", ".hidden", ""):
        proc, fragment = _run_record(repo, out_dir, bad_name, [sys.executable, "-c", "print('ok')"])
        assert proc.returncode == 2, (bad_name, proc.stderr)
        assert fragment is None


def test_not_a_git_repo_fails(tmp_path):
    # No --repo and a cwd outside any git repo: there is no tree
    # digest to bind the capture to, so the wrapper refuses.
    plain = tmp_path / "plain"
    plain.mkdir()
    proc = subprocess.run(
        [
            sys.executable,
            str(_RECORD_CHECK),
            "--name",
            "test",
            "--out-dir",
            str(tmp_path / "bundle"),
            "--",
            sys.executable,
            "-c",
            "print('ok')",
        ],
        capture_output=True,
        text=True,
        cwd=plain,
        timeout=60,
    )
    assert proc.returncode == 2, proc.stderr
    assert not proc.stdout.strip()


def test_binding_hash_is_canonical_and_field_sensitive():
    fields = {
        "command_argv": [sys.executable, "-c", "print('ok')"],
        "shell": False,
        "cwd": "/repo",
        "started_at": "2026-11-08T00:00:00.000000Z",
        "finished_at": "2026-11-08T00:00:01.000000Z",
        "exit_code": 0,
        "stdout_sha256": hashlib.sha256(b"ok\n").hexdigest(),
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "content_digest": "sha256:" + "a" * 64,
        "revision": "b" * 40,
    }
    first = rc.capture_binding_hash(**fields)
    assert first == rc.capture_binding_hash(**fields)
    assert len(first) == 64
    for changed in (
        {"exit_code": 1},
        {"command_argv": [sys.executable, "-c", "print('nope')"]},
        {"content_digest": "sha256:" + "c" * 64},
        {"revision": "d" * 40},
        {"stdout_sha256": hashlib.sha256(b"other\n").hexdigest()},
    ):
        assert rc.capture_binding_hash(**{**fields, **changed}) != first, changed


def test_cap_constant_matches_validator():
    # The wrapper and the validator must agree on the cap, or a
    # recorded capture could be too large for the validator to read.
    assert rc.MAX_CAPTURE_BYTES == ve.MAX_ARTIFACT_BYTES


def test_recorded_check_validates_in_a_pass_bundle(tmp_path):
    # End to end: a check recorded by the wrapper validates as part
    # of a PASS bundle (docs-only, so no fail-first proof is needed).
    # The schema version is read from the schema itself, so this
    # test survives the next bump.
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    proc, fragment = _run_record(repo, out_dir, "test", [sys.executable, "-c", "print('ok')"])
    assert proc.returncode == 0, proc.stderr
    check = dict(fragment)
    # The fragment records the run, not the judgement: the agent adds
    # the verdict and the tool version when pasting it into the bundle.
    check["tool_version"] = "python 3.12.3"
    check["verdict"] = "PASS"
    bundle = {
        "schema_version": _SCHEMA["properties"]["schema_version"]["const"],
        "revision": "working-tree",
        "working_tree_state": "clean",
        "requirement": "Record one check.",
        "acceptance_criteria": ["The recorded check validates."],
        "files_changed": ["README.md"],
        "checks": [check],
        "findings": [],
        "unresolved_risks": [],
        "unverified_items": [],
        "verdict": "PASS",
        "reviewer_identity": "orcinus-verify (independent session)",
        "implementer_identity": "implementer (author session)",
        "verification_plan": {
            "change_type": "docs-only",
            "required_gates": ["test"],
            "not_applicable_gates": [
                {"gate": "build", "reason": "Docs-only change; nothing to build."},
                {"gate": "lint", "reason": "Docs-only change; no code to lint."},
                {"gate": "typecheck", "reason": "Docs-only change; nothing to typecheck."},
            ],
        },
    }
    assert ve.validate_bundle(bundle, _SCHEMA, bundle_dir=out_dir) == []
