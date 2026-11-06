#!/usr/bin/env python3
"""Detect an incomplete refactor: old identifiers still referenced, removed paths still present.

Usage:
    python3 check_refactor.py --root . --old budgetWarning,oldName \
        [--removed src/budget-old.ts] [--allow CHANGELOG.md,docs/migration.md]
        [--allow-empty]

Exit 0: clean (no leftovers, and the scan covered everything).
Exit 1: leftovers found, or the scan was incomplete, or the arguments
were unusable (a nonexistent root, an empty --old list).

Rules:
- Old identifiers are matched as whole identifiers, so ``budgetWarning``
  matches but ``budgetWarningV2`` does not. Identifiers that start with
  ``$`` (e.g. ``$store``) are matched with lookarounds, not ``\\b``.
- The files scanned are the ones git tracks plus untracked files that
  are not ignored (``git ls-files --cached --others --exclude-standard``),
  so .gitignore is respected automatically. When the root is not a git
  repository (or git is unavailable), the script walks the tree.
  In both modes, generated directories and lockfiles are skipped
  (see SKIP_DIRS/SKIP_FILES) — a lockfile that merely names an old
  package must not be a false positive.
- --allow lists files by relative path that may mention an old name on
  purpose, e.g. a CHANGELOG entry. It matches the relative path only —
  never a bare basename — so allowing README.md does not exempt every
  README.md in the tree. Every allowlist entry must be justified in the
  report; the script does not judge the justification.
- A hit inside a test file (a test directory, or a file named
  *.test.*, *.spec.*, test_*, *_test.*) is classified as a stale test.
- The summary always reports how many files were checked, skipped
  (non-UTF-8), binary, and unreadable. A scan that skipped a file it
  could not read, or that could not read a file, is INCOMPLETE — never
  clean. A scan that checked zero files is INCOMPLETE too, unless
  --allow-empty is given explicitly (an empty project is not proof
  that a refactor is complete).
"""

import argparse
import os
import re
import subprocess
import sys

SKIP_DIRS = {".git", "node_modules", "dist", "build", "coverage", ".next",
             "out", "target", "reports", "__pycache__", "venv", ".venv",
             ".turbo", ".cache", "vendor"}
SKIP_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml",
              "Cargo.lock", "poetry.lock", "Pipfile.lock", "composer.lock",
              "Gemfile.lock", "go.sum"}


def is_test_path(path):
    parts = path.replace(os.sep, "/").split("/")
    if any(p in ("test", "tests", "spec", "__tests__") for p in parts):
        return True
    name = parts[-1]
    return (".test." in name or ".spec." in name
            or name.startswith("test_") or name.startswith("test-")
            or "_test." in name)


def _is_skipped(rel):
    """Whether a relative path is a generated directory or a lockfile
    that must never be scanned, in either file-listing mode. A lockfile
    that merely names an old package is not evidence of a leftover."""
    parts = rel.replace(os.sep, "/").split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]):
        return True
    return parts[-1] in SKIP_FILES


def _git_files(root):
    """The files git knows about: tracked files plus untracked files
    that are not ignored. Returns None when git cannot list them."""
    try:
        result = subprocess.run(
            ["git", "-C", root, "ls-files", "-z", "--cached", "--others",
             "--exclude-standard"],
            capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return [p for p in result.stdout.decode("utf-8", errors="surrogateescape").split("\0") if p]


def _walk_files(root):
    """The files under root, skipping generated directories and
    lockfiles. Used only when git cannot list the files."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for filename in sorted(filenames):
            if filename in SKIP_FILES:
                continue
            out.append(os.path.relpath(os.path.join(dirpath, filename), root).replace(os.sep, "/"))
    return sorted(out)


def main():
    parser = argparse.ArgumentParser(description="Detect an incomplete refactor.")
    parser.add_argument("--root", default=".", help="project root to check")
    parser.add_argument("--old", required=True,
                        help="comma-separated old identifiers that must be gone")
    parser.add_argument("--removed", default="",
                        help="comma-separated paths that must not exist")
    parser.add_argument("--allow", default="",
                        help="comma-separated files (relative path) allowed to mention an old name")
    parser.add_argument("--allow-empty", action="store_true",
                        help="allow a clean result when zero files were checked "
                             "(default: zero coverage is INCOMPLETE)")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"error: root {args.root!r} does not exist or is not a directory",
              file=sys.stderr)
        return 1
    old_names = [n.strip() for n in args.old.split(",") if n.strip()]
    if not old_names:
        print("error: --old must list at least one identifier", file=sys.stderr)
        return 1
    removed = [p.strip() for p in args.removed.split(",") if p.strip()]
    allowed = {a.strip() for a in args.allow.split(",") if a.strip()}
    # Whole-identifier match, including identifiers that start with $.
    # \b fails there ($ is not a word character), so use lookarounds:
    # the character before and after must not be a word character or $.
    patterns = {name: re.compile(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])")
                for name in old_names}

    hits = []  # (kind, path, line, detail)
    checked = skipped_non_utf8 = skipped_binary = unreadable = 0

    for removed_path in removed:
        full = os.path.join(root, removed_path)
        if os.path.exists(full):
            hits.append(("removed-path", removed_path, 0,
                         "path still exists"))

    files = _git_files(root)
    used_git = files is not None
    if files is None:
        files = _walk_files(root)
    else:
        # The skip rules apply in git mode too: a tracked lockfile
        # (package-lock.json names its packages) must not be scanned,
        # and neither must a tracked file under a generated directory.
        files = [f for f in files if not _is_skipped(f)]
    for rel in files:
        if rel in allowed:
            continue
        full = os.path.join(root, rel)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, "rb") as f:
                raw = f.read()
        except OSError:
            # Unreadable: the scan did not cover this file. Counted, and
            # reported as INCOMPLETE below — it is not a leftover.
            unreadable += 1
            continue
        if b"\x00" in raw:
            skipped_binary += 1
            continue  # binary file
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            skipped_non_utf8 += 1
            continue
        checked += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, pattern in patterns.items():
                if pattern.search(line):
                    kind = "stale-test" if is_test_path(rel) else "old-name"
                    hits.append((kind, rel, lineno,
                                 "old identifier '%s' still referenced" % name))

    summary = (f"{checked} file(s) checked, {skipped_non_utf8} skipped "
               f"(non-UTF-8), {skipped_binary} binary, {unreadable} unreadable"
               + (" (via git ls-files)" if used_git else " (via walk)"))

    if hits:
        for kind, path, lineno, detail in hits:
            location = "%s:%d" % (path, lineno) if lineno else path
            print("%s\t%s\t%s" % (kind, location, detail))
        kinds = {}
        for kind, _, _, _ in hits:
            kinds[kind] = kinds.get(kind, 0) + 1
        print("FAIL: %d leftover(s) (%s)"
              % (len(hits), ", ".join("%s=%d" % kv for kv in sorted(kinds.items()))))
        print(f"  {summary}")
        return 1

    if skipped_non_utf8 or unreadable:
        # A scan that did not cover everything is INCOMPLETE, never clean.
        print(f"INCOMPLETE: no leftovers found, but the scan did not cover "
              f"everything ({summary})")
        return 1

    if checked == 0 and not args.allow_empty:
        # Zero files checked is not proof that the refactor is complete.
        print(f"INCOMPLETE: no files were checked ({summary}) — use "
              f"--allow-empty to accept an empty scan explicitly")
        return 1

    print("clean: no leftovers (%d old identifier(s), %d removed path(s) checked; %s)"
          % (len(old_names), len(removed), summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
