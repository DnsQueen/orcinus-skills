"""Programmatic graders for the waza orcinus-verify agent eval.

These functions are the EXECUTABLE SPECIFICATION of the grader
semantics — they are no longer called from the task YAMLs. The
task YAMLs' `code` assertions inline these bodies with `re` only,
using waza-documented names (round 7, F-05): waza's code-grader
namespace is closed — the context vars plus len, any, all, str,
int, float, bool, list, dict, re — and the real runner does NOT
resolve sibling-module helper names there, so the helper calls
raised NameError 9/9 on the real waza v0.40.0 run. `json` is not
in the documented built-in list either, so the inline assertions
parse the verdict block with regex field checks instead of
json.loads; test_graders.py pins both the names and the behaviour.
The old substring graders were bypassable three ways (2-E1 /
3-P1-6): a correct output with compact JSON was rejected 9/9, an
opposite-verdict LAST block passed 9/9, and a ```verdict block
that was not JSON at all passed with the keywords sitting outside
the block. Parsing the block fixes all three: the verdict, file,
checks and finding are read from the parsed block, never from bare
words in the prose.

Honest limits of the regex inlining (vs. this module's json.loads):
a field pattern could in principle match inside the finding
string, and a block that is not JSON fails through the field
checks rather than through a parse returning None — the outcome
is the same (the task fails), the mechanism differs. An assertion
that raises on a malformed block fails that task closed, never
passes. A live `waza run` of the suite remains the outstanding
confirmation that the inlined assertions resolve on the real
runner; there is no waza binary in this environment.
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
