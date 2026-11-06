#!/usr/bin/env python3
# ORCINUS change notice (Apache-2.0 §4(b)): ORCINUS changed this file from upstream anthropics/skills@ca45fc4 — stdout/stderr are drained in background threads, readiness is an HTTP check with a liveness check, cleanup signals the whole process group, and the test command has a timeout. The rest is verbatim; see ATTRIBUTION.md.
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
  response from that path. A bare port check can be fooled by a
  different service listening on the same port. While waiting, the
  script also checks that the server process is still alive — a server
  that exited is a failure, not a reason to wait out the timeout.
- Cleanup kills the whole process group, not just the shell. The server
  is started with shell=True (so commands with cd and && work), and
  terminating the shell leaves the real server running. Each server is
  started in its own process group (start_new_session=True on POSIX)
  and the group is signalled on cleanup.
- The test command has an independent timeout (--test-timeout, default
  300s). A hung test cannot hang this script forever.
"""

import http.client
import os
import signal
import subprocess
import socket
import sys
import threading
import time
import argparse


def _drain(pipe, label, stream):
    """Forward a server's output stream to this script's stream, line
    by line, in a background thread. This is what keeps the pipe from
    filling up and blocking the server."""
    try:
        for line in pipe:
            stream.write(f"[{label}] {line}")
            stream.flush()
    except (OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except (OSError, ValueError):
            pass


def _http_ready(port, path, timeout=2):
    """True when an HTTP GET to path returns any HTTP response."""
    try:
        conn = http.client.HTTPConnection("localhost", port, timeout=timeout)
        conn.request("GET", path)
        response = conn.getresponse()
        response.read()
        conn.close()
        return True
    except (OSError, http.client.HTTPException):
        return False


def is_server_ready(port, timeout=30, ready_path=None, process=None):
    """Wait for a server to be ready. The port must accept a connection
    and, when ready_path is given, answer an HTTP GET. Returns False
    immediately if the server process has exited."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if process is not None and process.poll() is not None:
            return False  # the server died; waiting longer will not help
        try:
            with socket.create_connection(("localhost", port), timeout=1):
                pass
        except (socket.error, ConnectionRefusedError):
            time.sleep(0.5)
            continue
        if ready_path is None:
            return True
        if _http_ready(port, ready_path):
            return True
        time.sleep(0.5)
    return False


def _stop_process_group(process, label, timeout=5):
    """Stop a server and everything it started. The server runs in its
    own process group, so signalling the group reaches the real server,
    not just the shell that launched it."""
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
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGKILL)
        else:
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
    parser.add_argument("--ready-path", default=None,
                        help="HTTP path to GET for readiness (e.g. /health). Without it, readiness is only that the port accepts a connection, which a different service on the same port can satisfy.")
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

    servers = []
    for cmd, port in zip(args.servers, args.ports):
        servers.append({"cmd": cmd, "port": port})

    server_processes = []
    exit_code = 1

    try:
        # Start all servers
        for i, server in enumerate(servers):
            label = f"server-{i + 1}"
            print(f"Starting server {i + 1}/{len(servers)}: {server['cmd']}")

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
            # Drain both pipes in background threads, so a log-heavy
            # server can never block on a full pipe.
            threading.Thread(target=_drain, args=(process.stdout, label, sys.stdout),
                             daemon=True).start()
            threading.Thread(target=_drain, args=(process.stderr, label, sys.stderr),
                             daemon=True).start()

            # Wait for this server to be ready
            print(f"Waiting for server on port {server['port']}...")
            if not is_server_ready(server["port"], timeout=args.timeout,
                                   ready_path=args.ready_path, process=process):
                if process.poll() is not None:
                    print(f"Error: server failed to start on port {server['port']} "
                          f"(it exited with code {process.returncode})",
                          file=sys.stderr)
                else:
                    print(f"Error: server failed to start on port {server['port']} "
                          f"within {args.timeout}s", file=sys.stderr)
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
