#!/usr/bin/env python3
# ORCINUS change notice (Apache-2.0 §4(b)): ORCINUS changed this file from upstream anthropics/skills@ca45fc4 — stdout/stderr are drained in background threads, readiness is an HTTP check with a liveness check, cleanup signals the whole process group, and the test command has a timeout. Round 6 (2026-11-07): readiness requires a 2xx response (any status used to count, so a 500/503 counted as ready); --ready-path is repeatable per server; a port already held by another service is rejected before starting; cleanup SIGKILLs the process group even when the leader exits promptly (a SIGTERM-ignoring child used to survive). Round-6 follow-up (2026-11-07): on Windows cleanup killed only the cmd.exe shell (no process groups there), so the server kept listening and the next run found the port held; cleanup now kills the whole tree with taskkill /PID <pid> /T /F. Round-6 follow-up (2026-11-07): on macOS CI the servers never became ready with no output anywhere (8 tests, 'failed to start within 30s', process alive, empty stderr) — a server stuck before listen looked exactly like a slow one; a readiness failure now prints the server's recent output, so the next failure names whether the server printed anything at all. Round-6 follow-up (2026-11-07): readiness polling connected to "localhost", which on macOS can resolve ::1 first and add a per-poll connect delay before falling back to 127.0.0.1; the three connection targets (_http_ready, _port_is_busy, is_server_ready) now use the literal 127.0.0.1. The rest is verbatim; see ATTRIBUTION.md.
"""
Start one or more servers, wait for them to be ready, run a command, then clean up.

Usage:
    # Single server
    python scripts/with_server.py --server "npm run dev" --port 5173 -- python automation.py
    python scripts/with_server.py --server "npm start" --port 3000 -- python test.py

    # Multiple servers
    python scripts/with_server.py \
      --server "cd backend && python server.py" --port 3000 \
      --server "cd frontend && npm run dev" --port 5173 \
      -- python test.py

    # Verify the server actually answers HTTP, not just that the port is open
    python scripts/with_server.py --server "npm start" --port 3000 \
      --ready-path /health -- python test.py

    # Bound the test command so a hung test cannot hang this script forever
    python scripts/with_server.py --server "npm start" --port 3000 \
      --test-timeout 120 -- python test.py

Rules this script follows (each one is a defect that was found and fixed):

- The server's stdout and stderr are drained continuously in background
  threads and forwarded to this script's stdout, so a log-heavy server
  can never block on a full pipe and its output is never swallowed.
- Readiness is the port AND (when --ready-path is given) an HTTP
  2xx response from that path (configurable with --ready-status:
  a 500/503 is a service that is not ready, not a ready one). A
  bare port check can be fooled by a different service listening
  on the same port, so the port is also checked free before the
  server starts — a port already held is an error, not readiness.
  --ready-path is repeatable, one path per server (a single value
  applies to every server). While waiting, the script also checks
  that the server process is still alive — a server that exited
  is a failure, not a reason to wait out the timeout. When a server
  never becomes ready, the failure prints the server's recent
  output, so a server stuck before listen does not look like a
  slow one (on macOS CI the servers never became ready with no
  output anywhere, and the bare 'failed to start' named no cause).
- Cleanup kills the whole process group, not just the shell. The server
  is started with shell=True (so commands with cd and && work), and
  terminating the shell leaves the real server running. Each server is
  started in its own process group (start_new_session=True on POSIX)
  and the group is signalled on cleanup — SIGTERM, then SIGKILL,
  even when the leader exits promptly (a SIGTERM-ignoring child
  used to survive that path: the SIGKILL ran only on timeout).
  On Windows there are no process groups (start_new_session is
  POSIX-only), so cleanup kills the whole tree with
  taskkill /PID <pid> /T /F instead — terminate() alone kills only
  the cmd.exe shell and the server keeps listening.
  The port-free check has a race: a service that binds between the
  check and the server start is still possible, and a different
  service answering 2xx on the ready path cannot be told apart
  from ours without a token — the check closes the common case, it
  does not prove ownership.
- The test command has an independent timeout (--test-timeout, default
  300s). A hung test cannot hang this script forever.
"""

import collections
import http.client
import os
import signal
import subprocess
import socket
import sys
import threading
import time
import argparse


def _drain(pipe, label, stream, tail=None):
    """Forward a server's output stream to this script's stream, line
    by line, in a background thread. This is what keeps the pipe from
    filling up and blocking the server. Each line is also kept in
    `tail` (a deque with a bound) when given, so a readiness failure
    can report what the server actually printed instead of only
    'failed to start'."""
    try:
        for line in pipe:
            stream.write(f"[{label}] {line}")
            stream.flush()
            if tail is not None:
                tail.append(f"[{label}] {line.rstrip()}")
    except (OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except (OSError, ValueError):
            pass


def _parse_ready_status(spec):
    """Parse a --ready-status value into a set of HTTP statuses.
    "2xx" (the default) is 200-299; "200-204" is a range;
    "200,503" is a list. Raises ValueError on anything else."""
    spec = (spec or "").strip()
    if spec.endswith("xx") and len(spec) == 3 and spec[0].isdigit():
        base = int(spec[0]) * 100
        return set(range(base, base + 100))
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            lo, hi = int(lo), int(hi)
            if not 100 <= lo <= hi <= 599:
                raise ValueError(f"invalid status range: {part!r}")
            out.update(range(lo, hi + 1))
        else:
            code = int(part)
            if not 100 <= code <= 599:
                raise ValueError(f"invalid status code: {part!r}")
            out.add(code)
    if not out:
        raise ValueError(f"empty --ready-status: {spec!r}")
    return out


def _http_ready(port, path, timeout=2, ok_statuses=None):
    """True when an HTTP GET to path returns a success status: 2xx
    by default, or a status in ok_statuses when given. An error
    response (500, 503, ...) is a service that is not ready."""
    ok = set(range(200, 300)) if ok_statuses is None else set(ok_statuses)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        conn.request("GET", path)
        response = conn.getresponse()
        response.read()
        conn.close()
        return response.status in ok
    except (OSError, http.client.HTTPException):
        return False


def _port_is_busy(port):
    """True when something already accepts TCP connections on the
    port — the port is held by another service."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def is_server_ready(port, timeout=30, ready_path=None, process=None, ok_statuses=None):
    """Wait for a server to be ready. The port must accept a connection
    and, when ready_path is given, answer an HTTP GET with a success
    status. Returns False immediately if the server process has exited."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if process is not None and process.poll() is not None:
            return False  # the server died; waiting longer will not help
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                pass
        except (socket.error, ConnectionRefusedError):
            time.sleep(0.5)
            continue
        if ready_path is None:
            return True
        if _http_ready(port, ready_path, ok_statuses=ok_statuses):
            return True
        time.sleep(0.5)
    return False


def _kill_tree_windows(pid):
    """Kill a process and all its children on Windows (taskkill /T).
    terminate() kills only the cmd.exe shell that shell=True started,
    so the real server kept listening after cleanup and the next run
    found the port still held. taskkill ships with Windows (System32),
    so it is present on the CI runners. Returns True when taskkill
    reported success, False when it is missing or the kill failed."""
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
        )
    except OSError:
        return False
    return result.returncode == 0


def _stop_process_group(process, label, timeout=5):
    """Stop a server and everything it started. The server runs in its
    own process group, so signalling the group reaches the real server,
    not just the shell that launched it."""
    if os.name == "nt":
        # No process groups on Windows (start_new_session is POSIX
        # only), and terminate() kills only the cmd.exe shell — the
        # real server and its children keep listening. taskkill /T
        # kills the whole tree; it runs while the leader is still
        # alive, so the children are still its children.
        if process.poll() is None and not _kill_tree_windows(process.pid):
            print(
                f"warning: server {label} could not be stopped with taskkill",
                file=sys.stderr,
            )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass
        if process.poll() is None:
            try:
                process.kill()
            except (OSError, ProcessLookupError):
                pass
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"warning: server {label} did not stop", file=sys.stderr)
        return
    pgid = None
    if os.name == "posix":
        try:
            pgid = os.getpgid(process.pid)
        except (OSError, ProcessLookupError):
            pgid = None
    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGTERM)
        else:
            process.terminate()
    except (OSError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
    # The leader may have exited promptly while a descendant that
    # ignores SIGTERM survives: the SIGKILL half used to run only
    # when the leader did NOT exit in time. Verify the group is
    # empty either way, and SIGKILL what is left. (Residual: a pgid
    # reused by an unrelated group in the milliseconds between the
    # leader's exit and this check would be killed too; only a
    # container/cgroup or job object closes that hole.)
    if pgid is not None:
        try:
            os.killpg(pgid, 0)
        except (OSError, ProcessLookupError):
            pass  # the group is gone: nothing left to kill
        else:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
    elif process.poll() is None:
        try:
            process.kill()
        except (OSError, ProcessLookupError):
            pass
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"warning: server {label} did not stop", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Run command with one or more servers")
    parser.add_argument("--server", action="append", dest="servers", required=True, help="Server command (can be repeated)")
    parser.add_argument("--port", action="append", dest="ports", type=int, required=True, help="Port for each server (must match --server count)")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout in seconds per server (default: 30)")
    parser.add_argument("--ready-path", action="append", dest="ready_paths", default=None,
                        help="HTTP path to GET for readiness (e.g. /health). Repeatable, one path per server; a single value applies to every server. Without it, readiness is only that the port accepts a connection, which a different service on the same port can satisfy.")
    parser.add_argument("--ready-status", default="2xx",
                        help="HTTP statuses that count as ready: '2xx' (default), a range like '200-299', or a list like '200,204'.")
    parser.add_argument("--test-timeout", type=int, default=300,
                        help="Timeout in seconds for the test command (default: 300). A hung test cannot hang this script forever.")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run after server(s) ready")

    args = parser.parse_args()

    # Remove the '--' separator if present
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]

    if not args.command:
        print("Error: No command specified to run", file=sys.stderr)
        return 1

    # Parse server configurations
    if len(args.servers) != len(args.ports):
        print("Error: Number of --server and --port arguments must match", file=sys.stderr)
        return 1

    # One --ready-path per server, or a single value for all of them.
    # Any other count is a usage error, not a silent ignore-the-extra.
    if args.ready_paths is None:
        ready_paths = [None] * len(args.servers)
    elif len(args.ready_paths) == 1:
        ready_paths = args.ready_paths * len(args.servers)
    elif len(args.ready_paths) == len(args.servers):
        ready_paths = args.ready_paths
    else:
        parser.error(
            f"Number of --ready-path arguments ({len(args.ready_paths)}) must be 1 or match "
            f"the number of --server arguments ({len(args.servers)})"
        )

    try:
        ok_statuses = _parse_ready_status(args.ready_status)
    except ValueError as e:
        parser.error(str(e))

    servers = []
    for cmd, port, ready_path in zip(args.servers, args.ports, ready_paths):
        servers.append({"cmd": cmd, "port": port, "ready_path": ready_path})

    server_processes = []
    exit_code = 1

    try:
        # Start all servers
        for i, server in enumerate(servers):
            label = f"server-{i + 1}"
            print(f"Starting server {i + 1}/{len(servers)}: {server['cmd']}")

            # A port already held by another service is an error, not
            # readiness: the check below would be satisfied by the
            # wrong service. (Racy by nature — a service binding
            # between this check and the start is still possible —
            # but it closes the common case.)
            if _port_is_busy(server["port"]):
                print(
                    f"Error: port {server['port']} is already in use by another "
                    f"process — refusing to start a server on it",
                    file=sys.stderr,
                )
                return 1

            # Use shell=True to support commands with cd and &&.
            # start_new_session puts the server in its own process group
            # so cleanup can kill the whole tree, not just the shell.
            process = subprocess.Popen(
                server["cmd"],
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=(os.name == "posix"),
            )
            server_processes.append(process)
            # Keep the server's recent output, so a readiness failure
            # can report what the server printed (or that it printed
            # nothing) instead of only 'failed to start'.
            tail = collections.deque(maxlen=10)
            # Drain both pipes in background threads, so a log-heavy
            # server can never block on a full pipe.
            threading.Thread(target=_drain, args=(process.stdout, label, sys.stdout, tail),
                             daemon=True).start()
            threading.Thread(target=_drain, args=(process.stderr, label, sys.stderr, tail),
                             daemon=True).start()

            # Wait for this server to be ready
            print(f"Waiting for server on port {server['port']}...")
            if not is_server_ready(server["port"], timeout=args.timeout,
                                   ready_path=server["ready_path"], process=process,
                                   ok_statuses=ok_statuses):
                if process.poll() is not None:
                    print(f"Error: server failed to start on port {server['port']} "
                          f"(it exited with code {process.returncode})",
                          file=sys.stderr)
                else:
                    print(f"Error: server failed to start on port {server['port']} "
                          f"within {args.timeout}s", file=sys.stderr)
                if tail:
                    print(f"Last output from {label}:", file=sys.stderr)
                    for line in tail:
                        print(f"  {line}", file=sys.stderr)
                else:
                    print(f"No output from {label}.", file=sys.stderr)
                return 1

            print(f"Server ready on port {server['port']}")

        print(f"\nAll {len(servers)} server(s) ready")

        # Run the command, with its own timeout.
        print(f"Running: {' '.join(args.command)}\n")
        try:
            result = subprocess.run(args.command, timeout=args.test_timeout)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            print(f"Error: test command timed out after {args.test_timeout}s",
                  file=sys.stderr)
            exit_code = 1

    finally:
        # Clean up all servers (the whole process group each time).
        if server_processes:
            print(f"\nStopping {len(server_processes)} server(s)...")
            for i, process in enumerate(server_processes):
                _stop_process_group(process, f"server-{i + 1}")
                print(f"Server {i + 1} stopped")
            print("All servers stopped")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
