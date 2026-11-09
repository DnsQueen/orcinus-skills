#!/usr/bin/env python3
"""Validate and transition `.orcinus/state.json` (round 6, 2-R2).

The state file was spec-only (docs/project-state.md + the digest
helper scripts/content_digest.py): nothing validated it, and nothing
enforced which stage could follow which. The schema lives in
scripts/state_schema.json; this module enforces it plus the
transition rules from docs/project-state.md.

The content digest is recomputed here, never supplied by the
caller (round 7, F-07): `transition()` computes it from the
revision's tree in the repo (scripts/content_digest.py, imported
— never inlined, so the algorithm has exactly one definition),
and `validate_state(..., repo=...)` recomputes the stored digest
for the state's revision and compares. A caller-supplied digest
was trusted input: any well-formed string was stored verbatim,
so Rule 2 only fired when the caller volunteered a change and a
hand-written approval reached RELEASE_READY. The old required
`--digest` flag is gone; `--expect-digest` only asserts against
the recomputed digest and is never stored.

0.11.0: the VERIFIED gate additionally requires a CI
attestation, checked LIVE at transition time
(scripts/verify_attestation.py — `gh attestation verify` on the
content digest, pinned to this repo's CI workflow and the
revision). A local PASS bundle is provisional: it proves the
bundle is complete and self-consistent, not that CI ran. The
attestation is never a recorded claim in the bundle — a state
file that says VERIFIED without a live check (or an explicit
targeted-rerun proof file, --attestation-proof) is refused.
`validate_state` keeps doing the local structural check only
(no network): the transition gate, not validate, enforces
attestation.

This is a local check, not the v1.1 tamper-proof enforcement layer:
any agent (or human) with write access can still edit the file
(project-state.md Rule 4). What this adds is a machine that refuses
an invalid file or an impossible transition instead of silently
recording it — and the next `validate` now DETECTS a hand-edited
digest, because the stored value is compared with the recomputed
one. Rewritten history yields a new revision (and digest), which
correctly fires Rule 2 rather than bypassing it.

Usage:
    python3 scripts/state.py validate <state.json> [--repo <repo>] [--no-require-head]
    python3 scripts/state.py transition <state.json> --to STAGE
        --revision <sha> [--expect-digest sha256:<hex>]
        [--evidence <bundle path>] [--attestation-proof <proof path>]
        [--note <text>] [--repo <repo>]

Stdlib only.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import types
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "scripts" / "state_schema.json"

# content_digest.py lives beside this file; state.py runs both as a
# script and imported by the tests, so the import is by path, not by
# package. The digest is the trusted value: it is computed in this
# process from git (import, not a subprocess — the algorithm is
# small, stdlib-only, and importing keeps one definition), never
# taken from the caller or the state file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from content_digest import ContentDigestError, content_digest  # noqa: E402

# The evidence validator lives in the orcinus-verify skill folder.
# It is imported, like the digest — but note the asymmetry: the
# digest is the trusted value (computed from git in this process),
# while the validator is only a checker (it judges whether a
# bundle file is a valid, consistent PASS bundle). A validator bug
# can refuse a good bundle, never mint a digest. The import is
# guarded so state.py still imports when the skill folder is
# absent (a lone copy), mirroring validate_evidence.py's own
# guarded record_check import; with no validator available,
# VERIFIED is refused instead of passed.
sys.path.insert(0, str(ROOT / "skills" / "orcinus-verify" / "scripts"))
_validate_evidence: types.ModuleType | None = None
try:
    import validate_evidence as _validate_evidence  # type: ignore[import-not-found]  # noqa: E402
except ImportError:
    pass

# The live attestation check lives beside this file
# (scripts/verify_attestation.py). Imported, like the digest —
# but guarded like the validator: with no checker available,
# VERIFIED is refused instead of passed. The seam is the
# `attestation_checker` parameter of transition(): it defaults
# to the real check, in production and in tests alike, and tests
# inject a stub explicitly, never by making the check optional.
_verify_attestation: types.ModuleType | None = None
try:
    import verify_attestation as _verify_attestation  # type: ignore[import-not-found]  # noqa: E402
except ImportError:
    pass

STAGES = ("BUILDING", "VERIFYING", "BLOCKED", "VERIFIED", "AWAITING_APPROVAL", "RELEASE_READY")

# Allowed transitions (docs/project-state.md): forward along the
# lifecycle, back to BUILDING on rework. RELEASE_READY is terminal.
# A content-digest change is not in this table: it forces BUILDING
# from any stage (Rule 2), handled in transition().
ALLOWED_TRANSITIONS = {
    "BUILDING": {"VERIFYING"},
    "VERIFYING": {"BLOCKED", "VERIFIED"},
    "BLOCKED": {"BUILDING"},
    "VERIFIED": {"AWAITING_APPROVAL", "BUILDING"},
    "AWAITING_APPROVAL": {"RELEASE_READY", "BUILDING"},
    "RELEASE_READY": set(),
}

_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIRED = (
    "format_version",
    "project",
    "stage",
    "revision",
    "content_digest",
    "evidence_bundle",
    "approval",
    "history",
)


def load_state(path):
    """Load a state file, or raise ValueError with a controlled
    message (never a traceback for a malformed file)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"cannot read state file: {e}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"state file is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("state file is not a JSON object")
    return data


def validate_state(data, repo=None, require_head=False):
    """Problems with a state dict, [] when valid. Mirrors
    scripts/state_schema.json (hand-rolled, stdlib only — the repo
    has no jsonschema dependency). This is the LOCAL structural
    check only: it never touches the network and never checks an
    attestation. A VERIFIED state that validates here may still
    never have been attested — the transition gate (transition(),
    0.11.0) is what enforces attestation, at the moment VERIFIED
    is minted. With `repo` given, the stored digest is also
    recomputed from the state's revision and compared: a stored
    digest that does not match the tree it claims to describe is
    corrupt, not verified (F-07) — this is what detects a
    hand-edited state file. With `repo` None only the structural
    checks run. With `require_head` (round 8, FND-008; the
    `validate` CLI passes it by default) the state's revision
    must also be HEAD: a state for a revision HEAD has moved past
    is stale, not valid — the digest may still match its own
    revision, but the stage no longer describes the current tree.
    `require_head` defaults off for in-process callers
    (transition() has its own stage-specific staleness refusal);
    pass it explicitly to inspect a state as the CLI does, or
    --no-require-head on the CLI to inspect a historical state on
    purpose."""
    problems = []
    if not isinstance(data, dict):
        return ["state is not an object"]
    for field in _REQUIRED:
        if field not in data:
            problems.append(f"missing required field: {field}")
    if data.get("format_version") != 2:
        problems.append("format_version must be 2")
    project = data.get("project")
    if project is not None and (not isinstance(project, str) or not project.strip()):
        problems.append("project must be a non-empty string")
    stage = data.get("stage")
    if stage is not None and stage not in STAGES:
        problems.append(f"stage is {stage!r}, expected one of {', '.join(STAGES)}")
    revision = data.get("revision")
    if revision is not None and (not isinstance(revision, str) or not _SHA_RE.match(revision)):
        problems.append("revision must be a commit SHA (7-40 hex chars)")
    digest = data.get("content_digest")
    if digest is not None and (not isinstance(digest, str) or not _DIGEST_RE.match(digest)):
        problems.append("content_digest must be 'sha256:<64 hex chars>'")
    if stage == "VERIFIED" and not data.get("evidence_bundle"):
        problems.append(
            "VERIFIED requires evidence_bundle (a state without one is corrupt, not verified)"
        )
    approval = data.get("approval")
    if approval is not None:
        if not isinstance(approval, dict):
            problems.append("approval must be an object or null")
        elif stage == "RELEASE_READY":
            if approval.get("content_digest") != digest:
                problems.append("approval content_digest does not match the state's content_digest")
    if stage == "RELEASE_READY" and not approval:
        problems.append("RELEASE_READY requires approval")
    history = data.get("history")
    if history is not None:
        if not isinstance(history, list):
            problems.append("history must be an array")
        else:
            for i, entry in enumerate(history):
                if not isinstance(entry, dict):
                    problems.append(f"history[{i}] is not an object")
                    continue
                if entry.get("stage") not in STAGES:
                    problems.append(f"history[{i}].stage is not a stage")
                if not isinstance(entry.get("revision"), str) or not _SHA_RE.match(
                    entry.get("revision") or ""
                ):
                    problems.append(f"history[{i}].revision must be a commit SHA")
                if not isinstance(entry.get("content_digest"), str) or not _DIGEST_RE.match(
                    entry.get("content_digest") or ""
                ):
                    problems.append(f"history[{i}].content_digest must be a sha256 digest")
    if repo is not None:
        # Evidence referenced by the state must exist; a VERIFIED
        # state must point at a bundle that validates with verdict
        # PASS (Rule 1: a state that says VERIFIED without an
        # evidence_bundle that validates is corrupt, not verified).
        problems.extend(
            _evidence_problems(
                data.get("evidence_bundle"),
                repo,
                require_valid=(stage == "VERIFIED"),
                expected_revision=(
                    revision if isinstance(revision, str) and _SHA_RE.match(revision) else None
                ),
            )
        )
        # Recompute, never trust: the stored digest is compared
        # with the digest of the revision's tree. A mismatch means
        # the file was edited by hand or history was rewritten —
        # either way the stage it claims is not verified. Only a
        # well-formed revision/digest pair is recomputed; a
        # malformed one is already a problem above.
        if (
            isinstance(revision, str)
            and _SHA_RE.match(revision)
            and isinstance(digest, str)
            and _DIGEST_RE.match(digest)
        ):
            try:
                recomputed = content_digest(repo, revision)
            except ContentDigestError as e:
                problems.append(f"cannot recompute content_digest for revision {revision!r}: {e}")
            else:
                if recomputed != digest:
                    problems.append(
                        "content_digest does not match the recomputed digest "
                        f"for revision {revision!r} (recomputed {recomputed}): "
                        "the state file was edited by hand, or history was rewritten"
                    )
        if require_head:
            # FND-008: the digest above proves the state matches
            # its own revision, not that the revision is current.
            # A stale revision is a problem, not a pass.
            head = _head_revision(repo)
            if head is None:
                problems.append(
                    f"cannot resolve HEAD in {repo}: --require-head cannot "
                    "prove the state revision is current"
                )
            elif (
                isinstance(revision, str)
                and _SHA_RE.match(revision)
                and _resolve_revision(repo, revision) not in (None, head)
            ):
                problems.append(
                    f"state revision {revision!r} is stale: HEAD is {head} — "
                    "the state describes a revision HEAD has moved past "
                    "(move the state to HEAD first, or pass "
                    "--no-require-head to inspect a historical state)"
                )
    return problems


def _evidence_problems(value, repo, require_valid, expected_revision=None):
    """Problems with an evidence_bundle value. [] when the value
    is None (no bundle recorded). A blank value, a path that names
    no file, an unreadable bundle, or — when `require_valid` — a
    bundle the validator rejects or one whose verdict is not PASS,
    is a problem. Paths resolve against `repo`, never the working
    directory. When `expected_revision` is given, the bundle must
    also have been recorded on that revision (round 8, FND-004):
    a bundle recorded at R1 is not evidence for a state pinned
    at R2, even when R1 resolves in the repo."""
    if value is None:
        return []
    if not isinstance(value, str) or not value.strip():
        return ["evidence_bundle must not be blank"]
    path = Path(value)
    if not path.is_absolute():
        path = repo / path
    if not path.is_file():
        return [f"evidence_bundle {value!r} does not exist"]
    if not require_valid:
        return []
    if _validate_evidence is None:
        return ["evidence_bundle: validator unavailable, cannot verify the bundle"]
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        return [f"evidence_bundle {value!r} could not be read as JSON: {e}"]
    if not isinstance(bundle, dict):
        return [f"evidence_bundle {value!r} is not a JSON object"]
    try:
        schema = _validate_evidence.load_schema(_validate_evidence.SCHEMA_PATH)
        # Round 8, FND-004: pass the resolved repo so state
        # validation gains the same tree binding the validator
        # CLI has — the bundle's revision must resolve in this
        # repo and its checks must match that tree — and pass
        # the expected revision so the bundle must also have
        # been recorded on that revision, not merely somewhere
        # in this repo.
        problems = _validate_evidence.validate_bundle(
            bundle,
            schema,
            bundle_dir=path.parent,
            repo=repo,
            expected_revision=expected_revision,
        )
    except (ValueError, OSError, RecursionError) as e:
        return [f"evidence_bundle {value!r}: validator error: {e}"]
    if problems:
        return [f"evidence_bundle {value!r} does not validate: {'; '.join(problems)}"]
    if bundle.get("verdict") != "PASS":
        return [f"evidence_bundle {value!r} has verdict {bundle.get('verdict')!r}, not PASS"]
    return []


def _is_int(value):
    # bool is a subclass of int in Python; an exit code or a
    # junit count of True is not an integer.
    return type(value) is int


def _default_attestation_checker(repo, revision):
    """The live check, defaulting to verify_attestation: the same
    default in production and in tests. With no checker module
    available the result is unavailable, never verified."""
    if _verify_attestation is None:
        return types.SimpleNamespace(
            status="unavailable",
            reason="scripts/verify_attestation.py is not available",
        )
    return _verify_attestation.verify_attestation(repo, revision)


def _check_attestation_proof(proof_path, repo, revision, content_digest, fail_first_test=None):
    """Check an explicit targeted-rerun proof file against the
    recomputed digest. Raises ValueError on any mismatch — the
    proof's digest is compared, never trusted; the method must be
    "targeted-rerun"; the exit code must be 0; the junit counts
    must show a passing rerun (total == passed > 0); the proof
    must name the revision being transitioned to; and when the
    bundle has a fail-first test it must be listed in the proof's
    tests. Returns None when the proof is valid. The proof shape
    is {"method": "targeted-rerun", "revision": "<40-hex>",
    "content_digest": "<digest>", "tests": ["<nodeid>", ...],
    "junit": {"total": N, "passed": N}, "exit_code": 0}."""
    try:
        proof = json.loads(Path(proof_path).read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"attestation proof {proof_path!r} could not be read: {e}") from e
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"attestation proof {proof_path!r} is not valid JSON: {e}") from e
    if not isinstance(proof, dict):
        raise ValueError(f"attestation proof {proof_path!r} is not a JSON object")
    if proof.get("method") != "targeted-rerun":
        raise ValueError(
            f"attestation proof {proof_path!r} has method {proof.get('method')!r}, "
            "not 'targeted-rerun'"
        )
    proof_revision = proof.get("revision")
    if not isinstance(proof_revision, str) or not _SHA_RE.match(proof_revision):
        raise ValueError(
            f"attestation proof {proof_path!r} has revision {proof_revision!r}, not a commit SHA"
        )
    resolved_proof = _resolve_revision(repo, proof_revision)
    resolved = _resolve_revision(repo, revision)
    if resolved_proof is None or resolved is None or resolved_proof != resolved:
        raise ValueError(
            f"attestation proof {proof_path!r} is for revision {proof_revision!r}, not {revision!r}"
        )
    if proof.get("content_digest") != content_digest:
        raise ValueError(
            f"attestation proof {proof_path!r} has content_digest "
            f"{proof.get('content_digest')!r}, not the recomputed digest {content_digest}"
        )
    if not _is_int(proof.get("exit_code")) or proof["exit_code"] != 0:
        raise ValueError(
            f"attestation proof {proof_path!r} has exit_code {proof.get('exit_code')!r}, not 0"
        )
    junit = proof.get("junit")
    if not isinstance(junit, dict):
        raise ValueError(f"attestation proof {proof_path!r} has no junit counts")
    total, passed = junit.get("total"), junit.get("passed")
    if not _is_int(total) or not _is_int(passed) or total <= 0 or total != passed:
        raise ValueError(
            f"attestation proof {proof_path!r} junit counts do not show a passing rerun "
            f"(total={total!r}, passed={passed!r})"
        )
    tests = proof.get("tests")
    if not isinstance(tests, list) or not all(isinstance(t, str) for t in tests):
        raise ValueError(f"attestation proof {proof_path!r} has no tests list")
    if fail_first_test is not None and fail_first_test not in tests:
        raise ValueError(
            f"attestation proof {proof_path!r} does not list the fail-first test "
            f"{fail_first_test!r}: the rerun must be the rerun of that test"
        )
    return None


def _check_attestation_gate(repo, revision, computed, bundle_path, checker, proof_path):
    """The VERIFIED attestation gate, checked live at transition
    time — never a recorded claim. With an explicit proof file the
    proof is checked and the live check never runs; otherwise the
    checker (default: the real verify_attestation check) must
    return verified. Raises ValueError otherwise. No silent
    fallback: without a live check AND without a proof file the
    transition is refused, and the refusal names both options."""
    if proof_path is not None:
        fail_first_test = None
        if bundle_path is not None:
            path = Path(bundle_path)
            if not path.is_absolute():
                path = Path(repo) / path
            try:
                bundle = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
                raise ValueError(
                    f"cannot read the evidence bundle for the attestation proof: {e}"
                ) from e
            if isinstance(bundle, dict):
                fail_first = bundle.get("fail_first")
                if isinstance(fail_first, dict) and isinstance(fail_first.get("test"), str):
                    fail_first_test = fail_first["test"]
        _check_attestation_proof(proof_path, repo, revision, computed, fail_first_test)
        return
    check = checker if checker is not None else _default_attestation_checker
    result = check(repo, revision)
    status = getattr(result, "status", None)
    reason = getattr(result, "reason", "")
    if status == "verified":
        return
    if status == "not_verified":
        raise ValueError(
            f"VERIFIED requires a CI attestation for revision {revision!r} "
            f"(content digest {computed}): no matching attestation found "
            f"({reason}) — the revision was never attested in CI, or the "
            "attestation is for another revision or digest; re-run CI on "
            "this revision, or pass --attestation-proof <file> with a "
            "targeted-rerun proof"
        )
    if status == "unavailable":
        raise ValueError(
            f"VERIFIED requires a CI attestation for revision {revision!r}, "
            f"but the live check could not run ({reason}); re-run with gh "
            "authenticated and network access, or pass --attestation-proof "
            "<file> with a targeted-rerun proof"
        )
    raise ValueError(f"attestation check returned unknown status {status!r} — refusing VERIFIED")


def _git_output(repo, *args):
    """One git command's stdout, stripped — or None when git
    fails, times out, or cannot run. None is never a value to
    trust: every caller fails closed on it."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _head_revision(repo):
    """The full SHA of HEAD in `repo`, or None when HEAD does
    not resolve (empty repo, not a repo, git broken)."""
    return _git_output(repo, "rev-parse", "HEAD")


def _resolve_revision(repo, revision):
    """The full SHA `revision` resolves to in `repo`, or None
    when it does not resolve. `--verify ...^{commit}` is git's
    verifying form: a bare `rev-parse` would echo an unknown
    revision back instead of failing."""
    return _git_output(repo, "rev-parse", "--verify", f"{revision}^{{commit}}")


def _tree_is_dirty(repo, revision):
    """True when the working tree has uncommitted changes outside
    the two excluded dirs. Applies only when `revision` is HEAD:
    for an older revision the working tree cannot be proven clean
    for that revision, so it now fails closed (round 8, N-B4 —
    the old code returned False there, so a stale-revision
    transition skipped the dirty-tree gate entirely). The
    transition refuses stale revisions before this gate, so True
    here is defence-in-depth for any future caller, never a
    silent pass. `git ls-tree` cannot see untracked files, so
    this is a separate check from the digest. A git failure
    counts as dirty, never "clean by accident".
    `--untracked-files=normal` excludes ignored files; the
    `:(exclude)` pathspecs exclude the two places where recording
    verification itself writes, so committing the state file or
    an evidence bundle never counts as dirt (the same exclusions
    as the digest)."""
    try:
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if head.returncode != 0:
            return True
        if not head.stdout.strip().startswith(revision):
            return True
        status = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "status",
                "--porcelain",
                "--untracked-files=normal",
                "--",
                ".",
                ":(exclude).orcinus",
                ":(exclude)docs/verification",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if status.returncode != 0:
            return True
        return bool(status.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        return True


# --- Round 8, FND-009: mutual exclusion for the read-modify-write ---
# Pattern: skills/idea-capture/scripts/capture.py — a durable lock
# file (never unlinked: unlinking is what made the old stale-lock
# recovery racy) plus an OS advisory lock (flock / msvcrt) on it.
# The lock file is created with O_EXCL when absent, opened when
# present; the lock is the flock, not the file's existence, so a
# leftover file from a dead holder never blocks anyone — the OS
# releases the flock when the holder dies, even on SIGKILL — and
# the recorded PID is diagnostic only. NOTE (N-B2): writing via
# a temp file + os.replace alone does NOT fix lost updates — it
# only prevents torn writes; both writers would still read the
# same base and last-rename-wins. The lock is the fix.


def _lock_path(path):
    return Path(path).parent / f".{Path(path).name}.lock"


def _try_lock(fd):
    """Take the OS advisory lock on an open fd, non-blocking.
    POSIX uses fcntl.flock; Windows uses msvcrt.locking on one
    byte at offset 0. Raises RuntimeError when no locking
    primitive exists — the caller must fail closed, never
    proceed unlocked."""
    if sys.platform == "win32":
        import msvcrt

        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    try:
        import fcntl
    except ImportError:
        raise RuntimeError("no advisory file-locking primitive on this platform")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fd):
    """Release the OS advisory lock on an open fd. Closing the fd
    releases it too; this is belt-and-braces, and it never fails
    the caller."""
    try:
        if sys.platform == "win32":
            import msvcrt

            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
    except ImportError:
        pass


def _read_lock_pid(lock_path):
    """The PID recorded in a lock file, or None when it cannot be
    read. The PID starts at offset 1 (byte 0 is the locked
    region), and the read starts there too, so a contender can
    read it without touching the locked byte. A missing PID means
    the lock cannot be proven stale, so the caller must treat it
    as held."""
    try:
        fd = os.open(lock_path, os.O_RDONLY)
    except OSError:
        return None
    try:
        os.lseek(fd, 1, os.SEEK_SET)
        data = os.read(fd, 32)
    except OSError:
        return None
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        pid = int(data.decode("utf-8").strip())
    except ValueError:
        return None
    return pid if pid > 0 else None


def _pid_is_alive(pid):
    """True when the process exists. A PermissionError means the
    process exists but belongs to another user — alive, so the
    lock is held. On Windows the probe is OpenProcess with
    PROCESS_QUERY_LIMITED_INFORMATION (round 9, N-F5x): a handle
    means alive; no handle with ERROR_ACCESS_DENIED (5) also
    means alive (the process exists but is not ours); any other
    failure means the PID names nothing. When the probe itself
    cannot run, the PID is never declared dead — the stale note
    is diagnostic only, and recovery never depends on it (the
    flock is the lock)."""
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return kernel32.GetLastError() == 5  # ERROR_ACCESS_DENIED
        except (OSError, AttributeError):
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _acquire_lock(path, timeout_s=10.0):
    """Take the lock for `path`'s read-modify-write. Returns (fd,
    lock_path, holder_pid): fd is None when the lock is still
    held after the timeout, and holder_pid is then the recorded
    PID when it could be read, else None. The caller must
    release it (unlock + close) in a finally block, on every
    path including errors. The lock file is never unlinked."""
    import time

    lock_path = _lock_path(path)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
    except FileExistsError:
        try:
            fd = os.open(lock_path, os.O_RDWR)
        except OSError:
            return None, lock_path, None
    except OSError:
        return None, lock_path, None
    deadline = time.monotonic() + timeout_s
    holder_pid = None
    # Whether the flock was free on the first try (round 9,
    # FND-005): the first attempt is made outside the wait loop so
    # the note below can tell a free lock from a contended one.
    free_on_first_try = _try_lock(fd)
    if not free_on_first_try:
        while True:
            pid = _read_lock_pid(lock_path)
            if pid is not None:
                holder_pid = pid
            if time.monotonic() >= deadline:
                try:
                    os.close(fd)
                except OSError:
                    pass
                return None, lock_path, holder_pid
            time.sleep(0.05)
            if _try_lock(fd):
                break
    # We hold the lock. The recorded PID may name a dead process
    # (the previous holder died; the OS released the lock and the
    # file stayed): note it — but only when the lock was NOT free
    # on the first try. When the flock was free immediately, a dead
    # recorded PID is the normal state after any completed
    # transition, not a stale lock recovered: printing the note on
    # every run after the first is noise on the happy path. The
    # lock file is never unlinked (unlinking is what made the old
    # stale-lock recovery racy).
    old_pid = _read_lock_pid(lock_path)
    if old_pid is not None and not _pid_is_alive(old_pid) and not free_on_first_try:
        print(
            f"note: stale lock {lock_path.name} recovered "
            f"(holder process {old_pid} no longer exists)",
            file=sys.stderr,
        )
    try:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        # Byte 0 is the locked region: the PID starts at offset 1.
        os.write(fd, f" {os.getpid()}\n".encode("utf-8"))
        try:
            os.fsync(fd)
        except OSError:
            pass
    except OSError:
        _release_lock(fd, lock_path)
        return None, lock_path, None
    return fd, lock_path, None


def _release_lock(fd, lock_path) -> None:
    """Release the advisory lock and close the fd. The lock file
    is NEVER unlinked."""
    _unlock(fd)
    try:
        os.close(fd)
    except OSError:
        pass


def transition(
    data,
    to_stage,
    revision,
    evidence_bundle=None,
    note="",
    repo=None,
    expect_digest=None,
    attestation_checker=None,
    attestation_proof=None,
):
    """Move a state dict to `to_stage`, returning a new dict (the
    input is not mutated). The content digest is recomputed here,
    from `revision`'s tree in `repo` — it is never a caller-supplied
    value (F-07): a caller cannot volunteer a digest, so the old
    `sha256:` + `"f" x 64` repro is impossible, and Rule 2 fires on
    the recomputed value. Raises ValueError on an invalid current
    state, a transition the table does not allow, a content-digest
    change to any stage but BUILDING, VERIFIED without an evidence
    bundle, or RELEASE_READY without an approval bound to the
    recomputed digest. `expect_digest`, when given, only asserts
    against the recomputed digest — it is never stored. VERIFIED
    requires an evidence bundle that exists and validates with
    verdict PASS (the --evidence flag, or the stored value when
    it names an existing validating file — a stale stored path
    never silently satisfies the gate). An --evidence flag
    replaces the stored bundle, so a stale stored path does not
    block a transition that supplies a fresh one; the flag's own
    bundle is checked in the VERIFIED gate. VERIFIED and
    RELEASE_READY also refuse on a dirty tree at HEAD: the digest
    describes committed content only, and `ls-tree` cannot see
    untracked files, so the tree is checked separately. VERIFIED
    additionally requires a CI attestation, checked LIVE at
    transition time (0.11.0): `attestation_checker` defaults to
    the real verify_attestation check — the same default in
    production and in tests, with tests injecting a stub
    explicitly — and `attestation_proof` is the explicit-only
    fallback, a targeted-rerun proof file (see
    _check_attestation_proof). Without a live check AND without
    a proof file the transition is refused. The history is
    append-only: the old entries are kept verbatim and one entry
    is added."""
    # Round 8, FND-007 / N-B3: `repo` defaults to the caller's
    # working directory, resolved at call time — not to the
    # ORCINUS install (the old `repo=ROOT` default) and not at
    # import time, so a later chdir is honoured.
    repo = Path.cwd() if repo is None else repo
    problems = validate_state(data, repo=repo)
    if evidence_bundle is not None:
        # The flag replaces the stored bundle: a stale stored path
        # must not block a transition that supplies a fresh bundle
        # (re-verifying after the old bundle was deleted is the
        # repair path, and the new state records the flag's value).
        # Every _evidence_problems message starts with
        # "evidence_bundle", so this drops exactly those — the
        # flag's own bundle is checked in the VERIFIED gate below.
        problems = [p for p in problems if not p.startswith("evidence_bundle")]
    if problems:
        raise ValueError(f"invalid state: {'; '.join(problems)}")
    if to_stage not in STAGES:
        raise ValueError(f"unknown stage: {to_stage!r}")
    try:
        computed = content_digest(repo, revision)
    except ContentDigestError as e:
        raise ValueError(f"cannot compute content_digest for revision {revision!r}: {e}") from e
    if expect_digest is not None and expect_digest != computed:
        raise ValueError(
            f"--expect-digest {expect_digest} does not match the recomputed digest "
            f"{computed} for revision {revision!r}"
        )
    current = data["stage"]
    digest_changed = computed != data["content_digest"]
    if digest_changed and to_stage != "BUILDING":
        raise ValueError(
            "content digest changed: the stage must go back to BUILDING first "
            "(a content change resets the stage)"
        )
    if to_stage not in ALLOWED_TRANSITIONS[current] and not (
        digest_changed and to_stage == "BUILDING"
    ):
        raise ValueError(
            f"not an allowed transition: {current} -> {to_stage} "
            f"(allowed: {', '.join(sorted(ALLOWED_TRANSITIONS[current])) or 'none'})"
        )
    if to_stage in ("VERIFIED", "RELEASE_READY"):
        # Round 8, FND-008 / N-B4: a VERIFIED or RELEASE_READY
        # stage minted at a revision HEAD has moved past binds
        # the stage to content HEAD no longer has — and the old
        # _tree_is_dirty() returned False for a non-HEAD revision,
        # so the dirty-tree gate was skipped too. Refuse outright,
        # naming the stale revision. (An unresolvable HEAD falls
        # through to the dirty gate, which fails closed.)
        head = _head_revision(repo)
        if head is not None:
            resolved = _resolve_revision(repo, revision)
            if resolved is not None and resolved != head:
                raise ValueError(
                    f"cannot transition to {to_stage} at stale revision "
                    f"{revision!r}: HEAD is {head} — move the state to "
                    "HEAD first"
                )
    if to_stage in ("VERIFIED", "RELEASE_READY") and _tree_is_dirty(repo, revision):
        raise ValueError(
            "working tree is dirty: VERIFIED and RELEASE_READY require a clean tree "
            "(uncommitted changes outside .orcinus/ and docs/verification/) — "
            "commit or stash first, the digest describes committed content only"
        )
    if to_stage == "VERIFIED":
        # The stored-bundle rule (N2): a stored evidence_bundle
        # may satisfy the gate with no --evidence flag — but only
        # if it names an existing file that validates with verdict
        # PASS. A stale stored path (missing file, invalid bundle,
        # non-PASS verdict) refuses the transition; it never
        # silently satisfies the gate. The flag is required only
        # when the stored value is absent or blank.
        if evidence_bundle is not None:
            candidate = evidence_bundle
            source = "--evidence"
        else:
            candidate = data.get("evidence_bundle")
            source = "the stored evidence_bundle"
        if candidate is None or (isinstance(candidate, str) and not candidate.strip()):
            raise ValueError(
                "VERIFIED requires evidence_bundle (--evidence <bundle path>; "
                "no bundle is recorded in the state)"
            )
        problems = _evidence_problems(
            candidate, repo, require_valid=True, expected_revision=revision
        )
        if problems:
            raise ValueError(
                f"VERIFIED requires a valid evidence bundle ({source} {candidate!r}): "
                f"{'; '.join(problems)}"
            )
        # 0.11.0: a local PASS is provisional — VERIFIED
        # additionally requires a CI attestation for this revision,
        # checked live at transition time (or an explicit
        # targeted-rerun proof file). The bundle alone never
        # suffices, whatever it says.
        _check_attestation_gate(
            repo, revision, computed, candidate, attestation_checker, attestation_proof
        )
    if to_stage == "RELEASE_READY":
        approval = data.get("approval")
        if not approval or approval.get("content_digest") != computed:
            raise ValueError("RELEASE_READY requires approval bound to this content_digest")
    new = dict(data)
    new["stage"] = to_stage
    new["revision"] = revision
    new["content_digest"] = computed
    if evidence_bundle is not None:
        new["evidence_bundle"] = evidence_bundle
    entry = {
        "stage": to_stage,
        "revision": revision,
        "content_digest": computed,
        "at": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }
    new["history"] = [*data["history"], entry]
    return new


def main(argv):
    parser = argparse.ArgumentParser(description="Validate and transition .orcinus/state.json.")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="check a state file against the schema")
    validate.add_argument("path")
    validate.add_argument(
        "--repo",
        default=None,
        help="the repo the digest is recomputed in (default: current working directory)",
    )
    validate.add_argument(
        "--no-require-head",
        action="store_true",
        help="do not require the state revision to be HEAD "
        "(default: require HEAD; use this only to inspect a historical state)",
    )
    move = sub.add_parser("transition", help="move a state file to a new stage")
    move.add_argument("path")
    move.add_argument("--to", required=True, choices=list(STAGES))
    move.add_argument("--revision", required=True)
    move.add_argument(
        "--expect-digest",
        default=None,
        help="assert the recomputed digest equals this (never stored)",
    )
    move.add_argument("--evidence")
    move.add_argument(
        "--attestation-proof",
        default=None,
        metavar="<file>",
        help="explicit fallback for the VERIFIED attestation gate: "
        "a targeted-rerun proof file (see scripts/state.py) — "
        "only when the live CI attestation cannot be checked",
    )
    move.add_argument("--note", default="")
    move.add_argument(
        "--repo",
        default=None,
        help="the repo the digest is recomputed in (default: current working directory)",
    )
    args = parser.parse_args(argv)
    # Round 8, FND-007: --repo defaults to the caller's working
    # directory, resolved at call time — not to the ORCINUS
    # install (the old `ROOT` default).
    repo = Path(args.repo).resolve() if args.repo else Path.cwd()
    if args.command == "validate":
        try:
            data = load_state(args.path)
        except ValueError as e:
            print(f"invalid: {e}")
            return 1
        problems = validate_state(data, repo=repo, require_head=not args.no_require_head)
        if problems:
            for problem in problems:
                print(f"invalid: {problem}")
            return 1
        print("OK: state is valid")
        return 0
    # Transition is a read-modify-write: the lock (round 8,
    # FND-009) covers load, transition, and write, so two
    # simultaneous transitions cannot read the same base and
    # lose each other's history entry. The write goes through a
    # temp file + os.replace for atomicity — but os.replace alone
    # does NOT fix lost updates (N-B2); the lock is the fix.
    # The lock is released in `finally`, on every path including
    # a refused transition; the lock file itself is never
    # unlinked, so a dead holder never blocks the next writer.
    path = Path(args.path)
    try:
        fd, lock_path, holder_pid = _acquire_lock(path)
    except RuntimeError as e:
        print(f"refused: cannot lock the state file: {e}")
        return 1
    if fd is None:
        if holder_pid is not None:
            print(
                f"refused: the state file is being changed by another process "
                f"(pid {holder_pid}) — try again"
            )
        else:
            print("refused: the state file is being changed by another process — try again")
        return 1
    try:
        try:
            data = load_state(args.path)
        except ValueError as e:
            print(f"invalid: {e}")
            return 1
        try:
            new = transition(
                data,
                args.to,
                args.revision,
                args.evidence,
                args.note,
                repo=repo,
                expect_digest=args.expect_digest,
                attestation_proof=args.attestation_proof,
            )
        except ValueError as e:
            print(f"refused: {e}")
            return 1
        tmp_fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(new, indent=2) + "\n")
            os.replace(tmp_name, path)
        except OSError as e:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            print(f"refused: cannot write the state file: {e}")
            return 1
        print(f"OK: stage is now {args.to}")
        return 0
    finally:
        _release_lock(fd, lock_path)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
