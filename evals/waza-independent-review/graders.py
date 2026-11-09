"""Programmatic graders for the waza independent-review eval.

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

The review block mirrors the orcinus-verify verdict block
(evals/waza-orcinus-verify-agent/graders.py): one fenced block,
the verdict, the primary file, one line of evidence. It is a
task-level grading contract, not a skill requirement: the
independent-review skill specifies the report form in prose,
not a machine block. The tasks instruct the agent to end with
the block so the verdict, the file, and the finding are read
from one place, never from bare words in the prose. Which other
reviewers ran, and the defects beyond the finding, are still
prose checks, because the report states them in prose.

Honest limit: the graders see only the agent's output text,
not its tool calls, so a fabricated report can still pass —
the suite measures verdict accuracy, not whether the checks
really ran. A live `waza run` of this suite is still the
outstanding confirmation that the inlined assertions resolve
on the real runner; there is no waza binary in this environment.
"""

import json
import re

__all__ = ["report_block", "verdict", "file", "finding"]

_BLOCK_RE = re.compile(r"```review\n(.*?)\n```", re.S)


def report_block(output):
    """Parse the output's single ```review block, or return None.

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


def verdict(output):
    """The block's verdict, or None."""
    block = report_block(output)
    if block is None:
        return None
    return block.get("verdict")


def file(output):
    """The block's file, or None."""
    block = report_block(output)
    if block is None:
        return None
    return block.get("file")


def finding(output):
    """The block's finding line, or ""."""
    block = report_block(output)
    if block is None:
        return ""
    value = block.get("finding")
    return value if isinstance(value, str) else ""
