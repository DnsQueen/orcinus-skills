#!/usr/bin/env python3
"""Check a revision's CI attestation, live (0.11.0).

`gh attestation verify` needs a FILE subject (there is no
--subject-digest mode), so the attested subject is a file holding
the tree content digest: CI writes it with
`python3 scripts/content_digest.py > content-digest.txt` and
attests it in the `attest` job (.github/workflows/ci.yml). This
module recomputes that digest itself (scripts/content_digest.py,
imported — never inlined, never caller-supplied), writes it to a
temp file byte-identically to what CI writes (digest + newline:
gh hashes the file bytes, so any other spelling attests a
different subject), and runs `gh attestation verify` on it with
the identity pinned: --repo, --signer-workflow
(<repo>/.github/workflows/ci.yml), and --source-digest (the
revision's full SHA).

Three outcomes, kept distinct — a transition gate must tell
"never attested" from "could not check":
- verified: gh exited 0 AND its --format json output lists the
  attested file's sha256 among the statement subjects. The JSON
  check matters: gh < 2.67.0 returned exit 0 when no
  attestations were present (CVE-2025-25204), so exit 0 alone is
  not proof — an empty array, or a subject digest that is not
  this file's, is not-verified.
- not_verified: gh proves the absence — "no attestations found"
  or the attestations API 404ing for the subject, or attestations
  that exist but match nothing. The revision was never attested
  in that repo's CI.
- unavailable: the check could not run — gh missing, not
  authenticated (exit 4), network error, API rate limit, an
  unrecognised gh failure, or an unparsable success output. The
  exact cause is the reason; never exit 0, never "not verified"
  on an unknown failure (absence must be proven, not assumed).

Forks: --attest-repo / --signer-workflow derive from the repo's
origin remote (the GitHub owner/repo it was cloned from), so a
fork's attestation proves a run in THAT repo's CI, not
upstream's. With no GitHub origin the default is upstream,
DnsQueen/orcinus-skills; --attest-repo overrides the derivation.

Offline: --bundle verifies from a bundle downloaded with
`gh attestation download` instead of the API. Offline verification
still needs a trusted root: gh fetches Sigstore's trusted root
over the network by default, so pass --custom-trusted-root with a
cached trusted_root.jsonl, or the check fails as unavailable.

Usage:
    python3 scripts/verify_attestation.py --repo <repo path> --revision <sha>
        [--attest-repo <owner/repo>] [--bundle <path>]
        [--custom-trusted-root <path>]
Exit 0 verified (prints repo, workflow, source digest, subject
digest); exit 1 not verified; exit 2 unavailable.

Stdlib only.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# content_digest.py lives beside this file; the import is by path,
# like scripts/state.py's — the digest algorithm has exactly one
# definition, and this module never hashes a tree itself.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from content_digest import ContentDigestError, content_digest  # noqa: E402

DEFAULT_ATTEST_REPO = "DnsQueen/orcinus-skills"
SIGNER_WORKFLOW_PATH = ".github/workflows/ci.yml"
_GH_TIMEOUT_S = 120

# Markers in gh's stderr, from the CLI's own messages and
# Homebrew's attestation check (which matches the same strings):
# "no attestations found" and an API 404 mean the subject has no
# attestation; exit 4 / HTTP 401 mean gh is not authenticated.
_NOT_VERIFIED_MARKERS = (
    "no attestations found",
    "no attestation",
    "http 404",
    "none of the attestations matched",
    "does not match any digest",
    "provided artifact digest does not match",
)
_UNAVAILABLE_MARKERS = (
    "auth",
    "http 401",
    "http 403",
    "http 429",
    "rate limit",
    "network",
    "connection",
    "timed out",
    "timeout",
    "tls",
    "certificate",
    "trusted root",
    "failed to fetch",
    "eof",
    "dns",
    "temporary failure",
)

_GITHUB_ORIGIN_RE = re.compile(
    r"^(?:git@github\.com:|https://github\.com/)(?P<repo>[^/\s]+/[^/\s]+?)(?:\.git)?/?$"
)


@dataclass(frozen=True)
class AttestationResult:
    """One outcome of the live check. `status` is "verified",
    "not_verified", or "unavailable"; `reason` is empty when
    verified, otherwise the exact cause."""

    status: str
    reason: str = ""


def attest_repo_for(repo):
    """The owner/repo whose CI attests this checkout: the git
    origin remote when it names a GitHub repo, else the upstream
    default. A fork's origin is the fork, so its attestation
    proves a run in the fork's CI, not upstream's."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return DEFAULT_ATTEST_REPO
    if proc.returncode != 0:
        return DEFAULT_ATTEST_REPO
    match = _GITHUB_ORIGIN_RE.match(proc.stdout.strip())
    return match.group("repo") if match else DEFAULT_ATTEST_REPO


def _resolve_revision(repo, revision):
    """The full SHA `revision` resolves to in `repo`, or None
    when it does not resolve."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", f"{revision}^{{commit}}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _statement_subject_digests(data):
    """Every subject digest hex in a `gh attestation verify
    --format json` output: the set of digests the verified
    attestations actually cover."""
    digests = set()
    if not isinstance(data, list):
        return digests
    for entry in data:
        if not isinstance(entry, dict):
            continue
        result = entry.get("verificationResult")
        statement = result.get("statement") if isinstance(result, dict) else None
        subjects = statement.get("subject") if isinstance(statement, dict) else None
        if not isinstance(subjects, list):
            continue
        for subject in subjects:
            if not isinstance(subject, dict):
                continue
            digest = subject.get("digest")
            if isinstance(digest, dict):
                for value in digest.values():
                    if isinstance(value, str):
                        digests.add(value.lower())
            elif isinstance(digest, str):
                digests.add(digest.lower())
    return digests


def _classify_failure(proc):
    """A non-zero gh run as (status, reason): not_verified only
    when gh proves the absence; anything else is unavailable
    with gh's exact stderr — an unknown failure never becomes a
    claim that no attestation exists."""
    stderr = (proc.stderr or "").strip()
    if proc.returncode == 4:
        return AttestationResult("unavailable", stderr or "gh is not authenticated (exit 4)")
    lowered = stderr.lower()
    if any(marker in lowered for marker in _NOT_VERIFIED_MARKERS):
        return AttestationResult("not_verified", stderr)
    if any(marker in lowered for marker in _UNAVAILABLE_MARKERS):
        return AttestationResult("unavailable", stderr)
    return AttestationResult(
        "unavailable",
        stderr or f"gh attestation verify exited {proc.returncode} with no output",
    )


def verify_attestation(repo, revision, attest_repo=None, bundle=None, custom_trusted_root=None):
    """The live attestation check for `revision` in `repo`.
    Returns an AttestationResult; never raises for a gh outcome
    (a missing gh, a timeout, an unresolvable revision, and a
    digest that cannot be computed are all "unavailable" with
    the cause). The digest is recomputed here from the revision's
    tree, never taken from the caller."""
    repo = Path(repo)
    full_sha = _resolve_revision(repo, revision)
    if full_sha is None:
        return AttestationResult("unavailable", f"revision {revision!r} does not resolve in {repo}")
    try:
        digest = content_digest(repo, revision)
    except ContentDigestError as e:
        return AttestationResult("unavailable", f"cannot compute content_digest: {e}")
    attest_repo = attest_repo or attest_repo_for(repo)
    signer_workflow = f"{attest_repo}/{SIGNER_WORKFLOW_PATH}"
    # Byte-identical to what CI writes: the digest plus the
    # newline from `content_digest.py > content-digest.txt`.
    subject_bytes = f"{digest}\n".encode("utf-8")
    file_sha256 = hashlib.sha256(subject_bytes).hexdigest()
    with tempfile.NamedTemporaryFile(
        mode="wb", prefix="content-digest-", suffix=".txt", delete=False
    ) as f:
        f.write(subject_bytes)
        subject_path = f.name
    try:
        argv = [
            "gh",
            "attestation",
            "verify",
            subject_path,
            "--repo",
            attest_repo,
            "--signer-workflow",
            signer_workflow,
            "--source-digest",
            full_sha,
            "--format",
            "json",
        ]
        if bundle is not None:
            argv += ["--bundle", str(bundle)]
        if custom_trusted_root is not None:
            argv += ["--custom-trusted-root", str(custom_trusted_root)]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=_GH_TIMEOUT_S)
        except FileNotFoundError as e:
            return AttestationResult("unavailable", f"gh is not installed: {e}")
        except subprocess.TimeoutExpired:
            return AttestationResult(
                "unavailable", f"gh attestation verify timed out after {_GH_TIMEOUT_S}s"
            )
        except OSError as e:
            return AttestationResult("unavailable", f"could not run gh: {e}")
        if proc.returncode != 0:
            return _classify_failure(proc)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return AttestationResult(
                "unavailable",
                "gh exited 0 but its --format json output could not be parsed: "
                f"{proc.stdout.strip()[:200]!r}",
            )
        if not isinstance(data, list) or not data:
            # CVE-2025-25204: an empty success is not a verification.
            return AttestationResult("not_verified", "gh verified no attestations for this subject")
        if file_sha256 not in _statement_subject_digests(data):
            return AttestationResult(
                "not_verified",
                "gh exited 0 but no verified attestation covers this subject "
                f"(subject digest sha256:{file_sha256})",
            )
        return AttestationResult("verified")
    finally:
        Path(subject_path).unlink(missing_ok=True)


def main(argv):
    parser = argparse.ArgumentParser(
        description="Check a revision's CI attestation, live.",
        usage="python3 scripts/verify_attestation.py --repo <repo> --revision <sha> "
        "[--attest-repo <owner/repo>] [--bundle <path>] [--custom-trusted-root <path>]",
    )
    parser.add_argument("--repo", required=True, help="the repo path to check")
    parser.add_argument("--revision", required=True, help="the revision to check (a commit SHA)")
    parser.add_argument(
        "--attest-repo",
        default=None,
        help="the owner/repo whose CI attests the revision "
        "(default: derived from the repo's origin, else DnsQueen/orcinus-skills)",
    )
    parser.add_argument(
        "--bundle",
        default=None,
        help="verify from a bundle on disk (downloaded with "
        "`gh attestation download`) instead of the GitHub API",
    )
    parser.add_argument(
        "--custom-trusted-root",
        default=None,
        help="a cached trusted_root.jsonl for offline verification "
        "(without one, offline verification fails as unavailable)",
    )
    args = parser.parse_args(argv[1:])
    attest_repo = args.attest_repo or attest_repo_for(args.repo)
    result = verify_attestation(
        args.repo,
        args.revision,
        attest_repo=attest_repo,
        bundle=args.bundle,
        custom_trusted_root=args.custom_trusted_root,
    )
    if result.status == "verified":
        # The check just recomputed these, so this re-read is a
        # print, not a second trust decision — but a repo that
        # vanished mid-run must still fail closed, not traceback.
        try:
            digest = content_digest(args.repo, args.revision)
            full_sha = _resolve_revision(args.repo, args.revision)
        except ContentDigestError as e:
            print(f"unavailable: cannot recompute content_digest: {e}")
            return 2
        if full_sha is None:
            print(f"unavailable: revision {args.revision!r} no longer resolves")
            return 2
        print(
            f"verified: repo={attest_repo} "
            f"workflow={attest_repo}/{SIGNER_WORKFLOW_PATH} "
            f"source-digest={full_sha} "
            f"subject-digest={digest}"
        )
        return 0
    if result.status == "not_verified":
        print(f"not verified: {result.reason}")
        return 1
    print(f"unavailable: {result.reason}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
