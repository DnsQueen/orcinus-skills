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
while hiding output.

The content digest is computed by the existing content_digest
function (scripts/content_digest.py) — imported, never reimplemented.
It is found, in order: --digest-module, the scripts/ directory beside
the skill folder in a repo/plugin install, or an already-importable
content_digest module. In an npx-skills install the repo-root
scripts/ do not travel, so pass --digest-module with a path to a
content_digest.py, or run from a repo/plugin checkout.
"""

import argparse
import hashlib
import importlib.util
import json
import re
import shlex
import subprocess
import sys
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
    --digest-module wins; then the scripts/ directory beside the
    skill folder in a repo/plugin install; then an already-importable
    module. Raises RecordError when none is found."""
    if digest_module is not None:
        path = Path(digest_module)
        if not path.is_file():
            raise RecordError(f"--digest-module {digest_module!r} is not a file")
        candidates = [path]
    else:
        candidates = []
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


def _resolve_repo(cwd, repo_arg):
    """The git repo the digest is taken from: --repo, or the repo
    containing the command's cwd. Raises RecordError outside a repo."""
    if repo_arg is not None:
        repo = Path(repo_arg)
        if not repo.is_dir():
            raise RecordError(f"--repo {repo_arg!r} is not a directory")
        return repo
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError as e:
        raise RecordError("git is not installed: cannot find the repository") from e
    if proc.returncode != 0:
        raise RecordError(
            f"{cwd} is not inside a git repository: there is no tree "
            f"digest to bind the capture to — pass --repo <repo>"
        )
    return Path(proc.stdout.strip())


def _resolve_revision(repo):
    """The full SHA of the repo's HEAD at run time."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError as e:
        raise RecordError("git is not installed: cannot resolve HEAD") from e
    if proc.returncode != 0:
        raise RecordError(f"cannot resolve HEAD in {repo}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def record(name, argv, shell, out_dir, cwd, repo, digest_module, timeout):
    """Run one command and record it. Returns (fragment, exit_code):
    the check fragment for the bundle, and the command's exit code.
    Raises RecordError when the recording itself failed."""
    if not _NAME_RE.fullmatch(name):
        raise RecordError(
            f"--name {name!r} is not a safe check name: use letters, digits, "
            f"'.', '_' or '-', starting with a letter or digit"
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
    out_dir.mkdir(parents=True, exist_ok=True)
    repo = _resolve_repo(cwd, repo)
    revision = _resolve_revision(repo)
    content_digest_fn = _load_content_digest(digest_module)
    try:
        digest = content_digest_fn(repo, revision)
    except Exception as e:
        raise RecordError(f"cannot compute the content digest of {repo}: {e}") from e
    started_at = _utc_now()
    try:
        proc = subprocess.run(command_argv, capture_output=True, cwd=cwd, timeout=timeout)
    except FileNotFoundError as e:
        raise RecordError(f"command not found: {command_argv[0]!r}") from e
    except subprocess.TimeoutExpired:
        raise RecordError(f"command timed out after {timeout}s") from None
    finished_at = _utc_now()
    if len(proc.stdout) > MAX_CAPTURE_BYTES:
        raise RecordError(f"stdout is larger than the {MAX_CAPTURE_BYTES}-byte artifact cap")
    if len(proc.stderr) > MAX_CAPTURE_BYTES:
        raise RecordError(f"stderr is larger than the {MAX_CAPTURE_BYTES}-byte artifact cap")
    stdout_path = out_dir / f"{name}.stdout"
    stderr_path = out_dir / f"{name}.stderr"
    try:
        stdout_path.write_bytes(proc.stdout)
        stderr_path.write_bytes(proc.stderr)
    except OSError as e:
        raise RecordError(f"cannot write the capture files in {out_dir}: {e}") from e
    stdout_sha256 = hashlib.sha256(proc.stdout).hexdigest()
    stderr_sha256 = hashlib.sha256(proc.stderr).hexdigest()
    fragment = {
        "name": name,
        "command": command,
        "command_argv": command_argv,
        "shell": shell,
        "cwd": str(cwd),
        "exit_code": proc.returncode,
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
        exit_code=proc.returncode,
        stdout_sha256=stdout_sha256,
        stderr_sha256=stderr_sha256,
        content_digest=digest,
        revision=revision,
    )
    return fragment, proc.returncode


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
        help="the git repo the digest is taken from (default: the repo containing --cwd)",
    )
    parser.add_argument(
        "--digest-module",
        default=None,
        help="path to a content_digest.py to import "
        "(default: the repo/plugin install's scripts/content_digest.py)",
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
