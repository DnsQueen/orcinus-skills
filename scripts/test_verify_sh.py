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
    launcher reports a readable message instead. A UTF-16LE BOM
    (``FF FE``) decodes to a leading U+FEFF, which is not part of
    the message, so it is stripped.
    """
    if b"\x00" in raw:
        try:
            text = raw.decode("utf-16-le")
        except UnicodeDecodeError:
            pass
        else:
            return text[1:] if text.startswith("\ufeff") else text
    return raw.decode("utf-8", errors="replace")


def _bash_exe() -> str:
    """A bash that can actually run verify.sh.

    On Windows, bare ``bash`` resolves to
    C:\\Windows\\System32\\bash.exe — the WSL launcher, not a shell.
    With no WSL distribution installed it fails with "Windows
    Subsystem for Linux has no installed distributions" instead of
    running the script (that is what broke all six tests on the
    Windows runner). Git for Windows ships a real bash, so prefer
    one that can run the script: first a bash on PATH, then via the
    git install or the usual Program Files locations. Only fall back
    to bare ``bash`` when no usable one was found, so the failure is
    loud, not a silent WSL error. PATH is checked first so a stub
    planted first on PATH wins (that is how the tests fake bash).
    The PATH scan is PATHEXT-aware, so a ``bash.cmd`` shim is found
    as well as ``bash.exe`` — but an extensionless ``bash`` is never
    a candidate: Windows cannot execute it (CreateProcess only
    tries the exact name and ``.exe``), so it must never be picked.
    Any System32/SysWOW64 bash.exe is the WSL launcher, not a shell,
    and is skipped wherever it appears.
    """
    if sys.platform != "win32":
        return "bash"
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    wsl_dirs = {system_root / "System32", system_root / "SysWOW64"}
    candidates: list[Path] = []
    # PATHEXT is semicolon-separated even when the platform is
    # stubbed on Linux (os.pathsep is ":" there); split on ";".
    pathext = [
        ext.strip().lower()
        for ext in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";")
        if ext.strip()
    ]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        for ext in pathext:
            candidate = Path(entry) / ("bash" + ext)
            if not candidate.is_file():
                continue
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved.parent in wsl_dirs:
                continue  # the WSL launcher, not a shell
            candidates.append(candidate)
    git = shutil.which("git")
    if git:
        # git.exe lives in <root>\\cmd or <root>\\bin; bash is in <root>\\bin.
        candidates.append(Path(git).resolve().parent.parent / "bin" / "bash.exe")
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            candidates.append(Path(base) / "Git" / "bin" / "bash.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return "bash"


def _run(*args):
    bash = _bash_exe()
    argv = [bash, str(SCRIPT), *[str(a) for a in args]]
    if sys.platform == "win32" and os.path.splitext(bash)[1].lower() in (".bat", ".cmd"):
        # A batch-file bash cannot be started by CreateProcess
        # directly; it has to go through the command interpreter
        # (same rule as run_eval._resolve_claude).
        comspec = os.environ.get("ComSpec")
        if not comspec:
            comspec = os.path.join(
                os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe"
            )
        argv = [comspec, "/c", bash, str(SCRIPT), *[str(a) for a in args]]
    proc = subprocess.run(argv, capture_output=True, timeout=30)
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
    Reproduced by stubbing ``bash`` on PATH with a script that emits
    the WSL message in UTF-16LE (with a BOM, the wide-char shape
    Windows tools produce). The stub is planted in both forms: the
    POSIX script (``bash``) and the Windows form (``bash.cmd``
    forwarding to a Python impl) — Windows cannot execute an
    extensionless file, so the script alone is never started there
    (same rule as run_eval's fake claude) and the test failed on the
    Windows runner with the real Git Bash running verify.sh instead
    (rc 2, INCOMPLETE)."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    body = (
        "import sys\n"
        "sys.stderr.buffer.write(\n"
        "    b'\\xff\\xfe' + 'Windows Subsystem for Linux has no installed distributions.\\n'.encode('utf-16-le')\n"
        ")\n"
        "sys.exit(1)\n"
    )
    text = "#!/usr/bin/env python3\n" + body
    fake_bash = fake_bin / "bash"
    fake_bash.write_text(text, encoding="utf-8")
    fake_bash.chmod(0o755)
    impl = fake_bin / "fake_bash.py"
    impl.write_text(text, encoding="utf-8")
    wrapper = fake_bin / "bash.cmd"
    wrapper.write_text(
        f'@echo off\r\n"{sys.executable}" "%~dp0fake_bash.py" %*\r\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ["PATH"])
    rc, out = _run(tmp_path / "does-not-exist")
    assert rc == 1, out
    assert "no installed distributions" in out
    assert "\x00" not in out
    assert "\ufeff" not in out
    assert "\ufffd" not in out


def test_decode_output_strips_utf16le_bom_and_keeps_ansi():
    """_decode_output on the WSL launcher's real byte shape: UTF-16LE
    with a BOM, mixed with ANSI escapes. The BOM is not part of the
    message and the escapes must survive decoding — the result is
    the exact message text, with no BOM, NUL, or replacement char."""
    raw = b"\xff\xfe" + (
        "\x1b[33mWindows Subsystem for Linux has no installed distributions.\x1b[0m\n"
    ).encode("utf-16-le")
    out = _decode_output(raw)
    assert out == "\x1b[33mWindows Subsystem for Linux has no installed distributions.\x1b[0m\n"
    assert "\ufeff" not in out
    assert "\ufffd" not in out
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


def _win32_no_git(tmp_path, monkeypatch):
    """Simulate a Windows box with no Git Bash: platform win32,
    no git on PATH, empty Program Files dirs. What remains is the
    PATH scan — the only way a planted stub can win."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "no-git-here"))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("PATHEXT", raising=False)


def test_windows_path_bash_cmd_stub_wins(tmp_path, monkeypatch):
    """The PATH scan is PATHEXT-aware: a ``bash.cmd`` stub planted
    first on PATH is picked, while the extensionless ``bash`` script
    next to it is not — Windows cannot execute it, so it must never
    be selected. Simulated on Linux by stubbing the platform and
    environment; the candidates are only checked for existence,
    never executed here."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "bash").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    stub = fake_bin / "bash.cmd"
    stub.write_text("@echo off\r\n", encoding="utf-8")
    _win32_no_git(tmp_path, monkeypatch)
    monkeypatch.setenv("PATH", str(fake_bin))
    assert _bash_exe() == str(stub)


def test_run_wraps_cmd_bash_via_comspec_on_windows(tmp_path, monkeypatch):
    """A ``bash.cmd`` cannot be started by CreateProcess directly —
    it has to go through the command interpreter (same rule as
    run_eval._resolve_claude). ``_run`` must invoke it as
    ``[ComSpec, /c, bash.cmd, ...]``. The subprocess is stubbed, so
    only the argv construction and the decode of its UTF-16LE
    output are exercised here; real execution is covered by
    test_wsl_launcher_output_is_decoded_readably on Windows CI."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    stub = fake_bin / "bash.cmd"
    stub.write_text("@echo off\r\n", encoding="utf-8")
    _win32_no_git(tmp_path, monkeypatch)
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setenv("ComSpec", r"C:\Windows\System32\cmd.exe")
    seen: dict = {}

    def _fake_run(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(
            argv,
            1,
            b"",
            b"\xff\xfe"
            + "Windows Subsystem for Linux has no installed distributions.\n".encode("utf-16-le"),
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    target = tmp_path / "does-not-exist"
    rc, out = _run(target)
    assert seen["argv"] == [
        r"C:\Windows\System32\cmd.exe",
        "/c",
        str(stub),
        str(SCRIPT),
        str(target),
    ]
    assert rc == 1, out
    assert "no installed distributions" in out
    assert "\ufeff" not in out
    assert "\ufffd" not in out


# --- Round 8, Track B: FND-012 — per-alert runbooks, --require-config ---

TWO_ALERTS_ONE_RUNBOOK = """\
alerts:
  - name: HighErrorRate
    expr: error_rate > 0.05
    windows: [5m, 1h]
    burn_rate: 14.4
    runbook: https://example.com/runbooks/high-error-rate
  - name: HighLatency
    expr: latency_p99 > 500
    windows: [5m, 1h]
    burn_rate: 14.4
health:
  livez: /livez
  readyz: /readyz
monitors:
  - target: /api/checkout
"""

TWO_ALERTS_TWO_RUNBOOKS = """\
alerts:
  - name: HighErrorRate
    expr: error_rate > 0.05
    windows: [5m, 1h]
    burn_rate: 14.4
    runbook: https://example.com/runbooks/high-error-rate
  - name: HighLatency
    expr: latency_p99 > 500
    windows: [5m, 1h]
    burn_rate: 14.4
    runbook: https://example.com/runbooks/high-latency
health:
  livez: /livez
  readyz: /readyz
monitors:
  - target: /api/checkout
"""

TWO_ALERTS_PROMETHEUS_ONE_RUNBOOK = """\
groups:
  - name: slo
    rules:
      - alert: HighErrorRate
        expr: error_rate > 0.05
        annotations:
          burn_rate: 14.4
          runbook_url: https://example.com/runbooks/high-error-rate
      - alert: HighLatency
        expr: latency_p99 > 500
        annotations:
          burn_rate: 14.4
"""


def test_runbook_required_per_alert(tmp_path):
    """FND-012 (1): two alerts, only one with a runbook — the
    haystack-wide check PASSED this (one reference anywhere).
    A PASS now requires a runbook reference per alert: FAIL,
    naming the alert that has none."""
    _write(tmp_path, "alerts.yml", TWO_ALERTS_ONE_RUNBOOK)
    rc, out = _run(tmp_path)
    assert rc == 1, out
    assert "HighLatency" in out
    assert "no runbook" in out
    assert "haystack-wide" not in out


def test_runbook_per_alert_all_present_passes(tmp_path):
    """FND-012 (1), control: two alerts each with a runbook pass
    — the per-alert check must not break a good config."""
    _write(tmp_path, "alerts.yml", TWO_ALERTS_TWO_RUNBOOKS)
    rc, out = _run(tmp_path)
    assert rc == 0, out


def test_runbook_per_alert_prometheus_style(tmp_path):
    """FND-012 (1): Prometheus-style `- alert:` blocks are
    parsed the same way as `- name:` blocks."""
    _write(tmp_path, "alerts.yml", TWO_ALERTS_PROMETHEUS_ONE_RUNBOOK)
    rc, out = _run(tmp_path)
    assert rc == 1, out
    assert "HighLatency" in out


def test_require_config_no_candidates_is_incomplete(tmp_path):
    """FND-012 (2): with --require-config, a target with no
    monitoring candidates is INCOMPLETE (exit 2) instead of the
    default exit 0 "nothing to gate". The default stays exit 0
    (test_empty_dir_still_passes) — the flag is the opt-in
    strict mode."""
    rc, out = _run("--require-config", tmp_path)
    assert rc == 2, out
    assert "INCOMPLETE" in out
    assert str(tmp_path) in out  # the real target, not the flag mistaken for one
    assert "nothing to gate" not in out


def test_require_config_good_config_still_passes(tmp_path):
    """FND-012 (2), control: --require-config does not fail a
    target that does have a config."""
    _write(tmp_path, "alerts.yml", GOOD)
    rc, out = _run("--require-config", tmp_path)
    assert rc == 0, out


def test_require_config_flag_after_target(tmp_path):
    """--require-config is accepted after the target too (the
    flag is parsed wherever it appears, not positionally)."""
    rc, out = _run(tmp_path, "--require-config")
    assert rc == 2, out
