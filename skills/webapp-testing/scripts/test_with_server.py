"""Tests for with_server.py.

Each test covers a real defect found by an external review (2026-11-06):
a log-heavy server blocked on a full pipe (and its output was swallowed),
readiness was only "the port is open" (a different service could satisfy
it), cleanup killed the shell but left the server running, and a hung
test command hung the script forever. Run:
    python3 -m pytest skills/webapp-testing/scripts/test_with_server.py -q
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

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
