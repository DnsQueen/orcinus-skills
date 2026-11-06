#!/usr/bin/env python3
"""Clean-environment install check for ORCINUS.

A skill collection that only works in the author's working tree is
not a one-install system. This script proves the repo works from a
clean copy: it copies the repo (excluding .git, caches, and
node_modules) into a fresh temp dir, then runs the gates there —
validator, drift check, ruff, and the script tests — with only the
tools a fresh machine would have (python3 + pip).

Usage:
  python3 scripts/clean_install_check.py [--source <repo>] [--keep]
Exit 0 when every gate passes in the clean copy; exit 1 otherwise.
--keep leaves the temp dir in place for inspection (its path is
printed); without it the temp dir is deleted.

This checks the repo's own gates, not a Claude Code plugin install:
a real `claude plugin install` needs a machine with Claude Code, and
is recorded as unverified (see SCOPE.md). The `npx skills` install
path is covered by the same copy: the skill files the installer
reads are exactly the ones checked here.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXCLUDE = {".git", "__pycache__", ".ruff_cache", "node_modules",
           ".pytest_cache", ".stryker-tmp"}


def _copy_clean(source, dest):
    def ignore(_dir, names):
        return [n for n in names if n in EXCLUDE]
    shutil.copytree(source, dest, ignore=ignore)


def _run(argv, cwd, timeout=300):
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _step(results, name, ok, detail=""):
    results.append((name, ok, detail))
    mark = "ok  " if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f": {detail}" if detail else ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(ROOT),
                        help="repo to copy (default: this repo)")
    parser.add_argument("--keep", action="store_true",
                        help="keep the temp dir for inspection")
    args = parser.parse_args()
    source = Path(args.source).resolve()
    if not (source / "skills" / "manifest.json").is_file():
        print(f"{source} does not look like the orcinus-skills repo "
              "(no skills/manifest.json)", file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="orcinus-clean-"))
    dest = tmp / "orcinus-skills"
    print(f"Clean copy: {dest}")
    results = []
    try:
        _copy_clean(source, dest)
        # 1. The manifest and every skill resolve in the clean copy.
        manifest = json.loads((dest / "skills" / "manifest.json")
                              .read_text(encoding="utf-8"))
        skills = manifest["skills"]
        missing = [n for n in skills
                   if not (dest / "skills" / n / "SKILL.md").is_file()]
        _step(results, "all manifest skills resolve",
              not missing,
              f"{len(skills)} skills" if not missing
              else f"missing SKILL.md: {', '.join(missing)}")
        # 2. The repo validator passes on the clean copy.
        rc, out = _run([sys.executable, "scripts/validate_repo.py"], dest)
        _step(results, "repo validator", rc == 0,
              out.splitlines()[-1] if out else "")
        # 3. The drift check passes (no vendored file was altered by the copy).
        rc, out = _run([sys.executable, "scripts/check_drift.py"], dest)
        _step(results, "drift check", rc == 0,
              out.splitlines()[-1] if out else "")
        # 4. Ruff passes on the clean copy.
        rc, out = _run([sys.executable, "-m", "ruff", "check"], dest)
        if rc != 0 and "No module named ruff" in out:
            _step(results, "ruff", False,
                  "ruff is not installed in this Python; "
                  "pip install ruff==0.17.4")
        else:
            _step(results, "ruff", rc == 0,
                  out.splitlines()[-1] if out else "")
        # 5. The script tests pass on the clean copy.
        rc, out = _run([sys.executable, "-m", "pytest", "-q"], dest)
        if rc != 0 and "No module named pytest" in out:
            _step(results, "script tests", False,
                  "pytest is not installed in this Python; "
                  "pip install pytest==8.4.2")
        else:
            _step(results, "script tests", rc == 0,
                  out.splitlines()[-1] if out else "")
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print(f"Kept: {dest}")
    failed = [name for name, ok, _ in results if not ok]
    if failed:
        print(f"FAIL: {len(failed)} step(s) failed in the clean copy: "
              f"{', '.join(failed)}")
        return 1
    print(f"OK: clean install check passed ({len(results)} steps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
