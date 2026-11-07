"""Tests for doctor.py (the environment diagnostic).

The doctor must distinguish three states honestly: ready, incomplete
(missing, skippable), and incompatible (present but wrong). A missing
tool reported as ready would let a verification claim PASS on a gate
that never ran; a missing tool reported as incompatible would send
the user fixing the wrong thing.

Run: python3 -m pytest scripts/test_doctor.py -q
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import doctor  # noqa: E402


def test_version_tuple():
    assert doctor._version_tuple("pytest 8.4.2") == (8, 4, 2)
    assert doctor._version_tuple("ruff 0.17.4") == (0, 17, 4)
    assert doctor._version_tuple("8.4.2") == (8, 4, 2)
    assert doctor._version_tuple("no version here") is None
    assert doctor._version_tuple("") is None


def test_python_check_ready():
    result = doctor.check_python()
    assert result["status"] == "ready"
    assert "Python" in result["detail"]


def test_repo_files_check_ready():
    result = doctor.check_repo_files()
    assert result["status"] == "ready"


def test_git_check_ready(tmp_path, monkeypatch):
    """Git is ready inside a real repository — the check runs against
    a repo the test creates, not the checkout pytest happens to run
    in. The old version asserted ready in the current directory, so
    it failed in the clean copy (which has no .git by design) and
    passed vacuously anywhere git was installed."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, timeout=30)
    monkeypatch.setattr(doctor, "ROOT", repo)
    result = doctor.check_git()
    assert result["status"] == "ready"
    assert "git version" in result["detail"]


def test_check_shape():
    for check in (doctor.check_python(), doctor.check_git(), doctor.check_repo_files()):
        assert set(check) == {"name", "status", "detail", "fix"}
        assert check["status"] in ("ready", "incomplete", "incompatible")


# --- Round-3 regression tests (reviewer 4, section 5). ---


def test_python_minimum_is_3_10():
    # Python 3.9 was dropped 2026-11-06 (EOL, no Ubuntu 26.04 build);
    # doctor must not report 3.9 as ready.
    assert doctor.MIN_PYTHON == (3, 10)
    result = doctor.check_python((3, 9, 0))
    assert result["status"] == "incompatible"
    assert "3.10" in result["fix"]
    assert doctor.check_python((3, 10, 0))["status"] == "ready"


def _patched_run(monkeypatch, mapping):
    """Replace doctor._run with a stub returning (rc, out) per argv."""

    def fake(argv, timeout=10):
        for key, value in mapping.items():
            if argv[: len(key)] == list(key):
                return value
        return (None, "")

    monkeypatch.setattr(doctor, "_run", fake)


def test_node_nonzero_exit_is_not_ready(monkeypatch):
    _patched_run(monkeypatch, {("node", "--version"): (1, "error")})
    result = doctor.check_node()
    assert result["status"] != "ready"


def test_git_version_failure_is_not_ready(monkeypatch):
    _patched_run(monkeypatch, {("git", "--version"): (1, "")})
    result = doctor.check_git()
    assert result["status"] != "ready"


def test_git_outside_repo_is_not_dirty_and_not_ready(monkeypatch):
    def fake(argv, timeout=10):
        if argv[:2] == ["git", "--version"]:
            return (0, "git version 2.40.0")
        return (128, "fatal: not a git repository")

    monkeypatch.setattr(doctor, "_run", fake)
    result = doctor.check_git()
    assert result["status"] != "ready"
    assert "dirty" not in result["detail"]
    assert "not a git repository" in result["detail"]


def test_waza_nonzero_exit_is_not_ready(monkeypatch):
    def fake(argv, timeout=10):
        return (1, "error")

    monkeypatch.setattr(doctor, "_run", fake)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/waza")
    result = doctor.check_waza()
    assert result["status"] != "ready"


def test_waza_reports_extracted_version(monkeypatch):
    # `waza --version` prints "waza version 0.40.0" (verified live).
    # Doctor must report the version it read, never the pinned one.
    def fake(argv, timeout=10):
        assert argv[1] == "--version"
        return (0, "waza version 0.41.0")

    monkeypatch.setattr(doctor, "_run", fake)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/waza")
    result = doctor.check_waza()
    assert result["status"] == "ready"
    assert "0.41.0" in result["detail"]
    assert "0.40.0" not in result["detail"]


def test_waza_unreadable_version_is_incompatible(monkeypatch):
    def fake(argv, timeout=10):
        return (0, "no version here")

    monkeypatch.setattr(doctor, "_run", fake)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/waza")
    result = doctor.check_waza()
    assert result["status"] == "incompatible"


# --- round 4, track 6: ruff on PATH, waza fallback, exit codes. ---


def test_ruff_found_on_path(tmp_path, monkeypatch):
    """A ruff binary on PATH (pip install puts one there) must be
    found — the old code only tried `python -m ruff` and reported a
    PATH-installed ruff as missing. The module lookup is disabled
    here (a python with no ruff module), so only the PATH lookup
    can make this pass."""
    fake = tmp_path / "ruff"
    fake.write_text("#!/bin/sh\necho 'ruff 0.17.4'\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)
    monkeypatch.setattr(doctor.sys, "executable", "/nonexistent/python")
    result = doctor.check_ruff()
    assert result["status"] == "ready"
    assert "0.17.4" in result["detail"]


def test_ruff_falls_back_to_module(monkeypatch):
    """When no ruff binary is on PATH, `python -m ruff` is still a
    valid find — the PATH lookup must not replace the fallback.
    The module run is faked here (2-E4): the test pins the lookup
    order, it must not depend on a real ruff module being installed
    in this Python."""
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    called = []

    def fake(argv, timeout=10):
        called.append(argv)
        return 0, "ruff 0.17.4"

    monkeypatch.setattr(doctor, "_run", fake)
    result = doctor.check_ruff()
    assert result["status"] == "ready"
    assert called == [[doctor.sys.executable, "-m", "ruff", "--version"]]


def test_waza_fallback_is_linux_only(monkeypatch):
    """The /tmp/waza-linux-amd64 fallback is a Linux binary: on any
    other platform a missing waza must be reported incomplete
    without ever probing that path."""
    called = []
    monkeypatch.setattr(doctor, "_run", lambda argv, timeout=10: called.append(argv) or (None, ""))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    result = doctor.check_waza()
    assert result["status"] == "incomplete"
    assert called == [], "the Linux fallback must not run on darwin"


def test_waza_fallback_used_on_linux(monkeypatch):
    """On Linux the /tmp fallback stays: CI downloads the binary
    there and it is not on PATH."""
    called = []
    monkeypatch.setattr(doctor, "_run", lambda argv, timeout=10: called.append(argv) or (None, ""))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    result = doctor.check_waza()
    assert result["status"] == "incomplete"
    assert called == [["/tmp/waza-linux-amd64", "--version"]]


# --- Round 6 (2026-11-07): S2 — the /tmp waza fallback is gated on
# ownership + a pinned checksum. /tmp is world-writable: anyone can
# plant a binary there when it is absent, and doctor used to execute
# it and report ready. A planted binary must never be executed. ---


def _planted_waza(tmp_path, content=b"#!/bin/sh\necho 'waza version 0.40.0'\n"):
    """A fake /tmp fallback binary, owned by the test user."""
    binary = tmp_path / "waza-linux-amd64"
    binary.write_bytes(content)
    binary.chmod(0o755)
    return binary


def test_waza_fallback_planted_binary_is_not_executed(tmp_path, monkeypatch):
    """S2: a planted binary (wrong checksum, right owner) is
    incompatible, and doctor never executes it."""
    binary = _planted_waza(tmp_path)
    called = []
    monkeypatch.setattr(doctor, "_run", lambda argv, timeout=10: called.append(argv) or (0, ""))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    monkeypatch.setattr(doctor, "WAZA_FALLBACK_PATH", str(binary))
    result = doctor.check_waza()
    assert result["status"] == "incompatible"
    assert called == [], "a planted binary must never be executed"
    assert "checksum" in result["detail"]


def test_waza_fallback_wrong_owner_is_not_executed(tmp_path, monkeypatch):
    """S2: a binary with the right checksum but the wrong owner is
    still untrusted — /tmp is shared, so ownership is part of the
    gate, not just the hash."""
    import hashlib

    binary = _planted_waza(tmp_path)
    called = []
    monkeypatch.setattr(doctor, "_run", lambda argv, timeout=10: called.append(argv) or (0, ""))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    monkeypatch.setattr(doctor, "WAZA_FALLBACK_PATH", str(binary))
    monkeypatch.setattr(
        doctor, "WAZA_LINUX_SHA256", hashlib.sha256(binary.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(doctor.os, "getuid", lambda: 999999)
    result = doctor.check_waza()
    assert result["status"] == "incompatible"
    assert called == [], "an unowned binary must never be executed"


def test_waza_fallback_trusted_binary_is_ready(tmp_path, monkeypatch):
    """S2: the gate must still let the real fallback through — a
    binary owned by the user whose hash matches the pinned release
    hash is ready. (The pinned hash is monkeypatched here to the
    fake file's hash; the gate logic, not the constant, is under
    test. The constant itself is the v0.40.0 release hash, verified
    against the downloaded binary.)"""
    import hashlib

    binary = _planted_waza(tmp_path)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    monkeypatch.setattr(doctor, "WAZA_FALLBACK_PATH", str(binary))
    monkeypatch.setattr(
        doctor, "WAZA_LINUX_SHA256", hashlib.sha256(binary.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(doctor, "_run", lambda argv, timeout=10: (0, "waza version 0.40.0"))
    result = doctor.check_waza()
    assert result["status"] == "ready"
    assert "0.40.0" in result["detail"]


def test_waza_fallback_missing_file_stays_incomplete(tmp_path, monkeypatch):
    """S2: an absent fallback binary is incomplete (missing), not
    incompatible — the gate only distrusts a binary that exists."""
    called = []
    monkeypatch.setattr(doctor, "_run", lambda argv, timeout=10: called.append(argv) or (None, ""))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    monkeypatch.setattr(doctor, "WAZA_FALLBACK_PATH", str(tmp_path / "waza-linux-amd64"))
    result = doctor.check_waza()
    assert result["status"] == "incomplete"
    assert called == [[str(tmp_path / "waza-linux-amd64"), "--version"]]


def _all_ready(monkeypatch, override):
    """Every doctor check returns ready except the one named in
    `override` (name -> status)."""
    for name in (
        "check_python",
        "check_pytest",
        "check_ruff",
        "check_git",
        "check_node",
        "check_waza",
        "check_repo_files",
    ):
        status = override.get(name, "ready")
        monkeypatch.setattr(doctor, name, lambda s=status: doctor._check("x", s, "x"))


def test_main_exit_1_for_incomplete_only(monkeypatch, capsys):
    """The docstring says exit 1 for incomplete: only incomplete
    checks (no incompatible one) must return 1."""
    _all_ready(monkeypatch, {"check_waza": "incomplete"})
    assert doctor.main() == 1


def test_main_exit_2_for_incompatible(monkeypatch, capsys):
    """The docstring said exit 1 for incomplete OR incompatible,
    but the code returns 2 for incompatible — the docstring was
    wrong, not the code. One incompatible check returns 2 even
    when another is merely incomplete."""
    _all_ready(monkeypatch, {"check_waza": "incompatible", "check_node": "incomplete"})
    assert doctor.main() == 2
