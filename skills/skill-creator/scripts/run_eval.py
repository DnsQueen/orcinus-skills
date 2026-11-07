#!/usr/bin/env python3
# ORCINUS change notice (Apache-2.0 §4(b)): ORCINUS changed this file from upstream anthropics/skills@ca45fc4 — every trial is three-state (TRIGGERED / NOT_TRIGGERED / ERROR): an infrastructure failure (missing `claude` CLI, timeout, non-zero exit, unparseable output) is an ERROR, never a NOT_TRIGGERED, so an error cannot pass a should_trigger: false case; trigger rates are computed only over valid trials, a query with no valid trial cannot pass, errors are surfaced in the JSON output, and the CLI exits non-zero when any query has none. `claude` is resolved with `shutil.which` (PATHEXT-aware, so the npm-installed `claude.cmd` on Windows is found and run via cmd.exe — a bare Popen cannot start it), and stdout is pumped by a reader thread (`select` cannot wait on a pipe on Windows). The rest is verbatim; see ATTRIBUTION.md.
"""Run trigger evaluation for a skill description.

Tests whether a skill's description causes Claude to trigger (read the skill)
for a set of queries. Outputs results as JSON.

Every trial is three-state — TRIGGERED, NOT_TRIGGERED, or ERROR.
An infrastructure failure (missing `claude` CLI, timeout, non-zero
exit, unparseable output) is an ERROR, never a NOT_TRIGGERED: an
error must not pass a should_trigger: false case. Trigger rates are
computed only over valid trials; a query with no valid trial cannot
pass, and the CLI exits non-zero when any query has none.
"""

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from scripts.utils import parse_skill_md


def find_project_root() -> Path:
    """Find the project root by walking up from cwd looking for .claude/.

    Mimics how Claude Code discovers its project root, so the command file
    we create ends up where claude -p will look for it.
    """
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".claude").is_dir():
            return parent
    return current


def _resolve_claude() -> list[str] | None:
    """Resolve the `claude` CLI to a runnable argv prefix.

    `shutil.which` honours PATHEXT on Windows, so it finds both
    `claude.exe` and the npm-installed `claude.cmd`; a bare
    `Popen(["claude", ...])` does not — CreateProcess only tries
    the exact name and `.exe`, and cannot run a `.cmd` at all. A
    batch file therefore has to go through the command interpreter.
    Returns None when no `claude` is on PATH.
    """
    path = shutil.which("claude")
    if path is None:
        return None
    if sys.platform == "win32" and os.path.splitext(path)[1].lower() in (".bat", ".cmd"):
        comspec = os.environ.get("ComSpec")
        if not comspec:
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            comspec = os.path.join(system_root, "System32", "cmd.exe")
        return [comspec, "/c", path]
    return [path]


def _pump_stdout(stream, chunks: queue.Queue[bytes]) -> None:
    """Read a process stdout stream into a queue until EOF.

    Runs in a daemon thread: `select.select` cannot wait on a pipe
    on Windows (Winsock only accepts sockets, so it raises
    `OSError: [WinError 10038]`), so stdout is pumped by a thread
    on every platform instead of by select. The empty chunk is the
    EOF sentinel; it is always enqueued, even if the read fails.
    """
    try:
        while True:
            chunk = os.read(stream.fileno(), 8192)
            if not chunk:
                break
            chunks.put(chunk)
    except (OSError, ValueError):
        pass
    finally:
        chunks.put(b"")


def run_single_query(
    query: str,
    skill_name: str,
    skill_description: str,
    timeout: int,
    project_root: str,
    model: str | None = None,
) -> tuple[str, str | None]:
    """Run a single query and return its three-state outcome.

    Returns (status, error): status is TRIGGERED, NOT_TRIGGERED, or
    ERROR; error is None unless the trial itself failed (missing
    CLI, timeout, non-zero exit, unparseable output), in which case
    it says why. A model that uses a different tool, or finishes
    without touching the skill, is a real NOT_TRIGGERED — only a
    failure to run or read the trial is an ERROR.

    Creates a command file in .claude/commands/ so it appears in Claude's
    available_skills list, then runs `claude -p` with the raw query.
    Uses --include-partial-messages to detect triggering early from
    stream events (content_block_start) rather than waiting for the
    full assistant message, which only arrives after tool execution.
    """
    unique_id = uuid.uuid4().hex[:8]
    clean_name = f"{skill_name}-skill-{unique_id}"
    project_commands_dir = Path(project_root) / ".claude" / "commands"
    command_file = project_commands_dir / f"{clean_name}.md"

    try:
        project_commands_dir.mkdir(parents=True, exist_ok=True)
        # Use YAML block scalar to avoid breaking on quotes in description
        indented_desc = "\n  ".join(skill_description.split("\n"))
        command_content = (
            f"---\n"
            f"description: |\n"
            f"  {indented_desc}\n"
            f"---\n\n"
            f"# {skill_name}\n\n"
            f"This skill handles: {skill_description}\n"
        )
        command_file.write_text(command_content)

        claude_argv = _resolve_claude()
        if claude_argv is None:
            return ("ERROR", "could not start 'claude': 'claude' is not on PATH")
        cmd = claude_argv + [
            "-p", query,
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]
        if model:
            cmd.extend(["--model", model])

        # Remove CLAUDECODE env var to allow nesting claude -p inside a
        # Claude Code session. The guard is for interactive terminal conflicts;
        # programmatic subprocess usage is safe.
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        process = None
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=project_root,
                env=env,
            )
        except OSError as e:
            # The CLI is missing (or cannot start): an infrastructure
            # error, never a NOT_TRIGGERED.
            return ("ERROR", f"could not start 'claude': {e}")

        triggered = False
        timed_out = False
        events_seen = 0
        start_time = time.time()
        buffer = ""
        # Track state for stream event detection
        pending_tool_name = None
        accumulated_json = ""

        def _feed(chunk: bytes) -> tuple[str, str | None] | None:
            """Feed one stdout chunk through the event parser.

            Appends to the buffer and processes complete lines.
            Returns an early outcome (TRIGGERED / NOT_TRIGGERED) or
            None to keep reading.
            """
            nonlocal buffer, events_seen, triggered
            nonlocal pending_tool_name, accumulated_json
            buffer += chunk.decode("utf-8", errors="replace")

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                events_seen += 1

                # Early detection via stream events
                if event.get("type") == "stream_event":
                    se = event.get("event", {})
                    se_type = se.get("type", "")

                    if se_type == "content_block_start":
                        cb = se.get("content_block", {})
                        if cb.get("type") == "tool_use":
                            tool_name = cb.get("name", "")
                            if tool_name in ("Skill", "Read"):
                                pending_tool_name = tool_name
                                accumulated_json = ""
                            else:
                                return ("NOT_TRIGGERED", None)

                    elif se_type == "content_block_delta" and pending_tool_name:
                        delta = se.get("delta", {})
                        if delta.get("type") == "input_json_delta":
                            accumulated_json += delta.get("partial_json", "")
                            if clean_name in accumulated_json:
                                return ("TRIGGERED", None)

                    elif se_type in ("content_block_stop", "message_stop"):
                        if pending_tool_name:
                            return (
                                ("TRIGGERED", None)
                                if clean_name in accumulated_json
                                else ("NOT_TRIGGERED", None)
                            )
                        if se_type == "message_stop":
                            return ("NOT_TRIGGERED", None)

                # Fallback: full assistant message
                elif event.get("type") == "assistant":
                    message = event.get("message", {})
                    for content_item in message.get("content", []):
                        if content_item.get("type") != "tool_use":
                            continue
                        tool_name = content_item.get("name", "")
                        tool_input = content_item.get("input", {})
                        if tool_name == "Skill" and clean_name in tool_input.get("skill", ""):
                            triggered = True
                        elif tool_name == "Read" and clean_name in tool_input.get("file_path", ""):
                            triggered = True
                        return ("TRIGGERED", None) if triggered else ("NOT_TRIGGERED", None)

                elif event.get("type") == "result":
                    return ("TRIGGERED", None) if triggered else ("NOT_TRIGGERED", None)
            return None

        chunks: queue.Queue[bytes] = queue.Queue()
        reader = threading.Thread(
            target=_pump_stdout, args=(process.stdout, chunks), daemon=True
        )
        reader.start()
        saw_eof = False
        try:
            while True:
                remaining = timeout - (time.time() - start_time)
                if remaining <= 0:
                    break
                try:
                    chunk = chunks.get(timeout=min(1.0, remaining))
                except queue.Empty:
                    continue
                if chunk == b"":
                    saw_eof = True
                    break
                outcome = _feed(chunk)
                if outcome is not None:
                    return outcome
            # The loop ended on EOF or on the deadline. If the process
            # finished, its last output may still be queued behind the
            # reader: drain it (bounded) so a trial that finished just
            # before the deadline is judged on its real output.
            if not saw_eof and process.poll() is not None:
                drain_deadline = time.time() + 2.0
                while time.time() < drain_deadline:
                    try:
                        chunk = chunks.get(
                            timeout=max(0.0, drain_deadline - time.time())
                        )
                    except queue.Empty:
                        break
                    if chunk == b"":
                        break
                    outcome = _feed(chunk)
                    if outcome is not None:
                        return outcome
            # The loop ended without an early return: either the
            # process finished or the timeout expired.
            timed_out = process.poll() is None and time.time() - start_time >= timeout
        finally:
            # Clean up process on any exit path (return, exception, timeout)
            if process.poll() is None:
                process.kill()
                process.wait()
            reader.join(timeout=5)

        if timed_out:
            return ("ERROR", f"claude timed out after {timeout}s")
        if process.returncode not in (0, None) and not triggered:
            return ("ERROR", f"claude exited with code {process.returncode}")
        if not triggered and events_seen == 0:
            return ("ERROR", "claude produced no parseable stream-json events")
        return ("TRIGGERED", None) if triggered else ("NOT_TRIGGERED", None)
    finally:
        if command_file.exists():
            command_file.unlink()


def run_eval(
    eval_set: list[dict],
    skill_name: str,
    description: str,
    num_workers: int,
    timeout: int,
    project_root: Path,
    runs_per_query: int = 1,
    trigger_threshold: float = 0.5,
    model: str | None = None,
    runner=None,
) -> dict:
    """Run the full eval set and return results.

    Each trial is three-state (see run_single_query). Rates are
    computed only over valid (non-ERROR) trials; a query with no
    valid trial has trigger_rate None and pass False. `runner` is
    the trial function (run_single_query by default); tests pass a
    fake.
    """
    if runner is None:
        runner = run_single_query
    results = []

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        future_to_info = {}
        for item in eval_set:
            for run_idx in range(runs_per_query):
                future = executor.submit(
                    runner,
                    item["query"],
                    skill_name,
                    description,
                    timeout,
                    str(project_root),
                    model,
                )
                future_to_info[future] = (item, run_idx)

        query_trials: dict[str, list[tuple[str, str | None]]] = {}
        query_items: dict[str, dict] = {}
        for future in as_completed(future_to_info):
            item, _ = future_to_info[future]
            query = item["query"]
            query_items[query] = item
            if query not in query_trials:
                query_trials[query] = []
            try:
                query_trials[query].append(future.result())
            except Exception as e:
                print(f"Warning: query failed: {e}", file=sys.stderr)
                query_trials[query].append(("ERROR", str(e)))

    for query, trials in query_trials.items():
        item = query_items[query]
        valid = [s for s, _ in trials if s != "ERROR"]
        errors = [e for s, e in trials if s == "ERROR" and e]
        triggers = sum(1 for s in valid if s == "TRIGGERED")
        valid_runs = len(valid)
        trigger_rate = (triggers / valid_runs) if valid_runs else None
        should_trigger = item["should_trigger"]
        if valid_runs == 0:
            did_pass = False
        elif should_trigger:
            did_pass = trigger_rate >= trigger_threshold
        else:
            did_pass = trigger_rate < trigger_threshold
        results.append({
            "query": query,
            "should_trigger": should_trigger,
            "trigger_rate": trigger_rate,
            "triggers": triggers,
            "valid_runs": valid_runs,
            "runs": len(trials),
            "errors": errors,
            "pass": did_pass,
        })

    passed = sum(1 for r in results if r["pass"])
    total = len(results)

    return {
        "skill_name": skill_name,
        "description": description,
        "results": results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "errored": sum(1 for r in results if r["errors"]),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Run trigger evaluation for a skill description")
    parser.add_argument("--eval-set", required=True, help="Path to eval set JSON file")
    parser.add_argument("--skill-path", required=True, help="Path to skill directory")
    parser.add_argument("--description", default=None, help="Override description to test")
    parser.add_argument("--num-workers", type=int, default=10, help="Number of parallel workers")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout per query in seconds")
    parser.add_argument("--runs-per-query", type=int, default=3, help="Number of runs per query")
    parser.add_argument("--trigger-threshold", type=float, default=0.5, help="Trigger rate threshold")
    parser.add_argument("--model", default=None, help="Model to use for claude -p (default: user's configured model)")
    parser.add_argument("--verbose", action="store_true", help="Print progress to stderr")
    args = parser.parse_args()

    eval_set = json.loads(Path(args.eval_set).read_text())
    skill_path = Path(args.skill_path)

    if not (skill_path / "SKILL.md").exists():
        print(f"Error: No SKILL.md found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    name, original_description, content = parse_skill_md(skill_path)
    description = args.description or original_description
    project_root = find_project_root()

    if args.verbose:
        print(f"Evaluating: {description}", file=sys.stderr)

    output = run_eval(
        eval_set=eval_set,
        skill_name=name,
        description=description,
        num_workers=args.num_workers,
        timeout=args.timeout,
        project_root=project_root,
        runs_per_query=args.runs_per_query,
        trigger_threshold=args.trigger_threshold,
        model=args.model,
    )

    if args.verbose:
        summary = output["summary"]
        print(f"Results: {summary['passed']}/{summary['total']} passed", file=sys.stderr)
        for r in output["results"]:
            status = "PASS" if r["pass"] else "FAIL"
            rate_str = f"{r['triggers']}/{r['runs']}"
            print(f"  [{status}] rate={rate_str} expected={r['should_trigger']}: {r['query'][:70]}", file=sys.stderr)

    print(json.dumps(output, indent=2))

    # A query with no valid trial is an infrastructure failure, not
    # a result: the eval cannot pass, and the exit code must say so.
    if any(r["valid_runs"] == 0 for r in output["results"]):
        print(
            "Error: some queries had no valid trials (infrastructure failure)",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
