#!/usr/bin/env python3
"""The content digest for `.orcinus/state.json` (docs/project-state.md).

VERIFIED is bound to the *content* of the project, not to the commit
SHA: a commit that only records the state file or an evidence bundle
must not reset the stage, or VERIFIED could never survive its own
commit. The digest is sha256 over the sorted `git ls-tree -r -z` listing
of the revision's tree, excluding the paths under `.orcinus/` and
`docs/verification/` — the two places where recording verification
itself writes. `revision` (the commit SHA) stays in state.json as the
human-readable pointer; the digest is what VERIFIED is bound to.

Algorithm (the spec's single definition; keep this docstring and
docs/project-state.md in agreement):
1. Run `git ls-tree -r -z <rev>` and read the output as bytes;
   each record is `<mode> SP <type> SP <sha> TAB <path>`, records
   separated by NUL. The -z matters: without it git quotes
   non-ASCII paths (core.quotePath=true, the default), so one
   tree could hash two ways and a quoted `.orcinus/` path escaped
   the exclusion below (reviewer 4, F2, round 5).
2. Drop records whose path is under `.orcinus/` or
   `docs/verification/` (exact directory prefixes, with the slash
   — a file named `.orcinus-notes.txt` still counts).
3. Sort the remaining records by path bytes.
4. Join with b"\\n" (no trailing newline), sha256 hex.
   The digest is recorded as `sha256:<hex>`.

Format version 2 (round 5): version 1 hashed git's text display
(`ls-tree -r`, no -z), which quotes non-ASCII paths — so a tree
with a Persian filename had a different digest under
core.quotePath=true than under false, and quoted state/evidence
paths were not excluded. Digests computed by v1 on trees with
non-ASCII paths are NOT comparable with v2 digests; on ASCII-only
trees v1 and v2 agree byte for byte, so nothing already recorded
there changes.

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

# The digest algorithm's format version (round 5). Bump it whenever
# the serialization changes, and say so in the docstring above and
# in docs/project-state.md — a digest from one version must never
# be silently equated with a digest from another.
FORMAT_VERSION = 2

EXCLUDED_PREFIXES = (b".orcinus/", b"docs/verification/")


class ContentDigestError(Exception):
    pass


def content_digest(repo, rev="HEAD"):
    """The content digest of a revision's tree. See the module
    docstring for the exact algorithm."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", "-r", "-z", rev],
            capture_output=True,
            check=True,
            timeout=60,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise ContentDigestError(f"cannot list the tree of {rev!r} in {repo}: {e}")
    records = []
    for record in proc.stdout.split(b"\0"):
        if not record:
            continue  # the -z output ends with a trailing NUL
        if b"\t" not in record:
            raise ContentDigestError(f"unexpected ls-tree record (no tab): {record!r}")
        path = record.split(b"\t", 1)[1]
        if any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            continue
        records.append(record)
    records.sort(key=lambda record: record.split(b"\t", 1)[1])
    digest = hashlib.sha256(b"\n".join(records)).hexdigest()
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
