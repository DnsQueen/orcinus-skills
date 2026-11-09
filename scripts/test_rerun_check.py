"""Tests for scripts/rerun_check.py (0.11.0 attested verification).

The targeted rerun: read a bundle's fail_first nodeid and changed
test files, run ONLY those tests in a clean worktree at the bundle
revision, and compare the rerun against itself — never against the
bundle's full-suite totals, which a targeted run cannot reproduce.

Run only these tests while the Layer 1 agent works in the same
tree (never the full suite):
    PYTHONDONTWRITEBYTECODE=1 python -m pytest scripts/test_rerun_check.py -p no:cacheprovider -q
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rerun_check as rc  # noqa: E402
import content_digest as cd  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "rerun_check.py"

PASSING_TEST = (
    "def test_sample_value():\n"
    "    assert True\n"
    "\n"
    "\n"
    "class TestSample:\n"
    "    def test_sample_method(self):\n"
    "        assert True\n"
)

FAILING_TEST = "def test_sample_value():\n    assert False\n"

FAIL_FIRST = "tests/test_sample.py::test_sample_value"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _head(repo):
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _fixture_repo(directory, test_source=None, second_source=None):
    """A throwaway git repo with tests/test_sample.py, in the
    _recording_repo pattern (test_validate_evidence.py): a sibling
    repo, never the checkout the tests run in. `second_source`
    replaces the test file in a second commit, so the HEAD tree can
    be the failing one while the bundle claims it passed."""
    repo = Path(directory) / "fixture-repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@orcinus.local")
    _git(repo, "config", "user.name", "ORCINUS Test")
    (repo / "sample.py").write_text("x = 1\n", encoding="utf-8")
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_sample.py").write_text(
        test_source if test_source is not None else PASSING_TEST, encoding="utf-8"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "sample")
    if second_source is not None:
        (repo / "tests" / "test_sample.py").write_text(second_source, encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "break the test")
    return repo


def _bundle(directory, revision, fail_first=FAIL_FIRST, files_changed=None, test_report=None):
    """A bundle with only the fields rerun_check reads: the
    fail_first nodeid, the changed files, and (optionally) a
    fabricated full-suite test_report — the totals a targeted
    rerun must NOT compare against."""
    bundle = {
        "fail_first": {"test": fail_first},
        "files_changed": files_changed if files_changed is not None else ["tests/test_sample.py"],
    }
    if fail_first is None:
        del bundle["fail_first"]
    if test_report is not None:
        bundle["test_report"] = test_report
    path = Path(directory) / "bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _worktrees(repo):
    proc = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in proc.stdout.splitlines() if line.startswith("worktree ")]


def test_honest_rerun_writes_exact_proof_shape(tmp_path):
    repo = _fixture_repo(tmp_path)
    head = _head(repo)
    bundle = _bundle(tmp_path, head, test_report={"total": 100, "passed": 100})
    proof_path = tmp_path / "proof.json"
    proc = _run_cli(
        "--bundle",
        str(bundle),
        "--repo",
        str(repo),
        "--revision",
        "main",
        "--output",
        str(proof_path),
    )
    assert proc.returncode == 0, proc.stderr
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert set(proof) == {"method", "revision", "content_digest", "tests", "junit", "exit_code"}
    assert proof["method"] == "targeted-rerun"
    assert proof["revision"] == head
    assert len(proof["revision"]) == 40
    assert proof["content_digest"] == cd.content_digest(repo, head)
    assert proof["tests"] == [
        FAIL_FIRST,
        "tests/test_sample.py::TestSample::test_sample_method",
    ]
    assert proof["junit"] == {"total": 2, "passed": 2}
    assert proof["exit_code"] == 0
    # The worktree is removed afterwards: no lingering checkout.
    assert _worktrees(repo) == [f"worktree {repo}"]


def test_proof_printed_to_stdout_without_output(tmp_path):
    repo = _fixture_repo(tmp_path)
    bundle = _bundle(tmp_path, _head(repo))
    proc = _run_cli("--bundle", str(bundle), "--repo", str(repo), "--revision", "main")
    assert proc.returncode == 0, proc.stderr
    proof = json.loads(proc.stdout)
    assert proof["method"] == "targeted-rerun"
    assert proof["tests"] == [
        FAIL_FIRST,
        "tests/test_sample.py::TestSample::test_sample_method",
    ]


def test_fabricated_full_suite_totals_are_not_compared(tmp_path):
    """The bundle's test_report totals are for the FULL suite, so
    they cannot match a targeted rerun — and must not be compared.
    A bundle claiming 100/100 for a two-test rerun still passes."""
    repo = _fixture_repo(tmp_path)
    bundle = _bundle(tmp_path, _head(repo), test_report={"total": 100, "passed": 100})
    proof_path = tmp_path / "proof.json"
    proc = _run_cli(
        "--bundle",
        str(bundle),
        "--repo",
        str(repo),
        "--revision",
        "main",
        "--output",
        str(proof_path),
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proof_path.read_text(encoding="utf-8"))["junit"] == {
        "total": 2,
        "passed": 2,
    }


def test_liar_failing_nodeid_exits_1_and_writes_no_proof(tmp_path):
    """The liar chain: the bundle claims the nodeid passed, but it
    FAILS in the rerun at that revision. Exit 1, no proof file."""
    repo = _fixture_repo(tmp_path, second_source=FAILING_TEST)
    bundle = _bundle(tmp_path, _head(repo))
    proof_path = tmp_path / "proof.json"
    proc = _run_cli(
        "--bundle",
        str(bundle),
        "--repo",
        str(repo),
        "--revision",
        "main",
        "--output",
        str(proof_path),
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "fail_first" in proc.stderr or "exit_code" in proc.stderr
    assert not proof_path.exists()


def test_failing_changed_test_file_exits_1(tmp_path):
    """Every test the rerun ran must have passed — including the
    tests in a changed test file other than the fail_first file."""
    repo = _fixture_repo(tmp_path)
    (repo / "tests" / "test_other.py").write_text(
        "def test_other():\n    assert False\n", encoding="utf-8"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "add a failing test file")
    bundle = _bundle(
        tmp_path,
        _head(repo),
        files_changed=["tests/test_sample.py", "tests/test_other.py"],
    )
    proof_path = tmp_path / "proof.json"
    proc = _run_cli(
        "--bundle",
        str(bundle),
        "--repo",
        str(repo),
        "--revision",
        "main",
        "--output",
        str(proof_path),
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "tests/test_other.py::test_other" in proc.stderr
    assert not proof_path.exists()


def test_changed_test_files_all_run_and_pass(tmp_path):
    repo = _fixture_repo(tmp_path)
    (repo / "tests" / "test_other.py").write_text(
        "def test_other():\n    assert True\n", encoding="utf-8"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "add a passing test file")
    bundle = _bundle(
        tmp_path,
        _head(repo),
        files_changed=["tests/test_sample.py", "tests/test_other.py"],
    )
    proof_path = tmp_path / "proof.json"
    proc = _run_cli(
        "--bundle",
        str(bundle),
        "--repo",
        str(repo),
        "--revision",
        "main",
        "--output",
        str(proof_path),
    )
    assert proc.returncode == 0, proc.stderr
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert proof["tests"] == [
        "tests/test_sample.py::test_sample_value",
        "tests/test_sample.py::TestSample::test_sample_method",
        "tests/test_other.py::test_other",
    ]
    assert proof["junit"] == {"total": 3, "passed": 3}


def test_skipped_selected_test_exits_1(tmp_path):
    repo = _fixture_repo(
        tmp_path,
        test_source=(
            "import pytest\n"
            "\n"
            "\n"
            "@pytest.mark.skip(reason='not run')\n"
            "def test_sample_value():\n"
            "    assert True\n"
        ),
    )
    bundle = _bundle(tmp_path, _head(repo))
    proof_path = tmp_path / "proof.json"
    proc = _run_cli(
        "--bundle",
        str(bundle),
        "--repo",
        str(repo),
        "--revision",
        "main",
        "--output",
        str(proof_path),
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert not proof_path.exists()


def test_missing_fail_first_exits_1(tmp_path):
    repo = _fixture_repo(tmp_path)
    bundle = _bundle(tmp_path, _head(repo), fail_first=None)
    proof_path = tmp_path / "proof.json"
    proc = _run_cli(
        "--bundle",
        str(bundle),
        "--repo",
        str(repo),
        "--revision",
        "main",
        "--output",
        str(proof_path),
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "fail_first" in proc.stderr
    assert not proof_path.exists()


def test_unknown_revision_exits_2(tmp_path):
    repo = _fixture_repo(tmp_path)
    bundle = _bundle(tmp_path, _head(repo))
    proc = _run_cli(
        "--bundle",
        str(bundle),
        "--repo",
        str(repo),
        "--revision",
        "0000000000000000000000000000000000000000",
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "revision" in proc.stderr


def test_timeout_exits_2(tmp_path):
    repo = _fixture_repo(
        tmp_path,
        test_source=(
            "import time\n\n\ndef test_sample_value():\n    time.sleep(30)\n    assert True\n"
        ),
    )
    bundle = _bundle(tmp_path, _head(repo))
    proof_path = tmp_path / "proof.json"
    proc = _run_cli(
        "--bundle",
        str(bundle),
        "--repo",
        str(repo),
        "--revision",
        "main",
        "--output",
        str(proof_path),
        "--timeout",
        "1",
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "timed out" in proc.stderr
    assert not proof_path.exists()


def test_dirty_working_tree_is_not_run(tmp_path):
    """The rerun runs a clean copy at the revision, never the live
    working tree: dirtying the test file to fail must not fail a
    rerun at the (passing) HEAD."""
    repo = _fixture_repo(tmp_path)
    (repo / "tests" / "test_sample.py").write_text(FAILING_TEST, encoding="utf-8")
    bundle = _bundle(tmp_path, _head(repo))
    proc = _run_cli("--bundle", str(bundle), "--repo", str(repo), "--revision", "main")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["tests"] == [
        FAIL_FIRST,
        "tests/test_sample.py::TestSample::test_sample_method",
    ]


def test_summary_junit_mismatch_is_exit_1():
    """Unit: the rerun's own JUnit must agree with its own stdout
    summary — a 2-passed summary against a 1-test JUnit fails."""
    cases = [("tests.test_sample", "test_sample_value", "passed")]
    with pytest.raises(rc.RerunError) as excinfo:
        rc.check_rerun_agreement("=== 2 passed in 0.01s ===\n", cases, FAIL_FIRST)
    assert excinfo.value.exit_code == 1
    assert "summary" in str(excinfo.value)


def test_unparseable_summary_is_exit_1():
    """Unit: a summary the validator's parser cannot read (an
    xfailed/xpassed line) fails closed — agreement cannot be
    established, so the rerun does not attest."""
    cases = [("tests.test_sample", "test_sample_value", "passed")]
    with pytest.raises(rc.RerunError) as excinfo:
        rc.check_rerun_agreement("=== 1 xfailed in 0.01s ===\n", cases, FAIL_FIRST)
    assert excinfo.value.exit_code == 1
    assert "summary" in str(excinfo.value)


def test_agreement_passes_on_matching_run():
    cases = [("tests.test_sample", "test_sample_value", "passed")]
    rc.check_rerun_agreement("=== 1 passed in 0.01s ===\n", cases, FAIL_FIRST)


def test_pytest_missing_is_exit_2(tmp_path, monkeypatch):
    """Unit: a worktree whose python has no pytest cannot run —
    exit 2, fail closed, never 0."""
    real_run = rc._run

    def _fake(argv, **kwargs):
        if "pytest" in argv:
            raise FileNotFoundError("No module named pytest")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(rc, "_run", _fake)
    with pytest.raises(rc.RerunError) as excinfo:
        rc._probe_pytest(tmp_path)
    assert excinfo.value.exit_code == 2
    assert "pytest" in str(excinfo.value)
