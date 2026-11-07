"""Tests for with_server.py.

Each test covers a real defect found by an external review (2026-11-06):
a log-heavy server blocked on a full pipe (and its output was swallowed),
readiness was only "the port is open" (a different service could satisfy
it), cleanup killed the shell but left the server running, and a hung
test command hung the script forever. Run:
    python3 -m pytest skills/webapp-testing/scripts/test_with_server.py -q
"""

import os
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


def http_server_script(port, log_lines=0):
    """A small HTTP server that optionally prints many lines on startup."""
    return (
        "import http.server, sys\n"
        f"for _ in range({log_lines}):\n"
        "    print('log line ' + 'x' * 60, flush=True)\n"
        f"http.server.HTTPServer(('127.0.0.1', {port}), "
        "http.server.SimpleHTTPRequestHandler).serve_forever()\n"
    )


def test_normal_flow_and_server_is_stopped(tmp_path):
    """A real server, a real command, exit 0 — and after the run the
    port is free (the server and its children are actually dead)."""
    port = free_port()
    server = tmp_path / "server.py"
    server.write_text(http_server_script(port), encoding="utf-8")
    rc, out, err = run_with_server(
        f"{sys.executable} {server}",
        port,
        [
            sys.executable,
            "-c",
            f"import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:{port}/').status)",
        ],
        timeout=15,
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
        f"{sys.executable} {server}", port, [sys.executable, "-c", "print('test done')"], timeout=15
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
        f"{sys.executable} {raw}", port, [sys.executable, "-c", "print('ran')"], timeout=10
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
        timeout=15,
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
        + body
        + f"http.server.HTTPServer(('127.0.0.1', {port}), H).serve_forever()\n"
    )


def _start_server(tmp_path, name, code):
    """Start a server script as a subprocess; wait until its port
    accepts a connection. Returns (proc, port-freeing cleanup)."""
    script = tmp_path / name
    script.write_text(code, encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


def _wait_port_open(port, timeout=10):
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
        proc = _start_server(tmp_path, f"s{status}.py", _status_server_script(port, status))
        try:
            assert _wait_port_open(port), f"server on {port} never listened"
            assert with_server._http_ready(port, "/health") is expected, f"status {status}"
        finally:
            proc.terminate()
            proc.wait(timeout=10)


def test_ready_status_range_is_configurable(tmp_path):
    """F2-01: the 2xx rule is a default, not a hardcode — an operator
    whose health endpoint answers 503 while warming up can say so
    explicitly instead of the gate silently accepting every status."""
    port = free_port()
    proc = _start_server(tmp_path, "s503.py", _status_server_script(port, 503))
    try:
        assert _wait_port_open(port)
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
    proc = _start_server(
        tmp_path, "other.py", _status_server_script(port, 503, healthy_path="/health")
    )
    marker = tmp_path / "ran.txt"
    try:
        assert _wait_port_open(port)
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
            "15",
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
        "import http.server, signal, subprocess\n"
        "def _ignore():\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"child = subprocess.Popen(['sleep', '120'], preexec_fn=_ignore)\n"
        f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
        f"http.server.HTTPServer(('127.0.0.1', {port}), "
        "http.server.SimpleHTTPRequestHandler).serve_forever()\n",
        encoding="utf-8",
    )
    rc, out, err = run_with_server(
        f"{sys.executable} {server}",
        port,
        [sys.executable, "-c", "print('ran')"],
        timeout=15,
    )
    assert rc == 0, err
    assert "ran" in out
    child_pid = int(pidfile.read_text(encoding="utf-8"))
    try:
        deadline = time.time() + 10
        alive = True
        while time.time() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                alive = False
                break
            time.sleep(0.2)
        assert not alive, "the SIGTERM-ignoring child survived cleanup"
    finally:
        try:
            os.kill(child_pid, 9)
        except OSError:
            pass
