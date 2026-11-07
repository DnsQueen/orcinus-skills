#!/usr/bin/env python3
# ORCINUS change notice (Apache-2.0 §4(b)): ORCINUS changed this file from upstream anthropics/skills@ca45fc4 — every trial is three-state (TRIGGERED / NOT_TRIGGERED / ERROR): an infrastructure failure (missing `claude` CLI, timeout, non-zero exit, unparseable output) is an ERROR, never a NOT_TRIGGERED, so an error cannot pass a should_trigger: false case; trigger rates are computed only over valid trials, a query with no valid trial cannot pass, errors are surfaced in the JSON output, and the CLI exits non-zero when any query has none. The rest is verbatim; see ATTRIBUTION.md.
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
import select
import subprocess
import sys
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

        cmd = [
            "claude",
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

        try:
            while time.time() - start_time < timeout:
                if process.poll() is not None:
                    remaining = process.stdout.read()
                    if remaining:
                        buffer += remaining.decode("utf-8", errors="replace")
                    break

                ready, _, _ = select.select([process.stdout], [], [], 1.0)
                if not ready:
                    continue

                chunk = os.read(process.stdout.fileno(), 8192)
                if not chunk:
                    break
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
            # The loop ended without an early return: either the
            # process finished (break above) or the timeout expired.
            timed_out = process.poll() is None and time.time() - start_time >= timeout
        finally:
            # Clean up process on any exit path (return, exception, timeout)
            if process.poll() is None:
                process.kill()
                process.wait()

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
