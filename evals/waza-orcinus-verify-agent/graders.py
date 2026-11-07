"""Programmatic graders for the waza orcinus-verify agent eval.

The task YAMLs' `code` assertions call these helpers with `output`
in scope — the graders parse the verdict block instead of matching
substrings of it. The old substring graders were bypassable three
ways (2-E1 / 3-P1-6): a correct output with compact JSON was
rejected 9/9, an opposite-verdict LAST block passed 9/9, and a
```verdict block that was not JSON at all passed with the keywords
sitting outside the block. Parsing the block fixes all three: the
verdict, file, checks and finding are read from the parsed block,
never from bare words in the prose.

Honest limit: waza's documented code graders evaluate Python
expressions with `output` in scope, and whether the real waza
runner resolves these sibling-module names in that namespace is
UNVERIFIED — there is no waza binary in this environment and the
suite has never run with a real executor. The in-repo reproduction
(evals/waza-orcinus-verify-agent/test_graders.py::_grade) injects
these helpers into the eval namespace, so the semantics pinned
there are the semantics these functions implement. If a real waza
run does not resolve the names, every task fails closed with a
NameError — a visibly broken run, never a false pass.
"""

import json
import re

__all__ = ["verdict_block", "finding", "check"]

_BLOCK_RE = re.compile(r"```verdict\n(.*?)\n```", re.S)


def verdict_block(output):
    """Parse the output's single ```verdict block, or return None.

    Exactly one fenced block, valid JSON, a JSON object, and the
    last thing in the response (only whitespace may follow it) —
    the prompt instructs the agent to end with the block. Anything
    else (no block, two blocks, non-JSON, trailing prose) is not a
    verdict and returns None, so the task fails.
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


def finding(output):
    """The finding line of the parsed verdict block, or "".

    The finding is the one line of evidence: task-specific keywords
    (Math.floor, the test count) are checked here, in the block,
    not anywhere in the prose.
    """
    block = verdict_block(output)
    if block is None:
        return ""
    value = block.get("finding")
    return value if isinstance(value, str) else ""


def check(output, gate):
    """One gate's verdict from the parsed block, or None.

    A single gate (planted-bug's test gate) is read the same way as
    the whole checks map: from the parsed block, never from prose.
    """
    block = verdict_block(output)
    if block is None:
        return None
    checks = block.get("checks")
    if not isinstance(checks, dict):
        return None
    return checks.get(gate)
