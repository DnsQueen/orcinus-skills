#!/usr/bin/env python3
"""Fail a push that changes shipped plugin content without a version
bump and a changelog entry.

A push is a release when it changes anything the plugin ships:
skills/, agents/, commands/, or scripts/. Such a push must bump the
version in .claude-plugin/plugin.json AND change CHANGELOG.md in the
same range. A docs-only push needs no bump, and a CHANGELOG-only push
needs no version bump: the version rule is one-directional. A version
bump without a changelog entry fails even when nothing shipped
changed — a version number with no release notes is a release
that never happened.

The version must INCREASE, not merely change: after the first
release a downgrade (0.9.1 -> 0.9.0) is a mistake, not a correction
— the 1.0.0 -> 0.9.0 correction (2026-11-06) predates the first
release tag, when no release existed to protect. Two comparisons:
against the base version (the version the range started from) and
against the latest release tag vX.Y.Z, when one exists (CI fetches
the tags before running this script; locally, no tags means the tag
check is skipped). A version that does not parse as X.Y.Z is not
this script's failure to report — the repo validator enforces
semver on plugin.json.

Usage (CI, push and pull_request events — the workflow fetches the
base commit and the release tags; for a PR that is the PR's base
SHA, for a push the push's before SHA):

  git fetch --depth=1 origin <base>   # the base commit is not in a
                                      # depth-1 checkout
  git fetch --depth=1 origin --tags   # the release tags, for the
                                      # increase-against-latest-tag check
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
# What the plugin ships: anything whose change alters what the
# plugin does when installed. skills/, agents/ and commands/ are
# the plugin content; scripts/ is included because the plugin
# installs the whole repo (README: "the plugin is the whole
# repo"), so the root scripts are present in that install — a
# change to scripts/content_digest.py with no bump used to pass
# (reviewer 4, F6, round 5). docs/, evals/ and examples/ are
# dev-docs only: they ship in the same checkout but change no
# behaviour. Round 6 (S11) added .claude-plugin/ and hermes/ (both
# ship) and the package.json / package-lock.json pair — the pinned
# plugin-validate CLI install ships. The two root files are exact
# matches, not prefixes: a prefix match would also catch e.g.
# package.jsonx, which is not the manifest.
SHIPPED_PREFIXES = ("skills/", "agents/", "commands/", "scripts/", ".claude-plugin/", "hermes/")
SHIPPED_FILES = ("package.json", "package-lock.json")
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
            f"cannot resolve base {ref!r} — fetch it first "
            f"(git fetch --depth=1 origin {ref}); if the base was "
            f"force-pushed away it no longer exists upstream — "
            f"rebase onto the new main instead"
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
    # introduced against the old main. -z, read as bytes: without
    # it git quotes non-ASCII paths (core.quotePath=true, the
    # default), so a Persian filename came back as
    # '"skills/\\330\\...' and the shipped-prefix filter missed it
    # (reviewer 3, #1, round 5).
    args = ["diff", "-z", "--name-only", f"{base}..{head}"]
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return [p.decode("utf-8", "surrogateescape") for p in proc.stdout.split(b"\0") if p]


def _plugin_version(repo, ref):
    rc, out = _git(repo, "show", f"{ref}:{PLUGIN_JSON}")
    if rc != 0:
        return None
    try:
        return json.loads(out).get("version")
    except (json.JSONDecodeError, AttributeError):
        return None


def _semver_tuple(version):
    """(major, minor, patch) for a plain X.Y.Z version (an optional
    leading 'v' is allowed, for tags), or None when it is not one.
    The plugin.json version is enforced semver by the repo
    validator; an unparsable version here is not this script's
    failure to report, so the increase check skips it."""
    if version is None:
        return None
    v = version.strip()
    if v.startswith("v"):
        v = v[1:]
    parts = v.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def _latest_tag_version(repo):
    """The highest semver release tag in this repo as ((major,
    minor, patch), tag), or None when there is none. Local tags
    only: CI fetches them before running this script, so a repo
    with no tags (a fresh clone, the first release) simply skips
    the tag check."""
    rc, out = _git(repo, "tag", "--sort=-v:refname", "--list", "v*")
    if rc != 0:
        return None
    best = None
    for line in out.splitlines():
        tag = line.strip()
        parsed = _semver_tuple(tag)
        if parsed is not None and (best is None or parsed > best[0]):
            best = (parsed, tag)
    return best


def check(repo, base, head):
    """Return (ok, message) for the range base..head.

    Three independent rules:
    1. A shipped change (skills/, agents/, commands/, scripts/)
       needs BOTH a version bump and a changelog entry.
    2. A version bump needs a changelog entry even when nothing
       shipped changed.
    3. When the version changes it must INCREASE: greater than the
       base version, and greater than the latest release tag when
       one exists (a downgrade, or a bump to an already-released
       version, fails).
    Rules 1 and 2 are one-directional: a CHANGELOG-only push needs
    no bump.
    """
    base = _resolve(repo, base)
    head = _resolve(repo, head)
    files = _changed_files(repo, base, head)
    shipped = [f for f in files if f.startswith(SHIPPED_PREFIXES) or f in SHIPPED_FILES]
    base_version = _plugin_version(repo, base)
    head_version = _plugin_version(repo, head)
    version_changed = base_version != head_version
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
            what = f"the version was bumped ({base_version!r} -> {head_version!r})"
        return False, (
            f"{what} but the push is missing "
            f"{' and '.join(missing)} — the version bump "
            f"and the changelog entry travel together"
        )
    if version_changed:
        base_v = _semver_tuple(base_version)
        head_v = _semver_tuple(head_version)
        if base_v is not None and head_v is not None and head_v <= base_v:
            return False, (
                f"the version went DOWN or sideways "
                f"({base_version!r} -> {head_version!r}) — a "
                f"release must increase the version; the "
                f"1.0.0 -> 0.9.0 correction predates the first "
                f"release tag and is not a pattern to repeat"
            )
        latest = _latest_tag_version(repo)
        if latest is not None and head_v is not None and head_v <= latest[0]:
            return False, (
                f"the version {head_version!r} is not greater "
                f"than the latest release tag {latest[1]!r} — "
                f"that version is already released"
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
        "(skills/, agents/, commands/, scripts/) and the version "
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
