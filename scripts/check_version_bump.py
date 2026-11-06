#!/usr/bin/env python3
"""Fail a push that changes shipped plugin content without a version
bump and a changelog entry.

A push is a release when it changes anything the plugin ships:
skills/, agents/, or commands/. Such a push must bump the version in
.claude-plugin/plugin.json AND change CHANGELOG.md in the same range.
A docs-only push needs no bump; a version bump without a changelog
entry (or vice versa) still fails — the two travel together.

The check is that the version CHANGED, not that it increased: the
1.0.0 → 0.9.0 correction (2026-11-06) lowered an unreleased version
number to the honest pre-1.0 value, and direction is the release
process's job (tags), not this script's.

Usage (CI, push events only — the repo's workflow is direct pushes
to main; a PR merged to main is caught by the merge push, whose diff
includes the PR's skill changes):

  git fetch --depth=1 origin <base>   # the base commit is not in a
                                      # depth-1 checkout
  python3 scripts/check_version_bump.py --base <before-sha> --head <sha>

A base of all zeros (first push to a new branch) diffs against the
empty tree, so the initial plugin.json + CHANGELOG.md count as the
bump. Exit 0 = the push is fine; exit 1 = the bump is missing.

This script is stdlib-only and needs only git and python3.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
# What the plugin ships. docs/, evals/, examples/ and scripts/ are
# not shipped plugin content, so changing them needs no bump.
SHIPPED_PREFIXES = ("skills/", "agents/", "commands/")
PLUGIN_JSON = ".claude-plugin/plugin.json"
CHANGELOG = "CHANGELOG.md"


def _git(repo, *args):
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=60)
    return proc.returncode, proc.stdout.strip()


def _resolve(repo, ref):
    """A ref, or the empty tree for a first push (base of all
    zeros). Any other unresolvable ref is an error, not a fallback:
    silently diffing against the empty tree would make any push
    pass, because everything differs from an empty tree."""
    if not ref or set(ref) == {"0"}:
        return EMPTY_TREE
    rc, out = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if rc != 0 or not out:
        raise RuntimeError(
            f"cannot resolve base {ref!r} — fetch it first "
            f"(git fetch --depth=1 origin {ref})")
    return out


def _changed_files(repo, base, head):
    # Two-dot diff: it compares the two trees directly, with no
    # merge-base needed. A three-dot (merge-base) diff fails in CI,
    # where the checkout is depth-1 and only the base commit is
    # fetched — the two commits share no reachable merge-base there
    # (2026-11-06: the version-bump job failed with exit 2 on a
    # docs-only push for exactly this reason). Two-dot is also the
    # right semantic here: for a linear push it is the push's own
    # changes, and for a merge push it is everything the merge
    # introduced against the old main.
    args = ["diff", "--name-only", f"{base}..{head}"]
    rc, out = _git(repo, *args)
    if rc != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out}")
    return [line for line in out.splitlines() if line]


def _plugin_version(repo, ref):
    rc, out = _git(repo, "show", f"{ref}:{PLUGIN_JSON}")
    if rc != 0:
        return None
    try:
        return json.loads(out).get("version")
    except (json.JSONDecodeError, AttributeError):
        return None


def check(repo, base, head):
    """Return (ok, message) for the range base..head."""
    base = _resolve(repo, base)
    head = _resolve(repo, head)
    files = _changed_files(repo, base, head)
    shipped = [f for f in files
               if f.startswith(SHIPPED_PREFIXES)]
    if not shipped:
        return True, ("no shipped plugin content changed "
                      "(skills/, agents/, commands/); "
                      "no version bump needed")
    version_changed = _plugin_version(repo, base) != _plugin_version(
        repo, head)
    changelog_changed = CHANGELOG in files
    if version_changed and changelog_changed:
        return True, (f"shipped content changed ({len(shipped)} "
                      f"file(s)); version bumped and {CHANGELOG} "
                      f"updated")
    missing = []
    if not version_changed:
        missing.append(f"a version bump in {PLUGIN_JSON}")
    if not changelog_changed:
        missing.append(f"an entry in {CHANGELOG}")
    return False, (f"shipped plugin content changed "
                   f"({', '.join(shipped[:3])}"
                   f"{'...' if len(shipped) > 3 else ''}) but the "
                   f"push is missing {' and '.join(missing)} — the "
                   f"version bump and the changelog entry travel "
                   f"together")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True,
                        help="base revision (e.g. the push's before SHA)")
    parser.add_argument("--head", required=True,
                        help="head revision (e.g. the push's SHA)")
    parser.add_argument("--repo", default=str(ROOT),
                        help="repo to check (default: this repo)")
    args = parser.parse_args(argv)
    try:
        ok, message = check(Path(args.repo), args.base, args.head)
    except RuntimeError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2
    print(("OK: " if ok else "FAIL: ") + message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
