#!/usr/bin/env python3
"""ORCINUS doctor — check whether this machine can run the ORCINUS
gates, and say exactly which ones it cannot.

Each check reports one of three states:
- ready: the tool is installed and usable;
- incomplete: an OPTIONAL tool is missing, but the gate it serves
  can be skipped (node for the demo and the JS/TS skills,
  oasdiff/stryker/mutmut for the breaking-change and
  mutation-testing skills, waza for the eval suites — the report
  says what is unverified because of it);
- incompatible: a MANDATORY tool is missing (git, python, pytest,
  ruff — without one of those a gate cannot run at all), the tool
  is present but the wrong version, or the environment cannot run
  the gate at all (not a git repository, repo files missing).

Usage: python3 scripts/doctor.py
Exit 0 when every gate that must run here is ready; exit 1 when any
gate is incomplete; exit 2 when any gate is incompatible (the
report says which).

This is a diagnostic, not a gate: it never changes anything, never
installs anything, and never claims a check passed. It tells the
user what to install before they trust a verification run.
"""

import hashlib
import importlib.util
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The minimum versions the gates need. pytest 9.0.3 and ruff 0.17.4
# are the pinned versions in CI. Python 3.9 itself was dropped
# 2026-11-06: it reached end-of-life 2025-10-31 and has no build for
# Ubuntu 26.04, which is what the CI runner is now. Python 3.10 was
# dropped 2026-11-07 (round 6, 2-S7): it reached end-of-life
# 2026-10-01 (PEP 619) — the same logic that dropped 3.9. The
# CHANGELOG 0.9.3 note of a 3.10 CI failure is NOT the evidence for
# this: that failure was a tomli pinning failure, not EOL.
MIN_PYTHON = (3, 11)
MIN_PYTEST = (8, 4)
MIN_RUFF = (0, 17)
MIN_WAZA = (0, 40, 0)
WAZA_VERSION = "0.40.0"
# The Linux fallback binary lives in world-writable /tmp, so it is
# only trusted when it is the released binary: a regular file owned
# by the current user whose SHA256 matches the pinned v0.40.0
# release hash. The hash is the waza-linux-amd64 entry of the
# v0.40.0 release checksums.txt (the same file CI verifies at
# download, ci.yml:57-62) — verified against the downloaded binary.
# It proves the file is the released one, not a planted one; it
# does not prove the release itself was not forged (2-S6).
# Residual (round 11, FND-012): the pinned hash lives in this same
# repo, so a repo compromise could replace the hash and the binary
# together. The pin only stops a planted /tmp binary; it is not a
# root of trust outside the repo.
WAZA_FALLBACK_PATH = "/tmp/waza-linux-amd64"
WAZA_LINUX_SHA256 = "d09117a3c631f44a00a6c362462c951aed83c87751e8c25f39916a77d1013802"


def _run(argv, timeout=10):
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except (OSError, subprocess.TimeoutExpired):
        # FileNotFoundError (no such tool) and PermissionError (a
        # non-executable file) alike: the tool cannot be run. S3 —
        # catching only the first two let PermissionError escape as
        # an uncaught traceback, outside the 0/1/2 scheme.
        # TimeoutExpired is not an OSError, so it stays listed.
        return None, ""


def _version_tuple(text):
    """Parse '8.4.2' (or 'pytest 8.4.2') into (8, 4, 2)."""
    import re

    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        return None
    return tuple(int(g) for g in m.groups() if g is not None)


def _check(name, status, detail, fix=None):
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def check_python(version=None):
    version = version or sys.version_info[:3]
    if version >= MIN_PYTHON:
        return _check("python", "ready", f"Python {'.'.join(map(str, version))}")
    return _check(
        "python",
        "incompatible",
        f"Python {'.'.join(map(str, version))} is below {'.'.join(map(str, MIN_PYTHON))}",
        fix="Install Python 3.11 or newer.",
    )


def check_pytest():
    rc, out = _run([sys.executable, "-m", "pytest", "--version"])
    if rc is None or rc != 0 or "No module named" in out:
        # S4: pytest is mandatory — the script tests cannot run
        # without it — so a missing pytest is incompatible, not
        # incomplete (incomplete is for optional tools only).
        return _check(
            "pytest",
            "incompatible",
            "pytest is not installed (the script tests cannot run without it)",
            fix="pip install pytest==9.0.3",
        )
    version = _version_tuple(out)
    if version is None:
        return _check(
            "pytest", "incompatible", f"pytest is installed but its version is unreadable: {out!r}"
        )
    if version >= MIN_PYTEST:
        return _check("pytest", "ready", f"pytest {'.'.join(map(str, version))}")
    return _check(
        "pytest",
        "incompatible",
        f"pytest {'.'.join(map(str, version))} is below {'.'.join(map(str, MIN_PYTEST))}",
        fix="pip install pytest==9.0.3",
    )


def check_ruff():
    # A ruff binary on PATH (pip install puts one there) first; the
    # module form is the fallback, not the only lookup — the old
    # code only tried `python -m ruff` and reported a PATH-installed
    # ruff as missing.
    binary = shutil.which("ruff")
    argv = [binary, "--version"] if binary else [sys.executable, "-m", "ruff", "--version"]
    rc, out = _run(argv)
    if rc is None or rc != 0 or "No module named" in out:
        # S4: ruff is mandatory — the lint/format gates cannot run
        # without it — so a missing ruff is incompatible.
        return _check(
            "ruff",
            "incompatible",
            "ruff is not installed (the lint gates cannot run without it)",
            fix="pip install ruff==0.17.4",
        )
    version = _version_tuple(out)
    if version is None:
        return _check(
            "ruff", "incompatible", f"ruff is installed but its version is unreadable: {out!r}"
        )
    if version >= MIN_RUFF:
        return _check("ruff", "ready", f"ruff {'.'.join(map(str, version))}")
    return _check(
        "ruff",
        "incompatible",
        f"ruff {'.'.join(map(str, version))} is below {'.'.join(map(str, MIN_RUFF))}",
        fix="pip install ruff==0.17.4",
    )


def check_git():
    rc, out = _run(["git", "--version"])
    if rc is None or rc != 0:
        # S4: git is mandatory — the version-bump and clean-copy
        # gates cannot run without it — so a missing git is
        # incompatible, not incomplete.
        return _check(
            "git",
            "incompatible",
            "git is not installed or does not run (the git gates cannot run without it)",
            fix="Install git.",
        )
    # Round 8, FND-025: the version is parsed, like ruff/pytest/
    # waza — a git printing garbage used to report [ok] on the
    # strength of rc == 0 alone. No minimum is enforced: no
    # minimum git version is documented anywhere in this repo,
    # so any parseable version is ready; only an unreadable one
    # is incompatible.
    version = _version_tuple(out)
    if version is None:
        return _check(
            "git", "incompatible", f"git is installed but its version is unreadable: {out!r}"
        )
    rc2, out2 = _run(["git", "-C", str(ROOT), "status", "--porcelain"], timeout=15)
    if rc2 is None or rc2 != 0:
        # Not a repository (or status timed out) is not a dirty
        # repository: the git gate cannot run here at all.
        return _check(
            "git",
            "incompatible",
            f"{out.strip()}; this directory is not a git repository (git status failed)",
            fix="Run doctor from inside the orcinus-skills repository.",
        )
    state = "clean" if not out2.strip() else "dirty"
    detail = f"{out.strip()}; working tree is {state}"
    if state == "dirty":
        detail += " (uncommitted changes — a verification PASS is bound to the revision, not to this tree)"
    return _check("git", "ready", detail)


def check_node():
    rc, out = _run(["node", "--version"])
    if rc is None or rc != 0 or not out.strip():
        return _check(
            "node",
            "incomplete",
            "node is not installed or does not run (needed for "
            "the demo and the JS/TS skills, not for the Python "
            "gates)",
            fix="Install Node 24 (see docs or nodejs.org).",
        )
    # Round 8, N-B1: same class as FND-025 — the version is
    # parsed, so a node printing garbage is incompatible, not
    # ready. Node is optional when missing (incomplete), but
    # present-but-unreadable is wrong, not ready. No minimum is
    # enforced: no minimum node version is documented here.
    version = _version_tuple(out)
    if version is None:
        return _check(
            "node", "incompatible", f"node is installed but its version is unreadable: {out!r}"
        )
    return _check("node", "ready", f"node {out.strip()}")


def _check_optional_cli(name, detail_missing, fix):
    """One optional external binary, in the check_node shape: missing
    (or not runnable) is incomplete, never incompatible — the gate
    it serves can be skipped — and present-but-unreadable is
    incompatible, like node (round 8, N-B1). No minimum version is
    enforced: no minimum is documented for these tools here."""
    rc, out = _run([name, "--version"])
    if rc is None or rc != 0 or not out.strip():
        return _check(name, "incomplete", detail_missing, fix=fix)
    version = _version_tuple(out)
    if version is None:
        return _check(
            name, "incompatible", f"{name} is installed but its version is unreadable: {out!r}"
        )
    return _check(name, "ready", f"{name} {out.strip()}")


def check_oasdiff():
    # Round 11, FND-013: the breaking-change skill shells out to
    # oasdiff, but doctor had no probe for it — an agent could be
    # routed there on a machine without it and get a shell error
    # instead of an INCOMPLETE step.
    return _check_optional_cli(
        "oasdiff",
        "oasdiff is not installed or does not run (needed for "
        "the breaking-change skill, not for the Python gates)",
        fix="Install oasdiff from github.com/oasdiff/oasdiff/releases, or run go install github.com/oasdiff/oasdiff@latest.",
    )


def check_stryker():
    # Round 11, FND-013: the mutation-testing skill shells out to
    # Stryker, but doctor had no probe for it.
    return _check_optional_cli(
        "stryker",
        "stryker is not installed or does not run (needed for "
        "the mutation-testing skill, not for the Python gates)",
        fix="Install Stryker (npm install -g @stryker-mutator/core, or per-project; see the mutation-testing skill).",
    )


def check_mutmut():
    # Round 11, FND-013: the mutation-testing-python skill shells
    # out to mutmut, but doctor had no probe for it.
    return _check_optional_cli(
        "mutmut",
        "mutmut is not installed or does not run (needed for "
        "the mutation-testing-python skill, not for the Python gates)",
        fix="pip install mutmut",
    )


def _windows_owned_by_current_user(path):
    """Windows ownership check: the file owner's SID must equal one
    of the SIDs that identify the current user as an owner — the
    token's user SID (TokenUser) or its default-owner SID
    (TokenOwner). A file's owner is assigned from the token's
    default owner, not from the user account: for a member of the
    Administrators group the default owner is the Administrators
    group, not the user (Microsoft KB 126629), so comparing only
    against TokenUser rejects an administrator's own files — that
    is the Windows CI failure (runneradmin). Either SID matching
    trusts the file: a non-elevated file is owned by the user SID,
    an elevated admin file by the default-owner SID. Any failure
    to read a SID fails closed (untrusted). ctypes.windll exists
    only on Windows; without it there is no owner to compare, so
    the file is untrusted."""
    import ctypes
    from ctypes import wintypes

    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return False
    advapi32 = windll.advapi32
    kernel32 = windll.kernel32
    TOKEN_QUERY = 0x0008
    TokenUser = 1
    TokenOwner = 4
    OWNER_SECURITY_INFORMATION = 0x00000001

    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetFileSecurityW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetFileSecurityW.restype = wintypes.BOOL
    advapi32.GetSecurityDescriptorOwner.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.BOOL),
    ]
    advapi32.GetSecurityDescriptorOwner.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [wintypes.LPVOID, wintypes.LPVOID]
    advapi32.EqualSid.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    def _token_sid(token, info_class):
        """One SID out of the token (TokenUser or TokenOwner), via
        the two-call GetTokenInformation pattern. Returns (sid,
        buf): the SID pointer and the buffer it points into — the
        caller must keep buf alive while using sid. Returns
        (None, None) when the read fails. TOKEN_USER is
        { SID_AND_ATTRIBUTES User; } and TOKEN_OWNER is
        { PSID Owner; }: both start with the SID pointer."""
        size = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, info_class, None, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, info_class, buf, size, ctypes.byref(size)):
            return None, None
        return ctypes.cast(buf, ctypes.POINTER(wintypes.LPVOID)).contents, buf

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)
    ):
        return False
    try:
        user_sid, user_buf = _token_sid(token, TokenUser)
        if user_sid is None:
            return False
        default_owner_sid, default_owner_buf = _token_sid(token, TokenOwner)
        if default_owner_sid is None:
            return False
        size = wintypes.DWORD(0)
        advapi32.GetFileSecurityW(
            str(path), OWNER_SECURITY_INFORMATION, None, 0, ctypes.byref(size)
        )
        sec = ctypes.create_string_buffer(size.value)
        if not advapi32.GetFileSecurityW(
            str(path), OWNER_SECURITY_INFORMATION, sec, size, ctypes.byref(size)
        ):
            return False
        owner_sid = wintypes.LPVOID()
        defaulted = wintypes.BOOL()
        if not advapi32.GetSecurityDescriptorOwner(
            sec, ctypes.byref(owner_sid), ctypes.byref(defaulted)
        ):
            return False
        return bool(advapi32.EqualSid(user_sid, owner_sid)) or bool(
            advapi32.EqualSid(default_owner_sid, owner_sid)
        )
    finally:
        kernel32.CloseHandle(token)


def _owned_by_current_user(st, path):
    """True when the file is owned by the current user. POSIX
    compares st_uid with os.getuid(); Windows has no getuid, so the
    file owner's SID is compared with the current user's SID or the
    token's default-owner SID (an administrator's files are owned
    by the Administrators group, not the account). Any failure
    fails closed (untrusted)."""
    getuid = getattr(os, "getuid", None)
    if getuid is not None:
        return st.st_uid == getuid()
    return _windows_owned_by_current_user(path)


def _waza_fallback_is_trusted(path):
    """True only when the /tmp fallback binary is a regular file
    owned by the current user whose SHA256 matches the pinned
    release hash. /tmp is world-writable (mode 1777): anyone can
    plant a file there when it is absent, so an unowned or
    mismatched binary is never executed."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode):
        return False
    if not _owned_by_current_user(st, path):
        return False
    try:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return False
    return digest == WAZA_LINUX_SHA256


def check_waza():
    binary = shutil.which("waza")
    fallback = False
    if binary is None and sys.platform.startswith("linux"):
        # CI downloads the Linux binary to /tmp; it is not on PATH.
        # The fallback is Linux-only: on any other platform a
        # missing waza is incomplete without probing a Linux path.
        binary = WAZA_FALLBACK_PATH
        fallback = True
    if binary is None:
        return _check(
            "waza",
            "incomplete",
            "waza is not installed or does not run (needed for "
            "the eval suites, not for the Python gates)",
            fix=f"Download v{WAZA_VERSION} from github.com/microsoft/waza/releases and verify the checksum (see .github/workflows/ci.yml).",
        )
    if fallback and os.path.exists(binary) and not _waza_fallback_is_trusted(binary):
        # Present but untrusted: never execute it. An absent file
        # stays incomplete (the run below reports it as missing).
        return _check(
            "waza",
            "incompatible",
            f"the {binary} fallback is present but untrusted "
            "(not owned by you, or its checksum does not match the "
            f"pinned v{WAZA_VERSION} release hash) — it will not be executed",
            fix=f"Remove {binary}, then re-download v{WAZA_VERSION} from github.com/microsoft/waza/releases and verify the checksum (see .github/workflows/ci.yml).",
        )
    # `waza --version` prints "waza version 0.40.0" (verified live
    # against the v0.40.0 binary). Report the version read from the
    # binary, never the pinned one: a different installed version
    # must be visible, not silently relabelled.
    rc, out = _run([binary, "--version"], timeout=15)
    if rc is None or rc != 0:
        return _check(
            "waza",
            "incomplete",
            "waza is not installed or does not run (needed for "
            "the eval suites, not for the Python gates)",
            fix=f"Download v{WAZA_VERSION} from github.com/microsoft/waza/releases and verify the checksum (see .github/workflows/ci.yml).",
        )
    version = _version_tuple(out)
    if version is None:
        return _check(
            "waza", "incompatible", f"waza runs at {binary} but its version is unreadable: {out!r}"
        )
    if version >= MIN_WAZA:
        return _check("waza", "ready", f"waza {'.'.join(map(str, version))} available at {binary}")
    return _check(
        "waza",
        "incompatible",
        f"waza {'.'.join(map(str, version))} is below {'.'.join(map(str, MIN_WAZA))}",
        fix=f"Download v{WAZA_VERSION} from github.com/microsoft/waza/releases and verify the checksum (see .github/workflows/ci.yml).",
    )


def _repo_version():
    """The repo version, from .claude-plugin/plugin.json — the same
    source validate_repo.py's version checks use. Returns None when
    the file is missing or unparsable, so a caller can report
    'cannot verify' instead of guessing a version."""
    plugin = ROOT / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(plugin.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return None


def _parse_hermes_bundle(path):
    """Parse hermes/orcinus.yaml with validate_repo's stdlib-only
    subset parser — the same parser validate_repo uses for this
    exact file, so doctor and the validator cannot disagree about
    whether it parses. Returns (data, error)."""
    spec = importlib.util.spec_from_file_location(
        "orcinus_validate_repo", ROOT / "scripts" / "validate_repo.py"
    )
    if spec is None or spec.loader is None:
        return None, "cannot load scripts/validate_repo.py"
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.parse_yaml_file(path)
    except Exception as e:  # noqa: BLE001 — any load/parse failure is a diagnostic, not a crash
        return None, str(e)


def check_hermes_bundle():
    # Round 11, FND-009: Hermes compatibility was documented but
    # never executed against a real Hermes install — no Hermes CLI
    # exists in this environment. This check proves the bundle is
    # well-formed (parses, lists only the router, and its version
    # matches the repo version when the bundle carries one), NOT
    # that Hermes runs it.
    path = ROOT / "hermes" / "orcinus.yaml"
    if not path.is_file():
        # Missing is incomplete, never incompatible: Hermes users
        # lose their entry point, but no Python gate depends on it.
        return _check(
            "hermes",
            "incomplete",
            "hermes/orcinus.yaml is missing (the Hermes bundle is "
            "not present; the Claude Code plugin path is unaffected)",
            fix="Restore hermes/orcinus.yaml from the repository.",
        )
    try:
        data, error = _parse_hermes_bundle(path)
    except OSError as e:
        return _check("hermes", "incomplete", f"hermes/orcinus.yaml cannot be read: {e}")
    if error is not None:
        return _check("hermes", "incompatible", f"hermes/orcinus.yaml: unparsable YAML: {error}")
    if not isinstance(data, dict):
        return _check("hermes", "incompatible", "hermes/orcinus.yaml: the bundle is not a mapping")
    skills = data.get("skills")
    if skills != ["orcinus"]:
        # A bundle loads everything it lists at once, so listing
        # sub-skills would dump the whole collection into one
        # message; and without the router there is no entry point.
        return _check(
            "hermes",
            "incompatible",
            f"hermes/orcinus.yaml: skills must be exactly ['orcinus'], got {skills!r}",
        )
    # The bundle carries no version field today, so the version
    # comparison only applies when one is present — a missing field
    # is not a mismatch, it is an unversioned bundle.
    bundle_version = data.get("version")
    if bundle_version is None:
        return _check(
            "hermes",
            "ready",
            "hermes/orcinus.yaml parses and lists only the router "
            "skill 'orcinus' (no version field in the bundle, so no "
            "version to pin) — well-formed only, never loaded by a "
            "real Hermes installation",
        )
    repo_version = _repo_version()
    if repo_version is None:
        return _check(
            "hermes",
            "incomplete",
            f"hermes/orcinus.yaml lists only the router, but the repo "
            f"version in .claude-plugin/plugin.json is unreadable, so "
            f"bundle version {bundle_version!r} could not be checked",
        )
    if str(bundle_version) != str(repo_version):
        return _check(
            "hermes",
            "incompatible",
            f"hermes/orcinus.yaml version {bundle_version!r} != repo version {repo_version!r}",
        )
    return _check(
        "hermes",
        "ready",
        f"hermes/orcinus.yaml parses, lists only the router skill "
        f"'orcinus', and version {bundle_version!r} matches the repo "
        f"version — well-formed only, never loaded by a real Hermes "
        f"installation",
    )


def check_repo_files():
    missing = []
    for rel in (
        "skills/manifest.json",
        "skills/orcinus-verify/references/evidence.schema.json",
        "skills/orcinus-verify/scripts/validate_evidence.py",
        "scripts/validate_repo.py",
        "scripts/check_drift.py",
        "pyproject.toml",
    ):
        if not (ROOT / rel).is_file():
            missing.append(rel)
    if missing:
        # S4, same class: the repo files ARE the gates — without
        # them no gate can run, so missing files are incompatible.
        return _check("repo files", "incompatible", f"missing: {', '.join(missing)}")
    return _check(
        "repo files",
        "ready",
        "manifest, evidence schema, validator, drift check, and ruff config are present",
    )


def main():
    checks = [
        check_python(),
        check_pytest(),
        check_ruff(),
        check_git(),
        check_node(),
        check_oasdiff(),
        check_stryker(),
        check_mutmut(),
        check_waza(),
        check_hermes_bundle(),
        check_repo_files(),
    ]
    print(f"ORCINUS doctor — {ROOT} (Python {platform.python_version()})")
    worst = 0
    for c in checks:
        mark = {"ready": "ok  ", "incomplete": "MISS", "incompatible": "BAD "}[c["status"]]
        print(f"  [{mark}] {c['name']}: {c['detail']}")
        if c.get("fix"):
            print(f"         -> {c['fix']}")
        if c["status"] == "incompatible":
            worst = max(worst, 2)
        elif c["status"] == "incomplete":
            worst = max(worst, 1)
    ready = sum(1 for c in checks if c["status"] == "ready")
    print(f"{ready}/{len(checks)} ready")
    if worst == 0:
        print("All gates can run here.")
    elif worst == 1:
        print(
            "Some optional tools are missing (see MISS above). A "
            "verification that needs one of them is INCOMPLETE, not PASS."
        )
    else:
        print(
            "A tool is present but incompatible (see BAD above). Fix it "
            "before trusting a verification run."
        )
    return worst


if __name__ == "__main__":
    sys.exit(main())
