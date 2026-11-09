#!/usr/bin/env python3
"""Re-run the selected tests of an evidence bundle in a clean copy
of the repo, and attest that they pass — the optional offline
fallback for consumers with no CI.

What it reads from the bundle: the fail_first pytest nodeid and the
test files in files_changed (test_*.py / *_test.py only). It runs
ONLY those tests, SWE-bench FAIL_TO_PASS / PASS_TO_PASS style, in a
clean copy of the repo at exactly --revision — never in the live
working tree, never the full suite.

How the clean copy is made: `git worktree add --detach` (not
`git archive`). A worktree is one git command, a real checkout at
the resolved revision, and git removes it again afterwards; an
archive would need a tar extraction step whose availability and
path handling differ across platforms, for no benefit — the rerun
needs a directory pytest can run in, not a tarball. The worktree
is removed in a finally block, so a failed rerun leaves no
checkout behind either.

One deliberate deviation from the specified command: the rerun
runs pytest WITHOUT `-q`. The brief specifies `... --junitxml=<path>
-q` and, in the same breath, that the stdout summary be parsed
the same way validate_evidence.py parses it (reused, not
duplicated). Those two cannot both hold: `-q` prints the summary
bare (`1 passed in 0.01s`), while the validator's parser only
recognises the `=== 1 passed in 0.01s ===` form — so with `-q`
every honest passing rerun would fail its own summary check.
`-q` changes only console verbosity, never which tests run, so
dropping it preserves the load-bearing requirement (the reused
parser) at the cost of a cosmetic flag. The rerun still runs
exactly the selected tests, with --junitxml, under
sys.executable.

What is compared — and what is NOT: the bundle's test_report
totals are for the FULL suite, so they will not match a targeted
rerun and are never compared. Instead the rerun is compared
against itself: its exit code must be 0; its own JUnit must agree
with its own stdout summary (parsed the same way
validate_evidence.py parses it — reused, not duplicated); the
fail_first nodeid must be present and passed in the rerun JUnit;
every test the rerun ran must have passed. Any mismatch exits 1
with the specific check named.

Trust model (stated honestly): this verifies the CLAIM — the
selected tests pass at this revision — not the artifacts'
provenance. A fabricated JUnit that claims a nodeid passed which
FAILS in the rerun is caught (exit 1). But if the fabricated
artifacts exactly match what a real run would produce (because the
underlying tests genuinely pass), the rerun agrees: that is the
design, not a bug. A lying command can only be caught by a trust
boundary the job cannot touch (a CI runner holding the log); this
script has none, so it never claims proof of execution.

Limitation: transitive affected tests are NOT discovered — there
is no import graph here. Only fail_first plus the changed test
files run; a change that breaks an unlisted test is not caught by
this rerun. A runaway test's output is read back capped at 10 MiB
(the validator's artifact cap); the pytest summary line is at the
end of the output, so the capped tail still carries it.

Exit codes: 0 — the rerun attests the claim, and the proof file
is written (or the proof printed, with no --output). 1 — the
rerun ran but the claim did not hold (a named check failed), and
no proof file is written. 2 — cannot run (the bundle cannot be
read, the revision cannot be resolved, the worktree cannot be
created, pytest is missing, the run timed out): fail closed,
never 0.

Usage: python3 scripts/rerun_check.py --bundle <bundle.json>
    --repo <repo> --revision <rev> [--output <proof.json>]
    [--timeout <seconds>]   (default timeout 600s)
The proof is {"method": "targeted-rerun", "revision": "<resolved
full SHA>", "content_digest": "<recomputed, never trusted from
the bundle>", "tests": ["<nodeid>", ...], "junit": {"total": N,
"passed": N}, "exit_code": 0}.
"""

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

# The pytest stdout/stderr read-back cap, in bytes. The same number
# as validate_evidence.MAX_ARTIFACT_BYTES: a rerun artifact the
# validator could not read is not evidence, and the cap bounds the
# memory a runaway test can force this script to hold.
MAX_OUTPUT_BYTES = 10 * 1024 * 1024

# A full commit SHA in this repo's object format: SHA-1 (40 hex)
# or SHA-256 (64 hex). A revision that is not one is not a
# revision git resolved — it is empty or garbage output.
_SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")

EXIT_MISMATCH = 1
EXIT_CANNOT_RUN = 2


class RerunError(Exception):
    """A rerun failure, with the exit code it maps to: 1 when the
    rerun ran but the claim did not hold, 2 when it could not run
    at all. The message always names the specific check."""

    def __init__(self, exit_code, message):
        super().__init__(message)
        self.exit_code = exit_code


def _load_module(name, path):
    """Import the module at `path` under `name`, or raise
    RerunError(2) when it cannot be found or loaded."""
    if not Path(path).is_file():
        raise RerunError(
            EXIT_CANNOT_RUN, f"cannot run: {path} is not a file — run from a repo checkout"
        )
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RerunError(EXIT_CANNOT_RUN, f"cannot run: {path} cannot be imported")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        raise RerunError(EXIT_CANNOT_RUN, f"cannot run: {path} cannot be imported: {e}") from e
    return module


_VALIDATE_EVIDENCE = None


def _validator():
    """validate_evidence.py, loaded once from the skill folder
    beside this repo — its pytest-summary parser, its nodeid to
    JUnit mapping, its test-file pattern, and its bounded bundle
    reader are reused here, never reimplemented."""
    global _VALIDATE_EVIDENCE
    if _VALIDATE_EVIDENCE is None:
        path = (
            Path(__file__).resolve().parent.parent
            / "skills"
            / "orcinus-verify"
            / "scripts"
            / "validate_evidence.py"
        )
        _VALIDATE_EVIDENCE = _load_module("orcinus_validate_evidence", path)
    return _VALIDATE_EVIDENCE


_CONTENT_DIGEST_FN = None


def _content_digest_fn():
    """content_digest() from scripts/ beside this file, or the
    byte-identical copy bundled beside validate_evidence.py —
    imported, never reimplemented."""
    global _CONTENT_DIGEST_FN
    if _CONTENT_DIGEST_FN is None:
        candidates = [
            Path(__file__).resolve().parent / "content_digest.py",
            Path(__file__).resolve().parent.parent
            / "skills"
            / "orcinus-verify"
            / "scripts"
            / "content_digest.py",
        ]
        for path in candidates:
            if path.is_file():
                _CONTENT_DIGEST_FN = _load_module("orcinus_content_digest", path).content_digest
                break
        if _CONTENT_DIGEST_FN is None:
            raise RerunError(
                EXIT_CANNOT_RUN,
                "cannot run: content_digest.py not found beside rerun_check.py "
                "or beside validate_evidence.py",
            )
    return _CONTENT_DIGEST_FN


def _run(argv, cwd=None, timeout=None):
    """One subprocess call, through a single seam the tests can
    stub. Returns the CompletedProcess (text, captured)."""
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _resolve_revision(repo, revision):
    """The full SHA `revision` names, or RerunError(2): an
    unresolvable revision means the rerun cannot run at all."""
    try:
        proc = _run(["git", "-C", str(repo), "rev-parse", "--verify", f"{revision}^{{commit}}"])
    except FileNotFoundError as e:
        raise RerunError(EXIT_CANNOT_RUN, "cannot run: git is not installed") from e
    if proc.returncode != 0:
        raise RerunError(
            EXIT_CANNOT_RUN,
            f"cannot run: revision {revision!r} cannot be resolved in {repo}: "
            f"{proc.stderr.strip()}",
        )
    resolved = proc.stdout.strip()
    if not _SHA_RE.fullmatch(resolved):
        raise RerunError(
            EXIT_CANNOT_RUN,
            f"cannot run: git resolved revision {revision!r} to {resolved!r}, "
            "not a full commit SHA",
        )
    return resolved


def _read_bundle(path):
    """The bundle as a dict. Read through the validator's bounded
    reader (no symlinks, 5 MiB cap, fatal UTF-8), so a hostile
    bundle cannot smuggle itself in as input. Unreadable or
    malformed input is exit 2: the rerun cannot run at all."""
    try:
        text = _validator().read_bundle_file(path)
    except ValueError as e:
        raise RerunError(EXIT_CANNOT_RUN, f"cannot run: bundle {path} cannot be read: {e}") from e
    try:
        bundle = json.loads(text)
    except (json.JSONDecodeError, RecursionError, ValueError) as e:
        raise RerunError(
            EXIT_CANNOT_RUN, f"cannot run: bundle {path} is not valid JSON: {e}"
        ) from e
    if not isinstance(bundle, dict):
        raise RerunError(EXIT_CANNOT_RUN, f"cannot run: bundle {path} must be a JSON object")
    return bundle


def select_targets(bundle):
    """(fail_first nodeid, [pytest targets]) from a bundle. The
    targets are the nodeid plus the changed test files, in that
    order — pytest collects a test named twice only once, so
    naming the nodeid alongside its file does not double-run it.
    A bundle that names no test to rerun is a failed claim (exit
    1), not a tool failure: there is nothing to attest."""
    validator = _validator()
    fail_first = bundle.get("fail_first")
    if not isinstance(fail_first, dict):
        raise RerunError(
            EXIT_MISMATCH,
            "fail_first is missing: the bundle names no test to rerun, "
            "so the claim cannot be attested",
        )
    test = fail_first.get("test")
    if not isinstance(test, str) or not test:
        raise RerunError(
            EXIT_MISMATCH,
            "fail_first.test is missing: the bundle names no test to rerun, "
            "so the claim cannot be attested",
        )
    if validator._nodeid_to_junit(test) is None:
        raise RerunError(
            EXIT_MISMATCH,
            f"fail_first.test {test!r} is not a pytest nodeid "
            "(expected 'path/test_file.py::test_name'): the rerun "
            "cannot run a test it cannot name",
        )
    files = bundle.get("files_changed", [])
    if not isinstance(files, list):
        raise RerunError(EXIT_MISMATCH, "files_changed is not a list of file paths")
    test_files = []
    for entry in files:
        if not isinstance(entry, str):
            raise RerunError(EXIT_MISMATCH, f"files_changed entry {entry!r} is not a file path")
        path = entry.removeprefix("./")
        if validator._TEST_FILE_RE.search(path) and path not in test_files:
            test_files.append(path)
    return test, [test, *test_files]


def parse_junit(path):
    """The rerun's JUnit report as [(classname, name, status)] in
    file order, with status in passed / failed / error / skipped —
    the same outcome rule as validate_evidence (a failure/error/
    skipped child means not passed, no child means passed). A
    missing or unparsable report is a failed claim (exit 1): the
    rerun ran but left nothing to check against."""
    try:
        root = ET.parse(path).getroot()
    except FileNotFoundError as e:
        raise RerunError(
            EXIT_MISMATCH,
            f"rerun junit is missing: pytest left no report at {path} — "
            "the rerun cannot be checked without one",
        ) from e
    except ET.ParseError as e:
        raise RerunError(EXIT_MISMATCH, f"rerun junit at {path} is not valid JUnit XML: {e}") from e
    cases = []
    for case in root.iter("testcase"):
        status = "passed"
        for child in case:
            if child.tag in ("failure", "error"):
                status = "failed" if child.tag == "failure" else "error"
                break
            if child.tag == "skipped":
                status = "skipped"
        cases.append((case.get("classname") or "", case.get("name") or "", status))
    return cases


def _module_map(targets):
    """Dotted module name -> repo-relative file path, for every
    test file the rerun covers (the fail_first file included, even
    when files_changed does not list it)."""
    modules = {}
    files = []
    for target in targets:
        path = target.split("::", 1)[0].removeprefix("./")
        if path not in files:
            files.append(path)
    for path in files:
        dotted = PurePosixPath(path).with_suffix("").as_posix().replace("/", ".")
        modules[dotted] = path
    return modules


def reconstruct_nodeid(classname, name, modules):
    """A JUnit (classname, name) pair back to its pytest nodeid,
    via the longest known module prefix: `tests.test_x.TestFoo` +
    `test_bar` with module `tests.test_x` becomes
    `tests/test_x.py::TestFoo::test_bar`. A classname from no
    known module (a test pytest collected from outside the
    targets, which should not happen) falls back to a dotted-path
    guess rather than crashing the comparison."""
    for module in sorted(modules, key=len, reverse=True):
        if classname == module or classname.startswith(module + "."):
            rest = classname[len(module) :].lstrip(".")
            prefix = f"{modules[module]}::{rest}::" if rest else f"{modules[module]}::"
            return f"{prefix}{name}"
    return f"{classname.replace('.', '/')}.py::{name}"


def check_rerun_agreement(stdout, cases, fail_first, modules=None):
    """The rerun compared against itself. Returns (total, passed).
    Raises RerunError(1) naming the specific check on any
    mismatch: the fail_first nodeid absent or not passed in the
    rerun JUnit, any rerun test not passed, or the stdout summary
    disagreeing with (or unparseable against) the JUnit counts.
    The bundle's test_report totals are never consulted here."""
    validator = _validator()
    modules = modules or {}
    by_key = {}
    for classname, name, status in cases:
        key = (classname, name)
        # A test listed twice keeps its worst status: a duplicate
        # that failed anywhere is not a pass.
        if key not in by_key or by_key[key] == "passed":
            by_key[key] = status
    total = len(cases)
    passed = sum(1 for _, _, status in cases if status == "passed")
    expected = validator._nodeid_to_junit(fail_first)
    if expected is None:
        raise RerunError(
            EXIT_MISMATCH,
            f"fail_first.test {fail_first!r} is not a pytest nodeid",
        )
    status = by_key.get(expected)
    if status is None:
        raise RerunError(
            EXIT_MISMATCH,
            f"fail_first {fail_first!r} does not appear in the rerun JUnit: "
            "the rerun did not run the test the bundle claims passed",
        )
    if status != "passed":
        raise RerunError(
            EXIT_MISMATCH,
            f"fail_first {fail_first!r} has status {status!r} in the rerun, "
            "not passed: the bundle's claim does not hold at this revision",
        )
    for (classname, name), entry_status in by_key.items():
        if entry_status != "passed":
            raise RerunError(
                EXIT_MISMATCH,
                f"rerun test {reconstruct_nodeid(classname, name, modules)!r} "
                f"has status {entry_status!r}, not passed: every test the "
                "rerun ran must have passed",
            )
    summary = validator._parse_pytest_summary(stdout)
    if summary is None:
        raise RerunError(
            EXIT_MISMATCH,
            "rerun stdout summary could not be parsed (pytest prints "
            "'N passed ... in Xs'; an xfailed/xpassed line is not "
            "parseable): the rerun JUnit cannot be checked against "
            "its stdout, so the rerun does not attest",
        )
    if summary != (total, passed):
        raise RerunError(
            EXIT_MISMATCH,
            f"rerun stdout summary says {summary[0]} test(s) with "
            f"{summary[1]} passed but the rerun JUnit lists {total} "
            f"test(s) with {passed} passed: the report does not match "
            "the run that produced it",
        )
    return total, passed


def _probe_pytest(worktree):
    """Fail closed (exit 2) when the worktree's python has no
    pytest: a rerun that cannot run is never a pass."""
    try:
        proc = _run([sys.executable, "-m", "pytest", "--version"], cwd=str(worktree), timeout=60)
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        raise RerunError(EXIT_CANNOT_RUN, f"cannot run: pytest is not available ({e})") from e
    if proc.returncode != 0:
        raise RerunError(
            EXIT_CANNOT_RUN,
            "cannot run: pytest is not available: "
            f"{sys.executable} -m pytest --version exited {proc.returncode}",
        )


def _read_tail_text(path, cap):
    """The tail of a file as text (at most `cap` bytes): the pytest
    summary line is at the end of the output, so the capped tail
    still carries it, however much a runaway test printed."""
    size = path.stat().st_size
    with open(path, "rb") as f:
        if size > cap:
            f.seek(size - cap)
        return f.read().decode("utf-8", errors="replace")


def _remove_worktree(repo, worktree):
    """Best-effort worktree removal: a stale registration must not
    flip a rerun's verdict, so failures warn instead of raising."""
    try:
        proc = _run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree)],
            timeout=60,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        proc = None
    if proc is None or proc.returncode != 0:
        shutil.rmtree(worktree, ignore_errors=True)
        try:
            _run(["git", "-C", str(repo), "worktree", "prune"], timeout=60)
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
        print(
            f"rerun_check: warning: could not remove the worktree at {worktree}",
            file=sys.stderr,
        )


def rerun(bundle_path, repo, revision, timeout):
    """Run the bundle's selected tests at `revision` and return the
    proof dict. Raises RerunError(1) when the claim did not hold
    and RerunError(2) when the rerun could not run."""
    bundle = _read_bundle(bundle_path)
    fail_first, targets = select_targets(bundle)
    repo = Path(repo).resolve()
    if not repo.is_dir():
        raise RerunError(EXIT_CANNOT_RUN, f"cannot run: --repo {repo} is not a directory")
    resolved = _resolve_revision(repo, revision)
    try:
        digest = _content_digest_fn()(repo, resolved)
    except Exception as e:
        raise RerunError(
            EXIT_CANNOT_RUN,
            f"cannot run: cannot compute the content digest of {resolved} in {repo}: {e}",
        ) from e
    with tempfile.TemporaryDirectory(prefix="rerun-check-") as tmp:
        worktree = Path(tmp) / "wt"
        junit_path = worktree / "rerun-junit.xml"
        stdout_path = Path(tmp) / "rerun.stdout"
        stderr_path = Path(tmp) / "rerun.stderr"
        try:
            try:
                proc = _run(
                    [
                        "git",
                        "-C",
                        str(repo),
                        "worktree",
                        "add",
                        "--detach",
                        str(worktree),
                        resolved,
                    ],
                    timeout=120,
                )
            except FileNotFoundError as e:
                raise RerunError(EXIT_CANNOT_RUN, "cannot run: git is not installed") from e
            if proc.returncode != 0:
                raise RerunError(
                    EXIT_CANNOT_RUN,
                    f"cannot run: cannot create a worktree at {resolved} in {repo}: "
                    f"{proc.stderr.strip()}",
                )
            # The selected files must exist at the revision: a
            # missing file is a failed claim, named before pytest
            # reports it as a collection error.
            for target in targets:
                path = target.split("::", 1)[0].removeprefix("./")
                if not (worktree / path).is_file():
                    raise RerunError(
                        EXIT_MISMATCH,
                        f"selected test file {path!r} does not exist at "
                        f"revision {resolved}: the bundle's claim cannot "
                        "hold for a test that is not there",
                    )
            _probe_pytest(worktree)
            # No -q: the reused summary parser only recognises the
            # `=== N passed in Xs ===` form, which -q suppresses
            # (see the module docstring). Verbosity only — the
            # selected tests and the JUnit report are unchanged.
            argv = [
                sys.executable,
                "-m",
                "pytest",
                *targets,
                f"--junitxml={junit_path}",
            ]
            try:
                with open(stdout_path, "wb") as out, open(stderr_path, "wb") as err:
                    proc = subprocess.run(
                        argv, cwd=str(worktree), stdout=out, stderr=err, timeout=timeout
                    )
            except subprocess.TimeoutExpired as e:
                raise RerunError(
                    EXIT_CANNOT_RUN,
                    f"cannot run: rerun timed out after {timeout}s",
                ) from e
            except FileNotFoundError as e:
                raise RerunError(
                    EXIT_CANNOT_RUN, f"cannot run: {sys.executable} is not runnable: {e}"
                ) from e
            stdout = _read_tail_text(stdout_path, MAX_OUTPUT_BYTES)
            if proc.returncode != 0:
                lines = [line for line in stdout.splitlines() if line.strip()][-10:]
                tail = "\n".join(lines)
                raise RerunError(
                    EXIT_MISMATCH,
                    f"rerun exit_code is {proc.returncode}, not 0: the selected "
                    f"tests did not pass at revision {resolved}" + (f"\n{tail}" if tail else ""),
                )
            cases = parse_junit(junit_path)
            modules = _module_map(targets)
            total, passed = check_rerun_agreement(stdout, cases, fail_first, modules)
            tests = []
            for classname, name, _status in cases:
                nodeid = reconstruct_nodeid(classname, name, modules)
                if nodeid not in tests:
                    tests.append(nodeid)
            return {
                "method": "targeted-rerun",
                "revision": resolved,
                "content_digest": digest,
                "tests": tests,
                "junit": {"total": total, "passed": passed},
                "exit_code": 0,
            }
        finally:
            _remove_worktree(repo, worktree)


def main(argv):
    parser = argparse.ArgumentParser(
        description="Re-run an evidence bundle's selected tests in a "
        "clean worktree at a revision, and attest that they pass.",
        usage="python3 scripts/rerun_check.py --bundle <bundle.json> "
        "--repo <repo> --revision <rev> [--output <proof.json>] "
        "[--timeout <seconds>]",
    )
    parser.add_argument("--bundle", required=True, help="the evidence bundle (JSON)")
    parser.add_argument("--repo", required=True, help="the git repo the bundle is bound to")
    parser.add_argument(
        "--revision", required=True, help="the revision to rerun at (resolved to a full SHA)"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="where to write the proof JSON (default: print it on stdout)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="seconds before the pytest run is killed (default 600)",
    )
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be a positive number of seconds")
    try:
        proof = rerun(args.bundle, args.repo, args.revision, args.timeout)
    except RerunError as e:
        print(f"rerun_check: {e}", file=sys.stderr)
        return e.exit_code
    text = json.dumps(proof, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(text, end="")
        return 0
    try:
        Path(args.output).write_text(text, encoding="utf-8")
    except OSError as e:
        print(f"rerun_check: cannot write the proof to {args.output}: {e}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
