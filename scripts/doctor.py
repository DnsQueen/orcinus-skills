#!/usr/bin/env python3
"""ORCINUS doctor — check whether this machine can run the ORCINUS
gates, and say exactly which ones it cannot.

Each check reports one of three states:
- ready: the tool is installed and usable;
- incomplete: the tool is missing, but the gate it serves can be
  skipped (the report says what is unverified because of it);
- incompatible: the tool is present but the wrong version, or the
  environment cannot run the gate at all.

Usage: python3 scripts/doctor.py
Exit 0 when every gate that must run here is ready; exit 1 when any
gate is incomplete; exit 2 when any gate is incompatible (the
report says which).

This is a diagnostic, not a gate: it never changes anything, never
installs anything, and never claims a check passed. It tells the
user what to install before they trust a verification run.
"""

import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The minimum versions the gates need. pytest 8.4.2 and ruff 0.17.4
# are the pinned versions in CI. Python 3.9 itself was dropped
# 2026-11-06: it reached end-of-life 2025-10-31 and has no build for
# Ubuntu 26.04, which is what the CI runner is now.
MIN_PYTHON = (3, 10)
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
WAZA_FALLBACK_PATH = "/tmp/waza-linux-amd64"
WAZA_LINUX_SHA256 = "d09117a3c631f44a00a6c362462c951aed83c87751e8c25f39916a77d1013802"


def _run(argv, timeout=10):
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
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
        fix="Install Python 3.10 or newer.",
    )


def check_pytest():
    rc, out = _run([sys.executable, "-m", "pytest", "--version"])
    if rc is None or rc != 0 or "No module named" in out:
        return _check(
            "pytest", "incomplete", "pytest is not installed", fix="pip install pytest==8.4.2"
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
        fix="pip install pytest==8.4.2",
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
        return _check("ruff", "incomplete", "ruff is not installed", fix="pip install ruff==0.17.4")
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
        return _check(
            "git", "incomplete", "git is not installed or does not run", fix="Install git."
        )
    rc2, out2 = _run(["git", "-C", str(ROOT), "status", "--porcelain"], timeout=15)
    if rc2 is None or rc2 != 0:
        # Not a repository (or status timed out) is not a dirty
        # repository: the git gate cannot run here at all.
        return _check(
            "git",
            "incomplete",
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
    return _check("node", "ready", f"node {out.strip()}")


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
    if st.st_uid != os.getuid():
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
        return _check("repo files", "incomplete", f"missing: {', '.join(missing)}")
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
        check_waza(),
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
            "Some gates cannot run here (see MISS above). A verification "
            "that needs one of them is INCOMPLETE, not PASS."
        )
    else:
        print(
            "A tool is present but incompatible (see BAD above). Fix it "
            "before trusting a verification run."
        )
    return worst


if __name__ == "__main__":
    sys.exit(main())
