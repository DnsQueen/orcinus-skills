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
import json
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clean_copy_check  # noqa: E402

HERE = Path(__file__).resolve().parent


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
    # directory outright.
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
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)
    assert _snapshot(src) == before
    assert not src.with_name(src.name + ".orcinus-hidden").exists()


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


def test_missing_manifest_in_copy_fails_the_step(tmp_path):
    """A clean copy without skills/manifest.json must fail its step,
    not raise FileNotFoundError (R3 #3)."""
    dest = _fixture_repo(tmp_path)
    (dest / "skills" / "manifest.json").unlink()
    failed, total = clean_copy_check._gates(dest)
    assert failed == ["all manifest skills resolve"]
    assert total == 7


def test_ci_requirements_are_hashed():
    """Every CI pip install goes through requirements-ci.txt with
    --require-hashes, so a compromised package cannot slip in
    (R3 #17). Every pin carries its hashes."""
    req = REPO / "requirements-ci.txt"
    assert req.is_file(), "requirements-ci.txt is missing"
    expected = {
        "pytest": "8.4.2",
        "ruff": "0.17.4",
        "pyyaml": "6.0.1",
        "mypy": "1.18.2",
        "psycopg": "3.3.8",
        # tomli is a conditional mypy dependency (Python < 3.11 only):
        # pip-compile on 3.12 omits it, but the 3.10 CI job resolves
        # it unpinned and --require-hashes rejects that (run
        # 42298838900). It must be pinned with hashes like the rest.
        "tomli": "2.5.0",
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
