#!/usr/bin/env python3
"""Detect an incomplete refactor: old identifiers still referenced, removed paths still present.

Usage:
    python3 check_refactor.py --root . --old budgetWarning,oldName \
        [--removed src/budget-old.ts] [--allow CHANGELOG.md,docs/migration.md]

Exit 0: no leftovers. Exit 1: leftovers found.

Rules:
- Old identifiers are matched as whole words (``\\bname\\b``), so ``budgetWarning``
  matches but ``budgetWarningV2`` does not.
- Directories .git, node_modules, dist, reports, __pycache__, venv, .venv are skipped.
- Generated lockfiles are skipped.
- --allow lists files (relative path or basename) that may mention an old name on
  purpose, e.g. a CHANGELOG entry. Every allowlist entry must be justified in the
  report; the script does not judge the justification.
- A hit inside a test file (path contains test/tests/spec) is classified as a
  stale test.
"""

import argparse
import os
import re
import sys

SKIP_DIRS = {".git", "node_modules", "dist", "reports", "__pycache__", "venv", ".venv"}
SKIP_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml"}


def is_test_path(path):
    parts = path.replace(os.sep, "/").split("/")
    return any(p in ("test", "tests", "spec", "__tests__") for p in parts)


def main():
    parser = argparse.ArgumentParser(description="Detect an incomplete refactor.")
    parser.add_argument("--root", default=".", help="project root to check")
    parser.add_argument("--old", required=True,
                        help="comma-separated old identifiers that must be gone")
    parser.add_argument("--removed", default="",
                        help="comma-separated paths that must not exist")
    parser.add_argument("--allow", default="",
                        help="comma-separated files allowed to mention an old name")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    old_names = [n.strip() for n in args.old.split(",") if n.strip()]
    removed = [p.strip() for p in args.removed.split(",") if p.strip()]
    allowed = {a.strip() for a in args.allow.split(",") if a.strip()}
    patterns = {name: re.compile(r"\b" + re.escape(name) + r"\b") for name in old_names}

    hits = []  # (kind, path, line, detail)

    for removed_path in removed:
        full = os.path.join(root, removed_path)
        if os.path.exists(full):
            hits.append(("removed-path", removed_path, 0,
                         "path still exists"))

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for filename in sorted(filenames):
            if filename in SKIP_FILES:
                continue
            full = os.path.join(dirpath, filename)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if rel in allowed or filename in allowed:
                continue
            try:
                with open(full, "rb") as f:
                    raw = f.read()
            except OSError:
                continue
            if b"\x00" in raw:
                continue  # binary file
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                for name, pattern in patterns.items():
                    if pattern.search(line):
                        kind = "stale-test" if is_test_path(rel) else "old-name"
                        hits.append((kind, rel, lineno,
                                     "old identifier '%s' still referenced" % name))

    if not hits:
        print("clean: no leftovers (%d old identifier(s), %d removed path(s) checked)"
              % (len(old_names), len(removed)))
        return 0

    for kind, path, lineno, detail in hits:
        location = "%s:%d" % (path, lineno) if lineno else path
        print("%s\t%s\t%s" % (kind, location, detail))
    kinds = {}
    for kind, _, _, _ in hits:
        kinds[kind] = kinds.get(kind, 0) + 1
    print("FAIL: %d leftover(s) (%s)"
          % (len(hits), ", ".join("%s=%d" % kv for kv in sorted(kinds.items()))))
    return 1


if __name__ == "__main__":
    sys.exit(main())
