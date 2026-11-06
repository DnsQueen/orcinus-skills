#!/usr/bin/env python3
"""Fail a push that changes shipped plugin content without a version
bump and a changelog entry.

A push is a release when it changes anything the plugin ships:
skills/, agents/, or commands/. Such a push must bump the version in
.claude-plugin/plugin.json AND change CHANGELOG.md in the same range.
A docs-only push needs no bump, and a CHANGELOG-only push needs
no version bump: the version rule is one-directional. A version
bump without a changelog entry fails even when nothing shipped
changed — a version number with no release notes is a release
that never happened.

The check is that the version CHANGED, not that it increased: the
1.0.0 → 0.9.0 correction (2026-11-06) lowered an unreleased version
number to the honest pre-1.0 value, and direction is the release
process's job (tags), not this script's.

Usage (CI, push and pull_request events — the workflow fetches the
base commit; for a PR that is the PR's base SHA, for a push the
push's before SHA):

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
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60
    )
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
            f"cannot resolve base {ref!r} — fetch it first (git fetch --depth=1 origin {ref})"
        )
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
    """Return (ok, message) for the range base..head.

    Two independent rules:
    1. A shipped change (skills/, agents/, commands/) needs BOTH a
       version bump and a changelog entry.
    2. A version bump needs a changelog entry even when nothing
       shipped changed.
    Rule 2 is one-directional: a CHANGELOG-only push needs no bump.
    """
    base = _resolve(repo, base)
    head = _resolve(repo, head)
    files = _changed_files(repo, base, head)
    shipped = [f for f in files if f.startswith(SHIPPED_PREFIXES)]
    version_changed = _plugin_version(repo, base) != _plugin_version(repo, head)
    changelog_changed = CHANGELOG in files
    missing = []
    if shipped and not version_changed:
        missing.append(f"a version bump in {PLUGIN_JSON}")
    if (shipped or version_changed) and not changelog_changed:
        missing.append(f"an entry in {CHANGELOG}")
    if missing:
        if shipped:
            what = (
                f"shipped plugin content changed "
                f"({', '.join(shipped[:3])}"
                f"{'...' if len(shipped) > 3 else ''})"
            )
        else:
            what = (
                f"the version was bumped "
                f"({_plugin_version(repo, base)!r} -> "
                f"{_plugin_version(repo, head)!r})"
            )
        return False, (
            f"{what} but the push is missing "
            f"{' and '.join(missing)} — the version bump "
            f"and the changelog entry travel together"
        )
    if shipped:
        return True, (
            f"shipped content changed ({len(shipped)} "
            f"file(s)); version bumped and {CHANGELOG} "
            f"updated"
        )
    if version_changed:
        return True, (f"version bumped and {CHANGELOG} updated; no shipped content changed")
    return True, (
        "no shipped plugin content changed "
        "(skills/, agents/, commands/) and the version "
        "did not change; no version bump needed"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="base revision (e.g. the push's before SHA)")
    parser.add_argument("--head", required=True, help="head revision (e.g. the push's SHA)")
    parser.add_argument("--repo", default=str(ROOT), help="repo to check (default: this repo)")
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
