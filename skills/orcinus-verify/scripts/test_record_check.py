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

# A command whose stdout is byte-identical on every platform. print()
# is NOT one: CPython's TextIOWrapper (newline=None) translates '\n'
# to os.linesep on write, so print('ok') emits b'ok\r\n' on Windows
# and b'ok\n' elsewhere — pinning b'ok\n' for it fails on Windows
# (CI run 42427290363). sys.stdout.buffer.write writes raw bytes
# with no translation, so the recorded bytes are deterministic and
# the exact-byte assertions below are valid on every platform.
_OK_ARGV = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'ok\\n')"]


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


def test_bundled_content_digest_is_byte_identical():
    """FND-003 (round 8): the copy beside record_check.py must be
    byte-identical to scripts/content_digest.py — a drifted copy
    would bind captures to a different digest algorithm."""
    skill_copy = Path(__file__).resolve().parent / "content_digest.py"
    repo_copy = (
        Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "content_digest.py"
    )
    assert skill_copy.is_file(), "bundled content_digest.py is missing from the skill folder"
    if not repo_copy.is_file():
        import pytest

        pytest.skip("repo-root scripts/content_digest.py is absent (skills-only install)")
    assert skill_copy.read_bytes() == repo_copy.read_bytes()


def test_load_content_digest_prefers_beside_self():
    """FND-003 (round 8): _load_content_digest searches beside
    itself FIRST — before the repo-root scripts/ — so a skills-only
    install (no repo checkout) finds its bundled copy."""
    fn = rc._load_content_digest(None)
    assert (
        Path(fn.__code__.co_filename).resolve()
        == (Path(__file__).resolve().parent / "content_digest.py").resolve()
    )


def test_skills_only_install_records_without_digest_module(tmp_path):
    """FND-003 (round 8): a copy of just the skill folder, run with
    the documented step-4 command (no --digest-module), records a
    check: the bundled content_digest.py beside record_check.py is
    found. The copied skill's ancestor chain holds no repo-root
    scripts/, so the repo install path cannot rescue it."""
    import shutil

    skill = Path(__file__).resolve().parent.parent
    elsewhere = tmp_path / "skill-only"
    shutil.copytree(skill, elsewhere)
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    proc = subprocess.run(
        [
            sys.executable,
            str(elsewhere / "scripts" / "record_check.py"),
            "--name",
            "test",
            "--out-dir",
            str(out_dir),
            "--repo",
            str(repo),
            "--",
            *_OK_ARGV,
        ],
        capture_output=True,
        text=True,
        cwd=repo,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    fragment = json.loads(proc.stdout)
    assert fragment["content_digest"].startswith("sha256:")
    assert fragment["revision"] == _head_sha(repo)


def _fake_git(monkeypatch, respond):
    """Stub git by faking subprocess.run.

    No file on PATH can stub git on Windows: CreateProcess appends
    only .exe to an extensionless name (it never consults PATHEXT),
    and a .bat/.cmd file needs cmd.exe to run it — so both the
    extensionless stub and the git.bat stub from round 1 are
    silently ignored and the real git.exe runs (CI runs 42499224528
    and 42501954616). Faking subprocess.run works on every
    platform, so there is no platform branch here at all; non-git
    calls go to the real run, so the check command itself still
    executes for real. `respond(argv, kwargs)` returns the canned
    CompletedProcess for each git call."""
    real_run = subprocess.run

    def fake_run(argv, *args, **kwargs):
        if argv and argv[0] == "git":
            return respond(argv, kwargs)
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)


def _completed(argv, kwargs, stdout):
    """A CompletedProcess with stdout in the call's text/bytes mode:
    the production calls use text=True for rev-parse and bytes for
    ls-tree, and the fake must match or the validation under test
    sees the wrong type."""
    if kwargs.get("text", False):
        out = stdout if isinstance(stdout, str) else stdout.decode("utf-8")
        err = ""
    else:
        out = stdout if isinstance(stdout, bytes) else stdout.encode("utf-8")
        err = b""
    return subprocess.CompletedProcess(argv, 0, stdout=out, stderr=err)


def test_empty_git_output_fails_closed(tmp_path, monkeypatch):
    """FND-023 (round 8): git printing nothing with exit 0 used to
    bind a capture to revision "" and the empty digest. _resolve_repo
    must require --show-toplevel to name an existing directory."""
    repo = _repo(tmp_path)
    seen = []

    def respond(argv, kwargs):
        seen.append(argv)
        return _completed(argv, kwargs, "")

    _fake_git(monkeypatch, respond)
    try:
        rc.record("test", _OK_ARGV, False, tmp_path / "bundle", repo, None, None, 60)
    except rc.RecordError as e:
        # The rejection must come from _resolve_repo (empty
        # --show-toplevel), not a later stage: the message names it,
        # and exactly one git call was made.
        assert "did not name a repository" in str(e), str(e)
        assert seen == [["git", "-C", str(repo), "rev-parse", "--show-toplevel"]], seen
        return
    raise AssertionError("expected RecordError for empty git output")


def test_revision_must_be_a_full_sha(tmp_path, monkeypatch):
    """FND-023 (round 8): _resolve_revision must require rev-parse
    --verify to succeed with a single-line full SHA (40 or 64 hex),
    not any non-empty stdout."""
    repo = _repo(tmp_path)
    seen = []

    def respond(argv, kwargs):
        seen.append(argv)
        if "--show-toplevel" in argv:
            return _completed(argv, kwargs, str(repo) + "\n")
        return _completed(argv, kwargs, "not-a-sha!!\n")

    _fake_git(monkeypatch, respond)
    try:
        rc.record("test", _OK_ARGV, False, tmp_path / "bundle", repo, None, None, 60)
    except rc.RecordError as e:
        # The bad SHA must be rejected by _resolve_revision, not
        # earlier or later: the message names it, and --verify HEAD
        # has to have been asked for (the round-1 $3/$4 bug let this
        # test pass without reaching it).
        assert "not a full commit SHA" in str(e), str(e)
        assert any("--verify" in argv for argv in seen), seen
        return
    raise AssertionError("expected RecordError for a non-SHA revision")


def test_bundled_content_digest_entry_point(tmp_path):
    """FND-001/FND-003 (round 8): the bundled copy's real entry
    point must work too — it is byte-identical to the repo script,
    so its argv handling is the same; this pins it by execution."""
    repo = _repo(tmp_path)
    script = Path(__file__).resolve().parent / "content_digest.py"
    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=repo, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().startswith("sha256:")
    assert len(proc.stdout.strip()) == len("sha256:") + 64


def test_recorded_check_fragment(tmp_path):
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    proc, fragment = _run_record(repo, out_dir, "test", _OK_ARGV)
    assert proc.returncode == 0, proc.stderr
    assert fragment is not None
    assert fragment["name"] == "test"
    assert fragment["command_argv"] == _OK_ARGV
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
    proc, fragment = _run_record(repo, out_dir, "test", _OK_ARGV)
    assert proc.returncode == 0, proc.stderr
    stdout = (out_dir / "test.stdout").read_bytes()
    stderr = (out_dir / "test.stderr").read_bytes()
    assert stdout == b"ok\n"
    assert stderr == b""
    assert hashlib.sha256(stdout).hexdigest() == fragment["stdout_sha256"]
    assert hashlib.sha256(stderr).hexdigest() == fragment["stderr_sha256"]


def test_crlf_stdout_recorded_verbatim(tmp_path):
    # A CRLF-emitting command must be recorded byte-for-byte: the
    # transcript records the bytes that actually happened, so the
    # recorder must never normalise CRLF to LF. This guards against
    # "fixing" the Windows failure inside record_check.py: if the
    # recorder ever rewrote the bytes, the artifact and the fragment
    # hash would stop matching the emitted bytes and this test would
    # fail. Windows itself cannot be reproduced here, so the CRLF
    # bytes are produced explicitly through the raw buffer.
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    proc, fragment = _run_record(
        repo,
        out_dir,
        "test",
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'ok\\r\\n')"],
    )
    assert proc.returncode == 0, proc.stderr
    stdout = (out_dir / "test.stdout").read_bytes()
    stderr = (out_dir / "test.stderr").read_bytes()
    assert stdout == b"ok\r\n"
    assert stderr == b""
    assert fragment["stdout_sha256"] == hashlib.sha256(b"ok\r\n").hexdigest()
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


def test_output_over_cap_does_not_buffer_unboundedly(tmp_path):
    """F2 (friend's review): the 10 MiB cap was checked only after
    subprocess.run buffered the whole output in RAM, so it was not
    a memory cap. The wrapper must stream to disk and kill the
    command as soon as the cap is exceeded: a producer emitting
    200 MiB must be refused with the wrapper's own peak RSS far
    below 200 MiB. Proven through a driver process — its
    RUSAGE_CHILDREN is the wrapper alone (the producer is the
    wrapper's child, not the driver's), so there is no polling race
    and no suite-wide max to pollute the reading. Linux only:
    ru_maxrss is KiB there (bytes on macOS) and the driver uses
    the resource module, which Windows does not have."""
    import pytest

    if sys.platform != "linux":
        pytest.skip("peak-RSS proof needs Linux resource.ru_maxrss (KiB)")
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    driver = tmp_path / "measure_rss.py"
    driver.write_text(
        "import resource, subprocess, sys\n"
        "proc = subprocess.run([sys.executable, sys.argv[1], '--name', 'test',"
        " '--out-dir', sys.argv[2], '--repo', sys.argv[3], '--', sys.executable,"
        " '-c', sys.argv[4]], capture_output=True, text=True)\n"
        "print('RC:', proc.returncode)\n"
        "print('ERR:', proc.stderr.strip().replace(chr(10), ' | '))\n"
        "print('RSS_KB:', resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)\n",
        encoding="utf-8",
    )
    producer = "import sys; [sys.stdout.buffer.write(b'x' * (1024 * 1024)) for _ in range(200)]"
    proc = subprocess.run(
        [sys.executable, str(driver), str(_RECORD_CHECK), str(out_dir), str(repo), producer],
        capture_output=True,
        text=True,
        cwd=repo,
        timeout=120,
    )
    lines = proc.stdout.strip().splitlines()
    assert proc.returncode == 0, proc.stderr
    assert lines[0] == "RC: 2", lines
    assert "larger than" in lines[1], lines
    peak_kb = int(lines[2].split(":", 1)[1].strip())
    assert peak_kb < 100 * 1024, f"wrapper peak RSS {peak_kb} KiB exceeds 100 MiB"
    assert not (out_dir / "test.stdout").exists()
    assert not (out_dir / "test.stderr").exists()


def test_symlink_capture_destination_is_refused(tmp_path):
    """F3 (friend's review): stdout_path.write_bytes follows a
    pre-planted symlink, so a capture could overwrite a file
    outside the bundle dir. A symlinked destination is refused
    before the command runs, and the link's target is untouched."""
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    out_dir.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("untouched\n", encoding="utf-8")
    (out_dir / "test.stdout").symlink_to(victim)
    proc, fragment = _run_record(repo, out_dir, "test", _OK_ARGV)
    assert proc.returncode == 2, proc.stderr
    assert fragment is None
    assert "symlink" in proc.stderr
    assert victim.read_text(encoding="utf-8") == "untouched\n"
    assert not (out_dir / "test.stderr").exists()


def test_symlink_out_dir_is_refused(tmp_path):
    """F3: a bundle directory that is itself a symlink is refused
    — captures must land in the directory named, not wherever the
    link points."""
    repo = _repo(tmp_path)
    target = tmp_path / "elsewhere"
    target.mkdir()
    out_dir = tmp_path / "bundle"
    out_dir.symlink_to(target, target_is_directory=True)
    proc, fragment = _run_record(repo, out_dir, "test", _OK_ARGV)
    assert proc.returncode == 2, proc.stderr
    assert fragment is None
    assert "symlink" in proc.stderr
    assert not (target / "test.stdout").exists()


def test_rerecord_same_name_replaces_regular_capture(tmp_path):
    """F3: a pre-existing REGULAR capture file is replaced atomically
    (re-recording a gate is normal); only symlinks are refused."""
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    proc, fragment = _run_record(repo, out_dir, "test", _OK_ARGV)
    assert proc.returncode == 0, proc.stderr
    proc, fragment2 = _run_record(repo, out_dir, "test", _OK_ARGV)
    assert proc.returncode == 0, proc.stderr
    assert fragment2 is not None
    assert (out_dir / "test.stdout").read_bytes() == b"ok\n"


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


def test_cwd_outside_repo_is_refused(tmp_path):
    """FND-001 (round 9): --cwd in a scratch directory outside any
    repo, with --repo naming a real repo, used to record a capture
    bound to that repo's tree — a fake command in the scratch dir
    could file a PASS for code it never ran against. The wrapper
    must refuse: the repo is derived from the cwd, and an explicit
    --repo must be that repo."""
    repo = _repo(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    proc = subprocess.run(
        [
            sys.executable,
            str(_RECORD_CHECK),
            "--name",
            "test",
            "--out-dir",
            str(tmp_path / "bundle"),
            "--repo",
            str(repo),
            "--",
            *_OK_ARGV,
        ],
        capture_output=True,
        text=True,
        cwd=scratch,
        timeout=60,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert not proc.stdout.strip()
    # The refusal comes from deriving the repo from the cwd (the
    # scratch dir is in no repo at all), before --repo is even
    # compared: no tree means no capture to bind.
    assert "not inside a git repository" in proc.stderr, proc.stderr


def test_repo_must_be_the_repo_containing_cwd(tmp_path):
    """FND-001 (round 9): --repo naming a different real repo than
    the one containing --cwd is refused, even when both exist."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    repo_a = _repo(tmp_path / "a")
    repo_b = _repo(tmp_path / "b")
    proc = subprocess.run(
        [
            sys.executable,
            str(_RECORD_CHECK),
            "--name",
            "test",
            "--out-dir",
            str(tmp_path / "bundle"),
            "--repo",
            str(repo_b),
            "--",
            *_OK_ARGV,
        ],
        capture_output=True,
        text=True,
        cwd=repo_a,
        timeout=60,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert not proc.stdout.strip()
    assert "not the repository containing" in proc.stderr, proc.stderr


def test_bare_repo_is_refused(tmp_path):
    """N-B (round 9): a bare repo has no work tree, so
    --show-toplevel fails there — an explicit --repo naming one
    must be refused, not bound to. Both directions: --repo a bare
    repo, and no --repo with the cwd inside a bare repo."""
    repo = _repo(tmp_path)
    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(repo), str(bare)],
        check=True,
        capture_output=True,
        text=True,
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(_RECORD_CHECK),
            "--name",
            "test",
            "--out-dir",
            str(tmp_path / "bundle"),
            "--repo",
            str(bare),
            "--",
            *_OK_ARGV,
        ],
        capture_output=True,
        text=True,
        cwd=repo,
        timeout=60,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert not proc.stdout.strip()
    proc = subprocess.run(
        [
            sys.executable,
            str(_RECORD_CHECK),
            "--name",
            "test",
            "--out-dir",
            str(tmp_path / "bundle2"),
            "--",
            *_OK_ARGV,
        ],
        capture_output=True,
        text=True,
        cwd=bare,
        timeout=60,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert not proc.stdout.strip()


def test_worktree_cwd_records_against_base_commit(tmp_path):
    """FND-001 control: a --cwd inside a worktree still records —
    the derived repo is the worktree, and the revision is the base
    commit the worktree is checked out at."""
    repo = _repo(tmp_path)
    base = _head_sha(repo)
    (repo / "src" / "app.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fix")
    wt = tmp_path / "wt"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", str(wt), "HEAD~1"],
        check=True,
        capture_output=True,
        text=True,
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(_RECORD_CHECK),
            "--name",
            "test",
            "--out-dir",
            str(tmp_path / "bundle"),
            "--cwd",
            str(wt),
            "--",
            *_OK_ARGV,
        ],
        capture_output=True,
        text=True,
        cwd=wt,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    fragment = json.loads(proc.stdout)
    assert fragment["revision"] == base
    assert fragment["cwd"] == str(wt.resolve())
    assert fragment["content_digest"].startswith("sha256:")


def test_cwd_subdir_with_repo_root_passes(tmp_path):
    """FND-001 control: a --cwd in a subdirectory of the repo, with
    --repo naming the repo root, still records — the explicit repo
    is the repo containing the cwd."""
    repo = _repo(tmp_path)
    proc, fragment = _run_record(repo, tmp_path / "bundle", "test", _OK_ARGV)
    assert proc.returncode == 0, proc.stderr
    assert fragment is not None
    sub = repo / "src"
    proc = subprocess.run(
        [
            sys.executable,
            str(_RECORD_CHECK),
            "--name",
            "test",
            "--out-dir",
            str(tmp_path / "bundle2"),
            "--cwd",
            str(sub),
            "--repo",
            str(repo),
            "--",
            *_OK_ARGV,
        ],
        capture_output=True,
        text=True,
        cwd=sub,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    fragment = json.loads(proc.stdout)
    assert fragment["cwd"] == str(sub.resolve())
    assert fragment["revision"] == _head_sha(repo)


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
    # test survives the next bump. The recorded `test` gate runs a
    # real pytest against a fixture test in the repo (round 11,
    # FND-001): a print one-liner used to stand here, and the runner
    # rule rejects it now.
    repo = _repo(tmp_path)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "test")
    out_dir = tmp_path / "bundle"
    proc, fragment = _run_record(
        repo, out_dir, "test", [sys.executable, "-m", "pytest", "tests/test_ok.py", "-v"]
    )
    assert proc.returncode == 0, proc.stderr
    check = dict(fragment)
    # The fragment records the run, not the judgement: the agent adds
    # the verdict and the tool version when pasting it into the bundle.
    check["tool_version"] = "python 3.12.3"
    check["verdict"] = "PASS"
    # FND-005 (round 8): a PASS with a required test gate needs a
    # JUnit test_report with tests>0 and passed>0.
    import hashlib as _hashlib

    report = (
        b'<?xml version="1.0" encoding="utf-8"?><testsuites>'
        b'<testsuite name="pytest" tests="1">'
        b'<testcase classname="tests.test_ok" name="test_ok" time="0.01" />'
        b"</testsuite></testsuites>"
    )
    (out_dir / "test-report.xml").write_bytes(report)
    bundle = {
        "schema_version": _SCHEMA["properties"]["schema_version"]["const"],
        "revision": "working-tree",
        "working_tree_state": "clean",
        "requirement": "Record one check.",
        "acceptance_criteria": ["The recorded check validates."],
        "files_changed": ["README.md"],
        "checks": [check],
        "test_report": {
            "artifact": "test-report.xml",
            "sha256": _hashlib.sha256(report).hexdigest(),
            "format": "junit-xml",
        },
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


def test_name_rejects_windows_reserved_names(tmp_path):
    # Cloudflare takeaway 1 (round 10, track 1): a check name becomes
    # <name>.stdout / <name>.stderr, so a Windows reserved stem
    # (con/prn/aux/nul/com1-9/lpt1-9, any case, with any extension)
    # would write to a device on Windows, not a file in the bundle.
    repo = _repo(tmp_path)
    out_dir = tmp_path / "bundle"
    for bad_name in ("con", "COM1", "nul", "aux", "lpt9", "con.txt"):
        proc, fragment = _run_record(repo, out_dir, bad_name, [sys.executable, "-c", "print('ok')"])
        assert proc.returncode == 2, (bad_name, proc.stderr)
        assert fragment is None
    # A name that merely starts with a reserved stem is fine.
    proc, fragment = _run_record(repo, out_dir, "contest", [sys.executable, "-c", "print('ok')"])
    assert proc.returncode == 0, proc.stderr
    assert fragment is not None
