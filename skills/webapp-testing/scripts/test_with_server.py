"""Tests for with_server.py.

Each test covers a real defect found by an external review (2026-11-06):
a log-heavy server blocked on a full pipe (and its output was swallowed),
readiness was only "the port is open" (a different service could satisfy
it), cleanup killed the shell but left the server running, and a hung
test command hung the script forever. Run:
    python3 -m pytest skills/webapp-testing/scripts/test_with_server.py -q
"""

import ctypes
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import with_server  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "with_server.py"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_with_server(server_cmd, port, command, timeout=30, extra=None):
    argv = [
        sys.executable,
        str(SCRIPT),
        "--server",
        server_cmd,
        "--port",
        str(port),
        "--timeout",
        str(timeout),
    ]
    if extra:
        argv += extra
    argv += ["--", *command]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    return result.returncode, result.stdout, result.stderr


def port_is_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


STARTUP_AFTER_IMPORT = "print('STARTUP after-import', flush=True)\n"


def _http_server_construct_snippet(port, handler_expr):
    """Build an HTTPServer step by step, printing a flushed marker
    after each step. Constructing with bind_and_activate=False and
    calling server_bind() / server_activate() explicitly is the
    same sequence the constructor runs; splitting it only names
    the step a stalled server reached. On macOS CI 0.9.6 every
    http.server child stalled with no output and READY never
    printed — but the log-heavy child printed its 2000 lines,
    which come after the import, so the import is exonerated and
    the stall is at or after this constructor call. The markers
    say which step: socket-created, bound, or listening.

    Since CI 0.9.7 the markers prove the stall is INSIDE
    server_bind() (socket-created printed, bound never reached),
    so server_bind() itself is inlined here step by step instead
    of called whole: the steps mirror socketserver.TCPServer.
    server_bind (CPython 3.12, socketserver.py:463-475) — the two
    guarded setsockopt calls, socket.bind(), getsockname() — plus
    the HTTPServer.server_bind override's getfqdn line
    (http/server.py:134-139), each followed by a flushed marker.
    The inlining changes nothing about the bind: same calls, same
    order, same guards (allow_reuse_address / allow_reuse_port),
    only a marker between steps. The getfqdn step is the only
    network-I/O step in the whole interval — socket.getfqdn(host)
    does a reverse DNS lookup via gethostbyaddr('127.0.0.1')
    (socket.py:781-805), and gethostbyaddr has no timeout, so a
    hanging resolver on the runner would stall exactly here while
    a raw socket binds fine. That is the prime suspect by
    elimination (verified locally with a blocked gethostbyaddr:
    the child hangs after socket-created, a raw socket binds, and
    skipping getfqdn reaches READY); WHY the macOS 26 runner's
    resolver hangs is still unproven. If a future CI failure
    still stalls here, its last marker names the exact step
    (setsockopt / socket-bound / getsockname / getfqdn) instead
    of just 'inside server_bind()'."""
    return (
        f"srv = http.server.HTTPServer(('127.0.0.1', {port}), {handler_expr}, "
        "bind_and_activate=False)\n"
        "print('STARTUP socket-created', flush=True)\n"
        "import socket as _socket\n"
        "if srv.allow_reuse_address and hasattr(_socket, 'SO_REUSEADDR'):\n"
        "    srv.socket.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)\n"
        "if srv.allow_reuse_port and hasattr(_socket, 'SO_REUSEPORT'):\n"
        "    srv.socket.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEPORT, 1)\n"
        "print('STARTUP setsockopt', flush=True)\n"
        "srv.socket.bind(srv.server_address)\n"
        "print('STARTUP socket-bound', flush=True)\n"
        "srv.server_address = srv.socket.getsockname()\n"
        "print('STARTUP getsockname', flush=True)\n"
        "_host, _port = srv.server_address[:2]\n"
        "srv.server_name = _socket.getfqdn(_host)\n"
        "srv.server_port = _port\n"
        "print('STARTUP getfqdn', flush=True)\n"
        "print('STARTUP bound', flush=True)\n"
        "srv.server_activate()\n"
        "print('STARTUP listening', flush=True)\n"
        f"print('READY {port}', flush=True)\n"
    )


def http_server_script(port, log_lines=0):
    """A small HTTP server that optionally prints many lines on startup.

    It prints a STARTUP marker after each startup step (see
    _http_server_construct_snippet) and READY once the server is
    listening: on macOS CI the servers never listened with no
    output anywhere (CI 0.9.5, 8 tests), so the markers are what
    separate 'stuck before listen' from 'listening but the port
    check fails' — and, since CI 0.9.6, which step inside the
    constructor it stuck on."""
    return (
        "import http.server, sys\n" + STARTUP_AFTER_IMPORT + f"for _ in range({log_lines}):\n"
        "    print('log line ' + 'x' * 60, flush=True)\n"
        + _http_server_construct_snippet(port, "http.server.SimpleHTTPRequestHandler")
        + "srv.serve_forever()\n"
    )


def test_normal_flow_and_server_is_stopped(tmp_path):
    """A real server, a real command, exit 0 — and after the run the
    port is free (the server and its children are actually dead)."""
    port = free_port()
    server = tmp_path / "server.py"
    server.write_text(http_server_script(port), encoding="utf-8")
    # Startup waits are 30s throughout these tests — the tool's own
    # default. 15s failed on the slower macOS CI runner (CI 0.9.4,
    # macos job: 8 tests, 'failed to start within 15s'). The short
    # timeouts below (6s, 20s) are deliberate: they test failure
    # paths, where a short wait is the point.
    rc, out, err = run_with_server(
        f"{sys.executable} {server}",
        port,
        [
            sys.executable,
            "-c",
            f"import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:{port}/').status)",
        ],
        timeout=30,
    )
    assert rc == 0, err
    assert "200" in out
    # The server is gone: the port must be closed after cleanup.
    deadline = time.time() + 10
    while port_is_open(port) and time.time() < deadline:
        time.sleep(0.2)
    assert not port_is_open(port), "the server is still listening after cleanup"


def test_log_heavy_server_does_not_block(tmp_path):
    """A server that writes >64KB to stdout used to block on the full
    pipe (the old code never read it) and hang the run."""
    port = free_port()
    server = tmp_path / "server.py"
    # 2000 lines x ~70 bytes = ~140KB, well over the 64KB pipe buffer.
    server.write_text(http_server_script(port, log_lines=2000), encoding="utf-8")
    rc, out, err = run_with_server(
        f"{sys.executable} {server}", port, [sys.executable, "-c", "print('test done')"], timeout=30
    )
    assert rc == 0, err
    assert "test done" in out
    # The server's output is forwarded, not swallowed.
    assert "log line" in out


def test_ready_path_rejects_a_non_http_service(tmp_path):
    """A raw TCP server accepts connections but does not speak HTTP.
    The port check alone would call it ready; --ready-path must not."""
    port = free_port()
    raw = tmp_path / "raw.py"
    raw.write_text(
        "import socket\n"
        f"s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        f"s.bind(('127.0.0.1', {port})); s.listen(1)\n"
        "while True:\n"
        "    conn, _ = s.accept()\n"
        "    conn.close()\n",
        encoding="utf-8",
    )
    # Without --ready-path the port check alone says ready (and the
    # command runs). That is the documented limitation of the port check.
    rc, out, err = run_with_server(
        f"{sys.executable} {raw}", port, [sys.executable, "-c", "print('ran')"], timeout=30
    )
    assert rc == 0, err
    assert "ran" in out
    # With --ready-path the same service is NOT ready (no HTTP response).
    rc, out, err = run_with_server(
        f"{sys.executable} {raw}",
        port,
        [sys.executable, "-c", "print('ran')"],
        timeout=6,
        extra=["--ready-path", "/"],
    )
    assert rc == 1, out
    assert "failed to start" in err


def test_server_that_exits_fails_fast(tmp_path):
    """A server that exits immediately must fail fast, not wait out the
    whole timeout."""
    port = free_port()
    start = time.time()
    rc, out, err = run_with_server(
        f"{sys.executable} -c 'import sys; sys.exit(3)'",
        port,
        [sys.executable, "-c", "print('ran')"],
        timeout=20,
    )
    elapsed = time.time() - start
    assert rc == 1, out
    assert "exited" in err
    assert elapsed < 10, f"took {elapsed:.1f}s, should have failed fast"


def test_test_command_timeout(tmp_path):
    """A hung test command must not hang this script forever."""
    port = free_port()
    server = tmp_path / "server.py"
    server.write_text(http_server_script(port), encoding="utf-8")
    start = time.time()
    rc, out, err = run_with_server(
        f"{sys.executable} {server}",
        port,
        [sys.executable, "-c", "import time; time.sleep(60)"],
        timeout=30,
        extra=["--test-timeout", "3"],
    )
    elapsed = time.time() - start
    assert rc == 1, out
    assert "timed out" in err
    assert elapsed < 20, f"took {elapsed:.1f}s, should have timed out in ~3s"
    # And the server is still cleaned up afterwards.
    deadline = time.time() + 10
    while port_is_open(port) and time.time() < deadline:
        time.sleep(0.2)
    assert not port_is_open(port)


def test_mismatched_server_and_port_counts(tmp_path):
    port = free_port()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--server",
            "true",
            "--port",
            str(port),
            "--port",
            str(port + 1),
            "--",
            "true",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "must match" in result.stderr


# --- Round 6 (2026-11-07): S7 / 3-F2-01 / 3-F2-02 / 3-F2-03 ---


def _status_server_script(port, status, healthy_path=None):
    """An HTTP server answering `status` on every GET — or 200 only
    on `healthy_path` and 404 elsewhere, when one is given."""
    if healthy_path is None:
        body = (
            "class H(http.server.BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            f"        self.send_response({status})\n"
            "        self.send_header('Content-Length', '2')\n"
            "        self.end_headers()\n"
            "        self.wfile.write(b'ok')\n"
            "    def log_message(self, *a): pass\n"
        )
    else:
        body = (
            "class H(http.server.BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            f"        code = 200 if self.path == {healthy_path!r} else 404\n"
            "        self.send_response(code)\n"
            "        self.send_header('Content-Length', '2')\n"
            "        self.end_headers()\n"
            "        self.wfile.write(b'ok')\n"
            "    def log_message(self, *a): pass\n"
        )
    return (
        "import http.server\n"
        + STARTUP_AFTER_IMPORT
        + body
        + _http_server_construct_snippet(port, "H")
        + "srv.serve_forever()\n"
    )


def _start_server(tmp_path, name, code):
    """Start a server script as a subprocess. Returns (proc,
    err_file, out_file): the server's stdout goes to out_file, not
    DEVNULL, and its stderr to err_file — a server that crashes on
    startup used to be indistinguishable from a slow one, because
    its traceback was discarded (which is what the macOS CI failures
    looked like: 'never listened' with no server output anywhere in
    the log). The test servers also print READY after binding (see
    http_server_script), so out_file is what separates 'stuck before
    listen' from 'listening but the port check fails'."""
    script = tmp_path / name
    script.write_text(code, encoding="utf-8")
    err_file = tmp_path / (name + ".stderr")
    out_file = tmp_path / (name + ".stdout")
    with (
        open(err_file, "w", encoding="utf-8") as err_handle,
        open(out_file, "w", encoding="utf-8") as out_handle,
    ):
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            stdout=out_handle,
            stderr=err_handle,
        )
    return proc, err_file, out_file


def _server_detail(proc, err_file, out_file=None):
    """One line on why a server never listened: whether the process
    is still alive or exited (with its code), whether it printed
    READY after binding — READY means it was listening, so the port
    check itself failed; no READY means it never reached listen —
    plus the last STARTUP marker it reached, so a stalled server
    names the step it stuck on, plus the tails of its stdout and
    stderr. A crash and a slow start must not look the same."""
    if proc.poll() is None:
        state = "process still alive"
    else:
        state = f"process exited with code {proc.returncode}"
    if out_file is not None:
        try:
            out = out_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            out = ""
        out_lines = [line for line in out.splitlines() if line.strip()]
        if any(line.startswith("READY") for line in out_lines):
            state += "; server printed READY (it was listening)"
        else:
            state += "; server never printed READY (stuck before listen)"
        startup = [line for line in out_lines if line.startswith("STARTUP")]
        if startup:
            state += f"; last startup step: {startup[-1]}"
        tail = out_lines[-2:]
        if tail:
            state += "; stdout: " + " | ".join(tail)
    try:
        err = err_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        err = ""
    tail = [line for line in err.strip().splitlines() if line.strip()][-3:]
    if tail:
        state += "; stderr: " + " | ".join(tail)
    return state


def _wait_port_open(port, timeout=30):
    """Wait until the port accepts a connection. 30s, not 10s: the
    tool's own startup default is 30s, and a 10s budget failed on
    the slower macOS CI runner even though the same servers start
    in ~1s on Linux (CI 0.9.4, macos job: 8 tests, 'never
    listened' / 'failed to start within 15s')."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_is_open(port):
            return True
        time.sleep(0.1)
    return False


def test_http_ready_requires_2xx(tmp_path):
    """F2-01 / S7: _http_ready returned True for ANY HTTP response —
    a health endpoint answering 503 (or 500) counted as ready. Only
    a 2xx response is readiness (configurable via --ready-status)."""
    for status, expected in (
        (200, True),
        (204, True),
        (301, False),
        (404, False),
        (500, False),
        (503, False),
    ):
        port = free_port()
        proc, err_file, out_file = _start_server(
            tmp_path, f"s{status}.py", _status_server_script(port, status)
        )
        try:
            assert _wait_port_open(port), (
                f"server on {port} never listened ({_server_detail(proc, err_file, out_file)})"
            )
            assert with_server._http_ready(port, "/health") is expected, f"status {status}"
        finally:
            proc.terminate()
            proc.wait(timeout=10)


def test_ready_status_range_is_configurable(tmp_path):
    """F2-01: the 2xx rule is a default, not a hardcode — an operator
    whose health endpoint answers 503 while warming up can say so
    explicitly instead of the gate silently accepting every status."""
    port = free_port()
    proc, err_file, out_file = _start_server(tmp_path, "s503.py", _status_server_script(port, 503))
    try:
        assert _wait_port_open(port), (
            f"server on {port} never listened ({_server_detail(proc, err_file, out_file)})"
        )
        assert with_server._http_ready(port, "/health", ok_statuses={503}) is True
        assert with_server._http_ready(port, "/health", ok_statuses={200}) is False
        assert with_server._parse_ready_status("2xx") == set(range(200, 300))
        assert with_server._parse_ready_status("200-204") == {200, 201, 202, 203, 204}
        assert with_server._parse_ready_status("200,503") == {200, 503}
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_busy_port_is_rejected_before_starting(tmp_path):
    """F2-02: another service already holding the port was declared
    ready — even WITH --ready-path, because any responder counted.
    The run must fail before starting, and the test command must
    never run against the wrong service."""
    port = free_port()
    proc, err_file, out_file = _start_server(
        tmp_path, "other.py", _status_server_script(port, 503, healthy_path="/health")
    )
    marker = tmp_path / "ran.txt"
    try:
        assert _wait_port_open(port), (
            f"server on {port} never listened ({_server_detail(proc, err_file, out_file)})"
        )
        rc, out, err = run_with_server(
            "sleep 10",
            port,
            [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('ran')"],
            timeout=10,
            extra=["--ready-path", "/health"],
        )
        assert rc == 1, out
        assert "already in use" in (out + err)
        assert not marker.exists(), "the test command ran against the wrong service"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_ready_path_is_repeatable_per_server(tmp_path):
    """S7: --ready-path was a single value passed to every server,
    although backend and frontend usually have different health
    paths. Two servers with different health paths must both be
    checked on their own path."""
    port_a, port_b = free_port(), free_port()
    server_a = tmp_path / "a.py"
    server_b = tmp_path / "b.py"
    server_a.write_text(
        _status_server_script(port_a, 200, healthy_path="/health-a"), encoding="utf-8"
    )
    server_b.write_text(
        _status_server_script(port_b, 200, healthy_path="/health-b"), encoding="utf-8"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--server",
            f"{sys.executable} {server_a}",
            "--port",
            str(port_a),
            "--server",
            f"{sys.executable} {server_b}",
            "--port",
            str(port_b),
            "--timeout",
            "30",
            "--ready-path",
            "/health-a",
            "--ready-path",
            "/health-b",
            "--",
            sys.executable,
            "-c",
            "print('both ready')",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "both ready" in result.stdout
    # A wrong per-server path must fail, not silently fall back to
    # the other server's path.
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--server",
            f"{sys.executable} {server_a}",
            "--port",
            str(port_a),
            "--server",
            f"{sys.executable} {server_b}",
            "--port",
            str(port_b),
            "--timeout",
            "6",
            "--ready-path",
            "/health-a",
            "--ready-path",
            "/wrong",
            "--",
            sys.executable,
            "-c",
            "print('both ready')",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1
    assert "failed to start" in result.stderr


def test_ready_path_count_must_match_server_count(tmp_path):
    """S7: two --ready-path values for one server (or any count that
    is neither one nor the server count) is a usage error, not a
    silent ignore-the-extra."""
    port = free_port()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--server",
            "sleep 10",
            "--port",
            str(port),
            "--ready-path",
            "/a",
            "--ready-path",
            "/b",
            "--",
            "true",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "ready-path" in result.stderr


def _termination_resistant_child_script(port, pidfile, os_name=os.name):
    """Server script whose child survives a kill of the shell alone.
    On POSIX the child ignores SIGTERM (preexec_fn); on Windows
    preexec_fn raises ValueError and there is no 'sleep' binary, so
    the child is a Python sleeper instead — it still survives
    terminate() of the shell, because that signal never reaches it."""
    if os_name == "nt":
        spawn = "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        imports = "import http.server, subprocess, sys\n"
    else:
        spawn = (
            "def _ignore():\n"
            "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "child = subprocess.Popen(['sleep', '120'], preexec_fn=_ignore)\n"
        )
        imports = "import http.server, signal, subprocess\n"
    return (
        imports
        + STARTUP_AFTER_IMPORT
        + spawn
        + f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
        + _http_server_construct_snippet(port, "http.server.SimpleHTTPRequestHandler")
        + "srv.serve_forever()\n"
    )


def _wait_pid_dead(pid, timeout=10):
    """Wait until the process is gone. Returns True when it died
    within the timeout, False when it is still alive afterwards.
    The probe is _pid_is_alive, not os.kill(pid, 0): signal 0 is
    an invalid parameter on Windows (WinError 87), so a direct
    os.kill probe fails the test there instead of reporting the
    child's state (CI 0.9.6, Windows)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_is_alive(pid):
            return True
        time.sleep(0.2)
    return False


def test_sigterm_ignoring_child_does_not_survive_cleanup(tmp_path):
    """F2-03: cleanup SIGTERMed the group, then waited for the LEADER
    only — when the leader died promptly, a SIGTERM-ignoring child
    survived (the SIGKILL half ran only on timeout). The group must
    be SIGKILLed / verified empty even on the leader-exits-early
    path."""
    port = free_port()
    pidfile = tmp_path / "child.pid"
    server = tmp_path / "server.py"
    server.write_text(
        _termination_resistant_child_script(port, pidfile),
        encoding="utf-8",
    )
    rc, out, err = run_with_server(
        f"{sys.executable} {server}",
        port,
        [sys.executable, "-c", "print('ran')"],
        timeout=30,
    )
    assert rc == 0, err
    assert "ran" in out
    child_pid = int(pidfile.read_text(encoding="utf-8"))
    try:
        assert _wait_pid_dead(child_pid, timeout=10), "the SIGTERM-ignoring child survived cleanup"
    finally:
        if _pid_is_alive(child_pid):
            try:
                # signal.SIGKILL does not exist on Windows; SIGTERM
                # terminates the process there (see the cleanup in
                # test_sigterm_child_script_is_windows_compatible).
                # Never name signal.SIGKILL — or a literal 9 —
                # unconditionally: on Windows that is an invalid
                # parameter (WinError 87), the same failure as the
                # os.kill(pid, 0) probe this test used to use.
                os.kill(child_pid, getattr(signal, "SIGKILL", signal.SIGTERM))
            except OSError:
                pass


def test_wait_pid_dead_does_not_use_signal_zero_on_windows(monkeypatch):
    """Regression for CI 0.9.6, Windows: the sigterm test's aliveness
    loop called os.kill(pid, 0) directly, and on Windows signal 0 is
    an invalid parameter (WinError 87) — os.kill there only supports
    SIGTERM. The wait must go through _pid_is_alive, whose Windows
    probe is OpenProcess/GetExitCodeProcess. Simulated on Linux:
    os.name is 'nt', os.kill raises OSError(87) for signal 0 (the
    Windows behaviour), and ctypes.windll is a fake kernel32 backed
    by the real os.kill."""
    real_kill = os.kill

    def windows_kill(pid, sig):
        if sig == 0:
            raise OSError(87, "The parameter is incorrect")
        return real_kill(pid, sig)

    class _FakeKernel32:
        """Minimal kernel32 stand-in: OpenProcess/GetExitCodeProcess
        with the Windows contract, backed by the real os.kill."""

        def __init__(self):
            self._last_error = 0

        def OpenProcess(self, access, inherit, pid):
            try:
                real_kill(pid, 0)
            except ProcessLookupError:
                self._last_error = 87
                return 0
            except OSError:
                self._last_error = 5
                return 0
            return pid  # any non-zero value is a handle

        def GetExitCodeProcess(self, handle, exit_code):
            # handle is the pid. A zombie has exited: on real Windows
            # there are no zombies, and the exit code is readable as
            # soon as the process dies — so a zombie's code is its
            # real exit code (0 here), not STILL_ACTIVE. Without this
            # the fake reports every unreaped child alive forever.
            code = 259
            try:
                with open(f"/proc/{handle}/stat", encoding="utf-8") as f:
                    state = f.read().rsplit(") ", 1)[1].split()[0]
                if state == "Z":
                    code = 0
            except OSError:
                code = 0  # /proc entry gone: the process is dead
            ctypes.cast(exit_code, ctypes.POINTER(ctypes.c_ulong)).contents.value = code
            return 1

        def GetLastError(self):
            return self._last_error

        def CloseHandle(self, handle):
            return 1

    class _FakeWindll:
        kernel32 = _FakeKernel32()

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(os, "kill", windows_kill)
    monkeypatch.setattr(ctypes, "windll", _FakeWindll(), raising=False)

    # Already dead: the wait must return True promptly, not raise.
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=10)
    assert _wait_pid_dead(proc.pid, timeout=10) is True

    # Alive, then exits on its own: the wait must see it die.
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
    assert _wait_pid_dead(proc.pid, timeout=10) is True
    proc.wait(timeout=10)


def test_crashing_server_reports_its_stderr(tmp_path):
    """A server that crashes on startup must say so in the failure:
    _start_server used to discard the server's stderr, so a crash
    looked exactly like a slow start ('never listened') and the cause
    was invisible — which is what the macOS CI failures looked like
    (8 tests, 'server failed to start within 15s', no server output
    anywhere in the log)."""
    port = free_port()
    proc, err_file, out_file = _start_server(tmp_path, "crash.py", "raise RuntimeError('boom')\n")
    try:
        assert not _wait_port_open(port, timeout=5)
        detail = _server_detail(proc, err_file, out_file)
        assert "exited" in detail
        assert "boom" in detail
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=10)


def test_server_detail_reports_ready_marker(tmp_path):
    """A server that bound and printed READY must say so in the
    detail: READY separates 'stuck before listen' from 'listening
    but the port check fails' — on macOS CI the two looked
    identical ('never listened', process alive, empty stderr;
    CI 0.9.5, macos job, 8 tests)."""
    port = free_port()
    proc, err_file, out_file = _start_server(tmp_path, "ready.py", _status_server_script(port, 200))
    try:
        assert _wait_port_open(port), (
            f"server on {port} never listened ({_server_detail(proc, err_file, out_file)})"
        )
        assert "printed READY" in _server_detail(proc, err_file, out_file)
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_server_detail_reports_missing_ready_marker(tmp_path):
    """A process that is alive but never printed READY never reached
    listen — the detail must say so, instead of the bare 'process
    still alive' that hid this on macOS CI."""
    port = free_port()
    proc, err_file, out_file = _start_server(tmp_path, "stuck.py", "import time; time.sleep(30)\n")
    try:
        assert not _wait_port_open(port, timeout=5)
        detail = _server_detail(proc, err_file, out_file)
        assert "still alive" in detail
        assert "never printed READY" in detail
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=10)


def test_with_server_failure_reports_server_output(tmp_path):
    """When a server never becomes ready, the failure must name what
    the server actually did: with_server.py used to report only
    'failed to start within Ns', so a server stuck before listen
    looked exactly like a slow one (CI 0.9.5, macos job). The
    server's recent output is now printed with the failure."""
    port = free_port()
    server = tmp_path / "server.py"
    server.write_text(
        "print('marker-output-before-stall', flush=True)\nimport time; time.sleep(60)\n",
        encoding="utf-8",
    )
    rc, out, err = run_with_server(
        f"{sys.executable} {server}",
        port,
        [sys.executable, "-c", "print('ran')"],
        timeout=3,
    )
    assert rc == 1, out
    assert "failed to start" in err
    assert "marker-output-before-stall" in err


def test_sigterm_child_script_is_windows_compatible(tmp_path):
    """The sigterm test's server script must not use preexec_fn or the
    'sleep' binary: on Windows preexec_fn raises ValueError and
    there is no sleep binary, so the server crashed at startup
    (CI 0.9.5, Windows: 'preexec_fn is not supported on Windows
    platforms'). The Windows variant must also actually run."""
    port = free_port()
    pidfile = tmp_path / "child.pid"
    script = _termination_resistant_child_script(port, pidfile, os_name="nt")
    assert "preexec_fn" not in script
    assert "['sleep'" not in script
    assert "time.sleep(120)" in script
    proc, err_file, out_file = _start_server(tmp_path, "win-server.py", script)
    try:
        assert _wait_port_open(port), (
            f"server on {port} never listened ({_server_detail(proc, err_file, out_file)})"
        )
        assert int(pidfile.read_text(encoding="utf-8")) > 0
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=10)
        try:
            child_pid = int(pidfile.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            child_pid = None
        if child_pid is not None:
            try:
                # signal.SIGKILL does not exist on Windows; SIGTERM
                # terminates the process there (TerminateProcess), so
                # it is the fallback where SIGKILL is absent. Never
                # name signal.SIGKILL unconditionally.
                os.kill(child_pid, getattr(signal, "SIGKILL", signal.SIGTERM))
            except OSError:
                pass


# --- Round-6 follow-up (2026-11-07): Windows cleanup killed only the shell ---


def _tree_server_script(port, pidfile):
    """A server that spawns a long-lived child and serves HTTP: the
    child survives a kill of the shell alone, so it proves whether
    cleanup killed the tree or just the leader."""
    return (
        "import http.server, subprocess, sys\n"
        + STARTUP_AFTER_IMPORT
        + "child = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(120)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
        + _http_server_construct_snippet(port, "http.server.SimpleHTTPRequestHandler")
        + "srv.serve_forever()\n"
    )


def _pid_is_alive(pid):
    """True when the process exists, without killing it. On Windows
    os.kill(pid, 0) terminates the process instead of probing it,
    so the Windows probe goes through OpenProcess +
    GetExitCodeProcess — the same probe as
    skills/idea-capture/scripts/capture.py::_pid_is_alive_windows
    (round 6, S1). A process that cannot be opened because it does
    not exist (error 87) is dead; any other failure to open it, or
    to read its exit code, is treated as alive (fail-safe)."""
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return kernel32.GetLastError() != 87
        try:
            exit_code = ctypes.c_ulong(0)
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True  # unreadable exit code — fail-safe: alive.
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _fake_kill_tree_windows(pid):
    """Linux stand-in for taskkill /T /F: SIGKILL the leader's whole
    process group. Only used to exercise the Windows branch of
    _stop_process_group on Linux; on Windows the real taskkill runs."""
    os.killpg(os.getpgid(pid), signal.SIGKILL)
    return True


def test_kill_tree_windows_uses_taskkill(monkeypatch):
    """The Windows tree-kill must be taskkill /PID <pid> /T /F:
    terminate() alone kills only the cmd.exe shell, so the flag
    that kills the children (/T) is the whole point."""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(with_server.subprocess, "run", fake_run)
    assert with_server._kill_tree_windows(1234) is True
    assert calls == [["taskkill", "/PID", "1234", "/T", "/F"]]

    def missing_run(argv, **kwargs):
        raise FileNotFoundError("taskkill")

    monkeypatch.setattr(with_server.subprocess, "run", missing_run)
    assert with_server._kill_tree_windows(1234) is False


def test_windows_cleanup_kills_whole_tree(tmp_path, monkeypatch):
    """CI 0.9.5, Windows: after cleanup the server was still
    listening (test_normal_flow, test_test_command_timeout) and the
    next run on the same port was refused as 'already in use'
    (test_ready_path_rejects, test_ready_path_repeatable). Root
    cause: on Windows there are no process groups, so cleanup
    called terminate() on the cmd.exe shell only and the real
    server kept running. The Windows branch must kill the whole
    tree. Simulated on Linux: the Windows branch runs with the
    POSIX APIs stubbed out (taskkill emulated by a group SIGKILL).
    On Windows the real taskkill runs — the POSIX fake is Linux-only
    (it calls os.getpgid itself) — and the setup, cleanup and probe
    use only APIs that exist on Windows (no os.getpgid / os.killpg
    there; the probe is _pid_is_alive, because os.kill(pid, 0)
    terminates the process on Windows instead of probing it)."""
    port = free_port()
    pidfile = tmp_path / "child.pid"
    server = tmp_path / "server.py"
    server.write_text(_tree_server_script(port, pidfile), encoding="utf-8")
    proc = subprocess.Popen(
        f"{sys.executable} {server}",
        shell=True,
        start_new_session=True,
    )
    # os.getpgid does not exist on Windows, and there are no process
    # groups there to remember: only record the pgid where the API
    # exists, and let the finally below fall back to the taskkill
    # tree-kill on Windows.
    pgid = os.getpgid(proc.pid) if hasattr(os, "getpgid") else None
    try:
        assert _wait_port_open(port), "server never listened"
        child_pid = int(pidfile.read_text(encoding="utf-8"))
        # Read os.name before the context below patches it: on
        # Windows the real taskkill runs; the POSIX fake is installed
        # only on Linux/macOS.
        real_windows = os.name == "nt"
        with monkeypatch.context() as m:
            m.setattr(os, "name", "nt")
            if not real_windows:
                m.setattr(with_server, "_kill_tree_windows", _fake_kill_tree_windows, raising=False)
            with_server._stop_process_group(proc, "server-1")
        deadline = time.time() + 10
        alive = True
        while time.time() < deadline:
            if not _pid_is_alive(child_pid):
                alive = False
                break
            time.sleep(0.2)
        assert not alive, "the server's child survived the Windows cleanup"
        assert not port_is_open(port), "the server is still listening after cleanup"
    finally:
        # Whatever the run under test left behind, kill the whole
        # group (the shell's session) so no server lingers.
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except OSError:
                pass
        else:
            # No process groups on Windows: kill the whole tree with
            # the product's own taskkill helper instead.
            with_server._kill_tree_windows(proc.pid)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


# --- Round-6 follow-up (2026-11-07): macOS startup-step diagnostics ---


def _raw_socket_after_import_script(port):
    """Discriminating probe for the macOS CI failures: import
    http.server, then bind and listen a plain raw socket (the exact
    steps the passing raw-socket test uses, without the import).
    On macOS CI 0.9.6 every http.server child stalled at or after
    the HTTPServer constructor while a raw socket bound and listened
    fine — but that raw test never imported http.server, so the two
    observations do not separate 'the import poisons the process'
    from 'the HTTPServer constructor itself blocks'. This probe
    does: it passes on macOS only if a raw bind/listen still works
    after the import (blocker inside the HTTPServer constructor);
    it fails with 'after-import' printed but no 'raw-listening' if
    the import breaks bind/listen; it fails with neither marker if
    the import itself stalls (which CI 0.9.6 already contradicts:
    the log-heavy child printed its 2000 lines, which come after
    the import). A failure here is diagnostic, not a product
    regression — it names the step, which is the whole point."""
    return (
        "import http.server, socket\n"
        "print('STARTUP after-import', flush=True)\n"
        f"s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        f"s.bind(('127.0.0.1', {port})); s.listen(1)\n"
        "print('STARTUP raw-listening', flush=True)\n"
        "while True:\n"
        "    conn, _ = s.accept()\n"
        "    conn.close()\n"
    )


def test_startup_markers_appear_in_order(tmp_path):
    """The test servers report each startup step with a flushed
    STARTUP marker — after the import, after the HTTPServer socket
    is created, after each step inside server_bind() (setsockopt,
    socket bind, getsockname, getfqdn), after bind, after listen —
    so the next macOS CI failure names the exact step it stuck on
    instead of repeating 'stuck before listen' (CI 0.9.6: 11 tests,
    process alive, empty stderr, READY never printed) or even
    'inside server_bind()' (CI 0.9.7: 12 tests, socket-created
    printed, bound never reached)."""
    port = free_port()
    proc, err_file, out_file = _start_server(tmp_path, "marked.py", http_server_script(port))
    try:
        assert _wait_port_open(port), (
            f"server on {port} never listened ({_server_detail(proc, err_file, out_file)})"
        )
        out = out_file.read_text(encoding="utf-8", errors="replace")
        markers = [
            "STARTUP after-import",
            "STARTUP socket-created",
            "STARTUP setsockopt",
            "STARTUP socket-bound",
            "STARTUP getsockname",
            "STARTUP getfqdn",
            "STARTUP bound",
            "STARTUP listening",
            f"READY {port}",
        ]
        positions = [out.index(marker) for marker in markers]
        assert positions == sorted(positions), f"markers out of order in: {out!r}"
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=10)


def test_server_detail_names_last_startup_step(tmp_path):
    """_server_detail must name the last STARTUP marker a stuck
    server reached, as its own field: the stdout tail is only the
    last 2 lines, so the stuck step should not depend on nothing
    printing after the markers — without it a server stuck after
    bind reports only 'never printed READY'."""
    port = free_port()
    proc, err_file, out_file = _start_server(
        tmp_path,
        "stuck-mid-startup.py",
        "import http.server\n"
        "print('STARTUP after-import', flush=True)\n"
        "print('STARTUP socket-created', flush=True)\n"
        "import time; time.sleep(30)\n",
    )
    try:
        assert not _wait_port_open(port, timeout=5)
        detail = _server_detail(proc, err_file, out_file)
        assert "still alive" in detail
        assert "never printed READY" in detail
        assert "last startup step: STARTUP socket-created" in detail
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=10)


def test_raw_socket_listens_after_http_server_import(tmp_path):
    """Probe (see _raw_socket_after_import_script): a raw socket
    must bind and listen after importing http.server. Passes on
    Linux; on macOS CI its outcome separates the two remaining
    suspects for the 0.9.6 failures — pass means the blocker is
    inside the HTTPServer constructor, fail-after-import means the
    import breaks bind/listen."""
    port = free_port()
    proc, err_file, out_file = _start_server(
        tmp_path, "probe.py", _raw_socket_after_import_script(port)
    )
    try:
        assert _wait_port_open(port), (
            f"server on {port} never listened ({_server_detail(proc, err_file, out_file)})"
        )
        out = out_file.read_text(encoding="utf-8", errors="replace")
        assert "STARTUP after-import" in out
        assert "STARTUP raw-listening" in out
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=10)
