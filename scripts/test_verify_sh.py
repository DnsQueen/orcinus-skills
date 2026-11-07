"""Tests for skills/monitoring/scripts/verify.sh.

The script is a bash gate, so the tests run it as a subprocess
against throwaway config dirs — the same style as
test_check_refactor.py. Round 6 (2-S3 / 3-F2-04 / 3-F2-05).

Run: python3 -m pytest scripts/test_verify_sh.py -q
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "monitoring" / "scripts" / "verify.sh"


def _decode_output(raw: bytes) -> str:
    """Decode subprocess output, including UTF-16LE.

    wsl.exe writes UTF-16LE, so decoding its output as the locale
    encoding yields NUL-separated garbage (``W\\x00i\\x00n...``) and
    every assertion on it fails unreadably. NUL bytes are the tell:
    decode those as UTF-16LE so a failure caused by invoking the WSL
    launcher reports a readable message instead.
    """
    if b"\x00" in raw:
        try:
            return raw.decode("utf-16-le")
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def _bash_exe() -> str:
    """A bash that can actually run verify.sh.

    On Windows, bare ``bash`` resolves to
    C:\\Windows\\System32\\bash.exe — the WSL launcher, not a shell.
    With no WSL distribution installed it fails with "Windows
    Subsystem for Linux has no installed distributions" instead of
    running the script (that is what broke all six tests on the
    Windows runner). Git for Windows ships a real bash, so prefer it:
    via the git install, the usual Program Files locations, or any
    non-System32 bash on PATH. Only fall back to bare ``bash`` when
    no usable one was found, so the failure is loud, not a silent
    WSL error.
    """
    if sys.platform != "win32":
        return "bash"
    candidates: list[Path] = []
    git = shutil.which("git")
    if git:
        # git.exe lives in <root>\\cmd or <root>\\bin; bash is in <root>\\bin.
        candidates.append(Path(git).resolve().parent.parent / "bin" / "bash.exe")
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            candidates.append(Path(base) / "Git" / "bin" / "bash.exe")
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    wsl_dirs = {system_root / "System32", system_root / "SysWOW64"}
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(entry) / "bash.exe"
        if not candidate.is_file():
            continue
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.parent in wsl_dirs:
            continue  # the WSL launcher, not a shell
        candidates.append(candidate)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return "bash"


def _run(target):
    proc = subprocess.run([_bash_exe(), str(SCRIPT), str(target)], capture_output=True, timeout=30)
    return proc.returncode, _decode_output(proc.stdout + proc.stderr)


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


GOOD = """\
alerts:
  - name: HighErrorRate
    expr: error_rate > 0.05
    windows: [5m, 1h]
    burn_rate: 14.4
    runbook: https://example.com/runbooks/high-error-rate
health:
  livez: /livez
  readyz: /readyz
monitors:
  - target: /api/checkout
"""

# Every load-bearing keyword appears ONLY in comments; the real
# content is a bare cpu threshold. Before the fix the gate passed
# this vacuously on the comments (3-F2-04); the eval
# (evals/monitoring-01.md) had to remove the comments to make the
# bad config fail honestly.
COMMENT_ONLY_BAD = """\
# liveness and readiness are split: /livez and /readyz
# burn_rate multi-window alert with runbook reference
# critical journey target, not the homepage
alerts:
  - name: HighCpu
    expr: cpu > 90
monitors:
  - target: /
"""


def test_missing_path_is_incomplete_not_skip(tmp_path):
    """2-S3 / 3-F2-05: a nonexistent path used to print SKIP and exit
    0 — indistinguishable from a clean config. A path that does not
    exist means nothing was checked: INCOMPLETE, exit 2."""
    rc, out = _run(tmp_path / "does-not-exist")
    assert rc == 2, out
    assert "INCOMPLETE" in out or "not found" in out.lower()


def test_comment_keywords_do_not_pass(tmp_path):
    """3-F2-04: keywords in comments must not satisfy any check —
    the config above has no real liveness/readiness split, no
    burn-rate alert, no runbook, and only a cpu threshold."""
    _write(tmp_path, "alerts.yml", COMMENT_ONLY_BAD)
    rc, out = _run(tmp_path)
    assert rc == 1, out
    assert "only cause-based" in out
    assert "no runbook" in out
    # With the comments stripped the config has NO health spec at
    # all, so check 2 honestly skips instead of failing on a split
    # that was never specified — what matters is that no comment
    # keyword passes it: there is no PASS for liveness/readiness.
    assert "no health-endpoint spec present" in out
    assert "PASS: health spec separates" not in out


def test_comment_opsgenie_does_not_fail(tmp_path):
    """3-F2-04, banlist side: an Opsgenie mention in a comment only
    (e.g. a do-not note or a historical mention) must not fail the
    gate — the stripped haystack has no opsgenie at all."""
    _write(
        tmp_path,
        "alerts.yml",
        "# opsgenie alerting was configured in the old console\n" + GOOD,
    )
    rc, out = _run(tmp_path)
    assert rc == 0, out


def test_good_config_still_passes_with_comments(tmp_path):
    """Control: stripping full-line comments must not break a good
    config that also carries comments."""
    _write(tmp_path, "alerts.yml", "# deployment notes\n" + GOOD)
    rc, out = _run(tmp_path)
    assert rc == 0, out


def test_summary_reports_counts(tmp_path):
    """The summary reports how much was actually gated — candidate
    files and alert blocks — so a pass over one file cannot be
    mistaken for a pass over the whole config."""
    _write(tmp_path, "alerts.yml", GOOD)
    rc, out = _run(tmp_path)
    assert rc == 0, out
    assert "1 candidate" in out
    assert "alert" in out.lower()


def test_empty_dir_still_passes(tmp_path):
    """Documented policy, unchanged: an existing path with no
    monitoring candidates exits 0 — a clean target is never a
    failure. (The reviewer's --allow-empty suggestion for this case
    was skipped: there is nothing to allow, the exit already says
    nothing was gated.)"""
    rc, out = _run(tmp_path)
    assert rc == 0, out
    assert "nothing to gate" in out


def test_wsl_launcher_output_is_decoded_readably(tmp_path, monkeypatch):
    """Regression: on Windows, bare ``bash`` resolves to the WSL
    launcher (System32\\bash.exe). With no distribution installed it
    fails, and wsl.exe writes UTF-16LE — the old text=True decode
    produced NUL-separated garbage, so every assertion on the output
    failed unreadably. The harness must surface the message readably.
    Reproduced on Linux by stubbing ``bash`` on PATH with a script
    that emits the exact WSL message in UTF-16LE."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_bash = fake_bin / "bash"
    fake_bash.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stderr.buffer.write(\n"
        "    'Windows Subsystem for Linux has no installed distributions.\\n'.encode('utf-16-le')\n"
        ")\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    fake_bash.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ["PATH"])
    rc, out = _run(tmp_path / "does-not-exist")
    assert rc == 1, out
    assert "no installed distributions" in out
    assert "\x00" not in out


def test_windows_prefers_git_bash_over_wsl_launcher(tmp_path, monkeypatch):
    """On Windows the System32 ``bash.exe`` is the WSL launcher, not
    a shell: it must never be picked, even when it is the only bash
    on PATH. Git Bash (via the git install) wins. Simulated on Linux
    by stubbing the platform and environment — the candidates are
    only checked for existence, never executed here."""
    git_bin = tmp_path / "Git" / "bin"
    git_bin.mkdir(parents=True)
    git_bash = git_bin / "bash.exe"
    git_bash.write_bytes(b"")
    (tmp_path / "Git" / "cmd").mkdir()
    fake_git = tmp_path / "Git" / "cmd" / "git.exe"
    fake_git.write_bytes(b"")
    system32 = tmp_path / "System32"
    system32.mkdir()
    (system32 / "bash.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    monkeypatch.setenv("PATH", str(system32))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "no-git-here"))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: str(fake_git) if name == "git" else None)
    assert _bash_exe() == str(git_bash)
