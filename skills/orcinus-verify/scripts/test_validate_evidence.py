"""Tests for validate_evidence.py (the evidence-bundle gate).

The gate's job is to catch a PASS that hides a failure: a check with
verdict FAIL, a blocking finding, or a non-empty unverified_items
must never come out as an overall PASS. Each test is one such
contradiction, plus the happy path.

Run: python3 -m pytest skills/orcinus-verify/scripts/test_validate_evidence.py -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_evidence as ve  # noqa: E402

_SCHEMA = ve.load_schema(
    Path(__file__).resolve().parent.parent / "references" / "evidence.schema.json"
)

# The canonical fail-first test for the good bundle, as a pytest
# nodeid (F-03): the JUnit fixtures below are written for exactly
# this test, so a bundle naming any other test must fail the
# structural link.
_CANONICAL_NODEID = "tests/test_capture.py::test_capture_persian_only"
_CANONICAL_CLASSNAME = "tests.test_capture"
_CANONICAL_NAME = "test_capture_persian_only"


def _junit_xml(cases):
    """A real JUnit XML report for `cases`: a list of
    (classname, name, status) with status in passed/failed/error/
    skipped. pytest --junitxml emits exactly this shape."""
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<testsuites><testsuite name="pytest" tests="{len(cases)}">',
    ]
    for classname, name, status in cases:
        if status == "failed":
            child = '<failure message="AssertionError">assert False</failure>'
        elif status == "error":
            child = '<error message="Error">boom</error>'
        elif status == "skipped":
            child = '<skipped message="skipped" />'
        else:
            child = ""
        lines.append(
            f'<testcase classname="{classname}" name="{name}" time="0.01">{child}</testcase>'
        )
    lines.append("</testsuite></testsuites>")
    return "\n".join(lines).encode()


def _write_junit_reports(bundle, directory, red_cases=None, green_cases=None):
    """Write real JUnit red/green reports for the canonical test
    under `directory` and record them on the bundle's fail_first
    (red_report / green_report, with the sha256 of each file). The
    green report is the cached real pytest run's own --junitxml
    output (round 11, FND-001) unless the caller passes explicit
    cases — a test that needs a specific green shape (a failed
    green report, a different test id) still gets exactly the XML
    it asked for. The red report stays fixture-written: the red run
    is the print one-liner, not a real failing run, so there is no
    real red JUnit to reuse."""
    import hashlib

    directory = Path(directory)
    if red_cases is None:
        red_cases = [(_CANONICAL_CLASSNAME, _CANONICAL_NAME, "failed")]
    reports = [("red_report", "red.xml", _junit_xml(red_cases))]
    if green_cases is None:
        _fragment, _captures, junit = _cached_test_capture()
        reports.append(("green_report", "green.xml", junit))
    else:
        reports.append(("green_report", "green.xml", _junit_xml(green_cases)))
    for field, filename, data in reports:
        (directory / filename).write_bytes(data)
        bundle["fail_first"][field] = {
            "artifact": filename,
            "sha256": hashlib.sha256(data).hexdigest(),
            "format": "junit-xml",
        }


def _write_test_report(bundle, directory):
    """Record the required 'test' gate's JUnit report as the
    bundle's test_report (FND-005, round 8): the cached real pytest
    run's own --junitxml output — two passing tests, so tests>0 and
    passed>0. The report is the run's own green.xml (round 11,
    FND-003): the recorded test command names that file in its
    --junitxml argv, so test_report must name the same file — a
    second copy under another name would be a report no recorded
    command wrote. green.xml is written by _write_junit_reports
    just before this runs; the sha is read back from the file on
    disk, so a caller that wrote explicit green cases gets a
    test_report matching those cases, not the cached ones."""
    import hashlib

    directory = Path(directory)
    if not (directory / "green.xml").exists():
        _fragment, _captures, data = _cached_test_capture()
        (directory / "green.xml").write_bytes(data)
    data = (directory / "green.xml").read_bytes()
    bundle["test_report"] = {
        "artifact": "green.xml",
        "sha256": hashlib.sha256(data).hexdigest(),
        "format": "junit-xml",
    }


def _test_gate_required(bundle):
    plan = bundle.get("verification_plan")
    return (
        isinstance(plan, dict)
        and isinstance(plan.get("required_gates"), list)
        and "test" in plan["required_gates"]
    )


def _problems(bundle, bundle_dir=None, **validate_kwargs):
    # A PASS bundle for a behaviour change must carry real JUnit
    # reports (F-03) and real recorded captures (F-01), so the
    # fixture writes them into a temp bundle directory and validates
    # against it. The reports are always for the canonical test: a
    # bundle naming another test must fail the structural link, not
    # silently gain a matching report. When the caller passes a
    # bundle_dir (a test that recorded its captures there with
    # _recorded_bundle), the reports are written into that same
    # directory, so one directory holds reports and captures. A PASS
    # bundle with a required test gate also needs its test_report
    # (FND-005): written here whenever the plan requires the gate,
    # so the fixture's passing bundles stay passing.
    import tempfile

    if bundle_dir is not None:
        bundle_dir = Path(bundle_dir)
        if isinstance(bundle.get("fail_first"), dict):
            _write_junit_reports(bundle, bundle_dir)
        if _test_gate_required(bundle) and bundle.get("verdict") == "PASS":
            _write_test_report(bundle, bundle_dir)
        return ve.validate_bundle(bundle, _SCHEMA, bundle_dir=bundle_dir, **validate_kwargs)
    if isinstance(bundle.get("fail_first"), dict):
        with tempfile.TemporaryDirectory() as d:
            _write_junit_reports(bundle, Path(d))
            if _test_gate_required(bundle) and bundle.get("verdict") == "PASS":
                _write_test_report(bundle, Path(d))
            return ve.validate_bundle(bundle, _SCHEMA, bundle_dir=Path(d), **validate_kwargs)
    return ve.validate_bundle(bundle, _SCHEMA, **validate_kwargs)


# The real commands the fixture's checks are recorded with. The
# `test` gate runs a real pytest against the recording repo's
# fixture test file (round 11, FND-001): a PASS fixture's test gate
# must invoke a test runner, never a command that merely prints a
# passing-looking summary. The lint check has no runner to invoke,
# so it stays a print (the runner rule applies to the `test` gate
# only). _recorded_bundle runs record_check.py on these argv lists
# — never on the hand-written command strings in _good_bundle.
# The `test` entry is the command the cache in _cached_test_capture
# records once per module; a recording against an explicit repo
# runs it for real against that repo instead.
_RECORD_COMMANDS = {
    "test": [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_capture.py",
        "-v",
    ],
    "lint": [sys.executable, "-c", "print('All checks passed!')"],
}
_RED_COMMAND = [
    sys.executable,
    "-c",
    "import sys; print('FAILED tests/test_capture.py::test_capture_persian_only - AssertionError: Persian-only idea raised'); sys.exit(1)",
]


def _git(repo, *args):
    import subprocess

    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _recording_repo(directory, test_source=None):
    """A throwaway git repo to record captures against, beside the
    bundle directory. record_check.py binds every capture to a
    revision + content digest, so it needs a git repo — but the
    checkout the tests run in is not one they may use: a git-archive
    clean copy has no .git, so recording against the checkout fails
    there (24 failures in the CI clean-install job) while the same
    tests pass in the working tree. The same pattern as
    test_record_check.py's _repo, for the validator tests. The repo
    is a sibling of the bundle directory, never inside it, so the
    validator — which reads named artifacts from the bundle
    directory — never sees it. `test_source` overrides the fixture
    test file's content (round 11, FND-002: an assertion-free
    variant); the default is the assertion-bearing canonical file."""
    directory = Path(directory)
    repo = directory.parent / (directory.name + "-repo")
    if (repo / ".git").exists():
        return repo
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@orcinus.local")
    _git(repo, "config", "user.name", "ORCINUS Test")
    # Two commits (round 9, FND-002): the base commit holds the
    # pre-fix code, the fix commit holds the fix AND the canonical
    # test file — the documented fail-first procedure records the
    # red run in a worktree at the base and the green checks at the
    # fix commit, so the fixture's bundle revision (HEAD) has a
    # real base to bind the red to. A one-commit repo cannot model
    # that shape: its red would sit on the bundle revision itself,
    # which is exactly the mislabelled shape the validator rejects.
    # The fixture file is sample.py, not code.py: pytest inserts
    # the repo root on sys.path, so a stdlib name at the root
    # shadows the stdlib module — on Python 3.13 `code.py` breaks
    # pytest's own configure (`pdb` imports stdlib `code`) with an
    # INTERNALERROR and exit code 3, failing every test that
    # records against this repo.
    (repo / "sample.py").write_text("x = 1\n", encoding="utf-8")
    # A real pytest run in this repo writes __pycache__ and
    # .pytest_cache: ignored, so the tree stays clean after the run
    # (round 11, FND-001 — the print one-liner never wrote anything).
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "sample")
    (repo / "sample.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_capture.py").write_text(
        test_source
        if test_source is not None
        else "def test_capture_persian_only():\n    assert True\n"
        "\n"
        "\n"
        "class TestCapture:\n"
        "    def test_capture_persian_only(self):\n"
        "        assert True\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fix")
    return repo


def _run_record_check(directory, name, argv, repo, shell=False):
    """Run record_check.py once, in `directory`, against `repo`,
    and return the fragment it prints. The command runs for real;
    the fragment is the wrapper's own record of it. `repo` is the
    throwaway repo from _recording_repo — never the checkout the
    tests run in (see _recording_repo)."""
    import json
    import subprocess

    record_check = Path(__file__).resolve().parent / "record_check.py"
    args = [
        sys.executable,
        str(record_check),
        "--name",
        name,
        "--out-dir",
        str(directory),
        "--repo",
        str(repo),
    ]
    if shell:
        args.append("--shell")
    args += ["--", *argv]
    # The command runs inside the repo it binds to (round 9,
    # FND-001): record_check.py derives the repo from the cwd and
    # refuses a --repo that is not that repo, so a recording with
    # cwd=directory (the bundle dir, outside the throwaway repo)
    # is refused. The old cwd=directory recorded exactly the shape
    # the new rule rejects — a capture whose cwd is outside its
    # repo — so the fixture records inside the repo instead. The
    # capture files still land in `directory` (--out-dir).
    proc = subprocess.run(args, capture_output=True, text=True, cwd=repo, timeout=60)
    # 0 for a passing command, 1 for the red run (sys.exit(1)); 2
    # would be a recording failure, and then there is no fragment.
    assert proc.returncode in (0, 1), proc.stderr
    return json.loads(proc.stdout)


# The one real pytest run this module reuses (round 11, FND-001):
# the recorded `test` check from `python -m pytest` against the
# canonical fixture test file, with its stdout/stderr capture files
# and its JUnit report. _good_bundle is built by dozens of tests,
# so a fresh pytest subprocess per call would add a process spawn
# to each of them; the run happens once per module instead, and
# _recorded_bundle reuses the fragment (deep-copied) plus the
# capture bytes. The capture binds to the cache's own throwaway
# repo — its revision and content digest — never to the caller's
# repo, so it is used only when no explicit repo was given; a
# recording against an explicit repo runs the real command against
# that repo instead. The TemporaryDirectory is held in a module
# global so it lives for the module and cleans up at exit.
_CACHED_TEST_CAPTURE = None
_CACHED_TEST_CAPTURE_DIR = None


def _cached_test_capture():
    """(fragment, {capture filename: bytes}, junit bytes): the one
    real pytest run, recorded by record_check.py itself — never
    hand-written. The JUnit is pytest's own --junitxml output for
    the run, so the green report and the test report reuse real
    artifacts too."""
    global _CACHED_TEST_CAPTURE, _CACHED_TEST_CAPTURE_DIR
    if _CACHED_TEST_CAPTURE is None:
        import tempfile

        _CACHED_TEST_CAPTURE_DIR = tempfile.TemporaryDirectory(
            prefix="orcinus-verify-test-capture-"
        )
        cache_dir = Path(_CACHED_TEST_CAPTURE_DIR.name)
        # The bundle dir and the repo both live inside the temporary
        # directory, so both are cleaned up with it.
        bundle_dir = cache_dir / "bundle"
        repo = _recording_repo(bundle_dir)
        junit_path = bundle_dir / "green.xml"
        fragment = _run_record_check(
            bundle_dir,
            "test",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_capture.py",
                "-v",
                "--junitxml",
                str(junit_path),
            ],
            repo,
        )
        fragment.pop("stdout_text", None)
        fragment.pop("stderr_text", None)
        captures = {
            fragment["stdout_artifact"]: (bundle_dir / fragment["stdout_artifact"]).read_bytes(),
            fragment["stderr_artifact"]: (bundle_dir / fragment["stderr_artifact"]).read_bytes(),
        }
        _CACHED_TEST_CAPTURE = (fragment, captures, junit_path.read_bytes())
    return _CACHED_TEST_CAPTURE


def _red_worktree(directory, repo):
    """A worktree of `repo` at the base commit (HEAD~1, the pre-fix
    tree), with the canonical test file copied in: the tree the red
    run records against, per SKILL.md step 3. The test file does not
    exist at the base — it is part of the fix — so it is copied in
    uncommitted, exactly as the documented procedure does. The
    worktree is a sibling of the bundle directory, never inside it."""
    import subprocess

    directory = Path(directory)
    wt = directory.parent / (directory.name + "-worktree")
    if (wt / ".git").exists():
        return wt
    base = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD~1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", str(wt), base],
        check=True,
        capture_output=True,
        text=True,
    )
    src = repo / "tests" / "test_capture.py"
    dst = wt / "tests" / "test_capture.py"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
    return wt


def _recorded_bundle(bundle, directory, commands=None, repo=None):
    """Record every check in `bundle` (and fail_first.red_check) by
    running record_check.py for real, writing the capture files into
    `directory` and merging each fragment into the check. A bundle is
    a PASS bundle only after this: under schema v6 hand-written checks
    do not validate. `commands` maps a check name (or "red_check") to
    the argv to actually run — a list for argv mode, or a string for
    --shell mode; the default is the fixture's trivial commands above.
    `repo` is the git repo the captures bind to; the default is a
    throwaway repo beside `directory` (see _recording_repo). The
    `test` check is the exception: unless an explicit repo was given
    or the caller overrides the `test` command, it reuses the one
    real pytest run from _cached_test_capture — the fragment is
    deep-copied (tests mutate recorded checks) and its capture
    files are copied into `directory`, so the binding recomputes
    there. A recording against an explicit repo runs the real
    `test` command against that repo instead, so the capture binds
    to the repo the caller named."""
    directory = Path(directory)
    explicit_repo = repo is not None
    if repo is None:
        repo = _recording_repo(directory)
    directory.mkdir(parents=True, exist_ok=True)
    cmds = dict(_RECORD_COMMANDS)
    if commands:
        cmds.update(commands)
    for check in bundle.get("checks") or []:
        cmd = cmds.get(check.get("name"))
        if cmd is None:
            continue
        if check.get("name") == "test" and isinstance(cmd, list):
            # Round 11, FND-003: a real test recording must name its
            # JUnit report in the argv it records — pytest writes
            # the report the bundle's test_report names (green.xml).
            # A caller that already names a report (the equals-form
            # control) is left alone; shell strings name their own.
            # A new list: never mutate the shared _RECORD_COMMANDS.
            if not any(t == "--junitxml" or t.startswith("--junitxml=") for t in cmd):
                cmd = [*cmd, "--junitxml", str(directory / "green.xml")]
        if (
            check.get("name") == "test"
            and not explicit_repo
            and not (commands and "test" in commands)
        ):
            import copy

            fragment, captures, _junit = _cached_test_capture()
            for filename, data in captures.items():
                (directory / filename).write_bytes(data)
            check.update(copy.deepcopy(fragment))
        elif isinstance(cmd, str):
            fragment = _run_record_check(directory, check["name"], [cmd], repo, shell=True)
            check.update(fragment)
        else:
            fragment = _run_record_check(directory, check["name"], cmd, repo)
            check.update(fragment)
        check.pop("stdout_text", None)
        check.pop("stderr_text", None)
    ff = bundle.get("fail_first")
    if isinstance(ff, dict) and isinstance(ff.get("red_check"), dict):
        # Round 9, FND-002: the red run is recorded in a worktree at
        # the base commit (HEAD~1, the pre-fix tree), not in the
        # repo at the fix commit — the documented procedure (SKILL.md
        # step 3). The test file does not exist at the base, so it is
        # copied into the worktree first, and its sha256 is recorded
        # in fail_first as the material binding the red run to the
        # test that passes green.
        red_repo = _red_worktree(directory, repo)
        cmd = cmds.get("red_check", _RED_COMMAND)
        if isinstance(cmd, str):
            fragment = _run_record_check(directory, "red_check", [cmd], red_repo, shell=True)
        else:
            fragment = _run_record_check(directory, "red_check", cmd, red_repo)
        # Round 11, FND-007: the fragment pastes verbatim into
        # red_check, name included — the schema allows it, so no
        # field is dropped here.
        ff["red_check"].update(fragment)
        ff["red_check"].pop("stdout_text", None)
        import hashlib

        ff["test_file_sha256"] = hashlib.sha256(
            (repo / "tests" / "test_capture.py").read_bytes()
        ).hexdigest()
        ff["base_revision"] = _head_sha_of(red_repo)


def _good_bundle():
    # The check commands are the real commands _recorded_bundle
    # runs: the `test` gate runs pytest against the fixture test
    # file (round 11, FND-001), and the lint check prints its
    # result. A PASS fixture's captures must be generated by
    # record_check.py itself, never hand-written; the hand-written
    # command and stdout below are what the recorded fragment
    # overwrites, kept so the unrecorded shape still describes the
    # same real run.
    return {
        "schema_version": 6,
        "revision": "abc1234",
        "working_tree_state": "clean",
        "requirement": "Fix the Persian capture crash.",
        "acceptance_criteria": ["A Persian-only idea captures without a traceback."],
        "files_changed": ["skills/idea-capture/scripts/capture.py", "tests/test_capture.py"],
        "checks": [
            {
                "name": "test",
                "command": "python3 -m pytest tests/test_capture.py -v",
                "cwd": "/repo",
                "exit_code": 0,
                "verdict": "PASS",
                "tool_version": "pytest 8.4.2",
                "started_at": "2026-11-06T10:00:00Z",
                "finished_at": "2026-11-06T10:00:12Z",
                "stdout_text": "tests/test_capture.py::test_capture_persian_only PASSED\n"
                "tests/test_capture.py::TestCapture::test_capture_persian_only PASSED\n"
                "2 passed in 0.42s",
            },
            {
                "name": "lint",
                "command": "python3 -c \"print('All checks passed!')\"",
                "cwd": "/repo",
                "exit_code": 0,
                "verdict": "PASS",
                "tool_version": "ruff 0.17.4",
                "started_at": "2026-11-06T10:00:12Z",
                "finished_at": "2026-11-06T10:00:13Z",
                "stdout_text": "All checks passed!",
            },
        ],
        "findings": [],
        "unresolved_risks": [],
        "unverified_items": [],
        "verdict": "PASS",
        "reviewer_identity": "orcinus-verify (independent session)",
        "implementer_identity": "implementer (author session)",
        "verification_plan": {
            "change_type": "bug-fix",
            "required_gates": ["test", "lint"],
            "not_applicable_gates": [
                {"gate": "build", "reason": "Python scripts have no build step."},
                {"gate": "typecheck", "reason": "No typechecker in this Python project."},
            ],
        },
        "fail_first": {
            "test": "tests/test_capture.py::test_capture_persian_only",
            "failed_before": True,
            "passed_after": True,
            "method": "worktree",
            "red_check": {
                "command": "python3 -c \"import sys; print('FAILED tests/test_capture.py::test_capture_persian_only - AssertionError: Persian-only idea raised'); sys.exit(1)\"",
                "exit_code": 1,
                "stdout_text": "FAILED tests/test_capture.py::test_capture_persian_only - AssertionError: Persian-only idea raised",
            },
        },
    }


def test_good_bundle_passes(tmp_path):
    b = _good_bundle()
    _recorded_bundle(b, tmp_path)
    assert _problems(b, tmp_path) == []


def test_recorded_bundle_binds_to_the_given_repo_not_the_checkout(tmp_path):
    """The validator tests record captures against a throwaway git
    repo, never against the checkout they run in: a git-archive
    clean copy has no .git, so recording against the checkout fails
    there — 24 failures in the CI clean-install job — while the same
    tests pass in the working tree. The recorded fragment must bind
    to the repo it was given: its revision is that repo's HEAD and
    the bundle still validates."""
    import subprocess

    repo = _recording_repo(tmp_path)
    b = _good_bundle()
    _recorded_bundle(b, tmp_path, repo=repo)
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert b["checks"][0]["revision"] == head
    assert b["checks"][0]["content_digest"].startswith("sha256:")
    assert _problems(b, tmp_path) == []


def test_recorded_bundle_default_repo_is_not_the_checkout(tmp_path):
    """The default recording repo is a throwaway repo beside the
    bundle directory, not the checkout: when the checkout has a
    HEAD, the recorded revision must differ from it (the throwaway
    repo is a different repo with its own commit). When there is no
    checkout HEAD at all — a git-archive clean copy — recording
    must still succeed and the bundle must still validate."""
    import subprocess

    checkout = Path(__file__).resolve().parent.parent.parent.parent
    head = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    checkout_head = head.stdout.strip() if head.returncode == 0 else None
    b = _good_bundle()
    _recorded_bundle(b, tmp_path)
    assert _problems(b, tmp_path) == []
    if checkout_head is not None:
        assert b["checks"][0]["revision"] != checkout_head


def test_pass_hiding_a_failed_check_fails():
    b = _good_bundle()
    b["checks"][0]["verdict"] = "FAIL"
    problems = _problems(b)
    assert any("FAIL" in p and "PASS" in p for p in problems)


def test_pass_hiding_a_blocking_finding_fails():
    b = _good_bundle()
    b["findings"] = [
        {
            "file": "src/x.ts",
            "line": 12,
            "evidence": "crashes on empty input",
            "severity": "blocking",
        }
    ]
    problems = _problems(b)
    assert any("blocking finding" in p for p in problems)


def test_pass_hiding_unverified_items_fails():
    b = _good_bundle()
    b["unverified_items"] = ["the 3.9 matrix has never run"]
    problems = _problems(b)
    assert any("unverified_items" in p for p in problems)


def test_pass_with_nonzero_exit_code_fails():
    b = _good_bundle()
    b["checks"][0]["exit_code"] = 1
    problems = _problems(b)
    assert any("exit_code 1" in p for p in problems)


def test_fail_without_a_blocking_finding_or_failed_check_fails():
    b = _good_bundle()
    b["verdict"] = "FAIL"
    problems = _problems(b)
    assert any("no blocking finding" in p for p in problems)


def test_incomplete_without_anything_unverified_fails():
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    problems = _problems(b)
    assert any("nothing is unverified" in p for p in problems)


def test_missing_required_field_fails():
    b = _good_bundle()
    del b["revision"]
    problems = _problems(b)
    assert any("revision" in p for p in problems)


def test_dirty_tree_without_dirty_files_fails():
    b = _good_bundle()
    b["working_tree_state"] = "dirty"
    problems = _problems(b)
    assert any("dirty_files" in p for p in problems)


def test_fail_first_never_shown_failing_fails():
    b = _good_bundle()
    b["fail_first"]["failed_before"] = False
    problems = _problems(b)
    assert any("never shown failing" in p for p in problems)


def test_fail_first_not_applicable_needs_a_note(tmp_path):
    b = _good_bundle()
    b["fail_first"]["method"] = "not-applicable"
    problems = _problems(b)
    assert any("no note" in p for p in problems)
    # not-applicable with a note is only acceptable when the change has
    # no behaviour to test: a docs-only change, not a bug-fix.
    b["fail_first"]["note"] = "Docs-only change; no behaviour to test."
    b["fail_first"]["failed_before"] = False
    b["fail_first"]["passed_after"] = False
    b["files_changed"] = ["README.md"]
    b["verification_plan"]["change_type"] = "docs-only"
    b["verification_plan"]["required_gates"] = []
    b["verification_plan"]["not_applicable_gates"] = [
        {"gate": "build", "reason": "Docs-only change; nothing to build."},
        {"gate": "lint", "reason": "Docs-only change; no code to lint."},
        {"gate": "typecheck", "reason": "Docs-only change; nothing to typecheck."},
        {"gate": "test", "reason": "Docs-only change; no behaviour to test."},
    ]
    # A docs-only PASS still needs its checks recorded (the red run
    # is not-applicable here, so only the two checks are recorded).
    _recorded_bundle(b, tmp_path)
    assert _problems(b, tmp_path) == []


# --- Round-3 regression tests (reviewer 4, section 3). Each of these
# failed or crashed on the old validator; they are the red-first
# tests for the rewrite. ---


def test_schema_version_true_fails():
    # True == 1 in Python; the schema says const 1, a boolean is not 1.
    b = _good_bundle()
    b["schema_version"] = True
    assert any("schema_version" in p for p in _problems(b))


def test_exit_code_false_fails():
    # False is an int subclass; an exit code must be a real integer.
    b = _good_bundle()
    b["checks"][0]["exit_code"] = False
    assert any("exit_code" in p for p in _problems(b))


def test_acceptance_criteria_non_string_fails():
    b = _good_bundle()
    b["acceptance_criteria"] = [123]
    assert any("acceptance_criteria" in p for p in _problems(b))


def test_check_name_command_cwd_must_be_non_empty_strings():
    b = _good_bundle()
    b["checks"][0]["name"] = 123
    b["checks"][0]["command"] = None
    b["checks"][0]["cwd"] = ""
    problems = _problems(b)
    assert any("checks[0].name" in p for p in problems)
    assert any("checks[0].command" in p for p in problems)
    assert any("checks[0].cwd" in p for p in problems)


def test_extra_top_level_key_fails():
    b = _good_bundle()
    b["surprise_field"] = "not in the schema"
    assert any("surprise_field" in p for p in _problems(b))


def test_extra_check_key_fails():
    b = _good_bundle()
    b["checks"][0]["surprise_field"] = "not in the schema"
    assert any("surprise_field" in p for p in _problems(b))


def test_fail_first_string_false_fails():
    # "false" is truthy; failed_before/passed_after must be booleans.
    b = _good_bundle()
    b["fail_first"]["failed_before"] = "false"
    b["fail_first"]["passed_after"] = "false"
    problems = _problems(b)
    assert any("failed_before" in p for p in problems)
    assert any("passed_after" in p for p in problems)


def _run_cli(bundle):
    """Run the validator as a subprocess on a temp bundle file.

    A crash must surface here as a traceback on stderr, not as a
    clean failure, so these tests prove the no-crash fix.
    """
    import json
    import subprocess
    import tempfile

    validator = Path(__file__).resolve().parent / "validate_evidence.py"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(bundle, f)
        path = f.name
    proc = subprocess.run([sys.executable, str(validator), path], capture_output=True, text=True)
    Path(path).unlink()
    return proc


def test_checks_null_reports_without_crash():
    b = _good_bundle()
    b["checks"] = None
    proc = _run_cli(b)
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "checks" in proc.stdout


def test_findings_null_reports_without_crash():
    b = _good_bundle()
    b["findings"] = None
    proc = _run_cli(b)
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "findings" in proc.stdout


def test_fail_plus_incomplete_forces_fail_verdict():
    b = _good_bundle()
    b["checks"].append(
        {
            "name": "lint",
            "command": "ruff check",
            "cwd": "/repo",
            "exit_code": 1,
            "verdict": "FAIL",
            "tool_version": "ruff 0.17.4",
            "started_at": "2026-11-06T10:00:00Z",
            "finished_at": "2026-11-06T10:00:01Z",
        }
    )
    b["checks"].append(
        {
            "name": "typecheck",
            "command": "tsc",
            "cwd": "/repo",
            "exit_code": 2,
            "verdict": "INCOMPLETE",
            "tool_version": "tsc 5.0.0",
            "started_at": "2026-11-06T10:00:00Z",
            "finished_at": "2026-11-06T10:00:01Z",
        }
    )
    b["verdict"] = "INCOMPLETE"
    problems = _problems(b)
    assert any("FAIL" in p for p in problems)


def test_blocking_finding_plus_incomplete_forces_fail_verdict():
    b = _good_bundle()
    b["findings"] = [
        {
            "file": "src/x.ts",
            "line": 12,
            "evidence": "crashes on empty input",
            "severity": "blocking",
        }
    ]
    b["unverified_items"] = ["the 3.9 matrix has never run"]
    b["verdict"] = "INCOMPLETE"
    problems = _problems(b)
    assert any("FAIL" in p for p in problems)


def test_pass_without_verification_plan_fails():
    # One passing check must not stand for all required gates: a PASS
    # needs a plan naming the gates and their coverage.
    b = _good_bundle()
    b.pop("verification_plan", None)
    problems = _problems(b)
    assert any("verification_plan" in p for p in problems)


def test_pass_with_uncovered_required_gate_fails():
    b = _good_bundle()
    b["verification_plan"]["required_gates"] = ["test", "lint", "typecheck"]
    problems = _problems(b)
    assert any("typecheck" in p for p in problems)


def test_pass_with_only_test_gate_fails():
    # Round-4 regression (reviewer 4, section 3.2): a bug-fix verified
    # by the test gate alone used to PASS — lint, build and typecheck
    # were never even mentioned. Every canonical gate must now be
    # required or explicitly waived with a reason.
    b = _good_bundle()
    b["verification_plan"]["required_gates"] = ["test"]
    b["verification_plan"]["not_applicable_gates"] = []
    problems = _problems(b)
    assert any("lint" in p for p in problems)
    assert any("build" in p for p in problems)
    assert any("typecheck" in p for p in problems)


def test_not_applicable_gate_needs_a_reason(tmp_path):
    b = _good_bundle()
    b["verification_plan"]["required_gates"] = ["test"]
    b["verification_plan"]["not_applicable_gates"] = [{"gate": "typecheck"}]
    problems = _problems(b)
    assert any("reason" in p for p in problems)
    b["verification_plan"]["not_applicable_gates"] = [
        {"gate": "build", "reason": "Python scripts have no build step."},
        {"gate": "typecheck", "reason": "No typechecker in this Python project."},
    ]
    b["verification_plan"]["required_gates"] = ["test", "lint"]
    _recorded_bundle(b, tmp_path)
    assert _problems(b, tmp_path) == []


def test_validator_is_self_contained_outside_the_repo(tmp_path):
    """The validator and its schema live inside the orcinus-verify
    skill folder and resolve relative to the script, so they work
    from a user project with no repo checkout: copy the skill folder
    elsewhere, run the validator from there, and the good bundle
    still validates. The old layout (scripts/ + evals/ at the repo
    root) only worked inside a full-repo install — in an npx-skills
    install (skill folders only) both files were absent."""
    import json
    import shutil
    import subprocess

    skill = Path(__file__).resolve().parent.parent
    assert (skill / "scripts" / "validate_evidence.py").is_file()
    assert (skill / "references" / "evidence.schema.json").is_file()
    elsewhere = tmp_path / "some-project"
    shutil.copytree(skill, elsewhere / "orcinus-verify")
    bundle = elsewhere / "bundle.json"
    b = _good_bundle()
    # The captures are recorded into the bundle directory (elsewhere)
    # before the validator runs there: the copied validator must
    # recompute the binding from the copied record_check.py alone,
    # with no repo checkout. The repo is named explicitly so the
    # captures bind to it: the shared cached test capture binds to
    # its own repo (round 11, FND-001), and the CLI run below names
    # this repo.
    repo = _recording_repo(elsewhere)
    _recorded_bundle(b, elsewhere, repo=repo)
    _write_junit_reports(b, elsewhere)
    _write_test_report(b, elsewhere)
    # FND-004 (round 8): the bundle revision is the recording
    # repo's HEAD, so the checks' revisions agree with it.
    b["revision"] = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    bundle.write_text(json.dumps(b), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(elsewhere / "orcinus-verify" / "scripts" / "validate_evidence.py"),
            str(bundle),
            # FND-004 (round 8): the CLI binds to a repo by default
            # (cwd), and the copied skill runs from a non-repo dir —
            # so the run names the repo the captures bind to.
            "--repo",
            str(repo),
        ],
        capture_output=True,
        text=True,
        cwd=elsewhere,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# --- Round-4 regression tests (reviewers 3 and 4, on cbb1bdf5).
# Each of these passed (or was untestable) on the old validator; they
# are the red-first tests for the v0.9.1 rewrite of the validator
# and the evidence schema (schema_version 1 -> 2). ---


def test_pass_without_fail_first_fails():
    # A behaviour-change PASS with no fail_first at all used to pass:
    # check_fail_first returned silently when the field was absent.
    b = _good_bundle()
    b.pop("fail_first", None)
    problems = _problems(b)
    assert any("fail_first" in p for p in problems)


def test_pass_with_fail_first_not_applicable_for_bug_fix_fails():
    # not-applicable with a note is only for changes with no behaviour
    # to test. A bug-fix cannot waive the red proof by assertion.
    b = _good_bundle()
    b["fail_first"]["method"] = "not-applicable"
    b["fail_first"]["note"] = "No behaviour to test."
    b["fail_first"]["failed_before"] = False
    b["fail_first"]["passed_after"] = False
    problems = _problems(b)
    assert any("not-applicable" in p for p in problems)


def test_docs_only_pass_without_fail_first_passes(tmp_path):
    # A docs-only change has no behaviour to test, so no fail_first
    # is needed — but every canonical gate must still be accounted
    # for, required or waived with a reason.
    b = _good_bundle()
    b.pop("fail_first", None)
    b["files_changed"] = ["README.md"]
    b["verification_plan"]["change_type"] = "docs-only"
    b["verification_plan"]["required_gates"] = []
    b["verification_plan"]["not_applicable_gates"] = [
        {"gate": "build", "reason": "Docs-only change; nothing to build."},
        {"gate": "lint", "reason": "Docs-only change; no code to lint."},
        {"gate": "typecheck", "reason": "Docs-only change; nothing to typecheck."},
        {"gate": "test", "reason": "Docs-only change; no behaviour to test."},
    ]
    _recorded_bundle(b, tmp_path)
    assert _problems(b, tmp_path) == []


def test_finding_without_severity_fails():
    # severity is required: a finding without one used to be treated
    # as non-blocking (fail-open).
    b = _good_bundle()
    b["findings"] = [{"file": "src/x.ts", "line": 12, "evidence": "crashes on empty input"}]
    problems = _problems(b)
    assert any("severity" in p for p in problems)


def test_severity_less_finding_is_blocking():
    # Fail-closed: anything not explicitly "non-blocking" counts as
    # blocking in the verdict computation itself. The non-blocking
    # case needs a passing check: since v3 an empty checks list
    # means "stopped before the first check" and is INCOMPLETE,
    # not PASS.
    assert (
        ve.expected_verdict(
            {"findings": [{"severity": "blocking"}], "checks": [], "unverified_items": []}
        )
        == "FAIL"
    )
    assert ve.expected_verdict({"findings": [{}], "checks": [], "unverified_items": []}) == "FAIL"
    assert (
        ve.expected_verdict(
            {
                "findings": [{"severity": "non-blocking"}],
                "checks": [{"verdict": "PASS"}],
                "unverified_items": [],
            }
        )
        == "PASS"
    )


def test_schema_check_name_example_must_not_mention_fail_first():
    # The schema's own example invited recording the red run as a
    # check named 'fail-first' — which the exit-code rule then
    # rejects. The red run belongs in fail_first, never in checks.
    name_desc = _SCHEMA["properties"]["checks"]["items"]["properties"]["name"]["description"]
    assert "fail-first" not in name_desc


def test_check_without_timestamps_or_tool_version_fails():
    b = _good_bundle()
    for field in ("tool_version", "started_at", "finished_at"):
        del b["checks"][0][field]
    problems = _problems(b)
    assert any("tool_version" in p for p in problems)
    assert any("started_at" in p for p in problems)
    assert any("finished_at" in p for p in problems)


def test_finished_before_started_fails():
    b = _good_bundle()
    b["checks"][0]["started_at"] = "2026-11-06T10:00:00Z"
    b["checks"][0]["finished_at"] = "2026-11-06T09:00:00Z"
    problems = _problems(b)
    assert any("finished_at" in p for p in problems)


def test_missing_stdout_artifact_fails(tmp_path):
    # An artifact path that does not exist (relative to the bundle)
    # must fail: a claimed output nobody can read is not evidence.
    # Since v3 the artifact also needs its sha256 recorded.
    import json

    b = _good_bundle()
    _recorded_bundle(b, tmp_path)
    b["checks"][0]["stdout_artifact"] = "logs/pytest-stdout.log"
    b["checks"][0]["stderr_artifact"] = "logs/pytest-stderr.log"
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps(b), encoding="utf-8")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("stdout_artifact" in p for p in problems)
    assert any("stderr_artifact" in p for p in problems)
    (tmp_path / "logs").mkdir()
    # The log files get the recorded capture's bytes, so the recorded
    # sha256 (and the binding hash over it) still match: the point
    # here is the artifact's presence, not its content.
    (tmp_path / "logs" / "pytest-stdout.log").write_bytes((tmp_path / "test.stdout").read_bytes())
    (tmp_path / "logs" / "pytest-stderr.log").write_bytes((tmp_path / "test.stderr").read_bytes())
    _write_junit_reports(b, tmp_path)
    _write_test_report(b, tmp_path)
    assert ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path) == []


def test_date_only_timestamp_fails():
    b = _good_bundle()
    b["checks"][0]["started_at"] = "2026-11-06"
    problems = _problems(b)
    assert any("started_at" in p for p in problems)


def test_naive_timestamp_fails():
    b = _good_bundle()
    b["checks"][0]["started_at"] = "2026-11-06T10:00:00"
    problems = _problems(b)
    assert any("started_at" in p for p in problems)


def test_week_date_timestamp_fails():
    # fromisoformat accepts ISO week dates on 3.11+ but not on 3.10:
    # acceptance must not depend on the Python version.
    b = _good_bundle()
    b["checks"][0]["started_at"] = "2026-W45-5"
    problems = _problems(b)
    assert any("started_at" in p for p in problems)


def test_rfc3339_with_offset_passes():
    # An offset timestamp is a valid RFC 3339 date-time: the schema
    # layer must accept it. This is a schema-layer assertion, not a
    # full-bundle one — record_check.py always records UTC (Z), so a
    # recorded bundle never carries an offset timestamp.
    b = _good_bundle()
    b["checks"][0]["started_at"] = "2026-11-06T10:00:00+03:30"
    b["checks"][0]["finished_at"] = "2026-11-06T10:00:12+03:30"
    assert ve.validate_against_schema(b, _SCHEMA) == []


def test_honest_incomplete_with_failed_fail_first_is_valid():
    # A verifier that honestly reports "no red proof" with verdict
    # INCOMPLETE used to be rejected as an invalid bundle. The
    # fail-first flags are PASS rules, not validity rules.
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    b["fail_first"]["failed_before"] = False
    b["fail_first"]["passed_after"] = False
    b["unverified_items"] = ["no red proof: the test never ran pre-fix"]
    assert _problems(b) == []


def test_honest_incomplete_without_acceptance_criteria_is_valid():
    # The schema itself says: with no acceptance criteria the
    # verification must stop (INCOMPLETE), not invent them. Recording
    # that stop must be possible.
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    b["acceptance_criteria"] = []
    b["unverified_items"] = ["no acceptance criteria were given; stopped"]
    assert _problems(b) == []


def test_pass_without_acceptance_criteria_fails():
    b = _good_bundle()
    b["acceptance_criteria"] = []
    problems = _problems(b)
    assert any("acceptance_criteria" in p for p in problems)


def test_change_type_must_be_a_known_value():
    b = _good_bundle()
    b["verification_plan"]["change_type"] = "whatever"
    problems = _problems(b)
    assert any("change_type" in p for p in problems)


def test_old_schema_version_is_rejected():
    # A v3 bundle is rejected with the migration message (F-24), not
    # the flat const error: the message says the schema moved on and
    # the fix is to re-run verification. Rejection is intentional.
    b = _good_bundle()
    b["schema_version"] = 3
    problems = _problems(b)
    assert any("schema_version" in p for p in problems)
    assert any("older" in p for p in problems)
    assert any("re-run verification" in p for p in problems)


def test_pass_check_without_any_output_fails():
    # F4 (round 5): a PASS bundle whose checks carry no output at
    # all — no artifact, no inline text — used to validate. The
    # validator proved the bundle was complete and self-consistent,
    # not that any check really ran.
    b = _good_bundle()
    for c in b["checks"]:
        c.pop("stdout_text", None)
        c.pop("stderr_text", None)
        c.pop("stdout_artifact", None)
        c.pop("stderr_artifact", None)
    problems = _problems(b)
    assert any("output" in p for p in problems)


def test_artifact_without_sha256_fails(tmp_path):
    # F4 / R3 #19: an artifact without its sha256 is a claim nobody
    # can verify — the file could have been replaced after the run.
    b = _good_bundle()
    b["checks"][0]["stdout_artifact"] = "logs/pytest-stdout.log"
    b["checks"][0].pop("stdout_text", None)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "pytest-stdout.log").write_text("ok")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("sha256" in p for p in problems)


def test_artifact_with_wrong_sha256_fails(tmp_path):
    # The hash must match the file, or the artifact changed since
    # the bundle was written.
    b = _good_bundle()
    b["checks"][0]["stdout_artifact"] = "logs/pytest-stdout.log"
    b["checks"][0]["stdout_sha256"] = "0" * 64
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "pytest-stdout.log").write_text("ok")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("sha256" in p for p in problems)


def test_artifact_with_correct_sha256_passes(tmp_path):
    # Control for the two tests above: artifact + matching hash is
    # valid evidence. The artifact lives at a non-capture path
    # (logs/...) with the recorded capture's bytes, so the recorded
    # sha256 and the binding still match: artifact paths are not
    # pinned to the capture filenames, only their bytes are.
    b = _good_bundle()
    _recorded_bundle(b, tmp_path)
    b["checks"][0]["stdout_artifact"] = "logs/pytest-stdout.log"
    (tmp_path / "logs").mkdir()
    # write_bytes, not write_text: the sha256 is computed over these
    # exact bytes, and text mode translates "\n" to "\r\n" on Windows
    # — the bytes on disk would no longer match the recorded hash.
    (tmp_path / "logs" / "pytest-stdout.log").write_bytes((tmp_path / "test.stdout").read_bytes())
    _write_junit_reports(b, tmp_path)
    _write_test_report(b, tmp_path)
    assert ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path) == []


def test_artifact_with_crlf_bytes_and_lf_hash_fails(tmp_path):
    # Round-6 follow-up (Windows CI): the two tests above failed on
    # Windows because their fixtures hashed the LF string but wrote
    # the log with write_text — text mode translates "\n" to "\r\n"
    # on Windows, so the bytes on disk no longer matched the recorded
    # hash. That is the validator working correctly, not a bug in it:
    # the sha256 is over exact bytes and must stay strict. This test
    # pins that strictness — a CRLF file with an LF hash must still
    # fail — which is also why the artifact fixtures must use
    # write_bytes.
    import hashlib

    b = _good_bundle()
    content = "2 passed in 0.12s\n"
    b["checks"][0]["stdout_artifact"] = "logs/pytest-stdout.log"
    b["checks"][0]["stdout_sha256"] = hashlib.sha256(content.encode()).hexdigest()
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "pytest-stdout.log").write_bytes(content.replace("\n", "\r\n").encode())
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("sha256" in p for p in problems)


def test_sha256_must_be_hex():
    # The schema pins the hash format: 64 lowercase hex chars.
    b = _good_bundle()
    b["checks"][0]["stdout_artifact"] = "logs/out.log"
    b["checks"][0]["stdout_sha256"] = "not-a-hash"
    problems = _problems(b)
    assert any("sha256" in p for p in problems)


def test_incomplete_with_no_checks_and_stop_reason_is_valid():
    # F5 (round 5): the verifier stopped before the first check
    # (no acceptance criteria) — the bundle records the stop with
    # a reason instead of inventing a check. The old schema
    # rejected checks: [] (minItems 1) and had no reason field, so
    # the stop the SKILL.md promises could not be filed.
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    b["acceptance_criteria"] = []
    b["checks"] = []
    b["stop_reason"] = "no acceptance criteria were given; stopped"
    b["unverified_items"] = ["no acceptance criteria were given; stopped"]
    assert _problems(b) == []


def test_empty_checks_without_stop_reason_fails():
    # An empty checks list with no recorded reason is not an
    # honest stop — it is a bundle that says nothing.
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    b["acceptance_criteria"] = []
    b["checks"] = []
    b["unverified_items"] = ["no acceptance criteria were given; stopped"]
    problems = _problems(b)
    assert any("stop_reason" in p for p in problems)


def test_empty_checks_with_pass_verdict_fails():
    # No checks can never be a PASS, even with a stop reason.
    b = _good_bundle()
    b["checks"] = []
    b["stop_reason"] = "no acceptance criteria were given; stopped"
    problems = _problems(b)
    assert problems


def test_stop_reason_only_for_incomplete_with_no_checks():
    # FND-006 (round 9) + N-F6x: stop_reason says why the
    # verification stopped before any check ran (schema: required
    # when checks is empty and the verdict is INCOMPLETE). A
    # non-empty stop_reason on any other shape is a
    # self-contradiction: a PASS or FAIL ran to a verdict, and an
    # INCOMPLETE with checks ran checks. Only the genuine
    # INCOMPLETE-with-empty-checks shape (see
    # test_incomplete_with_no_checks_and_stop_reason_is_valid) may
    # carry one.
    b = _good_bundle()
    b["stop_reason"] = "gave up before the checks"
    problems = _problems(b)
    assert any("stop_reason" in p for p in problems), problems
    b = _good_bundle()
    b["verdict"] = "FAIL"
    b["findings"] = [{"file": "src/x.py", "line": 1, "evidence": "crash", "severity": "blocking"}]
    b["stop_reason"] = "gave up before the checks"
    problems = _problems(b)
    assert any("stop_reason" in p for p in problems), problems
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    b["unverified_items"] = ["the test gate could not run"]
    b["stop_reason"] = "gave up before the checks"
    problems = _problems(b)
    assert any("stop_reason" in p for p in problems), problems


# --- Round-6 regression tests (M5–M8). Each of these passed on the
# old validator; they are the red-first tests for this fix pass. ---


def _artifact_bundle(tmp_path, artifact, content):
    """A good bundle whose test check records `artifact` with the
    sha256 of `content`, written under tmp_path. Returns the bundle;
    the caller places the file (or link) itself."""
    import hashlib

    b = _good_bundle()
    b["checks"][0]["stdout_artifact"] = artifact
    b["checks"][0]["stdout_sha256"] = hashlib.sha256(content).hexdigest()
    b["checks"][0].pop("stdout_text", None)
    return b


def test_artifact_absolute_path_fails(tmp_path):
    # M5 (V3 / 2-V3 / 3-P1-5): an absolute path overrides the bundle
    # directory, so a file outside the bundle used to hash and pass.
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"not in the bundle")
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    b = _artifact_bundle(bundle_dir, str(outside), b"not in the bundle")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=bundle_dir)
    assert any("absolute" in p for p in problems)


def test_artifact_traversal_fails(tmp_path):
    # M5: a ../ path that resolves outside the bundle must fail,
    # even with the correct sha256.
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"not in the bundle")
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    b = _artifact_bundle(bundle_dir, "../outside.txt", b"not in the bundle")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=bundle_dir)
    assert any("outside" in p or "escapes" in p for p in problems)


def test_artifact_symlink_fails(tmp_path):
    # M5: a symlink inside the bundle pointing outside it must fail,
    # even when the target has the recorded hash.
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"not in the bundle")
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "link.txt").symlink_to(outside)
    b = _artifact_bundle(bundle_dir, "link.txt", b"not in the bundle")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=bundle_dir)
    assert any("symlink" in p for p in problems)


def test_artifact_without_bundle_dir_is_unverified():
    # M5 (3-P1-5, API half): validate_bundle with bundle_dir=None
    # used to return [] for an artifact it never checked — "not
    # checked" silently equated with "passed". The artifact must be
    # recorded as explicitly unverified.
    b = _good_bundle()
    b["checks"][0]["stdout_artifact"] = "logs/out.log"
    b["checks"][0]["stdout_sha256"] = "0" * 64
    b["checks"][0].pop("stdout_text", None)
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=None)
    assert any("unverified" in p for p in problems)


def test_artifact_over_size_cap_fails(tmp_path):
    # M5: a huge artifact must fail instead of being read fully
    # into memory (the old code hashed with read_bytes()).
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    content = b"x" * (ve.MAX_ARTIFACT_BYTES + 1)
    (bundle_dir / "big.log").write_bytes(content)
    b = _artifact_bundle(bundle_dir, "big.log", content)
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=bundle_dir)
    assert any("larger than" in p for p in problems)


def test_fail_first_without_red_check_fails():
    # M6 (V1 / 2-V1): the red proof was only two booleans. A PASS
    # for a behaviour change now needs the red run itself: command,
    # non-zero exit code, and output.
    b = _good_bundle()
    b["fail_first"].pop("red_check", None)
    problems = _problems(b)
    assert any("red_check" in p for p in problems)


def test_fail_first_red_check_zero_exit_fails():
    # A red run that exits 0 is not a red.
    b = _good_bundle()
    b["fail_first"]["red_check"] = {
        "command": "python3 -m pytest -q -k test_capture_persian_only",
        "exit_code": 0,
        "stdout_text": "FAILED test_capture_persian_only - AssertionError",
    }
    problems = _problems(b)
    assert any("red_check" in p and "exit" in p for p in problems)


def test_fail_first_red_check_accepts_verbatim_record_check_fragment(tmp_path):
    # Round 11, FND-007: the fragment record_check.py prints must
    # paste verbatim into fail_first.red_check, exactly as SKILL.md
    # step 3 instructs — no hand-editing the fragment. The fragment
    # always carries `name`, so the schema must allow it.
    b = _good_bundle()
    _recorded_bundle(b, tmp_path)
    red_repo = _red_worktree(tmp_path, _recording_repo(tmp_path))
    fragment = _run_record_check(tmp_path, "red_check", _RED_COMMAND, red_repo)
    assert fragment["name"] == "red_check"
    b["fail_first"]["red_check"] = fragment
    assert _problems(b, tmp_path) == []


def test_fail_first_unlinked_test_name_fails():
    # M6 (2-V1): a bundle naming "nonexistent_test" used to pass —
    # check_fail_first never read fail_first.test at all. The test
    # id must appear in the red output and in the green check.
    b = _good_bundle()
    b["fail_first"]["test"] = "nonexistent_test"
    problems = _problems(b)
    assert any("nonexistent_test" in p for p in problems)


def test_fail_first_test_missing_from_red_output_fails():
    b = _good_bundle()
    b["fail_first"]["red_check"] = {
        "command": "python3 -m pytest -q -k test_capture_persian_only",
        "exit_code": 1,
        "stdout_text": "1 failed, 1 passed in 0.12s",
    }
    problems = _problems(b)
    assert any("red" in p and "test_capture_persian_only" in p for p in problems)


def test_fail_first_test_missing_from_green_check_fails():
    b = _good_bundle()
    b["checks"][0]["stdout_text"] = "45 passed in 0.42s"
    problems = _problems(b)
    assert any("test_capture_persian_only" in p for p in problems)


def test_whitespace_only_stdout_text_fails():
    # M8 (2-V2): stdout_text=" " used to count as output. Output
    # must contain a non-whitespace character.
    b = _good_bundle()
    b["checks"][0]["stdout_text"] = " "
    problems = _problems(b)
    assert any("stdout_text" in p for p in problems)


def test_empty_tool_version_fails():
    # M8 (2-V2): tool_version="" used to pass (presence only).
    b = _good_bundle()
    b["checks"][0]["tool_version"] = ""
    problems = _problems(b)
    assert any("tool_version" in p for p in problems)


def test_noop_command_fails():
    # M8 (2-V2): command="true" for the test gate used to pass
    # with exit 0 and whitespace output. A no-op command proves
    # nothing ran.
    for noop in ("true", "false", ":", "echo", "exit 0"):
        b = _good_bundle()
        b["checks"][0]["command"] = noop
        problems = _problems(b)
        assert any("no-op" in p for p in problems), noop


def test_bad_revision_fails():
    # M8 (2-V2): revision="not-a-sha!!" used to pass (minLength 1
    # only). A revision is a hex SHA or 'working-tree'.
    b = _good_bundle()
    b["revision"] = "not-a-sha!!"
    problems = _problems(b)
    assert any("revision" in p for p in problems)


def test_missing_implementer_identity_fails():
    # M8 (2-V2): implementer_identity did not exist at all, so the
    # "verifier != implementer" condition had nothing to compare
    # against. It is now required.
    b = _good_bundle()
    b.pop("implementer_identity", None)
    problems = _problems(b)
    assert any("implementer_identity" in p for p in problems)


def test_reviewer_is_implementer_fails():
    # M8 (2-V2): reviewer_identity="implementer" used to pass. The
    # verifier must differ from the implementer.
    b = _good_bundle()
    b["implementer_identity"] = "the-author"
    b["reviewer_identity"] = "the-author"
    problems = _problems(b)
    assert any("differ" in p for p in problems)
    b = _good_bundle()
    b["reviewer_identity"] = "implementer"
    problems = _problems(b)
    assert any("implementer" in p for p in problems)


# --- Round-6 Track 4 regression tests (P1 verifier: V2, V4, V5, V8,
# 2-V4, 2-V5, 2-V6, 2-V7). Each of these passed on the old validator;
# they are the red-first tests for this fix pass. ---


def _docs_only_no_checks_bundle():
    """A docs-only PASS with no checks at all: every canonical gate
    waived with a reason, so there is nothing to run — the 2-V5 case.
    """
    b = _good_bundle()
    b.pop("fail_first", None)
    b["checks"] = []
    b["files_changed"] = ["README.md"]
    b["verification_plan"]["change_type"] = "docs-only"
    b["verification_plan"]["required_gates"] = []
    b["verification_plan"]["not_applicable_gates"] = [
        {"gate": "build", "reason": "Docs-only change; nothing to build."},
        {"gate": "lint", "reason": "Docs-only change; no code to lint."},
        {"gate": "typecheck", "reason": "Docs-only change; nothing to typecheck."},
        {"gate": "test", "reason": "Docs-only change; no behaviour to test."},
    ]
    return b


def test_config_only_with_code_file_fails():
    # V2: a behavioural change labelled config-only used to escape
    # both fail-first and the test gate — the validator never read
    # files_changed at all.
    b = _good_bundle()
    b["verification_plan"]["change_type"] = "config-only"
    b["files_changed"] = ["src/a.py"]
    problems = _problems(b)
    assert any("config-only" in p and "src/a.py" in p for p in problems)


def test_docs_only_with_code_file_fails():
    # V2, docs-only half: same bypass with a .py file.
    b = _good_bundle()
    b["verification_plan"]["change_type"] = "docs-only"
    b["files_changed"] = ["skills/x/scripts/y.py"]
    problems = _problems(b)
    assert any("docs-only" in p for p in problems)


def test_docs_only_with_docs_files_passes():
    # V2 control: a docs-only change touching only docs is fine.
    b = _docs_only_no_checks_bundle()
    b["files_changed"] = ["README.md", "docs/guide.md"]
    assert _problems(b) == []


def test_pass_on_dirty_tree_without_diff_hash_fails():
    # V4: PASS on a dirty tree used to be accepted although the
    # schema ties PASS to a revision and a dirty tree has none. The
    # PASS must pin the diff it ran on (git diff HEAD | sha256sum).
    b = _good_bundle()
    b["working_tree_state"] = "dirty"
    b["dirty_files"] = ["skills/x/scripts/y.py"]
    b["revision"] = "working-tree"
    problems = _problems(b)
    assert any("dirty" in p and "diff" in p for p in problems)


def test_pass_on_dirty_tree_with_diff_hash_passes(tmp_path):
    # V4 control: the same dirty PASS with the diff pinned is valid.
    b = _good_bundle()
    b["working_tree_state"] = "dirty"
    b["dirty_files"] = ["skills/x/scripts/y.py"]
    b["revision"] = "working-tree"
    b["diff_sha256"] = "0" * 64
    _recorded_bundle(b, tmp_path)
    assert _problems(b, tmp_path) == []


def test_clean_tree_with_dirty_files_fails():
    # V5, second half: dirty_files is "empty otherwise" per the
    # schema, but a clean tree with non-empty dirty_files passed.
    b = _good_bundle()
    b["dirty_files"] = ["skills/x/scripts/y.py"]
    problems = _problems(b)
    assert any("dirty_files" in p for p in problems)


def test_gate_in_both_required_and_waived_fails():
    # V5 / 2-V7 overlap half: a gate in both required_gates and
    # not_applicable_gates used to be accepted.
    b = _good_bundle()
    b["verification_plan"]["not_applicable_gates"] = [
        {"gate": "lint", "reason": "Waived and required at once."},
        {"gate": "build", "reason": "Python scripts have no build step."},
        {"gate": "typecheck", "reason": "No typechecker in this Python project."},
    ]
    problems = _problems(b)
    assert any("lint" in p and ("both" in p or "required" in p) for p in problems)


def _run_cli_bytes(raw):
    """Run the validator CLI on a temp file with these exact bytes."""
    import subprocess
    import tempfile

    validator = Path(__file__).resolve().parent / "validate_evidence.py"
    with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False) as f:
        f.write(raw)
        path = f.name
    proc = subprocess.run([sys.executable, str(validator), path], capture_output=True, text=True)
    Path(path).unlink()
    return proc


def test_non_utf8_bundle_exits_2_without_traceback():
    # 2-V4: a non-UTF-8 file raised an uncaught UnicodeDecodeError
    # with a traceback and exit 1, against the "never a traceback"
    # docstring. It is a controlled error: exit 2, no traceback.
    proc = _run_cli_bytes(b'{"schema_version": 4, "bad": "\xff\xfe"}')
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr


def test_deeply_nested_json_exits_2_without_traceback():
    # 2-V4: 20,000 levels of nesting raised an uncaught
    # RecursionError with a traceback and exit 1.
    proc = _run_cli_bytes(("[" * 20000 + "]" * 20000).encode())
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr


def test_docs_only_pass_with_no_checks_passes():
    # 2-V5: docs-only with all gates waived and no checks used to be
    # forced INCOMPLETE, while the schema says required_gates may be
    # empty and the SKILL says "do not fabricate a check".
    assert _problems(_docs_only_no_checks_bundle()) == []


def test_config_only_pass_with_no_checks_passes():
    # 2-V5, config-only half.
    b = _docs_only_no_checks_bundle()
    b["verification_plan"]["change_type"] = "config-only"
    assert _problems(b) == []


def test_docs_only_pass_with_no_checks_needs_all_gates_waived():
    # 2-V5 boundary: the empty-checks PASS is only for a fully
    # waived plan — a docs-only change with a gate never mentioned
    # still fails (silence is not a waiver).
    b = _docs_only_no_checks_bundle()
    b["verification_plan"]["not_applicable_gates"] = [
        {"gate": "build", "reason": "Docs-only change; nothing to build."},
    ]
    problems = _problems(b)
    assert any("lint" in p or "test" in p for p in problems)


def test_iso8601_fractional_digits_pinned():
    # 2-V6: the regex accepted any number of fractional digits and
    # fromisoformat then behaved differently on 3.10 (only 3 or 6
    # digits) vs 3.12. Only 3 or 6 digits are accepted now.
    for frac in (".1", ".12", ".1234", ".12345", ".1234567"):
        b = _good_bundle()
        b["checks"][0]["started_at"] = f"2026-11-06T10:00:00{frac}Z"
        assert any("started_at" in p for p in _problems(b)), frac
    # The valid fractions are a schema-layer assertion, not a
    # full-bundle one: recording overwrites the timestamps with real
    # UTC values, so a recorded bundle never carries these.
    for frac in (".123", ".123456"):
        b = _good_bundle()
        b["checks"][0]["started_at"] = f"2026-11-06T10:00:00{frac}Z"
        assert ve.validate_against_schema(b, _SCHEMA) == [], frac


def test_iso8601_year_bounds():
    # 2-V6: years 1999 / 2100 are outside the sane range for a
    # verification timestamp (2000-2099).
    b = _good_bundle()
    b["checks"][0]["started_at"] = "1999-11-06T10:00:00Z"
    assert any("started_at" in p for p in _problems(b))
    b = _good_bundle()
    b["checks"][0]["started_at"] = "2100-11-06T10:00:00Z"
    assert any("started_at" in p for p in _problems(b))
    # The in-range year is a schema-layer assertion: recording
    # overwrites the timestamps with real UTC values.
    b = _good_bundle()
    b["checks"][0]["started_at"] = "2099-11-06T10:00:00Z"
    b["checks"][0]["finished_at"] = "2099-11-06T10:00:12Z"
    assert ve.validate_against_schema(b, _SCHEMA) == []


def test_security_finding_cannot_be_non_blocking():
    # 2-V7: a "SQL injection" finding labelled non-blocking used to
    # PASS — the findings schema had no category, so severity was
    # purely self-declared. Security / data-loss categories are
    # automatically blocking.
    # FND-003 (round 9): the old assertion — the substring
    # "blocking" in ANY problem — was satisfied by
    # check_finding_categories' own message even with the rule
    # deleted, so the M2 mutant (delete the auto-blocking rule)
    # survived with all 144 tests green. The test pins the rule
    # itself: the computed verdict must be FAIL, and the specific
    # verdict-consistency problem must be present.
    for category in ("security", "data-loss"):
        b = _good_bundle()
        b["findings"] = [
            {
                "file": "src/x.py",
                "line": 12,
                "evidence": "SQL injection via string concat",
                "severity": "non-blocking",
                "category": category,
            }
        ]
        assert ve.expected_verdict(b) == "FAIL", category
        problems = _problems(b)
        assert any("verdict is PASS but there is a blocking finding" in p for p in problems), (
            category,
            problems,
        )


def test_non_blocking_finding_needs_a_category():
    # 2-V7: without a category the auto-blocking rule could be
    # dodged by omitting it — a non-blocking claim must say what
    # kind of finding it is.
    b = _good_bundle()
    b["findings"] = [
        {
            "file": "src/x.py",
            "line": 12,
            "evidence": "typo in a comment",
            "severity": "non-blocking",
        }
    ]
    problems = _problems(b)
    assert any("category" in p for p in problems)


def test_non_blocking_finding_with_other_category_passes(tmp_path):
    # 2-V7 control: a genuinely non-blocking finding with a
    # non-security category still passes.
    b = _good_bundle()
    b["findings"] = [
        {
            "file": "src/x.py",
            "line": 12,
            "evidence": "typo in a comment",
            "severity": "non-blocking",
            "category": "other",
        }
    ]
    _recorded_bundle(b, tmp_path)
    assert _problems(b, tmp_path) == []


def test_old_schema_version_4_is_rejected():
    # A v4 bundle is rejected with the migration message (F-24), not
    # the flat const error. Rejection is intentional: old bundles are
    # rejected, not migrated.
    b = _good_bundle()
    b["schema_version"] = 4
    problems = _problems(b)
    assert any("schema_version" in p for p in problems)
    assert any("older" in p for p in problems)
    assert any("re-run verification" in p for p in problems)


def test_old_schema_version_5_is_rejected():
    # F-24: the same for v5, the immediately previous version — the
    # realistic migration case is a bundle written yesterday.
    b = _good_bundle()
    b["schema_version"] = 5
    problems = _problems(b)
    assert any("schema_version is 5" in p for p in problems)
    assert any("re-run verification" in p for p in problems)


def test_newer_schema_version_gets_flat_error():
    # F-24 boundary: the migration message is only for OLDER bundles.
    # A bundle from a newer schema gets the flat const error — it is
    # not an upgrade the user can perform by re-running verification.
    b = _good_bundle()
    b["schema_version"] = 7
    problems = _problems(b)
    assert any("schema_version" in p for p in problems)
    assert all("re-run verification" not in p for p in problems)


def _run_cli_with_verdict_block(bundle, block_text):
    """Run the validator CLI with --verdict-block on temp files."""
    import json
    import subprocess
    import tempfile

    validator = Path(__file__).resolve().parent / "validate_evidence.py"
    with tempfile.TemporaryDirectory() as d:
        bundle_path = Path(d) / "bundle.json"
        # FND-004 (round 8): the CLI binds the bundle to a repo by
        # default, so the run names the repo the captures were
        # recorded against — the checkout cwd is a different repo —
        # and the bundle revision is that repo's HEAD, so the
        # checks' revisions agree with it. The repo is named
        # explicitly so the captures bind to it: the shared cached
        # test capture binds to its own repo (round 11, FND-001).
        repo = _recording_repo(Path(d))
        # Record the bundle's captures into the same directory, so
        # the CLI run tests the block comparison — not the recording.
        _recorded_bundle(bundle, Path(d), repo=repo)
        _write_junit_reports(bundle, Path(d))
        _write_test_report(bundle, Path(d))
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        block_path = Path(d) / "response.md"
        block_path.write_text(block_text, encoding="utf-8")
        bundle["revision"] = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable,
                str(validator),
                str(bundle_path),
                "--repo",
                str(repo),
                "--verdict-block",
                str(block_path),
            ],
            capture_output=True,
            text=True,
        )
        return proc


def _matching_verdict_block():
    # The good bundle's checks are test + lint, both PASS.
    return (
        "Some prose.\n\n```verdict\n"
        '{"verdict": "PASS", "checks": {"test": "PASS", "lint": "PASS"}, '
        '"file": null, "finding": "test and lint pass"}\n```\n'
    )


def test_verdict_block_matching_passes():
    # V8: the prose verdict block and the bundle must agree.
    proc = _run_cli_with_verdict_block(_good_bundle(), _matching_verdict_block())
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_verdict_block_wrong_verdict_fails():
    # V8: a block saying FAIL while the bundle says PASS disagrees.
    block = _matching_verdict_block().replace('"verdict": "PASS"', '"verdict": "FAIL"')
    proc = _run_cli_with_verdict_block(_good_bundle(), block)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "verdict" in proc.stdout


def test_verdict_block_wrong_check_fails():
    # V8: a block saying the test gate FAILED while the bundle says
    # it passed disagrees.
    block = _matching_verdict_block().replace('"test": "PASS"', '"test": "FAIL"')
    proc = _run_cli_with_verdict_block(_good_bundle(), block)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "test" in proc.stdout


def test_verdict_block_missing_fence_fails():
    # V8: no ```verdict fence at all — there is nothing to compare.
    proc = _run_cli_with_verdict_block(_good_bundle(), "No verdict block here.\n")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "verdict" in proc.stdout.lower()
    assert "Traceback" not in proc.stderr


def test_verdict_block_not_json_fails():
    # V8: a ```verdict fence that is not JSON cannot agree with the
    # bundle (the 3-P1-6 attack shape, applied to the block itself).
    proc = _run_cli_with_verdict_block(_good_bundle(), "```verdict\nnot JSON\n```\n")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr


def test_verdict_block_file_not_in_findings_fails():
    # V8: the block names a finding file the bundle has no finding
    # for — the two formats disagree about what was found.
    block = _matching_verdict_block().replace('"file": null', '"file": "src/x.ts"')
    proc = _run_cli_with_verdict_block(_good_bundle(), block)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "src/x.ts" in proc.stdout


# --- Round-7 regression tests (Track 1: F-02, F-03, F-04, F-06, F-11).
# Each of these passed on the v0.9.8 validator; they are the
# red-first tests for this fix pass. ---


def test_noop_exit_code_masking_suffix_fails():
    # F-02: a check whose command masks its own exit code with an
    # always-zero suffix proves nothing ran, however clean the exit
    # code looks. ShellCheck recommends `|| true` as the "ignore the
    # return value" idiom (SC2312), so this is our own regex layer,
    # not a ShellCheck rule.
    masking = [
        "pytest -q || true",
        "pytest -q || /bin/true",
        "pytest -q || /usr/bin/true",
        "pytest -q || :",
        "pytest -q || exit 0",
        "pytest -q ; exit 0",
        "pytest -q ; :",
        "pytest -q | true",
        "bash -c true",
        "bash -c 'pytest -q || true'",
        'sh -c "exit 0"',
        "python3 -c 'pass'",
        "python3 -c 'exit(0)'",
        "python -c 'sys.exit(0)'",
        "python3 -c ''",
    ]
    for cmd in masking:
        b = _good_bundle()
        b["checks"][0]["command"] = cmd
        problems = _problems(b)
        assert any("no-op" in p for p in problems), cmd


def test_noop_masking_in_red_check_fails():
    # F-02: the masking check also applies to fail_first.red_check
    # — a red run whose command always exits 0 is not a red.
    b = _good_bundle()
    b["fail_first"]["red_check"]["command"] = "pytest -q || true"
    problems = _problems(b)
    assert any("no-op" in p for p in problems)


def test_noop_genuine_fallback_passes():
    # F-02 controls: a real fallback, a failure-preserving suffix,
    # a pipe to a real command, a nested shell running a real
    # command, a python -c that actually runs something, and the
    # legitimate `! cmd` absence assertion must NOT be flagged.
    # These are command strings the fixture cannot run for real
    # (they name pytest), so they are tested at the level the rule
    # lives — _noop_problem is a pure function of the command string
    # — and the recorded end-to-end case is the test below.
    genuine = [
        "pytest -q || ruff check",
        "pytest -q || exit 1",
        "pytest -q ; exit 1",
        "pytest -q ; echo done",
        "pytest -q | grep -q x",
        "bash -c 'pytest -q'",
        "python3 -c 'import sys; sys.exit(pytest.main())'",
        "! pytest -q",
        "pytest -q && exit 0",
        "pytest -q || exit 1",
    ]
    for cmd in genuine:
        assert ve._noop_problem(cmd, "check 'test'") is None, cmd


def test_noop_recorded_shell_fallback_passes(tmp_path):
    # F-02 control, end to end: a real recorded run of a command
    # with a genuine fallback (the RHS is a real command, not an
    # always-zero one) validates as PASS.
    import shutil

    if shutil.which("sh") is None:
        import pytest

        pytest.skip("sh is not installed")
    python = sys.executable.replace("\\", "/")
    fallback = (
        f"{python} -m pytest tests/test_capture.py -v "
        f"--junitxml {tmp_path / 'green.xml'} "
        f"|| {python} -c \"print('fallback')\""
    )
    b = _good_bundle()
    _recorded_bundle(b, tmp_path, commands={"test": fallback})
    assert _problems(b, tmp_path) == []


def test_identity_case_or_whitespace_difference_fails():
    # F-04: reviewer/implementer independence is a comparison of
    # identities, not of spellings — case and surrounding whitespace
    # must not defeat it.
    for reviewer, implementer in [
        ("Alice", "alice"),
        ("alice ", "alice"),
        (" Alice ", "ALICE"),
        (" IMPLEMENTER ", "someone-else"),
        ("Implementer", "someone-else"),
    ]:
        b = _good_bundle()
        b["reviewer_identity"] = reviewer
        b["implementer_identity"] = implementer
        problems = _problems(b)
        assert any("differ" in p or "implementer" in p for p in problems), (
            reviewer,
            implementer,
        )


def test_identity_genuinely_different_passes(tmp_path):
    # F-04 control: genuinely different identities still pass.
    b = _good_bundle()
    b["reviewer_identity"] = "bob (review session)"
    b["implementer_identity"] = "alice (author session)"
    _recorded_bundle(b, tmp_path)
    assert _problems(b, tmp_path) == []


def test_behaviour_change_pass_with_empty_files_changed_fails():
    # F-06: a behaviour-change PASS that lists no files changed
    # claims a change that touched nothing. The schema has no
    # minItems on files_changed, so this is a semantic constraint,
    # added here — not a schema change.
    for change_type in ("bug-fix", "feature", "refactor"):
        b = _good_bundle()
        b["verification_plan"]["change_type"] = change_type
        b["files_changed"] = []
        problems = _problems(b)
        assert any("files_changed" in p for p in problems), change_type


def test_docs_only_pass_with_empty_files_changed_passes():
    # F-06 control: the docs-only no-checks exemption must not
    # regress — a docs-only PASS with no files listed (nothing to
    # run, nothing changed in code) is still valid.
    b = _docs_only_no_checks_bundle()
    b["files_changed"] = []
    assert _problems(b) == []


def test_time_order_with_unvalidated_input_reports_instead_of_raising():
    # F-11: check_time_order calls datetime.fromisoformat on strings
    # it assumes the schema validated. Called directly on
    # unvalidated input it raised TypeError (mixed naive/aware) or
    # ValueError (garbage) — a latent coupling if the schema layer
    # is ever relaxed. It must record a problem instead of raising.
    for started, finished in [
        ("2026-11-06T10:00:00Z", "2026-11-06T10:00:00"),  # aware vs naive
        ("not-a-date", "2026-11-06T10:00:00Z"),  # garbage
        ("2026-11-06T10:00:00", "2026-11-06T10:00:00Z"),  # naive vs aware
    ]:
        bundle = {
            "checks": [
                {
                    "name": "test",
                    "started_at": started,
                    "finished_at": finished,
                }
            ]
        }
        problems = []
        ve.check_time_order(bundle, problems)  # must not raise
        assert problems, (started, finished)
        assert any("test" in p for p in problems), problems


def test_fail_first_one_char_id_fails():
    # F-03: a 1-char test id used to pass by substring ("e" appears
    # in every output). The id is now a pytest nodeid, linked
    # structurally to the JUnit reports — a bare 1-char id is not
    # a nodeid and matches no report entry.
    b = _good_bundle()
    b["fail_first"]["test"] = "e"
    problems = _problems(b)
    assert any("fail_first.test" in p and "e" in p for p in problems)


def test_fail_first_substring_collision_fails():
    # F-03: test "sum" with a red run of an unrelated test whose
    # output contains the substring used to pass. The nodeid must
    # match a (classname, name) entry in the JUnit reports exactly.
    b = _good_bundle()
    b["fail_first"]["test"] = "sum"
    b["fail_first"]["red_check"]["stdout_text"] = "FAIL totally_unrelated_sumthing_else"
    b["checks"][0]["stdout_text"] = "totally_unrelated_sumthing_else passed"
    problems = _problems(b)
    assert any("fail_first.test" in p and "sum" in p for p in problems)


def test_fail_first_real_junit_report_accepted(tmp_path):
    # F-03 control: a real nodeid from a real JUnit fixture passes.
    b = _good_bundle()
    _recorded_bundle(b, tmp_path)
    _write_junit_reports(b, tmp_path)
    _write_test_report(b, tmp_path)
    assert ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path) == []


def test_fail_first_missing_report_fails(tmp_path):
    # F-03: no report → no PASS. A bundle with no red_report /
    # green_report at all must be refused, even when the stdout
    # text mentions the test id.
    b = _good_bundle()
    assert ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path) != []
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("red_report" in p for p in problems)
    assert any("green_report" in p for p in problems)


def test_fail_first_unparsable_report_fails(tmp_path):
    # F-03: an unreadable / unparsable report is a refusal, not a
    # fallback to the stdout substring.
    b = _good_bundle()
    _write_junit_reports(b, tmp_path)
    (tmp_path / "red.xml").write_bytes(b"this is not xml <")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("red_report" in p for p in problems)


def test_fail_first_report_missing_test_fails(tmp_path):
    # F-03: the reports exist but name a different test — the
    # named test is in neither run.
    b = _good_bundle()
    _write_junit_reports(
        b,
        tmp_path,
        red_cases=[("tests.test_other", "test_other", "failed")],
        green_cases=[("tests.test_other", "test_other", "passed")],
    )
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any(_CANONICAL_NODEID in p for p in problems)


def test_fail_first_red_report_passing_status_fails(tmp_path):
    # F-03: the red report lists the test as passed — that is not
    # a red, whatever the booleans and the stdout say.
    b = _good_bundle()
    _write_junit_reports(
        b,
        tmp_path,
        red_cases=[(_CANONICAL_CLASSNAME, _CANONICAL_NAME, "passed")],
    )
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("red_report" in p and _CANONICAL_NODEID in p for p in problems)


def test_fail_first_green_report_failing_status_fails(tmp_path):
    # F-03: the green report lists the test as failed — that is
    # not a green, whatever the passing 'test' check claims.
    b = _good_bundle()
    _write_junit_reports(
        b,
        tmp_path,
        green_cases=[(_CANONICAL_CLASSNAME, _CANONICAL_NAME, "failed")],
    )
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("green_report" in p and _CANONICAL_NODEID in p for p in problems)


def test_fail_first_class_nodeid_links_by_classname(tmp_path):
    # F-03: a nodeid with a class (tests/test_x.py::TestFoo::
    # test_bar) derives classname tests.test_x.TestFoo — the
    # structural link uses classname + name, not the bare name.
    # The recorded green run is a real pytest -v run, so its
    # output contains the class nodeid, and the red run prints it —
    # the red/green corroboration still holds for it.
    b = _good_bundle()
    nodeid = "tests/test_capture.py::TestCapture::test_capture_persian_only"
    b["fail_first"]["test"] = nodeid
    _recorded_bundle(
        b,
        tmp_path,
        commands={
            "test": [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_capture.py",
                "-v",
            ],
            "red_check": [
                sys.executable,
                "-c",
                f"import sys; print('FAILED {nodeid} - AssertionError: Persian-only idea raised'); sys.exit(1)",
            ],
        },
    )
    _write_junit_reports(
        b,
        tmp_path,
        red_cases=[("tests.test_capture.TestCapture", _CANONICAL_NAME, "failed")],
        # Both tests the recorded run ran, so the green report's
        # counts agree with its stdout ("2 passed", round 11,
        # FND-003): the class test is the link, the plain test is
        # the second passing test of the same run.
        green_cases=[
            (_CANONICAL_CLASSNAME, _CANONICAL_NAME, "passed"),
            ("tests.test_capture.TestCapture", _CANONICAL_NAME, "passed"),
        ],
    )
    _write_test_report(b, tmp_path)
    assert ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path) == []


# --- Round-7 Track 2 regression tests (F-01 execution binding, schema v6).
# Each of these passed on the v0.9.8 validator; they are the
# red-first tests for this fix pass. ---


def test_pass_with_unrecorded_check_fails():
    # F-01: a hand-written PASS bundle is no longer evidence — every
    # check in a PASS bundle must be recorded by record_check.py,
    # with a binding hash the validator recomputes.
    b = _good_bundle()
    problems = _problems(b)
    assert any("recorded" in p for p in problems)


def test_pass_with_unrecorded_red_check_fails(tmp_path):
    # F-01: the red run is part of the PASS claim, so it must be
    # recorded too — not just the checks.
    b = _good_bundle()
    _recorded_bundle(b, tmp_path)
    for field in ("recorded_by", "capture_sha256"):
        b["fail_first"]["red_check"].pop(field, None)
    problems = _problems(b, tmp_path)
    assert any("red_check" in p and "recorded" in p for p in problems)


def test_pass_with_wrong_capture_hash_fails(tmp_path):
    # F-01: a capture whose binding hash does not recompute from the
    # stored fields and the artifact files is rejected.
    b = _good_bundle()
    _recorded_bundle(b, tmp_path)
    b["checks"][0]["capture_sha256"] = "0" * 64
    problems = _problems(b, tmp_path)
    assert any("capture_sha256" in p for p in problems)


def test_pass_with_capture_reused_under_different_digest_fails(tmp_path):
    # F-01: the content digest is inside the binding hash, so the
    # same capture reused under a different digest cannot recompute.
    b = _good_bundle()
    _recorded_bundle(b, tmp_path)
    b["checks"][0]["content_digest"] = "sha256:" + "f" * 64
    problems = _problems(b, tmp_path)
    assert any("capture_sha256" in p for p in problems)


def test_pass_with_same_capture_under_two_digests_fails(tmp_path):
    # F-01: the duplicate-capture check — one capture_sha256 under
    # two different content_digests is a forgery, reported as such
    # on top of the recompute failure.
    b = _good_bundle()
    _recorded_bundle(b, tmp_path)
    copy = dict(b["checks"][0], name="lint")
    copy["content_digest"] = "sha256:" + "e" * 64
    b["checks"].append(copy)
    problems = _problems(b, tmp_path)
    assert any("different content_digests" in p for p in problems)


def test_pass_with_command_not_matching_argv_fails(tmp_path):
    # F-01: the human-readable command must be the canonical
    # rendering of the recorded argv — otherwise the command could
    # claim a gate the argv never ran.
    b = _good_bundle()
    _recorded_bundle(b, tmp_path)
    b["checks"][0]["command"] = "python3 -m pytest -q"
    problems = _problems(b, tmp_path)
    assert any("does not match" in p for p in problems)


def test_fail_bundle_with_unrecorded_checks_is_valid():
    # The recorded-fields rule is a PASS rule, not a validity rule:
    # an honest FAIL bundle may carry unrecorded checks — a failure
    # report is not a success claim. (The INCOMPLETE half is already
    # pinned by test_honest_incomplete_with_failed_fail_first_is_valid
    # and test_honest_incomplete_without_acceptance_criteria_is_valid.)
    b = _good_bundle()
    b["verdict"] = "FAIL"
    b["checks"][0]["verdict"] = "FAIL"
    b["checks"][0]["exit_code"] = 1
    assert _problems(b) == []


# --- Round-8 regression tests (FND-004, FND-005, FND-006).
# Each of these passed on the v0.10.1 validator; they are the
# red-first tests for this fix pass. ---

import record_check as rc  # noqa: E402


def _head_sha_of(repo):
    import subprocess

    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _bound_bundle(tmp_path, repo=None):
    """A good bundle recorded against a throwaway repo, with its
    revision set to that repo's HEAD and its JUnit reports written:
    the fixture a tree-binding test starts from."""
    if repo is None:
        repo = _recording_repo(tmp_path)
    b = _good_bundle()
    _recorded_bundle(b, tmp_path, repo=repo)
    b["revision"] = _head_sha_of(repo)
    _write_junit_reports(b, tmp_path)
    _write_test_report(b, tmp_path)
    return b, repo


def _reforge(check, bundle_dir):
    """Recompute capture_sha256 after editing a recorded check's
    fields, so the binding hash still recomputes and only the
    edited field is under test."""
    import hashlib

    bundle_dir = Path(bundle_dir)
    stdout_hash = hashlib.sha256((bundle_dir / check["stdout_artifact"]).read_bytes()).hexdigest()
    stderr_hash = hashlib.sha256((bundle_dir / check["stderr_artifact"]).read_bytes()).hexdigest()
    check["capture_sha256"] = rc.capture_binding_hash(
        command_argv=check["command_argv"],
        shell=check["shell"],
        cwd=check["cwd"],
        started_at=check["started_at"],
        finished_at=check["finished_at"],
        exit_code=check["exit_code"],
        stdout_sha256=stdout_hash,
        stderr_sha256=stderr_hash,
        content_digest=check["content_digest"],
        revision=check["revision"],
    )


def _retime(bundle, bundle_dir, started, finished):
    """Move every recorded timestamp, reforging the capture hashes
    so a timestamp edit is the only difference under test."""
    for c in bundle.get("checks") or []:
        c["started_at"] = started
        c["finished_at"] = finished
        _reforge(c, bundle_dir)
    ff = bundle.get("fail_first")
    if isinstance(ff, dict) and isinstance(ff.get("red_check"), dict):
        red = ff["red_check"]
        red["started_at"] = started
        red["finished_at"] = finished
        _reforge(red, bundle_dir)


def _second_commit(repo):
    """A second commit on the recording repo; returns its HEAD."""
    (repo / "sample.py").write_text("x = 3\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "second")
    return _head_sha_of(repo)


def _run_cli_in(bundle_path, cwd, extra=()):
    """Run the validator CLI on a bundle file, from `cwd`."""
    import subprocess

    validator = Path(__file__).resolve().parent / "validate_evidence.py"
    return subprocess.run(
        [sys.executable, str(validator), str(bundle_path), *extra],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=60,
    )


def test_tree_binding_passes_with_matching_repo(tmp_path):
    # FND-004: a bundle recorded against a repo validates when the
    # validator is given that repo: every check revision equals the
    # bundle revision and every digest recomputes at it.
    b, repo = _bound_bundle(tmp_path)
    assert ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo) == []


def test_tree_binding_rejects_forged_bundle_revision(tmp_path):
    # FND-004 (a): the bundle revision swapped to another SHA —
    # the checks were recorded on the real HEAD.
    b, repo = _bound_bundle(tmp_path)
    b["revision"] = "f" * 40
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert any("revision" in p for p in problems)


def test_tree_binding_rejects_forged_check_revision(tmp_path):
    # FND-004: a check revision forged to a different real commit,
    # with the capture hash recomputed consistently — the capture
    # recompute passes, the tree binding must not.
    b, repo = _bound_bundle(tmp_path)
    head2 = _second_commit(repo)
    b["checks"][0]["revision"] = head2
    _reforge(b["checks"][0], tmp_path)
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert any("revision" in p for p in problems)


def test_tree_binding_rejects_forged_check_digest(tmp_path):
    # FND-004 (c): a check digest forged with a consistently
    # recomputed capture hash — the digest must equal the digest
    # recomputed from the tree at the bundle revision.
    b, repo = _bound_bundle(tmp_path)
    b["checks"][0]["content_digest"] = "sha256:" + "f" * 64
    _reforge(b["checks"][0], tmp_path)
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert any("content_digest" in p for p in problems)


def test_tree_binding_rejects_wrong_expected_revision(tmp_path):
    # FND-004: --expected-revision names the revision the caller
    # expects; a bundle for another revision must fail.
    b, repo = _bound_bundle(tmp_path)
    head2 = _second_commit(repo)
    problems = ve.validate_bundle(
        b, _SCHEMA, bundle_dir=tmp_path, repo=repo, expected_revision=head2
    )
    assert any("expected_revision" in p or "revision" in p for p in problems)


def test_tree_binding_expected_revision_matching_passes(tmp_path):
    # FND-004 control: the expected revision equal to the bundle
    # revision passes.
    b, repo = _bound_bundle(tmp_path)
    assert (
        ve.validate_bundle(
            b, _SCHEMA, bundle_dir=tmp_path, repo=repo, expected_revision=b["revision"]
        )
        == []
    )


def test_tree_binding_dirty_diff_passes_and_wrong_diff_fails(tmp_path):
    # FND-004 (d): a dirty-tree PASS binds the diff: the recorded
    # sha256 of `git diff HEAD` validates, an invented one does not.
    import hashlib
    import subprocess

    b, repo = _bound_bundle(tmp_path)
    # Round 9, FND-002 changed the recording repo's fix commit to
    # sample.py "x = 2", so dirtying the tree needs content that
    # differs from HEAD — writing "x = 2" is a no-op now.
    (repo / "sample.py").write_text("x = 99\n", encoding="utf-8")
    diff = subprocess.run(
        ["git", "-C", str(repo), "diff", "HEAD"], check=True, capture_output=True
    ).stdout
    diff_hash = hashlib.sha256(diff).hexdigest()
    b["working_tree_state"] = "dirty"
    b["dirty_files"] = ["sample.py"]
    b["revision"] = "working-tree"
    b["diff_sha256"] = diff_hash
    assert ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo) == []
    assert (
        ve.validate_bundle(
            b,
            _SCHEMA,
            bundle_dir=tmp_path,
            repo=repo,
            expected_diff_sha256=diff_hash,
        )
        == []
    )
    b["diff_sha256"] = "0" * 64
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert any("diff" in p for p in problems)
    b["diff_sha256"] = diff_hash
    problems = ve.validate_bundle(
        b, _SCHEMA, bundle_dir=tmp_path, repo=repo, expected_diff_sha256="0" * 64
    )
    assert any("diff" in p for p in problems)


def test_tree_binding_repo_none_is_legacy(tmp_path):
    # FND-004: validate_bundle with repo=None performs no tree
    # binding (legacy/in-process behaviour, documented): a forged
    # bundle revision still validates in-process.
    b, repo = _bound_bundle(tmp_path)
    b["revision"] = "f" * 40
    assert ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path) == []


def test_tree_binding_no_repo_fails_closed_via_cli(tmp_path):
    # FND-004: with no repo present, a PASS bundle claiming a
    # revision FAILS CLOSED — never silently passes. The CLI
    # defaults --repo to cwd, so a non-repo cwd fails it; an
    # explicit --repo naming a non-repo fails it too.
    import json

    b, repo = _bound_bundle(tmp_path)
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(b), encoding="utf-8")
    plain = tmp_path / "plain"
    plain.mkdir()
    proc = _run_cli_in(bundle_path, plain)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "repo" in proc.stdout.lower() or "repo" in proc.stderr.lower()
    proc = _run_cli_in(bundle_path, tmp_path, extra=("--repo", str(plain)))
    assert proc.returncode == 1, proc.stdout + proc.stderr


def test_tree_binding_cli_repo_and_expected_revision(tmp_path):
    # FND-004: the CLI --repo / --expected-revision flags.
    import json

    b, repo = _bound_bundle(tmp_path)
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(b), encoding="utf-8")
    proc = _run_cli_in(bundle_path, tmp_path, extra=("--repo", str(repo)))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    head2 = _second_commit(repo)
    proc = _run_cli_in(
        bundle_path, tmp_path, extra=("--repo", str(repo), "--expected-revision", head2)
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "revision" in proc.stdout


def test_tree_binding_rejects_check_cwd_outside_repo(tmp_path):
    # FND-001 (round 9): the validator mirrors the recorder's
    # containment — a check whose cwd is a scratch directory that
    # still exists, outside the repo the bundle is bound to, is
    # rejected even when its revision, digest, and capture hash all
    # recompute (the capture was forged consistently, the run was
    # not on this tree).
    b, repo = _bound_bundle(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    b["checks"][0]["cwd"] = str(scratch)
    _reforge(b["checks"][0], tmp_path)
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert any("cwd" in p and "not inside" in p for p in problems), problems


def test_tree_binding_accepts_check_cwd_in_worktree(tmp_path):
    # FND-001 control: a check recorded in a live worktree of the
    # repo validates against that repo — a worktree shares the
    # repo's git common dir, so it is the same repo, not another.
    import subprocess

    b, repo = _bound_bundle(tmp_path)
    wt = tmp_path / "wt"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", str(wt), "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    b["checks"][0]["cwd"] = str(wt)
    _reforge(b["checks"][0], tmp_path)
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert problems == [], problems


def test_tree_binding_ignores_missing_check_cwd(tmp_path):
    # FND-001: a check whose cwd no longer exists (a worktree
    # removed after recording, as SKILL.md step 3 instructs) cannot
    # be checked this way — the record-time containment is the
    # control there, and the revision/digest binding still applies.
    # The bundle must still validate on its other bindings.
    b, repo = _bound_bundle(tmp_path)
    b["checks"][0]["cwd"] = str(tmp_path / "gone-worktree")
    _reforge(b["checks"][0], tmp_path)
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert problems == [], problems


def _re_record_red_at_head(bundle, directory, repo):
    """Re-record the red run in the main repo at HEAD (the fix
    commit) instead of the worktree at the base: the mislabelled
    shape (round 9, FND-002) — the run happened on the pre-fix
    tree, but the capture claims the fixed tree."""
    fragment = _run_record_check(directory, "red_check", _RED_COMMAND, repo)
    fragment.pop("name", None)
    red = bundle["fail_first"]["red_check"]
    red.update(fragment)
    red.pop("stdout_text", None)
    return fragment


def test_tree_binding_rejects_red_check_at_bundle_revision(tmp_path):
    # FND-002 (round 9): the mislabelled shape — the red run is
    # recorded with --repo at the fixed tree, so its revision and
    # digest claim the fixed tree while the test it shows failing
    # ran on the pre-fix tree. A red run on the bundle revision
    # itself cannot show the test failing before the fix: for a
    # committed fix the red revision must be a strict ancestor of
    # the bundle revision (the base).
    b, repo = _bound_bundle(tmp_path)
    _re_record_red_at_head(b, tmp_path, repo)
    del b["fail_first"]["base_revision"]
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert any("red_check" in p and "bundle revision" in p for p in problems), problems


def test_tree_binding_rejects_red_check_on_wrong_base(tmp_path):
    # FND-002: a red run on a revision that is not an ancestor of
    # the bundle revision is not a red for this fix — here a later
    # commit (a descendant), forged with a consistent capture hash.
    b, repo = _bound_bundle(tmp_path)
    head2 = _second_commit(repo)
    b["fail_first"]["red_check"]["revision"] = head2
    _reforge(b["fail_first"]["red_check"], tmp_path)
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert any("red_check" in p and "ancestor" in p for p in problems), problems


def test_tree_binding_rejects_forged_red_digest(tmp_path):
    # FND-002: the red run's content digest must equal the digest
    # recomputed from the tree at the RED revision — a digest
    # forged with a consistent capture hash must not validate.
    b, repo = _bound_bundle(tmp_path)
    b["fail_first"]["red_check"]["content_digest"] = "sha256:" + "f" * 64
    _reforge(b["fail_first"]["red_check"], tmp_path)
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert any("red_check" in p and "content_digest" in p for p in problems), problems


def test_tree_binding_rejects_red_test_file_mismatch(tmp_path):
    # FND-002: fail_first.test_file_sha256 is the test file as a
    # material (in-toto): it must match the test file in the green
    # tree, so the red run ran the same test that passes green.
    b, repo = _bound_bundle(tmp_path)
    b["fail_first"]["test_file_sha256"] = "0" * 64
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert any("test_file_sha256" in p for p in problems), problems


def test_tree_binding_accepts_crlf_test_file_sha256(tmp_path):
    # CI fix round 4 (0.10.6, windows job): a bundle recorded on
    # Windows failed with "the red run did not run the test that
    # passes green" — the fixture writes the test file with
    # write_text, which translates \n to \r\n on Windows, so the
    # recorded sha256 is of the CRLF bytes while the green tree
    # holds the LF blob (git normalises on commit). The recorded
    # hash must match the green file under git's line-ending
    # canonicalisation: the LF hash or the CRLF hash of the same
    # file. A hash of different content still fails (see
    # test_tree_binding_rejects_red_test_file_mismatch).
    import hashlib

    b, repo = _bound_bundle(tmp_path)
    green = (repo / "tests" / "test_capture.py").read_bytes()
    # CI fix round 5 (0.10.7, windows job): the working-tree file
    # is CRLF on Windows (write_text translates LF->CRLF), so
    # expanding the raw read would turn each CRLF into CRCRLF
    # (\r\r\n) and hash the wrong bytes — the exact hash the
    # Windows job recorded (66d80570...). Normalise to LF first,
    # then expand: the CRLF form of the green-tree file.
    lf = green.replace(b"\r\n", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    assert crlf != lf  # the fixture file is LF; the CRLF form differs
    b["fail_first"]["test_file_sha256"] = hashlib.sha256(crlf).hexdigest()
    assert ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo) == []


def test_tree_binding_rejects_crcrlf_test_file_sha256(tmp_path):
    # CI fix round 5 (0.10.7, windows job): the round-4 test built
    # the CRLF form by expanding the working-tree read, which on
    # Windows is already CRLF — so it hashed CRCRLF (\r\r\n) bytes
    # instead. The validator's line-ending equivalence class is
    # exactly {LF, CRLF} (see _line_ending_hashes): a CRCRLF hash
    # is a hash of different content and must still fail, or the
    # round-4 fix would have loosened the material binding instead
    # of canonicalising it.
    import hashlib

    b, repo = _bound_bundle(tmp_path)
    green = (repo / "tests" / "test_capture.py").read_bytes()
    lf = green.replace(b"\r\n", b"\n")
    crcrlf = lf.replace(b"\n", b"\r\n").replace(b"\n", b"\r\n")
    assert crcrlf != lf.replace(b"\n", b"\r\n")
    b["fail_first"]["test_file_sha256"] = hashlib.sha256(crcrlf).hexdigest()
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert any("test_file_sha256" in p for p in problems), problems


def test_tree_binding_requires_red_test_file_sha256(tmp_path):
    # FND-002: a PASS for a behaviour change with method worktree
    # must record the test file's sha256 — without it the red run
    # is not tied to any test file at all.
    b, repo = _bound_bundle(tmp_path)
    del b["fail_first"]["test_file_sha256"]
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert any("test_file_sha256" in p for p in problems), problems


def test_tree_binding_rejects_red_base_mismatch(tmp_path):
    # FND-002: when fail_first.base_revision is declared, the red
    # run must have run on it — a red on another revision than the
    # declared base is a misbound red.
    b, repo = _bound_bundle(tmp_path)
    head2 = _second_commit(repo)
    b["fail_first"]["base_revision"] = head2
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert any("base_revision" in p for p in problems), problems


def _revert_bundle(tmp_path):
    """A bundle whose fail-first proof used revert-at-smallest-scope:
    the red run is recorded in the main repo at HEAD (the fix
    commit — the revert is a dirty-tree change, and the content
    digest covers committed content only), with red_diff_sha256 the
    sha256 of `git diff HEAD` in the reverted tree. Returns
    (bundle, repo, red_diff_sha256)."""
    import hashlib
    import subprocess

    b, repo = _bound_bundle(tmp_path)
    b["fail_first"]["method"] = "revert-at-smallest-scope"
    _re_record_red_at_head(b, tmp_path, repo)
    (repo / "sample.py").write_text("x = 1\n", encoding="utf-8")
    diff = subprocess.run(
        ["git", "-C", str(repo), "diff", "HEAD"], check=True, capture_output=True
    ).stdout
    red_diff = hashlib.sha256(diff).hexdigest()
    (repo / "sample.py").write_text("x = 2\n", encoding="utf-8")
    b["fail_first"]["red_diff_sha256"] = red_diff
    return b, repo, red_diff


def test_tree_binding_revert_shape_passes_with_red_diff(tmp_path):
    # FND-002: the revert shape is the other legitimate red — the
    # red run sits on the bundle revision (the revert is dirty-tree
    # only) and binds via the recorded red_diff_sha256.
    b, repo, _ = _revert_bundle(tmp_path)
    assert ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo) == []


def test_tree_binding_revert_requires_red_diff(tmp_path):
    # FND-002: a PASS with method revert-at-smallest-scope and no
    # recorded red_diff_sha256 has no binding for its red at all.
    b, repo, _ = _revert_bundle(tmp_path)
    del b["fail_first"]["red_diff_sha256"]
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert any("red_diff_sha256" in p for p in problems), problems


def test_tree_binding_rejects_clean_claim_on_dirty_tree(tmp_path):
    # F1 (friend's review): the validator recomputes the working-tree
    # state from git instead of trusting the bundle's claim — a
    # bundle claiming "clean" on a tree with tracked modifications
    # is rejected, whatever it claims.
    b, repo = _bound_bundle(tmp_path)
    (repo / "sample.py").write_text("x = 99\n", encoding="utf-8")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert any("clean" in p and "dirty" in p for p in problems), problems


def test_tree_binding_rejects_pass_with_untracked_files(tmp_path):
    # F1: `git diff HEAD` does not cover untracked files, so a PASS
    # filed while untracked files exist in the repo is not bound to
    # them — including a new fix file the agent forgot to commit.
    b, repo = _bound_bundle(tmp_path)
    (repo / "new_module.py").write_text("y = 1\n", encoding="utf-8")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert any("untracked" in p for p in problems), problems


def test_tree_binding_rejects_dirty_claim_on_clean_tree(tmp_path):
    # F1 (mirror): a bundle claiming "dirty" on a tree that is
    # actually clean is a false state claim too — the recorded diff
    # cannot be the diff of a clean tree.
    b, repo = _bound_bundle(tmp_path)
    b["working_tree_state"] = "dirty"
    b["dirty_files"] = ["sample.py"]
    b["diff_sha256"] = "0" * 64
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo)
    assert any("dirty" in p and "clean" in p for p in problems), problems


def test_tree_binding_untracked_files_in_bundle_dir_do_not_block(tmp_path):
    # F1: the bundle's own artifacts (captures, reports) are written
    # into the bundle directory during verification, so untracked
    # files inside the bundle directory do not block a PASS — they
    # are verified separately, by their sha256s. The bundle dir here
    # is inside the repo; the red worktree is removed first, as
    # SKILL.md step 3 instructs, so it is not an untracked leftover.
    import subprocess

    repo = _recording_repo(tmp_path)
    bundle_dir = repo / "evidence"
    bundle_dir.mkdir()
    b = _good_bundle()
    _recorded_bundle(b, bundle_dir, repo=repo)
    b["revision"] = _head_sha_of(repo)
    wt = bundle_dir.parent / (bundle_dir.name + "-worktree")
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)],
        check=True,
        capture_output=True,
        text=True,
    )
    _write_junit_reports(b, bundle_dir)
    _write_test_report(b, bundle_dir)
    assert ve.validate_bundle(b, _SCHEMA, bundle_dir=bundle_dir, repo=repo) == []


def test_tree_binding_verification_workspace_is_not_dirt(tmp_path):
    # F1: the validator's dirt rule and the state machine's dirt
    # gate agree on what "dirty" means (state.py _tree_is_dirty,
    # F-07): untracked files where recording verification itself
    # writes — .orcinus/ and docs/verification/ — are not dirt,
    # so a PASS validates while the state file and another bundle
    # sit uncommitted there.
    b, repo = _bound_bundle(tmp_path)
    (repo / ".orcinus").mkdir(exist_ok=True)
    (repo / ".orcinus" / "state.json").write_text("{}\n", encoding="utf-8")
    (repo / "docs" / "verification").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "verification" / "other.json").write_text("{}\n", encoding="utf-8")
    assert ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path, repo=repo) == []


def test_test_gate_without_junit_report_fails(tmp_path):
    # FND-005: a PASS with a required test gate and no JUnit report
    # is a vacuous pass — a command printing "no tests ran" used to
    # validate.
    b, repo = _bound_bundle(tmp_path)
    del b["test_report"]
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("test_report" in p for p in problems)


def _test_report_with_cases(bundle, directory, cases):
    """Replace the bundle's test_report with a report for `cases`."""
    import hashlib

    directory = Path(directory)
    data = _junit_xml(cases)
    (directory / "test-report.xml").write_bytes(data)
    bundle["test_report"] = {
        "artifact": "test-report.xml",
        "sha256": hashlib.sha256(data).hexdigest(),
        "format": "junit-xml",
    }


def test_test_gate_with_zero_test_report_fails(tmp_path):
    # FND-005: a JUnit report with zero tests is not a test run.
    b, repo = _bound_bundle(tmp_path)
    _test_report_with_cases(b, tmp_path, [])
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("test_report" in p for p in problems)


def test_test_gate_with_all_skipped_report_fails(tmp_path):
    # FND-005: an all-skipped suite ran no test — passed>0 is
    # required, not just tests>0.
    b, repo = _bound_bundle(tmp_path)
    _test_report_with_cases(b, tmp_path, [(_CANONICAL_CLASSNAME, _CANONICAL_NAME, "skipped")])
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("test_report" in p for p in problems)


def test_test_gate_with_failing_only_report_fails(tmp_path):
    # FND-005: a report with tests but zero passed is not a passing
    # gate (the check itself would already be FAIL, but the report
    # rule must say so too).
    b, repo = _bound_bundle(tmp_path)
    _test_report_with_cases(b, tmp_path, [(_CANONICAL_CLASSNAME, _CANONICAL_NAME, "failed")])
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("test_report" in p for p in problems)


def test_test_gate_report_hash_mismatch_fails(tmp_path):
    # FND-005: the report artifact must match its recorded sha256.
    b, repo = _bound_bundle(tmp_path)
    (tmp_path / b["test_report"]["artifact"]).write_bytes(b"tampered")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("test_report" in p for p in problems)


def test_test_gate_report_not_required_when_verdict_not_pass(tmp_path):
    # FND-005: the report rule is a PASS rule, not a validity rule —
    # an honest FAIL bundle with a required test gate and no report
    # is still a valid bundle.
    b = _good_bundle()
    b["verdict"] = "FAIL"
    b["checks"][0]["verdict"] = "FAIL"
    b["checks"][0]["exit_code"] = 1
    assert _problems(b) == []


def test_test_report_artifact_not_in_test_argv_fails(tmp_path):
    # FND-003 (round 11): the JUnit report must be the file the
    # recorded test command wrote — a report whose path never
    # appears in the test check's argv is not that run's report,
    # however well-formed the XML is. The counts agree here (2
    # passed in both), so the argv rule is the only reason to
    # reject.
    import hashlib

    b, repo = _bound_bundle(tmp_path)
    _fragment, _captures, data = _cached_test_capture()
    (tmp_path / "other.xml").write_bytes(data)
    b["test_report"] = {
        "artifact": "other.xml",
        "sha256": hashlib.sha256(data).hexdigest(),
        "format": "junit-xml",
    }
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("test_report" in p and "command_argv" in p for p in problems), problems


def test_test_report_counts_disagree_with_stdout_fails(tmp_path):
    # FND-003: the JUnit counts must agree with the recorded stdout
    # summary — a report listing 1 passed for a run whose stdout
    # says "2 passed" is not that run's report.
    b, repo = _bound_bundle(tmp_path)
    _test_report_with_cases(b, tmp_path, [(_CANONICAL_CLASSNAME, _CANONICAL_NAME, "passed")])
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("test_report" in p and "stdout" in p for p in problems), problems


def test_test_report_stdout_claiming_more_passed_fails(tmp_path):
    # FND-003, the other direction: the stdout summary claims 45
    # passed while the report lists 2. The stdout artifact is
    # rewritten and the capture hash reforged, so the count
    # mismatch is the only difference under test.
    import hashlib

    b, repo = _bound_bundle(tmp_path)
    check = b["checks"][0]
    stdout = (
        "tests/test_capture.py::test_capture_persian_only PASSED\n"
        "tests/test_capture.py::TestCapture::test_capture_persian_only PASSED\n"
        "============================== 45 passed in 0.42s ===============================\n"
    )
    (tmp_path / check["stdout_artifact"]).write_bytes(stdout.encode())
    check["stdout_sha256"] = hashlib.sha256(stdout.encode()).hexdigest()
    _reforge(check, tmp_path)
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("test_report" in p and "stdout" in p for p in problems), problems


def test_test_report_junitxml_equals_form_passes(tmp_path):
    # FND-003 control: the `--junitxml=<path>` spelling (one token)
    # names the report just as `--junitxml <path>` (two tokens)
    # does — a matching bundle recorded that way still validates.
    b = _good_bundle()
    _recorded_bundle(
        b,
        tmp_path,
        commands={
            "test": [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_capture.py",
                "-v",
                "--junitxml=" + str(tmp_path / "green.xml"),
            ],
        },
    )
    assert _problems(b, tmp_path) == []


def test_argv_mentions_path_shapes():
    # FND-003, the argv rule directly: both --junitxml spellings,
    # absolute and ./ paths, a nested report path, and the
    # non-matches. A shell string counts only when a segment that
    # runs a runner names the path — `echo green.xml` is a mention,
    # not a write. A non-runner argv naming the path passes this
    # rule alone; the runner rule is what rejects that shape.
    cases = [
        (["pytest", "--junitxml", "green.xml"], "green.xml", True),
        (["pytest", "--junitxml=green.xml"], "green.xml", True),
        (["pytest", "--junitxml", "/tmp/bundle/green.xml"], "green.xml", True),
        (["pytest", "--junitxml", "./green.xml"], "green.xml", True),
        (["pytest", "--junitxml", "/tmp/bundle/reports/test.xml"], "reports/test.xml", True),
        (["pytest", "--junitxml", "test.xml"], "reports/test.xml", False),
        (["pytest", "--junitxml", "other.xml"], "green.xml", False),
        (["pytest", "--junitxml", "/tmp/bundle/other.xml"], "green.xml", False),
        (["pytest", "tests/test_x.py"], "green.xml", False),
        (["python", "fake.py", "green.xml"], "green.xml", True),
        (["bash", "-c", "pytest --junitxml green.xml"], "green.xml", True),
        (["bash", "-c", "echo green.xml"], "green.xml", False),
        (["bash", "-c", "cd x && python3 -m pytest --junitxml green.xml"], "green.xml", True),
        (["bash", "-c", "echo 'unterminated"], "green.xml", False),
        ([], "green.xml", False),
        (None, "green.xml", False),
    ]
    for argv, artifact, expected in cases:
        assert ve._argv_mentions_path(argv, artifact) is expected, argv


def test_argv_windows_paths():
    # Windows CI (round 11): the good bundle's recorded argv
    # carries drive-letter paths with backslashes and a
    # `python.exe` interpreter — `C:\...\python.exe -m pytest
    # --junitxml C:\...\green.xml`. The helpers must read those
    # the same way they read POSIX argv: the basename split and
    # the `.exe` suffix for the runner match, backslash
    # normalisation for the trailing-components path match.
    win_python = r"C:\hostedtoolcache\windows\Python\3.12.10\x64\python.exe"
    win_report = r"C:\Users\runneradmin\AppData\Local\Temp\x\green.xml"
    assert ve._is_python(win_python) is True
    assert ve._is_python(r"C:\Python312\python3.12.exe") is True
    assert ve._is_python(r"C:\Python312\Scripts\pytest.exe") is False
    assert ve._argv_runner_tool_name([win_python, "-m", "pytest", "-q"]) == "pytest"
    assert ve._argv_runner_tool_name([r"C:\Python312\Scripts\pytest.exe", "-q"]) == "pytest"
    assert ve._argv_runner_tool_name([r"C:\Python312\Scripts\py.test.exe", "-q"]) == "pytest"
    assert (
        ve._invoked_runner_tool_name(
            [win_python, "-m", "pytest", "tests/test_capture.py", "-v", "--junitxml", win_report]
        )
        == "pytest"
    )
    assert ve._invokes_test_runner([win_python, "-m", "pytest", "-q"]) is True
    cases = [
        ([win_python, "-m", "pytest", "--junitxml", win_report], "green.xml", True),
        (["pytest", "--junitxml=" + win_report], "green.xml", True),
        (["pytest", "--junitxml", r"C:\bundle\reports\test.xml"], "reports/test.xml", True),
        (["pytest", "--junitxml", r"C:\bundle\other.xml"], "green.xml", False),
        (["pytest", "--junitxml", r"C:\bundle\green.xml"], "reports/green.xml", False),
    ]
    for argv, artifact, expected in cases:
        assert ve._argv_mentions_path(argv, artifact) is expected, argv


def test_parse_pytest_summary_counts():
    # FND-003, the stdout summary parser directly: the counts
    # pytest prints, a category omitted (zero), warnings and
    # deselected tests (not tests run), "no tests ran", and the
    # shapes left unparsed — no summary line, and xfailed/xpassed,
    # whose JUnit mapping is not established here.
    assert ve._parse_pytest_summary("== 2 passed in 0.02s ==") == (2, 2)
    assert ve._parse_pytest_summary("== 1 failed, 1 passed in 0.12s ==") == (2, 1)
    assert ve._parse_pytest_summary("== 2 passed, 3 skipped in 0.12s ==") == (5, 2)
    assert ve._parse_pytest_summary("== 1 failed in 0.12s ==") == (1, 0)
    assert ve._parse_pytest_summary("== 2 passed, 1 warning in 0.02s ==") == (2, 2)
    assert ve._parse_pytest_summary("== 2 passed, 1 deselected in 0.02s ==") == (2, 2)
    assert ve._parse_pytest_summary("== no tests ran in 0.02s ==") == (0, 0)
    assert ve._parse_pytest_summary("tests/x.py::test_y PASSED [100%]\n") is None
    assert ve._parse_pytest_summary("== 1 xfailed, 2 passed in 0.02s ==") is None
    assert ve._parse_pytest_summary("== 1 xpassed, 2 passed in 0.02s ==") is None
    assert ve._parse_pytest_summary("") is None
    assert ve._parse_pytest_summary(None) is None


# Round 11, FND-002: an assertion-free suite passes identically for
# a broken and a correct implementation, so a PASS for a behaviour
# change needs assertion-bearing tests in the changed test files.
# The fixture below is the auditor's repro in miniature: charge()
# returns -1 (wrong) and the tests call it without asserting
# anything — pytest reports 2 passed.
_NO_ASSERT_TEST_SOURCE = (
    "def charge(amount):\n"
    "    return -1\n"
    "\n"
    "\n"
    "def test_capture_persian_only():\n"
    "    charge(100)\n"
    "\n"
    "\n"
    "class TestCapture:\n"
    "    def test_capture_persian_only(self):\n"
    "        charge(100)\n"
)


def _no_assert_bundle(tmp_path):
    """A bound PASS bundle whose only changed test file has no
    assertions: the recording repo's test file is the no-assert
    source above, and files_changed names it."""
    repo = _recording_repo(tmp_path, test_source=_NO_ASSERT_TEST_SOURCE)
    b = _good_bundle()
    _recorded_bundle(b, tmp_path, repo=repo)
    b["revision"] = _head_sha_of(repo)
    b["files_changed"] = ["skills/idea-capture/scripts/capture.py", "tests/test_capture.py"]
    return b, repo


def test_count_assertions_counts_helpers_raises_and_unittest():
    # The counting rule, directly: asserts anywhere in the file
    # (including helpers the tests call), assert* method calls,
    # and pytest.raises / pytest.warns — a bare call counts zero,
    # and an unparsable file counts as None.
    assert ve._count_assertions(b"def helper():\n    assert True\n") == 1
    assert ve._count_assertions(b"def test_x(self):\n    self.assertEqual(1, 1)\n") == 1
    assert (
        ve._count_assertions(b"def test_x():\n    with pytest.raises(ValueError):\n        f()\n")
        == 1
    )
    assert (
        ve._count_assertions(b"def test_x():\n    with pytest.warns(UserWarning):\n        f()\n")
        == 1
    )
    assert ve._count_assertions(b"def test_x():\n    charge(100)\n") == 0
    assert ve._count_assertions(b"def test_x(:\n") is None


def test_assertion_free_changed_tests_fail(tmp_path):
    # FND-002: a behaviour change whose changed test files contain
    # zero assertions is INCOMPLETE, not PASS — the suite cannot
    # distinguish the broken implementation from the correct one.
    b, repo = _no_assert_bundle(tmp_path)
    problems = _problems(b, tmp_path, repo=repo)
    assert any("assertion" in p for p in problems), problems


def test_assertion_bearing_changed_tests_pass(tmp_path):
    # FND-002 control: the same shape with assertion-bearing tests
    # still passes — the rule must not reject a real suite.
    b, repo = _bound_bundle(tmp_path)
    b["files_changed"] = ["skills/idea-capture/scripts/capture.py", "tests/test_capture.py"]
    assert _problems(b, tmp_path, repo=repo) == []


def test_behaviour_change_without_changed_test_files_passes(tmp_path):
    # FND-002: only the changed test files count — a behaviour
    # change that touches no test file is not failed by this rule.
    b, repo = _bound_bundle(tmp_path)
    b["files_changed"] = ["skills/idea-capture/scripts/capture.py"]
    assert _problems(b, tmp_path, repo=repo) == []


def test_docs_only_pass_with_repo_ignores_assertion_rule(tmp_path):
    # FND-002: docs-only / config-only bundles have no behaviour
    # to test, so the assertion rule does not apply to them.
    b = _good_bundle()
    b.pop("fail_first", None)
    b["files_changed"] = ["README.md"]
    b["verification_plan"]["change_type"] = "docs-only"
    b["verification_plan"]["required_gates"] = []
    b["verification_plan"]["not_applicable_gates"] = [
        {"gate": "build", "reason": "Docs-only change; nothing to build."},
        {"gate": "lint", "reason": "Docs-only change; no code to lint."},
        {"gate": "typecheck", "reason": "Docs-only change; nothing to typecheck."},
        {"gate": "test", "reason": "Docs-only change; no behaviour to test."},
    ]
    repo = _recording_repo(tmp_path)
    _recorded_bundle(b, tmp_path, repo=repo)
    b["revision"] = _head_sha_of(repo)
    assert _problems(b, tmp_path, repo=repo) == []


def test_declared_mutation_gate_without_check_fails(tmp_path):
    # FND-002: a plan that declares mutation_gate must be backed by
    # a passing check with the declared name — otherwise the bundle
    # is INCOMPLETE, not PASS.
    b, repo = _bound_bundle(tmp_path)
    b["files_changed"] = ["skills/idea-capture/scripts/capture.py", "tests/test_capture.py"]
    b["verification_plan"]["mutation_gate"] = {"check": "mutation"}
    problems = _problems(b, tmp_path, repo=repo)
    assert any("mutation_gate" in p and "no passing check" in p for p in problems), problems


def test_declared_mutation_gate_with_passing_check_passes(tmp_path):
    # FND-002 control: the declared mutation gate satisfied by a
    # recorded passing check still passes.
    repo = _recording_repo(tmp_path)
    b = _good_bundle()
    b["files_changed"] = ["skills/idea-capture/scripts/capture.py", "tests/test_capture.py"]
    b["verification_plan"]["mutation_gate"] = {"check": "mutation", "min_score": 80}
    b["checks"].append(
        {
            "name": "mutation",
            "command": "python3 -c \"print('mutation score 100.00: 30 mutants, 30 killed')\"",
            "cwd": "/repo",
            "exit_code": 0,
            "verdict": "PASS",
            "tool_version": "mutmut 2.5.0",
            "started_at": "2026-11-06T10:00:13Z",
            "finished_at": "2026-11-06T10:00:14Z",
            "stdout_text": "mutation score 100.00: 30 mutants, 30 killed",
        }
    )
    _recorded_bundle(
        b,
        tmp_path,
        repo=repo,
        commands={
            "mutation": [
                sys.executable,
                "-c",
                "print('mutation score 100.00: 30 mutants, 30 killed')",
            ]
        },
    )
    b["revision"] = _head_sha_of(repo)
    assert _problems(b, tmp_path, repo=repo) == []


def test_future_timestamps_rejected(tmp_path):
    # FND-006: every timestamp in 2099 — checks and red_check —
    # must be rejected, not accepted as the verifier's "now".
    b, repo = _bound_bundle(tmp_path)
    _retime(b, tmp_path, "2099-06-01T10:00:00Z", "2099-06-01T10:00:12Z")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("future" in p for p in problems)


def test_future_red_check_timestamp_rejected(tmp_path):
    # FND-006: the red run's timestamps are checked the same way.
    b, repo = _bound_bundle(tmp_path)
    red = b["fail_first"]["red_check"]
    red["started_at"] = "2099-06-01T10:00:00Z"
    red["finished_at"] = "2099-06-01T10:00:12Z"
    _reforge(red, tmp_path)
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("future" in p and "red_check" in p for p in problems)


def test_future_timestamps_within_tolerance_pass(tmp_path):
    # FND-006: a 5-minute clock-skew tolerance — a run recorded a
    # few minutes ahead of the validator's clock still validates.
    from datetime import datetime, timedelta, timezone

    b, repo = _bound_bundle(tmp_path)
    now = datetime.now(timezone.utc)
    started = (now + timedelta(minutes=4)).isoformat(timespec="microseconds").replace("+00:00", "Z")
    finished = (
        (now + timedelta(minutes=4, seconds=12))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    _retime(b, tmp_path, started, finished)
    assert ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path) == []


def test_future_timestamps_beyond_tolerance_fail(tmp_path):
    # FND-006: beyond the 5-minute tolerance the same run fails.
    from datetime import datetime, timedelta, timezone

    b, repo = _bound_bundle(tmp_path)
    now = datetime.now(timezone.utc)
    started = (now + timedelta(minutes=6)).isoformat(timespec="microseconds").replace("+00:00", "Z")
    finished = (
        (now + timedelta(minutes=6, seconds=12))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    _retime(b, tmp_path, started, finished)
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("future" in p for p in problems)


def test_historical_timestamps_still_valid(tmp_path):
    # FND-006: no lower bound — a bundle recorded in 2000 must keep
    # validating; only the future is rejected.
    b, repo = _bound_bundle(tmp_path)
    _retime(b, tmp_path, "2000-01-01T10:00:00Z", "2000-01-01T10:00:12Z")
    assert ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path) == []


# --- Cloudflare takeaway 1 (round 10, track 1): validator hard limits,
# Windows reserved names, diagnostic escaping, three-verdict findings.
#
# Source: cloudflare/security-audit-skill (MIT),
# skills/security-audit/validate-findings.cjs — LIMITS block, Windows
# reserved-name rejection, unsafe-diagnostic-character escaping, and
# the confirmed / needs_validation / rejected contract. Ported to
# Python (adapted, own-words) where the source is Node; see
# validate_evidence.py for the attribution and the port notes.


def _run_cli_raw(data, suffix=".json"):
    """Run the validator as a subprocess on a temp file holding raw
    `data` (bytes or str). Like _run_cli, but for inputs json.dump
    cannot produce (oversized, invalid UTF-8, symlinked)."""
    import subprocess
    import tempfile

    validator = Path(__file__).resolve().parent / "validate_evidence.py"
    with tempfile.NamedTemporaryFile("wb", suffix=suffix, delete=False) as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        path = f.name
    proc = subprocess.run([sys.executable, str(validator), path], capture_output=True, text=True)
    Path(path).unlink()
    return proc


def test_json_text_nesting_beyond_limit_fails():
    # LIMITS.nestingDepth 64: a 65-deep object is rejected before
    # parsing, and 64-deep is accepted.
    deep = "{" * 65 + "}" * 65
    import pytest

    with pytest.raises(ve.JsonStructureError):
        ve.check_json_text_limits(deep)
    ve.check_json_text_limits("{" * 64 + "}" * 64)


def test_json_text_array_beyond_limit_fails():
    # LIMITS.arrayItems 1000: a 1001-item array is rejected before
    # parsing, and 1000 items are accepted.
    many = "[" + ",".join(["1"] * 1001) + "]"
    import pytest

    with pytest.raises(ve.JsonStructureError):
        ve.check_json_text_limits(many)
    ve.check_json_text_limits("[" + ",".join(["1"] * 1000) + "]")


def test_parsed_bundle_over_array_items_fails():
    # The same array cap on the parsed value: 1001 findings are a
    # limit error, reported before any schema or semantic check.
    b = _good_bundle()
    b["findings"] = [
        {"file": "src/x.ts", "line": 1, "evidence": "e", "severity": "blocking"}
        for _ in range(1001)
    ]
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=None)
    assert any("array limit" in p for p in problems)


def test_parsed_bundle_cyclic_input_fails():
    # A repeated/cyclic object reference cannot come from JSON, but
    # an in-process caller can pass one — and _validate would recurse
    # on it forever. The limit check rejects it first.
    b = _good_bundle()
    b["self"] = b
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=None)
    assert any("cyclic" in p or "repeated" in p for p in problems)


def test_bundle_file_over_byte_cap_fails():
    # LIMITS.inputBytes 5 MiB, enforced while reading (not after):
    # an oversized bundle file is a controlled read error, exit 2,
    # never a traceback and never a half-read bundle.
    import json

    b = _good_bundle()
    b["requirement"] = "x" * (ve.MAX_BUNDLE_BYTES + 1)
    proc = _run_cli_raw(json.dumps(b))
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr
    assert "byte limit" in (proc.stdout + proc.stderr)


def test_bundle_file_symlink_is_refused():
    # The bundle file itself must not be a symlink: the validator
    # reads the named file, not wherever a link points.
    import json
    import subprocess
    import tempfile

    validator = Path(__file__).resolve().parent / "validate_evidence.py"
    with tempfile.TemporaryDirectory() as d:
        real = Path(d) / "real.json"
        real.write_text(json.dumps(_good_bundle()), encoding="utf-8")
        link = Path(d) / "link.json"
        link.symlink_to(real)
        proc = subprocess.run(
            [sys.executable, str(validator), str(link)], capture_output=True, text=True
        )
        assert proc.returncode == 2
        assert "Traceback" not in proc.stderr
        assert "symlink" in (proc.stdout + proc.stderr)


def test_bundle_file_invalid_utf8_fails():
    # Fatal UTF-8 decoding: a bundle that is not valid UTF-8 is a
    # controlled read error, exit 2, never a traceback.
    proc = _run_cli_raw(b'{"schema_version": 6, "\xff": 1}')
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr
    assert "UTF-8" in (proc.stdout + proc.stderr)


def test_validation_errors_capped_at_100():
    # LIMITS.validationErrors 100: a bundle with 150 problems
    # reports exactly 100 — the output stays bounded however many
    # contradictions the bundle holds.
    b = _good_bundle()
    b["findings"] = [{"file": "src/x.ts", "line": 1, "evidence": "e"} for _ in range(150)]
    problems = _problems(b)
    assert len(problems) == ve.MAX_VALIDATION_ERRORS == 100


def test_artifact_windows_reserved_name_fails(tmp_path):
    # A Windows reserved name (con/prn/aux/nul/com1-9/lpt1-9, any
    # case, with any extension) must not be an artifact path: on
    # Windows such a file is a device, not a file in the bundle.
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    for artifact in ("con.stdout", "COM1.log", "logs/nul.txt"):
        (bundle_dir / "con.stdout").write_bytes(b"not in the bundle")
        (bundle_dir / "COM1.log").write_bytes(b"not in the bundle")
        (bundle_dir / "logs").mkdir(exist_ok=True)
        (bundle_dir / "logs" / "nul.txt").write_bytes(b"not in the bundle")
        b = _artifact_bundle(bundle_dir, artifact, b"not in the bundle")
        problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=bundle_dir)
        assert any("reserved" in p for p in problems), artifact
    # A name that merely starts with a reserved stem is fine.
    b = _artifact_bundle(bundle_dir, "contest.log", b"not in the bundle")
    (bundle_dir / "contest.log").write_bytes(b"not in the bundle")
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=bundle_dir)
    assert not any("reserved" in p for p in problems)


def test_diagnostic_escapes_unsafe_characters():
    # Unsafe diagnostic characters (control, format, surrogate,
    # line/paragraph separator, default-ignorable) are escaped in
    # problem strings: a hostile bundle must not smuggle terminal
    # control or bidi-override characters into validator output.
    escaped = ve.escape_unsafe_diagnostic_characters("a\u202eb\x01c")
    assert escaped == "a\\u202eb\\u0001c"
    assert "\u202e" not in escaped and "\x01" not in escaped
    b = _good_bundle()
    b["checks"][0]["command"] = "echo \u202e fake-pass"
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=None)
    assert problems
    assert not any("\u202e" in p for p in problems)
    assert any("\\u202e" in p for p in problems)


def _needs_validation_finding(**extra):
    finding = {
        "file": "src/auth.ts",
        "line": 12,
        "evidence": "the deployed config is not visible from source",
        "verdict": "needs_validation",
        "unresolved": "whether the deployed config enables the legacy fallback",
    }
    finding.update(extra)
    return finding


def test_needs_validation_finding_is_valid_but_incomplete():
    # The three-verdict contract: a needs_validation finding carries
    # the exact unresolved fact and NO severity, and it makes the
    # bundle INCOMPLETE — never a pass, never a failure.
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    b["findings"] = [_needs_validation_finding()]
    assert ve.expected_verdict(b) == "INCOMPLETE"
    assert _problems(b) == []


def test_needs_validation_finding_with_severity_fails():
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    b["findings"] = [_needs_validation_finding(severity="blocking")]
    problems = _problems(b)
    assert any("needs_validation" in p and "severity" in p for p in problems)


def test_needs_validation_finding_without_unresolved_fact_fails():
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    finding = _needs_validation_finding()
    del finding["unresolved"]
    b["findings"] = [finding]
    problems = _problems(b)
    assert any("needs_validation" in p and "unresolved" in p for p in problems)


def test_needs_validation_finding_forces_incomplete_not_pass():
    # A bundle that claims PASS while holding an unvalidated finding
    # is rejected, and the finding cannot be counted as a pass.
    b = _good_bundle()
    b["findings"] = [_needs_validation_finding()]
    assert ve.expected_verdict(b) == "INCOMPLETE"
    problems = _problems(b)
    assert any("needs_validation" in p for p in problems)


def test_needs_validation_security_finding_is_not_blocking():
    # An unvalidated candidate is not a confirmed finding: even a
    # suspected security issue filed as needs_validation forces
    # INCOMPLETE, not FAIL — and filing it that way gains no PASS,
    # so the auto-blocking rule cannot be dodged into one.
    b = _good_bundle()
    b["findings"] = [_needs_validation_finding(category="security")]
    assert ve.expected_verdict(b) == "INCOMPLETE"


def test_rejected_finding_is_valid_without_severity(tmp_path):
    # A rejected finding records a disproved candidate: no severity,
    # a reason, and it changes no verdict on its own — a PASS bundle
    # carrying one still passes.
    b = _good_bundle()
    b["findings"] = [
        {
            "file": "src/auth.ts",
            "line": 12,
            "evidence": "the sink is behind an allowlist check",
            "verdict": "rejected",
            "reason": "source shows the sink unreachable without auth",
        }
    ]
    assert ve.expected_verdict(b) == "PASS"
    _recorded_bundle(b, tmp_path)
    assert _problems(b, tmp_path) == []


def test_rejected_finding_with_severity_fails():
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    b["findings"] = [
        {
            "file": "src/auth.ts",
            "line": 12,
            "evidence": "e",
            "verdict": "rejected",
            "reason": "r",
            "severity": "blocking",
        }
    ]
    problems = _problems(b)
    assert any("rejected" in p and "severity" in p for p in problems)


def test_rejected_finding_without_reason_fails():
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    b["findings"] = [{"file": "src/auth.ts", "line": 12, "evidence": "e", "verdict": "rejected"}]
    problems = _problems(b)
    assert any("rejected" in p and "reason" in p for p in problems)


def test_confirmed_finding_must_not_carry_unresolved_or_reason():
    # The forbidden-field lists, adapted: a confirmed finding must
    # not smuggle in the needs_validation / rejected fields.
    b = _good_bundle()
    b["verdict"] = "INCOMPLETE"
    b["findings"] = [
        {
            "file": "src/x.ts",
            "line": 1,
            "evidence": "e",
            "severity": "blocking",
            "unresolved": "something still open",
        }
    ]
    problems = _problems(b)
    assert any("confirmed" in p and "unresolved" in p for p in problems)


# --- Round-11 regression tests (FND-001).
# A `test` gate whose recorded command never runs a test must not
# validate as PASS. The first test was written red-first: it failed
# on the unpatched validator (the lying bundle validated clean) and
# passes with the runner rule. ---

# The lying test runner: prints a pytest-shaped summary and writes a
# fabricated JUnit report, but never runs a test.
_LIAR_PYTEST = '''"""A lying test runner: prints a pytest-shaped summary and writes
a fabricated JUnit report, but never runs a test."""
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(
    '<?xml version="1.0" encoding="utf-8"?>'
    '<testsuites><testsuite name="pytest" tests="1">'
    '<testcase classname="tests.test_capture" '
    'name="test_capture_persian_only" time="0.01" />'
    "</testsuite></testsuites>",
    encoding="utf-8",
)
print("tests/test_capture.py::test_capture_persian_only passed; 45 passed in 0.42s")
'''


def test_lying_test_gate_is_rejected(tmp_path):
    # FND-001 (round 11, High): a `test` gate recorded from a command
    # that never runs a test must not validate as PASS, however clean
    # its exit code and however well-formed its JUnit looks. The liar
    # is recorded through the genuine record_check.py, exactly as the
    # attack does it, and the fabricated JUnit it writes is the
    # bundle's green_report and test_report — so the only thing
    # standing between this bundle and PASS is the runner rule.
    import hashlib

    liar = tmp_path / "fake_pytest.py"
    liar.write_text(_LIAR_PYTEST, encoding="utf-8")
    b = _good_bundle()
    _recorded_bundle(
        b,
        tmp_path,
        commands={
            "test": [sys.executable, str(liar), str(tmp_path / "green.xml")],
        },
    )
    green_data = (tmp_path / "green.xml").read_bytes()
    red_data = _junit_xml([(_CANONICAL_CLASSNAME, _CANONICAL_NAME, "failed")])
    (tmp_path / "red.xml").write_bytes(red_data)
    b["fail_first"]["red_report"] = {
        "artifact": "red.xml",
        "sha256": hashlib.sha256(red_data).hexdigest(),
        "format": "junit-xml",
    }
    b["fail_first"]["green_report"] = {
        "artifact": "green.xml",
        "sha256": hashlib.sha256(green_data).hexdigest(),
        "format": "junit-xml",
    }
    b["test_report"] = {
        "artifact": "green.xml",
        "sha256": hashlib.sha256(green_data).hexdigest(),
        "format": "junit-xml",
    }
    problems = ve.validate_bundle(b, _SCHEMA, bundle_dir=tmp_path)
    assert any("test runner" in p for p in problems), problems


def test_tool_version_naming_another_runner_fails(tmp_path):
    # FND-001, tool_version recommendation (round 11): a PASS whose
    # test gate ran pytest but claims "jest 29.0.0" is a
    # self-contradiction. The binding hash does not cover
    # tool_version (ADR 0005), so no reforge is needed to edit it.
    b = _good_bundle()
    _recorded_bundle(b, tmp_path)
    b["checks"][0]["tool_version"] = "jest 29.0.0"
    problems = _problems(b, tmp_path)
    assert any("tool_version" in p and "jest" in p for p in problems), problems


def test_tool_version_naming_the_interpreter_passes(tmp_path):
    # FND-001, tool_version narrowing: an agent may honestly record
    # the interpreter version ("python 3.12.3") for a `python -m
    # pytest` run — "python" names no runner, so the rule never
    # fires on it. This pins the narrowing the repo's own
    # test_record_check fixture relies on.
    b = _good_bundle()
    _recorded_bundle(b, tmp_path)
    b["checks"][0]["tool_version"] = "python 3.12.3"
    assert _problems(b, tmp_path) == []


def test_tool_version_matching_the_runner_passes(tmp_path):
    # FND-001, tool_version control: a tool_version naming the
    # runner that ran the gate validates.
    b = _good_bundle()
    _recorded_bundle(b, tmp_path)
    b["checks"][0]["tool_version"] = "pytest 9.0.3"
    assert _problems(b, tmp_path) == []


def test_invoked_runner_tool_name_mapping():
    # FND-001, tool_version mapping: `python -m pytest` names
    # pytest, not python; `./gradlew test` names gradle; `py.test`
    # is pytest's old binary name; a fake script names nothing.
    cases = [
        (["python3", "-m", "pytest", "-q"], "pytest"),
        (["python3", "-m", "unittest", "-v"], "unittest"),
        (["pytest", "-q"], "pytest"),
        (["py.test", "-q"], "pytest"),
        (["./gradlew", "test"], "gradle"),
        (["mvn", "test"], "mvn"),
        (["go", "test", "./..."], "go"),
        (["cargo", "nextest", "run"], "cargo"),
        (["npx", "jest"], "jest"),
        (["node", "--test"], "node"),
        (["bash", "-c", "python3 -m pytest -q"], "pytest"),
        (["bash", "-c", "echo pytest"], None),
        (["python3", "tools/fake_pytest.py"], None),
        ([], None),
    ]
    for argv, expected in cases:
        assert ve._invoked_runner_tool_name(argv) == expected, argv


def test_invokes_test_runner_shell_string_must_run_a_runner():
    # FND-001 hardening (round 11): the auditor's patch accepted any
    # `sh -c` / `bash -c` string merely mentioning a runner token
    # (`bash -c "echo pytest"` passed). A shell string must be parsed
    # and a segment must actually invoke a runner as a command.
    cases = [
        # (argv, expected)
        (["bash", "-c", "echo pytest"], False),
        (["bash", "-c", "python3 -m pytest -q"], True),
        (["bash", "-c", "cd x && python3 -m pytest -q"], True),
        (["bash", "-c", "echo pytest && true"], False),
        (["bash", "-c", "pytest -q; echo done"], True),
        (["bash", "-c", "pytest -q || ruff check"], True),
        (["sh", "-c", "echo 'pytest'"], False),
        (["bash", "-c", "echo 'unterminated"], False),
        (["bash", "-c", ""], False),
        (["bash", "-c"], False),
        (["python3", "tools/fake_pytest.py"], False),
        (["python3", "-m", "pytest", "-q"], True),
        (["python3", "-m", "unittest", "-v"], True),
        (["python3", "-m", "mypy", "."], False),
        (["python3.11", "-m", "pytest", "-q"], True),
        (["/usr/bin/python3", "-m", "pytest", "-q"], True),
        (["/usr/local/bin/pytest", "-q"], True),
        (["python3", "script.py", "-m", "pytest"], False),
        (["pytest", "-q"], True),
        (["go", "test", "./..."], True),
        (["go", "build", "./..."], False),
        (["cargo", "nextest", "run"], True),
        (["npx", "vitest", "run"], True),
        (["node", "--test"], True),
        (["node", "server.js"], False),
        ([], False),
        (None, False),
    ]
    for argv, expected in cases:
        assert ve._invokes_test_runner(argv) is expected, argv


def test_shell_test_gate_running_a_runner_passes(tmp_path):
    # FND-001 control: a `test` gate recorded as a shell string that
    # really runs pytest still validates — the hardened shell rule
    # must not reject genuine shell-wrapped runs.
    import shutil

    if shutil.which("sh") is None:
        import pytest

        pytest.skip("sh is not installed")
    b = _good_bundle()
    _recorded_bundle(
        b,
        tmp_path,
        commands={
            "test": (
                f"{sys.executable} -m pytest tests/test_capture.py -v "
                f"--junitxml {tmp_path / 'green.xml'} "
                f"|| {sys.executable} -c \"print('fallback')\""
            ),
        },
    )
    assert _problems(b, tmp_path) == []


def test_shell_test_gate_mentioning_a_runner_fails(tmp_path):
    # FND-001 hardening, end to end: a `test` gate recorded as a
    # shell string that only mentions pytest (`echo pytest`) is
    # rejected, even though it exits 0 and prints a passing-looking
    # line. The red run still records the canonical test failing.
    import shutil

    if shutil.which("sh") is None:
        import pytest

        pytest.skip("sh is not installed")
    b = _good_bundle()
    _recorded_bundle(
        b,
        tmp_path,
        commands={
            "test": (
                "echo 'tests/test_capture.py::test_capture_persian_only passed; 45 passed in 0.42s'"
            ),
        },
    )
    problems = _problems(b, tmp_path)
    assert any("test runner" in p for p in problems), problems
