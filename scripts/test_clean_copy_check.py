"""Tests for clean_copy_check.py (the clean-copy portability check).

The old design renamed the live checkout to <source>.orcinus-hidden
for the duration of the run: if the process was killed mid-run the
source stayed hidden and the next run refused to start. The redesign
never renames the source — the working-tree mode copies it, the
release mode extracts a committed revision with `git archive` — so
a kill at any point leaves the source exactly as it was.

Run: python3 -m pytest scripts/test_clean_copy_check.py -q
"""

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clean_copy_check  # noqa: E402

HERE = Path(__file__).resolve().parent

# Round-6 2-E4: the clean-copy gates run ruff/pytest/mypy as
# subprocesses of this Python. In an environment without them the
# gates fail — an environment fact, not a code failure — so the
# tests that need all seven gates to pass skip there instead of
# failing. The gates themselves still fail (with a clear "not
# installed" detail) when a tool is missing; see
# test_gates_report_missing_tools_without_crashing.
_MISSING_TOOLS = [
    name for name in ("ruff", "pytest", "mypy") if importlib.util.find_spec(name) is None
]
requires_tools = pytest.mark.skipif(
    bool(_MISSING_TOOLS),
    reason=f"clean-copy gates need installed tools; missing: {', '.join(_MISSING_TOOLS)}",
)


def _fixture_repo(tmp_path, sleep=0):
    """A minimal repo the clean-copy gates accept. The gate scripts
    are stubs: validate_repo.py either exits 0 at once or sleeps
    first (for the kill test)."""
    root = tmp_path / "repo"
    (root / "skills" / "other").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "skills" / "other" / "SKILL.md").write_text(
        "---\nname: other\ndescription: Other.\nlicense: MIT\n---\n\nBody.\n", encoding="utf-8"
    )
    (root / "skills" / "manifest.json").write_text(
        json.dumps({"skills": {"other": {}}}), encoding="utf-8"
    )
    validate = ("import time\ntime.sleep(%d)\n" % sleep) if sleep else ""
    (root / "scripts" / "validate_repo.py").write_text(validate, encoding="utf-8")
    (root / "scripts" / "check_drift.py").write_text("", encoding="utf-8")
    (root / "test_stub.py").write_text("def test_stub():\n    assert True\n", encoding="utf-8")
    # The mypy scope CI typechecks (see clean_copy_check.MYPY_SCOPE):
    # the fixture must contain every scope path, or the mypy gate
    # fails on a missing path instead of testing the copy. A scope
    # directory needs at least one .py file: mypy rejects an empty
    # directory outright. The scope itself lives in pyproject.toml
    # (round 6, S8), so the fixture carries a pyproject.toml with
    # the same list — the copied script reads its scope from there.
    (root / "pyproject.toml").write_text(
        "[tool.mypy]\nfiles = [\n"
        + "".join(f'    "{target}",\n' for target in clean_copy_check.MYPY_SCOPE)
        + "]\n",
        encoding="utf-8",
    )
    for target in clean_copy_check.MYPY_SCOPE:
        path = root / target
        if target.endswith("/"):
            path.mkdir(parents=True, exist_ok=True)
            # One .py file per scope directory, uniquely named:
            # mypy rejects both an empty directory and two modules
            # with the same name.
            stub = target.strip("/").replace("/", "_") + "_stub.py"
            (path / stub).write_text("", encoding="utf-8")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
    # Directories the copy must exclude.
    for name in (".venv", "venv", ".mypy_cache"):
        (root / name).mkdir()
        (root / name / "junk.txt").write_text("junk\n", encoding="utf-8")
    return root


def _snapshot(root):
    """name -> sha256 for every file under root."""
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def test_copy_excludes_venvs_and_caches(tmp_path):
    """The copy must not carry .venv, venv, or .mypy_cache — they are
    machine state, and a clean copy that includes them is not clean."""
    src = _fixture_repo(tmp_path)
    dest = tmp_path / "dest"
    clean_copy_check._copy_clean(src, dest)
    for name in (".venv", "venv", ".mypy_cache"):
        assert not (dest / name).exists(), f"{name} was copied"
    assert (dest / "skills" / "other" / "SKILL.md").is_file()
    assert (dest / "test_stub.py").is_file()


@requires_tools
def test_working_tree_mode_leaves_source_untouched(tmp_path):
    """A normal run must not rename, move, or change the source at
    any point — the before/after snapshot must be identical, and no
    .orcinus-hidden sibling may ever appear."""
    src = _fixture_repo(tmp_path)
    before = _snapshot(src)
    assert clean_copy_check.main(["--source", str(src)]) == 0
    assert _snapshot(src) == before
    assert not src.with_name(src.name + ".orcinus-hidden").exists()


def test_killed_run_leaves_source_intact(tmp_path):
    """Kill the check mid-run (while a gate is still executing) and
    the source must still be exactly as it was — the failure the
    old rename design could not survive."""
    src = _fixture_repo(tmp_path, sleep=30)
    shutil.copy(HERE / "clean_copy_check.py", src / "scripts" / "clean_copy_check.py")
    before = _snapshot(src)
    proc = subprocess.Popen(
        [sys.executable, str(src / "scripts" / "clean_copy_check.py"), "--source", str(src)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    time.sleep(2)
    assert proc.poll() is None, "the run finished before the kill"
    clean_copy_check._kill_process(proc)
    proc.wait(timeout=10)
    assert _snapshot(src) == before
    assert not src.with_name(src.name + ".orcinus-hidden").exists()


def test_kill_process_terminates_a_running_process():
    """The kill helper terminates a running process with no
    cleanup — the killed-run test depends on it. It must not name
    signal.SIGKILL (there is none on Windows): Popen.kill is
    SIGKILL on POSIX and TerminateProcess on Windows."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        clean_copy_check._kill_process(proc)
        assert proc.wait(timeout=10) is not None
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=10)


def _git_repo(tmp_path):
    """The fixture repo with a git history: one commit, then an
    uncommitted file on top."""
    src = _fixture_repo(tmp_path)

    def git(*args):
        subprocess.run(["git", "-C", str(src), *args], check=True, capture_output=True, timeout=30)

    git("init", "-q")
    git("-c", "user.name=x", "-c", "user.email=x@x", "add", ".")
    git("-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q", "-m", "first")
    (src / "UNCOMMITTED.txt").write_text("not committed\n", encoding="utf-8")
    return src


@requires_tools
def test_release_mode_uses_committed_tree(tmp_path, capsys):
    """--mode release tests the committed revision, not the working
    tree: the uncommitted file must not reach the clean copy."""
    src = _git_repo(tmp_path)
    assert clean_copy_check.main(["--source", str(src), "--mode", "release", "--keep"]) == 0
    out = capsys.readouterr().out
    kept = [line for line in out.splitlines() if line.startswith("Kept: ")]
    assert kept, "the kept copy path must be printed with --keep"
    dest = Path(kept[0][len("Kept: ") :].strip())
    try:
        assert not (dest / "UNCOMMITTED.txt").exists()
        assert (dest / "skills" / "other" / "SKILL.md").is_file()
    finally:
        shutil.rmtree(dest.parent, ignore_errors=True)


def test_release_mode_unknown_rev_fails(tmp_path):
    """An unresolvable revision fails loudly (exit 2) instead of
    silently testing something else."""
    src = _git_repo(tmp_path)
    before = _snapshot(src)
    assert (
        clean_copy_check.main(["--source", str(src), "--mode", "release", "--rev", "nonexistent"])
        == 2
    )
    assert _snapshot(src) == before


# --- Round 5, T6: controlled failures, full gates, hashed installs ---

REPO = Path(__file__).resolve().parent.parent


def test_run_timeout_is_a_controlled_failure(tmp_path):
    """A gate that runs past its timeout must fail the step with a
    FAIL line, not raise TimeoutExpired as a traceback (R3 #3)."""
    rc, out = clean_copy_check._run(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        cwd=tmp_path,
        timeout=1,
    )
    assert rc != 0
    assert "timed out" in out


def test_git_archive_timeout_is_a_controlled_failure(tmp_path, monkeypatch):
    """A git archive that runs past its timeout must return (False,
    ...) — a usage error the caller reports — not raise (R3 #3)."""

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=120)

    monkeypatch.setattr(clean_copy_check.subprocess, "run", boom)
    ok, error = clean_copy_check._git_archive(tmp_path, "HEAD", tmp_path / "dest")
    assert ok is False
    assert "timed out" in error


def test_corrupt_manifest_fails_the_step_not_the_run(tmp_path, capsys):
    """A corrupt skills/manifest.json must fail its step with a FAIL
    line (exit 1), not a JSONDecodeError traceback (R3 #3)."""
    src = _fixture_repo(tmp_path)
    (src / "skills" / "manifest.json").write_text("{not json", encoding="utf-8")
    assert clean_copy_check.main(["--source", str(src)]) == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.out + captured.err
    assert "[FAIL]" in captured.out
    assert "all manifest skills resolve" in captured.out


@requires_tools
def test_missing_manifest_in_copy_fails_the_step(tmp_path):
    """A clean copy without skills/manifest.json must fail its step,
    not raise FileNotFoundError (R3 #3)."""
    dest = _fixture_repo(tmp_path)
    (dest / "skills" / "manifest.json").unlink()
    failed, total = clean_copy_check._gates(dest)
    assert failed == ["all manifest skills resolve"]
    assert total == 7


def test_gates_report_missing_tools_without_crashing(tmp_path, monkeypatch):
    """2-E4: when ruff/pytest/mypy are not installed, exactly those
    four gates fail with a clear "not installed" detail — the same
    four failures a tool-less environment showed — and the run
    stays controlled (a failed-gates list, not a traceback). The
    tool lookups are faked here so the test is hermetic: it pins
    the gate behaviour, it does not need the tools to be absent."""
    dest = _fixture_repo(tmp_path)
    orig_run = clean_copy_check._run

    def fake(argv, cwd, timeout=300):
        if "-m" in argv:
            tool = argv[argv.index("-m") + 1]
            if tool in ("ruff", "pytest", "mypy"):
                return 1, f"{argv[0]}: No module named {tool}"
        return orig_run(argv, cwd, timeout)

    monkeypatch.setattr(clean_copy_check, "_run", fake)
    failed, total = clean_copy_check._gates(dest)
    assert failed == ["ruff", "script tests", "ruff format", "mypy"]
    assert total == 7


def test_ci_requirements_are_hashed():
    """Every CI pip install goes through requirements-ci.txt with
    --require-hashes, so a compromised package cannot slip in
    (R3 #17). Every pin carries its hashes."""
    req = REPO / "requirements-ci.txt"
    assert req.is_file(), "requirements-ci.txt is missing"
    expected = {
        # Round 8, FND-021: 8.4.2 has PYSEC-2026-1845 (fixed in 9.0.3).
        "pytest": "9.0.3",
        "ruff": "0.17.4",
        "pyyaml": "6.0.1",
        "mypy": "1.18.2",
        "psycopg": "3.3.8",
        # tzdata is psycopg[binary]'s dependency on Windows only,
        # pinned here because a plain `pip-compile` on Linux omits
        # it and then the Windows CI job resolves it unpinned (run
        # 42384742442).
        "tzdata": "2026.6",
        # tomli and exceptiongroup were < 3.11 shims, pinned here
        # only because the 3.10 CI job resolved them unpinned (runs
        # 42298838900, 42300115306). Both pins were removed
        # 2026-11-07 (round 6, 2-S7) when 3.10 was dropped: no
        # supported Python needs either shim now.
    }
    pins = {}
    current = None
    for raw in req.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("--hash="):
            assert current is not None, "a --hash line precedes any pin"
            pins[current]["hashes"] += 1
            continue
        assert "==" in line, f"unpinned requirement: {line!r}"
        # An extra (psycopg[binary]) belongs to the base package.
        name = line.split("==")[0].strip().lower().split("[")[0]
        version = line.split("==")[1].split(";")[0].split()[0].strip()
        pins[name] = {"version": version, "hashes": 0}
        current = name
    for name, version in expected.items():
        assert name in pins, f"{name} is missing from requirements-ci.txt"
        assert pins[name]["version"] == version, (
            f"{name} is {pins[name]['version']}, expected {version}"
        )
        assert pins[name]["hashes"] > 0, f"{name} has no --hash in requirements-ci.txt"


def test_package_lock_pins_claude_code():
    """The plugin-validate job installs the Claude Code CLI from a
    lockfile (npm ci), not an unpinned global install (R3 #17)."""
    package = REPO / "package.json"
    lock = REPO / "package-lock.json"
    assert package.is_file(), "package.json is missing"
    assert lock.is_file(), "package-lock.json is missing"
    dev_deps = json.loads(package.read_text(encoding="utf-8")).get("devDependencies", {})
    assert dev_deps.get("@anthropic-ai/claude-code") == "2.1.318"
    locked = json.loads(lock.read_text(encoding="utf-8"))
    assert locked.get("lockfileVersion", 0) >= 2
    pkgs = locked.get("packages", {})
    assert "node_modules/@anthropic-ai/claude-code" in pkgs
    assert pkgs["node_modules/@anthropic-ai/claude-code"]["version"] == "2.1.318"
    assert pkgs["node_modules/@anthropic-ai/claude-code"].get("integrity", "").startswith("sha512-")


def test_ci_uses_hashed_installs_and_release_clean_copy():
    """CI installs pip packages with --require-hashes from
    requirements-ci.txt, installs the CLI with npm ci, and runs the
    clean-copy check in release mode (R3 #16, #17)."""
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pip install --require-hashes -r requirements-ci.txt" in ci
    assert "pip install pytest==8.4.2" not in ci
    assert "npm install -g @anthropic-ai/claude-code" not in ci
    assert "npm ci" in ci
    assert "clean_copy_check.py --mode release" in ci


# --- Round 6 (2026-11-07): S8 — MYPY_SCOPE has one source of truth ---


def _pyproject_mypy_files():
    import tomllib

    repo = Path(__file__).resolve().parent.parent
    with open(repo / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["tool"]["mypy"]["files"]


def test_mypy_scope_has_a_single_source_of_truth():
    """S8: MYPY_SCOPE was hand-copied from ci.yml (plus a third hand
    copy in a pyproject.toml comment), with no guard — the three
    copies could drift silently. The list lives in exactly one
    place now ([tool.mypy] files in pyproject.toml, which mypy reads
    natively); clean_copy_check reads it from there, and CI passes
    no paths at all, so there is nothing left to hand-copy."""
    scope = _pyproject_mypy_files()
    assert scope, "pyproject.toml [tool.mypy] has no files list"
    assert clean_copy_check.MYPY_SCOPE == scope
    ci = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    for line in ci.splitlines():
        if "python3 -m mypy" in line or "python -m mypy" in line:
            assert "skills/" not in line and "scripts/" not in line, (
                f"ci.yml still hand-copies the mypy scope: {line.strip()!r} — "
                "run plain `python -m mypy` and let the config supply it"
            )


# --- Round 8, Track B: FND-024 — SIGTERM must not leak the temp dir ---


def _leftover_clean_dirs():
    """orcinus-clean-* temp dirs currently in the system temp dir."""
    import tempfile

    return set(Path(tempfile.gettempdir()).glob("orcinus-clean-*"))


def _run_clean_copy_until_killed(tmp_path, sig):
    """Run clean_copy_check as a subprocess against a fixture
    whose first gate sleeps, kill it with `sig`, and return
    (returncode, new leftovers)."""
    src = _fixture_repo(tmp_path, sleep=30)
    shutil.copy(HERE / "clean_copy_check.py", src / "scripts" / "clean_copy_check.py")
    before = _leftover_clean_dirs()
    proc = subprocess.Popen(
        [sys.executable, str(src / "scripts" / "clean_copy_check.py"), "--source", str(src)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    time.sleep(2)
    assert proc.poll() is None, "the run finished before the kill"
    proc.send_signal(sig)
    proc.wait(timeout=15)
    return proc.returncode, _leftover_clean_dirs() - before


def test_sigterm_removes_temp_dir(tmp_path):
    """FND-024: SIGTERM during the gates left a full repo copy
    behind (default SIGTERM disposition skips the `finally`
    rmtree; 2/2 trials in the verification repro). The process
    must still die by SIGTERM, with zero new leftovers."""
    import signal

    rc, leftovers = _run_clean_copy_until_killed(tmp_path, signal.SIGTERM)
    assert rc == -signal.SIGTERM, f"expected death by SIGTERM, got {rc}"
    assert leftovers == set(), f"SIGTERM left temp dirs behind: {leftovers}"


def test_sigint_still_removes_temp_dir(tmp_path):
    """Control: SIGINT already cleaned up (KeyboardInterrupt runs
    the finally) — the SIGTERM fix must not regress it."""
    import signal

    rc, leftovers = _run_clean_copy_until_killed(tmp_path, signal.SIGINT)
    assert rc == -signal.SIGINT, f"expected death by SIGINT, got {rc}"
    assert leftovers == set(), f"SIGINT left temp dirs behind: {leftovers}"
