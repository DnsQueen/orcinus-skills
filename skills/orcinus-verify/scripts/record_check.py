#!/usr/bin/env python3
"""Run one check command and record a transcript the validator can recompute.

The execution-binding wrapper (round 7, F-01, Option B-2). A bundle
whose checks are hand-written JSON can claim any command passed; this
wrapper makes fabrication structural instead of free-form: it runs
the command itself, writes the raw stdout/stderr to files beside the
bundle, and prints a check fragment for pasting into the bundle whose
capture_sha256 binds the exact argv, cwd, timestamps, exit code, both
stream hashes, and the tree digest + revision at run time. The
validator recomputes that hash from the stored fields and the files
on disk and rejects a PASS whose binding does not recompute.

Pattern: in-toto's Link (in-toto/in-toto, docs at
in-toto.readthedocs.io, Link struct in in-toto/in-toto-golang) — the
direct model: `name`, `command` as an argv LIST (never a shell
string), `byproducts` (stdout, stderr, return value), `environment`
(workdir). SLSA v1 provenance is the same shape build-flavoured, and
its spec states the trust model explicitly: "the builder is trusted
to have faithfully recorded the provenance". The simpler precedent is
Bazel's REAPI ActionResult (exit_code, stdout/stderr by digest,
outputs referenced by hash, executor-produced). What is NOT copied:
in-toto's signing/PKI (no key holder distinct from the agent exists,
so a signature would prove nothing), per-check materials/products
hashing (the whole-repo content digest already covers the tree), SLSA
`builder.id` (no trusted builder here), and any HMAC with a
repo-readable key (anyone who can write the bundle can read the key
and forge the tag). Pattern only — no in-toto, SLSA, or Bazel code is
copied or vendored.

Trust model (stated honestly, after waza's recorded-evidence model,
whose docs state it directly: "the grader program and other
processes running as the same user are trusted" — same-user tampering
is out of scope): a local writer can run this wrapper on a lying
command (`record_check.py -- true`, or a script that prints fake
pytest output and exits 0) and paste the genuine capture in. No local
hash distinguishes "the wrapper ran the real gate" from "the wrapper
ran a liar" — real systems close that gap only with a trust boundary
the job cannot touch (SLSA L3's hardened builder, in-toto's layout
author distinct from the functionary, Bazel's remote executor, a CI
runner holding the log). We have no such boundary, so the claim stays
"tamper-evident recording", never "proof of execution". What the
mechanism buys: fabrication now requires deliberately invoking the
wrapper on a fake command instead of typing JSON; accidental
inconsistency (wrong exit code, wrong tree, timestamps out of order,
stdout that does not match the claimed gate) is caught mechanically;
capture reuse across trees is caught by the digest inside the hash.

Usage: python3 skills/orcinus-verify/scripts/record_check.py
    --name <gate> --out-dir <bundle-dir> [--cwd <dir>] [--repo <repo>]
    [--digest-module <path>] [--shell] [--timeout <seconds>]
    -- <command...>
The wrapper runs the command, writes <name>.stdout / <name>.stderr
into --out-dir, and prints the check fragment (JSON) on stdout for
pasting into the bundle. The fragment does NOT carry tool_version:
the agent adds it (the wrapper does not know which tool ran).
A shell string is accepted only behind --shell, is run as
["sh", "-c", <string>], and is recorded as such (shell: true).

Exit code: the command's exit code when the command ran (the fragment
is still printed, so a failing gate is a recorded failure, not a
missing recording); 2 when the recording itself failed (no fragment:
command not found, timeout, output over the cap, no git repo, no
content_digest module). The stdout/stderr cap is the validator's
10 MiB (MAX_CAPTURE_BYTES must equal validate_evidence.MAX_ARTIFACT_BYTES;
a test pins the agreement). A capture over the cap is a recording
failure, not a truncation: a truncated artifact would hash cleanly
while hiding output. The cap is enforced live, during receipt
(round 9, F2): each stream is pumped to a temp file by its own
reader thread and the command is killed as soon as either stream
exceeds the cap, so the wrapper's memory stays bounded however
much the command emits. The captures are written atomically
(round 9, F3): the streams land in temp files and are renamed
into place, and a pre-planted symlink — as the bundle directory
itself, or as either destination file — is refused before the
command runs, so a capture can never overwrite a file outside
the bundle directory through a link. A pre-existing regular
capture file is still replaced (re-recording a gate is normal).
A check name that is a Windows reserved device name (con, prn,
aux, nul, com1-9, lpt1-9 — the Cloudflare validate-findings.cjs
pattern, MIT, ported verbatim) is refused for the same reason the
validator rejects such artifact paths: on Windows the captures
would be devices, not files in the bundle directory.

The content digest is computed by the existing content_digest
function (skills/orcinus-verify/scripts/content_digest.py — a
byte-identical copy of scripts/content_digest.py, bundled beside
this file so skills-only installs can find it) — imported, never
reimplemented. It is found, in order: --digest-module, the copy
bundled beside this file, the scripts/ directory beside the skill
folder in a repo/plugin install, or an already-importable
content_digest module.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# The binding format version. Bump it if the hashed fields change;
# the validator recomputes with this same constant, so the two must
# agree (they share capture_binding_hash below).
FORMAT_VERSION = "orcinus-record-check/1"

# The recorder identity stamped on every fragment. The validator
# requires exactly this value for a check in a PASS bundle.
RECORDED_BY = "record_check.py/1"

# The stdout/stderr cap, in bytes. Must equal
# validate_evidence.MAX_ARTIFACT_BYTES: a recorded capture the
# validator cannot read is not evidence.
MAX_CAPTURE_BYTES = 10 * 1024 * 1024

# A hanging gate must not hang the wrapper forever. in-toto's
# default timeout is 10 s — too short for a test suite; 600 s
# bounds a runaway without cutting a real suite short.
DEFAULT_TIMEOUT_SECONDS = 600

# A check name becomes two filenames (<name>.stdout/.stderr), so it
# must be a safe file stem: no separator, no leading dot (no "..",
# no hidden file), at most 100 characters.
_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")

# Windows reserved device names — verbatim from
# cloudflare/security-audit-skill (MIT, Copyright (c) 2025-2026
# Cloudflare, Inc.), skills/security-audit/validate-findings.cjs
# (WINDOWS_RESERVED_COMPONENT). A reserved stem would write the
# captures to a device on Windows (con, prn, aux, nul, com1-9,
# lpt1-9 — with any extension, in any case), not to files in the
# bundle directory, so such a name is refused before the command
# runs. The validator (validate_evidence.py) rejects the same names
# in artifact paths named by hand-written bundles.
_WINDOWS_RESERVED_COMPONENT = re.compile(
    r"^(?:con|prn|aux|nul|clock\$|conin\$|conout\$|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)",
    re.IGNORECASE,
)


# A full commit SHA in this repo's object format: SHA-1 (40 hex)
# or SHA-256 (64 hex). A revision that is not one is not a
# revision git resolved — it is empty or garbage output (round 8,
# FND-023).
_SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


class RecordError(Exception):
    """A recording failure: the command did not produce a fragment."""


def canonical_json(obj):
    """The canonical serialisation the binding hash is taken over:
    sorted keys, compact separators, UTF-8. The fragment printed on
    stdout is pretty-printed for pasting; the hash is never taken
    over that rendering."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def capture_binding_hash(
    command_argv,
    shell,
    cwd,
    started_at,
    finished_at,
    exit_code,
    stdout_sha256,
    stderr_sha256,
    content_digest,
    revision,
):
    """The one binding hash over exactly: format, command argv, shell,
    cwd, started_at, finished_at, exit_code, stdout_sha256,
    stderr_sha256, content_digest, revision. The stream hashes are
    hashes of the raw stream bytes — never of inline text or a
    pretty-printed rendering. The validator imports this function
    (same skill folder) and recomputes it; there is one definition."""
    payload = {
        "format": FORMAT_VERSION,
        "command": list(command_argv),
        "shell": shell,
        "cwd": cwd,
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": exit_code,
        "stdout_sha256": stdout_sha256,
        "stderr_sha256": stderr_sha256,
        "content_digest": content_digest,
        "revision": revision,
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _utc_now():
    """Now, as RFC 3339 UTC with a Z suffix and 6 fractional digits
    (the form the validator's timestamp regex accepts)."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _load_content_digest(digest_module):
    """The content_digest function, imported — never reimplemented.
    --digest-module wins; then the copy bundled beside this file
    (skills-only installs have no repo checkout, so this is what
    makes the documented step-4 command work there); then the
    scripts/ directory beside the skill folder in a repo/plugin
    install; then an already-importable module. Raises RecordError
    when none is found."""
    if digest_module is not None:
        path = Path(digest_module)
        if not path.is_file():
            raise RecordError(f"--digest-module {digest_module!r} is not a file")
        candidates = [path]
    else:
        candidates = []
    candidates.append(Path(__file__).resolve().parent / "content_digest.py")
    candidates.append(
        Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "content_digest.py"
    )
    for path in candidates:
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("orcinus_content_digest", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.content_digest
    try:
        from content_digest import content_digest
    except ImportError:
        raise RecordError(
            "content_digest.py not found: run from a repo/plugin install "
            "(skills/orcinus-verify/scripts/record_check.py with "
            "scripts/content_digest.py beside it) or pass --digest-module <path>"
        )
    return content_digest


def _repo_from_cwd(directory):
    """The work-tree root git names for `directory` (`rev-parse
    --show-toplevel`), resolved. Raises RecordError outside a repo,
    when git is absent, or when git's output cannot be trusted.
    The git-derived path is validated like an explicit --repo: git
    printing nothing with exit 0 used to resolve to Path("") = ".",
    binding a capture to whatever directory happened to be current
    (round 8, FND-023). A bare repo has no work tree, so
    --show-toplevel fails there (round 9, N-B) — a bare repo can
    never be the repo a capture is bound to."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError as e:
        raise RecordError("git is not installed: cannot find the repository") from e
    if proc.returncode != 0:
        raise RecordError(
            f"{directory} is not inside a git repository: there is no tree "
            f"digest to bind the capture to — pass --repo <repo>"
        )
    top = proc.stdout.strip()
    if not top or "\n" in top or not Path(top).is_dir():
        raise RecordError(
            f"git did not name a repository for {directory}: --show-toplevel "
            f"printed {proc.stdout!r} — pass --repo <repo>"
        )
    return Path(top)


def _resolve_repo(cwd, repo_arg):
    """The git repo the digest is taken from: the repo containing
    the command's cwd — always derived from the cwd first. An
    explicit --repo is accepted only when it names that same repo:
    the capture's tree is the tree the command ran on, never a
    tree named independently of it (round 9, FND-001: --cwd in a
    scratch directory with --repo at a real repo used to record a
    capture bound to that repo's tree, so a fake command could
    file a PASS for code it never ran against). A worktree's root
    is its own repo for this purpose: --cwd in a worktree binds
    to the worktree (its base commit), and --repo naming the main
    checkout does not match it. Raises RecordError outside a repo
    or on a mismatch."""
    derived = _repo_from_cwd(cwd)
    if repo_arg is None:
        return derived
    repo = Path(repo_arg)
    if not repo.is_dir():
        raise RecordError(f"--repo {repo_arg!r} is not a directory")
    explicit = _repo_from_cwd(repo)
    if explicit.resolve() != derived.resolve():
        raise RecordError(
            f"--repo {repo_arg!r} is not the repository containing "
            f"--cwd {cwd}: the capture's tree is the tree the command "
            f"ran on — record the command inside {repo_arg!r}, or pass "
            f"--repo {derived}"
        )
    return derived


def _resolve_revision(repo):
    """The full SHA of the repo's HEAD at run time. `rev-parse
    --verify` must succeed and print a single full SHA — a bare
    rev-parse echoing its input, or a stubbed git printing nothing
    with exit 0, used to pass as a revision (round 8, FND-023)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError as e:
        raise RecordError("git is not installed: cannot resolve HEAD") from e
    if proc.returncode != 0:
        raise RecordError(f"cannot resolve HEAD in {repo}: {proc.stderr.strip()}")
    revision = proc.stdout.strip()
    if not _SHA_RE.fullmatch(revision):
        raise RecordError(
            f"cannot resolve HEAD in {repo}: git printed {proc.stdout!r}, not a full commit SHA"
        )
    return revision


def _pump(stream, path, cap, state):
    """Drain one pipe to `path`, hashing as it goes (round 9, F2):
    one reader thread per stream, so neither pipe can block the
    command while the other fills. Stops at the first chunk that
    would take the total past `cap` — the over-cap chunk is not
    written — and records the breach in `state` for the main
    thread to act on. `state` ends with the bytes written and
    their sha256 when the stream ends cleanly."""
    hasher = hashlib.sha256()
    written = 0
    try:
        with open(path, "wb") as f:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                if written + len(chunk) > cap:
                    state["exceeded"] = True
                    return
                f.write(chunk)
                hasher.update(chunk)
                written += len(chunk)
    except OSError:
        state["error"] = True
        return
    state["bytes"] = written
    state["sha256"] = hasher.hexdigest()


def _run_capped(command_argv, cwd, timeout, out_dir, name):
    """Run the command, streaming its stdout/stderr to temp files
    in `out_dir` with a LIVE cap (round 9, F2): the cap is enforced
    during receipt, not after — as soon as either stream exceeds
    MAX_CAPTURE_BYTES the process is killed and RecordError is
    raised, so the wrapper's memory stays bounded however much the
    command emits (the old capture_output=True buffered the whole
    output in RAM first and checked afterwards). Returns
    (exit_code, stdout_tmp, stderr_tmp, stdout_sha256,
    stderr_sha256) for the two temp files; the caller atomically
    renames them to their final names. On any failure the temp
    files are removed here, so a refused capture leaves nothing
    behind. Raises RecordError on a cap breach, a timeout (same
    message as before), or a missing command."""
    stdout_fd, stdout_tmp = tempfile.mkstemp(prefix=f".{name}.stdout.", dir=out_dir)
    stderr_fd, stderr_tmp = tempfile.mkstemp(prefix=f".{name}.stderr.", dir=out_dir)
    os.close(stdout_fd)
    os.close(stderr_fd)
    try:
        return _run_capped_inner(
            command_argv, cwd, timeout, out_dir, Path(stdout_tmp), Path(stderr_tmp)
        )
    except RecordError:
        for tmp in (stdout_tmp, stderr_tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise


def _run_capped_inner(command_argv, cwd, timeout, out_dir, stdout_tmp, stderr_tmp):
    """The run itself; _run_capped owns the temp files' lifetime."""
    try:
        proc = subprocess.Popen(
            command_argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd
        )
    except FileNotFoundError as e:
        raise RecordError(f"command not found: {command_argv[0]!r}") from e
    stdout_state: dict = {}
    stderr_state: dict = {}
    out_thread = threading.Thread(
        target=_pump, args=(proc.stdout, stdout_tmp, MAX_CAPTURE_BYTES, stdout_state)
    )
    err_thread = threading.Thread(
        target=_pump, args=(proc.stderr, stderr_tmp, MAX_CAPTURE_BYTES, stderr_state)
    )
    out_thread.start()
    err_thread.start()
    deadline = time.monotonic() + timeout
    exit_code = None
    try:
        while True:
            exit_code = proc.poll()
            if exit_code is not None:
                break
            if stdout_state.get("exceeded") or stderr_state.get("exceeded"):
                proc.kill()
                break
            if time.monotonic() > deadline:
                proc.kill()
                exit_code = proc.wait()
                out_thread.join(timeout=5)
                err_thread.join(timeout=5)
                raise RecordError(f"command timed out after {timeout}s")
            time.sleep(0.02)
    finally:
        # Reap the process even on the kill paths above.
        if exit_code is None:
            exit_code = proc.wait()
    out_thread.join()
    err_thread.join()
    if stdout_state.get("error") or stderr_state.get("error"):
        raise RecordError(f"cannot write the capture files in {out_dir}")
    if stdout_state.get("exceeded"):
        stream = "stdout"
    elif stderr_state.get("exceeded"):
        stream = "stderr"
    else:
        stream = None
    if stream is not None:
        raise RecordError(f"{stream} is larger than the {MAX_CAPTURE_BYTES}-byte artifact cap")
    return (
        exit_code,
        stdout_tmp,
        stderr_tmp,
        stdout_state["sha256"],
        stderr_state["sha256"],
    )


def record(name, argv, shell, out_dir, cwd, repo, digest_module, timeout):
    """Run one command and record it. Returns (fragment, exit_code):
    the check fragment for the bundle, and the command's exit code.
    Raises RecordError when the recording itself failed."""
    if not _NAME_RE.fullmatch(name):
        raise RecordError(
            f"--name {name!r} is not a safe check name: use letters, digits, "
            f"'.', '_' or '-', starting with a letter or digit"
        )
    if _WINDOWS_RESERVED_COMPONENT.match(name):
        raise RecordError(
            f"--name {name!r} is a Windows reserved device name "
            f"(con/prn/aux/nul/com1-9/lpt1-9): the capture files would be "
            f"devices on Windows, not files in the bundle directory"
        )
    if shell:
        if len(argv) != 1:
            raise RecordError("--shell takes exactly one command string")
        command_argv = ["sh", "-c", argv[0]]
        command = argv[0]
    else:
        if not argv:
            raise RecordError("no command given after --")
        command_argv = list(argv)
        command = shlex.join(command_argv)
    cwd = Path(cwd).resolve()
    if not cwd.is_dir():
        raise RecordError(f"--cwd {cwd} is not a directory")
    out_dir = Path(out_dir)
    # Round 9, F3: refuse to write through a symlink, before the
    # command even runs. A bundle directory that is itself a
    # symlink would land the captures wherever the link points, and
    # a symlinked destination file would be overwritten through the
    # link (write_bytes follows it). A pre-existing REGULAR file is
    # still replaced atomically below — re-recording a gate is
    # normal — only links are refused. The atomic rename below is
    # the second layer: even a link planted between this check and
    # the rename is replaced, never followed. A symlink in a
    # PARENT component of out_dir is out of scope: the caller
    # chooses out_dir, as with --cwd and --repo.
    if out_dir.is_symlink():
        raise RecordError(
            f"--out-dir {out_dir} is a symlink: captures must land in the directory "
            "named, not wherever the link points"
        )
    stdout_path = out_dir / f"{name}.stdout"
    stderr_path = out_dir / f"{name}.stderr"
    for dest in (stdout_path, stderr_path):
        if dest.is_symlink():
            raise RecordError(
                f"refusing to write through a symlink: {dest} already exists as a "
                "symlink — remove it, or record under another --name"
            )
    out_dir.mkdir(parents=True, exist_ok=True)
    repo = _resolve_repo(cwd, repo)
    revision = _resolve_revision(repo)
    content_digest_fn = _load_content_digest(digest_module)
    try:
        digest = content_digest_fn(repo, revision)
    except Exception as e:
        raise RecordError(f"cannot compute the content digest of {repo}: {e}") from e
    started_at = _utc_now()
    exit_code, stdout_tmp, stderr_tmp, stdout_sha256, stderr_sha256 = _run_capped(
        command_argv, cwd, timeout, out_dir, name
    )
    finished_at = _utc_now()
    try:
        os.replace(stdout_tmp, stdout_path)
        os.replace(stderr_tmp, stderr_path)
    except OSError as e:
        for tmp in (stdout_tmp, stderr_tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise RecordError(f"cannot write the capture files in {out_dir}: {e}") from e
    fragment = {
        "name": name,
        "command": command,
        "command_argv": command_argv,
        "shell": shell,
        "cwd": str(cwd),
        "exit_code": exit_code,
        "started_at": started_at,
        "finished_at": finished_at,
        "stdout_artifact": stdout_path.name,
        "stdout_sha256": stdout_sha256,
        "stderr_artifact": stderr_path.name,
        "stderr_sha256": stderr_sha256,
        "content_digest": digest,
        "revision": revision,
        "recorded_by": RECORDED_BY,
    }
    fragment["capture_sha256"] = capture_binding_hash(
        command_argv=command_argv,
        shell=shell,
        cwd=str(cwd),
        started_at=started_at,
        finished_at=finished_at,
        exit_code=exit_code,
        stdout_sha256=stdout_sha256,
        stderr_sha256=stderr_sha256,
        content_digest=digest,
        revision=revision,
    )
    return fragment, exit_code


def main(argv):
    parser = argparse.ArgumentParser(
        description="Run one check command and record a transcript "
        "the validator can recompute (see the module docstring).",
        usage="python3 skills/orcinus-verify/scripts/record_check.py "
        "--name <gate> --out-dir <bundle-dir> [--shell] -- <command...>",
    )
    parser.add_argument("--name", required=True, help="the check name (gate)")
    parser.add_argument(
        "--out-dir", required=True, help="the bundle directory for the capture files"
    )
    parser.add_argument(
        "--cwd",
        default=None,
        help="the directory the command runs in (default: the working directory)",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="the git repo the digest is taken from (default: the repo "
        "containing --cwd; an explicit --repo must be that repo)",
    )
    parser.add_argument(
        "--digest-module",
        default=None,
        help="path to a content_digest.py to import (default: the copy bundled beside this file)",
    )
    parser.add_argument(
        "--shell",
        action="store_true",
        help="run the command as one shell string (recorded as shell: true)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"seconds before the command is killed (default {DEFAULT_TIMEOUT_SECONDS})",
    )
    parser.add_argument("command", nargs="*", help="the command to run (after --)")
    args = parser.parse_args(argv[1:])
    try:
        fragment, exit_code = record(
            name=args.name,
            argv=args.command,
            shell=args.shell,
            out_dir=args.out_dir,
            cwd=Path.cwd() if args.cwd is None else args.cwd,
            repo=args.repo,
            digest_module=args.digest_module,
            timeout=args.timeout,
        )
    except RecordError as e:
        print(f"record_check: {e}", file=sys.stderr)
        return 2
    print(json.dumps(fragment, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
