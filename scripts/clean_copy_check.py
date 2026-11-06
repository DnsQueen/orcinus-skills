#!/usr/bin/env python3
"""Clean-copy check for ORCINUS (renamed 2026-11-06: the old name,
clean_install_check, claimed an install it never tested).

A skill collection that only works in the author's working tree is
not a one-install system. This script proves the repo works from a
clean copy: it puts the repo into a fresh temp dir and runs the
gates there — validator, drift check, ruff, and the script tests —
with the working directory inside the copy, so relative paths
resolve there and nowhere else.

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
  its installed pytest/ruff — it is not a fresh virtualenv, and a
  fresh machine would still need `pip install pytest ruff`.
- It never invokes npx or Claude Code. The `npx skills` install
  path is covered only in the sense that the skill files the
  installer reads are exactly the ones checked here. A real
  `claude plugin install` still needs a machine with Claude Code and
  is recorded as unverified (see SCOPE.md). `claude plugin validate
  --strict` DOES run — in CI, on the same checkout.

Usage:
  python3 scripts/clean_copy_check.py [--source <repo>] [--keep]
  python3 scripts/clean_copy_check.py --mode release [--rev <rev>]
Exit 0 when every gate passes in the clean copy; exit 1 when a
gate fails; exit 2 for a usage error (bad source, bad revision).
--keep leaves the temp dir in place for inspection (its path is
printed); without it the temp dir is deleted.
"""

import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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
    of silently testing something else."""
    proc = subprocess.run(
        ["git", "-C", str(source), "archive", rev], capture_output=True, timeout=120
    )
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
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _step(results, name, ok, detail=""):
    results.append((name, ok, detail))
    mark = "ok  " if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f": {detail}" if detail else ""))


def _gates(dest):
    """Run the five gates inside the clean copy. Returns the list of
    failed step names (empty when all pass)."""
    results = []
    # 1. The manifest and every skill resolve in the clean copy.
    manifest = json.loads((dest / "skills" / "manifest.json").read_text(encoding="utf-8"))
    skills = manifest["skills"]
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
            "pytest is not installed in this Python; pip install pytest==8.4.2",
        )
    else:
        _step(results, "script tests", rc == 0, out.splitlines()[-1] if out else "")
    return [name for name, ok, _ in results if not ok]


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
    try:
        if args.mode == "release":
            ok, error = _git_archive(source, args.rev, dest)
            if not ok:
                print(f"FAIL: cannot extract revision {args.rev!r}: {error}", file=sys.stderr)
                return 2
        else:
            _copy_clean(source, dest)
        failed = _gates(dest)
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f"Kept: {dest}")
    if failed:
        print(f"FAIL: {len(failed)} step(s) failed in the clean copy: {', '.join(failed)}")
        return 1
    print("OK: clean copy check passed (5 steps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
