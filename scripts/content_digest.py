#!/usr/bin/env python3
"""The content digest for `.orcinus/state.json` (docs/project-state.md).

VERIFIED is bound to the *content* of the project, not to the commit
SHA: a commit that only records the state file or an evidence bundle
must not reset the stage, or VERIFIED could never survive its own
commit. The digest is sha256 over the sorted `git ls-tree -r` listing
of the revision's tree, excluding the paths under `.orcinus/` and
`docs/verification/` — the two places where recording verification
itself writes. `revision` (the commit SHA) stays in state.json as the
human-readable pointer; the digest is what VERIFIED is bound to.

Algorithm (the spec's single definition; keep this docstring and
docs/project-state.md in agreement):
1. Run `git ls-tree -r <rev>`; each line is
   `<mode> SP <type> SP <sha> TAB <path>`.
2. Drop lines whose path is under `.orcinus/` or `docs/verification/`
   (exact directory prefixes, with the slash — a file named
   `.orcinus-notes.txt` still counts).
3. Sort the remaining lines by path.
4. Join with "\n" (no trailing newline), UTF-8, sha256 hex.
   The digest is recorded as `sha256:<hex>`.

The digest covers committed content only: a dirty working tree is
never VERIFIED, because the digest would not describe what was
verified. Record VERIFIED only when the tree is clean.

Usage: python3 scripts/content_digest.py [repo] [rev]
Exit 0 and print the digest; exit 2 for a usage error or when git
cannot produce the tree (not a repository, unknown revision).
"""

import hashlib
import subprocess
import sys
from pathlib import Path

EXCLUDED_PREFIXES = (".orcinus/", "docs/verification/")


class ContentDigestError(Exception):
    pass


def content_digest(repo, rev="HEAD"):
    """The content digest of a revision's tree. See the module
    docstring for the exact algorithm."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", "-r", rev],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise ContentDigestError(f"cannot list the tree of {rev!r} in {repo}: {e}")
    lines = []
    for line in proc.stdout.splitlines():
        if "\t" not in line:
            raise ContentDigestError(f"unexpected ls-tree line (no tab): {line!r}")
        path = line.split("\t", 1)[1]
        if any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            continue
        lines.append(line)
    lines.sort(key=lambda line: line.split("\t", 1)[1])
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def main(argv):
    if len(argv) > 3:
        print("usage: python3 scripts/content_digest.py [repo] [rev]", file=sys.stderr)
        return 2
    repo = Path(argv[1]) if len(argv) > 1 else Path.cwd()
    rev = argv[2] if len(argv) > 2 else "HEAD"
    try:
        print(content_digest(repo, rev))
    except ContentDigestError as e:
        print(f"content_digest: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
