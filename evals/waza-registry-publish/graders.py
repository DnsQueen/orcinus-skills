"""Programmatic graders for the waza registry-publish eval.

These functions are the EXECUTABLE SPECIFICATION of the grader
semantics — they are no longer called from the task YAMLs. The
task YAMLs' `code` assertions inline these bodies with `re` only,
using waza-documented names (round 7, F-05): waza's code-grader
namespace is closed — the context vars plus len, any, all, str,
int, float, bool, list, dict, re — and the real runner does NOT
resolve sibling-module helper names there, so a helper call in a
task YAML raised NameError on the real waza v0.40.0 run. `json`
is not in the documented built-in list either, so the inline
assertions parse the report block with regex field checks
instead of json.loads; test_graders.py pins both the names and
the behaviour.

The publish block is a task-level grading contract, not a
skill requirement: the registry-publish skill specifies the
report form in prose, not a machine block. The tasks instruct
the agent to end with the block so the publish-ready verdict,
the version, the pack verdict, and the published flag are read
from one place, never from bare words in the prose. The dry-run
file list and the registry result are still prose checks,
because the report states them in prose.

Honest limit: the graders see only the agent's output text,
not its tool calls, so a fabricated report can still pass —
the suite measures report accuracy, not whether the agent read
the fixtures. A live `waza run` of this suite is still the
outstanding confirmation that the inlined assertions resolve
on the real runner; there is no waza binary in this environment.
"""

import json
import re

__all__ = ["report_block", "publish_ready", "version", "pack_ok", "published"]

_BLOCK_RE = re.compile(r"```publish\n(.*?)\n```", re.S)


def report_block(output):
    """Parse the output's single ```publish block, or return None.

    Exactly one fenced block, valid JSON, a JSON object, and the
    last thing in the response (only whitespace may follow it) —
    the prompt instructs the agent to end with the block. Anything
    else (no block, two blocks, non-JSON, trailing prose) is not a
    report and returns None, so the task fails.
    """
    if not isinstance(output, str):
        return None
    blocks = _BLOCK_RE.findall(output)
    if len(blocks) != 1:
        return None
    if not output.rstrip().endswith("```"):
        return None
    try:
        block = json.loads(blocks[0])
    except ValueError:
        return None
    if not isinstance(block, dict):
        return None
    return block


def publish_ready(output):
    """The block's publish_ready flag, or None."""
    block = report_block(output)
    if block is None:
        return None
    return block.get("publish_ready")


def version(output):
    """The block's version, or None."""
    block = report_block(output)
    if block is None:
        return None
    return block.get("version")


def pack_ok(output):
    """The block's pack_ok flag, or None."""
    block = report_block(output)
    if block is None:
        return None
    return block.get("pack_ok")


def published(output):
    """The block's published flag, or None."""
    block = report_block(output)
    if block is None:
        return None
    return block.get("published")
