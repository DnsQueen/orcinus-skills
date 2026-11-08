#!/usr/bin/env python3
"""Clean-copy check for ORCINUS (renamed 2026-11-06: the old name,
clean_install_check, claimed an install it never tested).

A skill collection that only works in the author's working tree is
not a one-install system. This script proves the repo works from a
clean copy: it puts the repo into a fresh temp dir and runs the
gates there — validator, drift check, ruff check, ruff format
--check, mypy (the CI scope), and the script tests — with the
working directory inside the copy, so relative paths resolve there
and nowhere else.

Two modes:
- working-tree (default): copy the working tree (excluding .git,
  caches, node_modules, and virtualenvs) into a temp dir. This is
  the mode for local development: it tests exactly what is on disk,
  including uncommitted files.
- release: extract one committed revision with `git archive` into a
  temp dir. This is the mode for a release candidate: it tests only
  what is committed, so an uncommitted fix cannot make a broken
  release look green.

The script NEVER renames, moves, or writes to the source. An
earlier design hid the source by renaming it to
<source>.orcinus-hidden for the duration of the run: if the process
was killed mid-run the source stayed hidden, the temp copy leaked,
and the next run refused to start until someone renamed it back by
hand. That failure was demonstrated with a SIGKILL (round 4, track
6) and the rename was removed. The price is stated plainly: hiding
the source was also the test that nothing in the copy reaches back
to the original checkout through an absolute path. Without it, an
absolute-path leak would still resolve to the live checkout and the
gates would pass anyway. The release mode narrows that gap (its
tree contains only committed files), but it does not close it: a
check for absolute-path leaks is future work, not a claim made
here.

What this does NOT prove, stated plainly:
- The working-tree mode copies the WORKING TREE, including
  uncommitted files — it is not a check of a committed revision.
  Use --mode release for that.
- It runs the gates with the CURRENT Python (sys.executable) and
  its installed pytest/ruff/mypy — it is not a fresh virtualenv, and
  a fresh machine would still need
  `pip install --require-hashes -r requirements-ci.txt`.
- A gate that times out, a corrupt manifest, or a `git archive`
  that cannot be extracted fails its step with a FAIL line and a
  controlled exit code — never a traceback. Exit 0 when every gate
  passes in the clean copy; exit 1 when a gate fails; exit 2 for a
  usage error (bad source, bad revision).
- It never invokes npx or Claude Code. The `npx skills` install
  path is covered only in the sense that the skill files the
  installer reads are exactly the ones checked here. A real
  `claude plugin install` still needs a machine with Claude Code and
  is recorded as unverified (see SCOPE.md). `claude plugin validate
  --strict` DOES run — in CI, on the same checkout.

Usage:
  python3 scripts/clean_copy_check.py [--source <repo>] [--keep]
  python3 scripts/clean_copy_check.py --mode release [--rev <rev>]
--keep leaves the temp dir in place for inspection (its path is
printed); without it the temp dir is deleted.
A SIGTERM during the gates removes the temp dir too (a signal
handler + atexit cleanup, round 8 FND-024) and the process still
dies by SIGTERM — on POSIX. On Windows there is no deliverable
SIGTERM (Popen.send_signal(SIGTERM) is TerminateProcess: the
process dies with returncode 1 and no handler, atexit or finally
ever runs), so this guarantee does not apply there. A SIGKILL
cannot be caught, so a SIGKILLed run still leaks its temp dir —
that is a property of the signal.
"""

import argparse
import atexit
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _mypy_scope():
    """The mypy scope, read from the single source of truth:
    [tool.mypy] files in pyproject.toml (round 6, S8). mypy reads
    the same list natively, and CI passes no paths at all — the list
    used to be hand-copied in three places. tomllib is stdlib on
    3.11+, the lowest version this repo supports; the tomli fallback
    for older Pythons was removed with the Python 3.10 drop (round
    6, 2-S7), because no supported Python needs the shim — and
    keeping the import broke mypy on 3.11+, where tomli is not
    installed (CI run 42384742442)."""
    import tomllib

    with open(ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    try:
        files = data["tool"]["mypy"]["files"]
    except (KeyError, TypeError):
        raise RuntimeError(
            "pyproject.toml has no [tool.mypy] files list — it is the "
            "single source of truth for the mypy scope"
        ) from None
    if not isinstance(files, list) or not files or not all(isinstance(p, str) for p in files):
        raise RuntimeError("pyproject.toml [tool.mypy] files is missing or not a list of paths")
    return files


# The mypy scope is the exact list CI typechecks — read from
# pyproject.toml, not hand-copied here. The clean-copy gates run the
# same list, not a subset: a copy that passes here must pass the
# same typecheck CI runs.
MYPY_SCOPE = _mypy_scope()

EXCLUDE = {
    ".git",
    "__pycache__",
    ".ruff_cache",
    "node_modules",
    ".pytest_cache",
    ".stryker-tmp",
    ".venv",
    "venv",
    ".mypy_cache",
}


def _copy_clean(source, dest):
    def ignore(_dir, names):
        return [n for n in names if n in EXCLUDE]

    shutil.copytree(source, dest, ignore=ignore)


def _git_archive(source, rev, dest):
    """Extract one committed revision into dest. Returns (ok, error):
    ok is False when the revision cannot be resolved — that is a
    usage error, not a gate failure, and must fail loudly instead
    of silently testing something else. A timeout is reported the
    same way, never raised as a traceback."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(source), "archive", rev], capture_output=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        return False, "git archive timed out after 120s"
    if proc.returncode != 0:
        return False, proc.stderr.decode("utf-8", "replace").strip()
    try:
        with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
            # filter="data": reject absolute paths and links escaping
            # the destination (and silence the 3.14 default change).
            tar.extractall(dest, filter="data")
    except tarfile.TarError as e:
        return False, f"cannot extract revision {rev!r}: {e}"
    return True, ""


def _run(argv, cwd, timeout=300):
    """Run a gate command. A timeout is a failed gate, not an
    exception: returncode 1 with the timeout as the detail, so the
    caller prints a FAIL line and a controlled exit code."""
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 1, f"timed out after {timeout}s"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _kill_process(proc):
    """Kill a process the way the platform allows: Popen.kill sends
    SIGKILL on POSIX and calls TerminateProcess on Windows —
    signal.SIGKILL does not exist on Windows, so no caller may name
    it. A kill is a kill either way: no cleanup runs, which is the
    point of the killed-run test."""
    proc.kill()


def _step(results, name, ok, detail=""):
    results.append((name, ok, detail))
    mark = "ok  " if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f": {detail}" if detail else ""))


def _gates(dest):
    """Run the seven gates inside the clean copy — the same list CI
    runs (validator, drift, ruff check, ruff format --check, mypy,
    script tests), plus the manifest resolution the copy itself
    makes possible. Returns (failed step names, total steps)."""
    results = []
    # 1. The manifest and every skill resolve in the clean copy.
    # A corrupt or missing manifest fails this step — it is a broken
    # copy, not a crash: the remaining gates still run.
    try:
        manifest = json.loads((dest / "skills" / "manifest.json").read_text(encoding="utf-8"))
        skills = manifest["skills"]
    except (json.JSONDecodeError, KeyError, OSError) as e:
        _step(
            results,
            "all manifest skills resolve",
            False,
            f"skills/manifest.json is not readable: {e}",
        )
        skills = None
    if skills is not None:
        missing = [n for n in skills if not (dest / "skills" / n / "SKILL.md").is_file()]
        _step(
            results,
            "all manifest skills resolve",
            not missing,
            f"{len(skills)} skills" if not missing else f"missing SKILL.md: {', '.join(missing)}",
        )
    # 2. The repo validator passes on the clean copy.
    rc, out = _run([sys.executable, "scripts/validate_repo.py"], dest)
    _step(results, "repo validator", rc == 0, out.splitlines()[-1] if out else "")
    # 3. The drift check passes (no vendored file was altered by the copy).
    rc, out = _run([sys.executable, "scripts/check_drift.py"], dest)
    _step(results, "drift check", rc == 0, out.splitlines()[-1] if out else "")
    # 4. Ruff passes on the clean copy.
    rc, out = _run([sys.executable, "-m", "ruff", "check"], dest)
    if rc != 0 and "No module named ruff" in out:
        _step(
            results, "ruff", False, "ruff is not installed in this Python; pip install ruff==0.17.4"
        )
    else:
        _step(results, "ruff", rc == 0, out.splitlines()[-1] if out else "")
    # 5. The script tests pass on the clean copy.
    rc, out = _run([sys.executable, "-m", "pytest", "-q"], dest)
    if rc != 0 and "No module named pytest" in out:
        _step(
            results,
            "script tests",
            False,
            "pytest is not installed in this Python; pip install pytest==9.0.3",
        )
    else:
        _step(results, "script tests", rc == 0, out.splitlines()[-1] if out else "")
    # 6. Formatting matches CI (ruff format --check).
    rc, out = _run([sys.executable, "-m", "ruff", "format", "--check"], dest)
    if rc != 0 and "No module named ruff" in out:
        _step(
            results,
            "ruff format",
            False,
            "ruff is not installed in this Python; pip install ruff==0.17.4",
        )
    else:
        _step(results, "ruff format", rc == 0, out.splitlines()[-1] if out else "")
    # 7. mypy, same scope as CI (see MYPY_SCOPE).
    rc, out = _run([sys.executable, "-m", "mypy", *MYPY_SCOPE], dest)
    if rc != 0 and "No module named mypy" in out:
        _step(
            results,
            "mypy",
            False,
            "mypy is not installed in this Python; pip install mypy==1.18.2",
        )
    else:
        _step(results, "mypy", rc == 0, out.splitlines()[-1] if out else "")
    failed = [name for name, ok, _ in results if not ok]
    return failed, len(results)


def _install_sigterm_cleanup(tmp):
    """Remove `tmp` when the process is killed by SIGTERM — and
    register the same removal with atexit for any other abrupt
    exit. Round 8, FND-024: the default SIGTERM disposition
    terminates the process without an exception, so the `finally:
    shutil.rmtree` in main() never ran and a full repo copy
    leaked on every SIGTERM. The handler removes the dir, then
    re-raises SIGTERM with the default disposition, so the
    process still dies by SIGTERM (returncode -15 on POSIX)
    instead of exiting 0 or 1. On Windows no SIGTERM is ever
    delivered, so this handler never runs there — see the module
    docstring. The `cleaned` flag (plus atexit.unregister
    in main's finally) keeps --keep honest: a kept dir is never
    removed at interpreter exit. SIGKILL cannot be caught —
    a SIGKILLed run still leaks its temp dir; that is a property
    of the signal, not a gap in this cleanup. Returns
    (old_handler, cleanup) so main() can restore/unregister."""
    state = {"cleaned": False}

    def cleanup():
        if not state["cleaned"]:
            state["cleaned"] = True
            shutil.rmtree(tmp, ignore_errors=True)

    atexit.register(cleanup)
    old_handler = None
    if hasattr(signal, "SIGTERM"):

        def _handler(signum, frame):
            cleanup()
            # Die by SIGTERM, as the sender asked: restore the
            # default disposition and re-send it to ourselves.
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            os.kill(os.getpid(), signal.SIGTERM)

        try:
            old_handler = signal.signal(signal.SIGTERM, _handler)
        except (OSError, ValueError):
            # Not the main thread (or another platform limit):
            # the atexit cleanup still covers normal exits, and
            # the finally in main() covers the gates.
            old_handler = None
    return old_handler, cleanup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(ROOT), help="repo to copy (default: this repo)")
    parser.add_argument(
        "--mode",
        default="working-tree",
        choices=("working-tree", "release"),
        help="working-tree: copy the working tree; release: extract a committed revision",
    )
    parser.add_argument("--rev", default="HEAD", help="revision for --mode release (default: HEAD)")
    parser.add_argument("--keep", action="store_true", help="keep the temp dir for inspection")
    args = parser.parse_args(argv)
    source = Path(args.source).resolve()
    if not (source / "skills" / "manifest.json").is_file():
        print(
            f"{source} does not look like the orcinus-skills repo (no skills/manifest.json)",
            file=sys.stderr,
        )
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="orcinus-clean-"))
    dest = tmp / "orcinus-skills"
    print(f"Clean copy: {dest}")
    old_handler, _cleanup = (None, None)
    if not args.keep:
        # Round 8, FND-024: without this, SIGTERM skips the
        # finally below and leaks the temp dir.
        old_handler, _cleanup = _install_sigterm_cleanup(tmp)
    try:
        if args.mode == "release":
            ok, error = _git_archive(source, args.rev, dest)
            if not ok:
                print(f"FAIL: cannot extract revision {args.rev!r}: {error}", file=sys.stderr)
                return 2
        else:
            _copy_clean(source, dest)
        failed, total = _gates(dest)
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)
            try:
                atexit.unregister(_cleanup)
            except (AttributeError, ValueError):
                pass
            if old_handler is not None and hasattr(signal, "SIGTERM"):
                try:
                    signal.signal(signal.SIGTERM, old_handler)
                except (OSError, ValueError):
                    pass
        else:
            print(f"Kept: {dest}")
    if failed:
        print(f"FAIL: {len(failed)} step(s) failed in the clean copy: {', '.join(failed)}")
        return 1
    print(f"OK: clean copy check passed ({total} steps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
