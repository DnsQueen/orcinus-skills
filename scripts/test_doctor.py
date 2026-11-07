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


def test_python_minimum_is_3_11():
    # Python 3.10 reached end-of-life 2026-10-01 (PEP 619) and was
    # dropped 2026-11-07 (round 6, 2-S7), the same logic that dropped
    # 3.9 in 2026-11-06; doctor must not report 3.10 as ready.
    assert doctor.MIN_PYTHON == (3, 11)
    result = doctor.check_python((3, 10, 0))
    assert result["status"] == "incompatible"
    assert "3.11" in result["fix"]
    assert doctor.check_python((3, 11, 0))["status"] == "ready"


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


# --- Round 6 (2026-11-07): S3 + S4 + 2-S6 + 2-S7 ---


def test_run_returns_none_on_permission_error(monkeypatch):
    """S3: _run caught only FileNotFoundError/TimeoutExpired, so a
    non-executable file raised PermissionError out of _run and out of
    every check — an uncaught traceback, outside the 0/1/2 scheme.
    PermissionError is an OSError; _run must return (None, '')."""
    import subprocess

    def boom(argv, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(subprocess, "run", boom)
    assert doctor._run(["/nonexistent/noexec"]) == (None, "")


def test_permission_error_in_check_is_controlled(monkeypatch):
    """S3, end to end: a check whose tool run raises PermissionError
    reports a status, it does not raise. (The run is faked at the
    subprocess level, so the real _run — with its except — is what
    is under test.)"""
    import subprocess

    def boom(argv, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/ruff")
    result = doctor.check_ruff()
    assert result["status"] in ("incomplete", "incompatible")


def test_missing_mandatory_tools_are_incompatible(monkeypatch):
    """S4: git missing and optional waza/node missing both returned
    `incomplete` + exit 1, although the docstring defines incomplete
    as 'the tool is missing, but the gate it serves can be skipped'
    — false for git/python/pytest/ruff, whose gates cannot run at
    all. A missing mandatory tool is incompatible (exit 2); only a
    missing optional tool is incomplete."""
    _patched_run(monkeypatch, {})
    assert doctor.check_git()["status"] == "incompatible"
    assert doctor.check_pytest()["status"] == "incompatible"
    assert doctor.check_ruff()["status"] == "incompatible"


def test_missing_optional_tools_stay_incomplete(monkeypatch):
    """S4: node and waza are optional (the demo / eval suites, not
    the Python gates) — missing them stays incomplete, exit 1."""
    _patched_run(monkeypatch, {})
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    assert doctor.check_node()["status"] == "incomplete"
    assert doctor.check_waza()["status"] == "incomplete"


def test_git_outside_repo_is_incompatible(monkeypatch):
    """S4: the not-a-repo branch returned incomplete while its own
    comment says 'the git gate cannot run here at all' — the
    docstring's definition of incompatible."""
    _patched_run(
        monkeypatch,
        {
            ("git", "--version"): (0, "git version 2.40.0"),
            ("git", "-C"): (128, "fatal: not a git repository"),
        },
    )
    assert doctor.check_git()["status"] == "incompatible"


def test_main_exit_2_for_missing_git(monkeypatch, capsys):
    """S4: a machine with no git cannot verify at all — exit 2, not
    the exit 1 of a merely-optional missing tool."""
    _all_ready(monkeypatch, {"check_git": "incompatible"})
    assert doctor.main() == 2


def test_main_exit_1_for_missing_optional_only(monkeypatch, capsys):
    """S4: a machine missing only node/waza stays exit 1."""
    _all_ready(monkeypatch, {"check_node": "incomplete", "check_waza": "incomplete"})
    assert doctor.main() == 1


def test_ci_waza_hash_matches_doctor_pin():
    """2-S6: the waza checksum pinned in CI must be the same value
    doctor gates the /tmp fallback on — one pinned hash, not two
    that can drift apart."""
    import re

    ci = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert doctor.WAZA_LINUX_SHA256 in ci, (
        "ci.yml does not pin the same waza SHA256 as doctor.WAZA_LINUX_SHA256"
    )
    assert "checksums.txt" not in ci, (
        "ci.yml still downloads the checksum from the release — the "
        "check is not anti-forgery while the hash comes from the same "
        "release it verifies"
    )
    assert re.search(r"[0-9a-f]{64}", ci)


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
    monkeypatch.setattr(doctor.os, "getuid", lambda: 999999, raising=False)
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


# --- Round-6 follow-up (2026-11-07): the /tmp waza trust check is
# POSIX-only — os.getuid does not exist on Windows, so the check
# crashed with AttributeError instead of answering. Ownership is
# now compared through _owned_by_current_user: st_uid vs getuid on
# POSIX, the file owner's SID vs the current user's SID on Windows.
# Either side failing fails closed (untrusted), never raises. ---


def test_waza_fallback_without_getuid_is_untrusted(tmp_path, monkeypatch):
    """Windows has no os.getuid: the trust check must answer
    untrusted, not raise AttributeError."""
    binary = _planted_waza(tmp_path)
    monkeypatch.delattr(doctor.os, "getuid", raising=False)
    assert doctor._waza_fallback_is_trusted(str(binary)) is False


def test_windows_ownership_check_fails_closed_without_windll():
    """The Windows SID comparison has no windll outside Windows:
    it must fail closed, never raise."""
    assert doctor._windows_owned_by_current_user("whatever") is False


def _fake_windll(*, user_sid, owner_sid):
    """A stand-in for ctypes.windll: canned user and file-owner
    SIDs, so the Windows ownership comparison can be exercised
    without Windows. The SID bytes are 8 bytes each."""
    import ctypes
    import types

    kept = []  # buffers handed out as SID pointers must stay alive

    def sid_pointer(sid):
        buf = ctypes.create_string_buffer(sid, len(sid))
        kept.append(buf)
        return ctypes.addressof(buf)

    def open_process_token(_process, _access, token_ref):
        token_ref._obj.value = 1
        return 1

    def get_token_information(_token, _cls, buf, _size, ret_size):
        if buf is None:
            ret_size._obj.value = 16
            return 0
        ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p)).contents.value = sid_pointer(user_sid)
        return 1

    def get_file_security(_path, _info, _sec, _size, ret_size):
        if _sec is None:
            ret_size._obj.value = 16
            return 0
        return 1

    def get_security_descriptor_owner(_sec, owner_ref, defaulted_ref):
        owner_ref._obj.value = sid_pointer(owner_sid)
        defaulted_ref._obj.value = 0
        return 1

    def equal_sid(a, b):
        return 1 if ctypes.string_at(a.value, 8) == ctypes.string_at(b.value, 8) else 0

    def get_current_process():
        return 1234

    def close_handle(_handle):
        return 1

    return types.SimpleNamespace(
        advapi32=types.SimpleNamespace(
            OpenProcessToken=open_process_token,
            GetTokenInformation=get_token_information,
            GetFileSecurityW=get_file_security,
            GetSecurityDescriptorOwner=get_security_descriptor_owner,
            EqualSid=equal_sid,
        ),
        kernel32=types.SimpleNamespace(
            GetCurrentProcess=get_current_process,
            CloseHandle=close_handle,
        ),
    )


def test_windows_ownership_check_compares_sids(monkeypatch):
    """The Windows ownership check trusts the file only when the
    owner's SID equals the current user's SID."""
    import ctypes

    monkeypatch.setattr(
        ctypes,
        "windll",
        _fake_windll(user_sid=b"USER-SID", owner_sid=b"USER-SID"),
        raising=False,
    )
    assert doctor._windows_owned_by_current_user("whatever") is True
    monkeypatch.setattr(
        ctypes,
        "windll",
        _fake_windll(user_sid=b"USER-SID", owner_sid=b"OTHER-ID"),
        raising=False,
    )
    assert doctor._windows_owned_by_current_user("whatever") is False


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
